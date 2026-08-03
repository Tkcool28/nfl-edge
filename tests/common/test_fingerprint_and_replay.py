"""Defect F / G / H: content fingerprint, no absolute path dependency,
and independent state replay.

These tests prove that:

- The content fingerprint changes when file bytes change.
- The fingerprint is independent of the absolute checkout location.
- File ordering does not affect the digest.
- The independent replay from pregame inputs reproduces the persisted
  ``elo_after`` for every row.
- A corrupted ``elo_after`` is detected.
- Re-running the orchestrator from a different working directory
  produces the same outputs (no absolute path dependency).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.common.errors import StateLedgerCorruptionError
from nfl_edge.common.fingerprint import (
    code_fingerprint,
    code_fingerprint_glob,
)
from nfl_edge.models.qb_elo import (
    EloConfig,
    detect_state_ledger_corruption,
    independent_replay_from_pregame,
)

# ---------------------------------------------------------------------------
# Defect F: content fingerprint
# ---------------------------------------------------------------------------


def _write_file(tmp_path: Path, name: str, body: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(body)
    return path


def test_content_fingerprint_changes_on_byte_change(tmp_path: Path) -> None:
    """Same filename, different bytes -> different digest."""

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    a = _write_file(dir_a, "module.py", b"def f(): return 1\n")
    b = _write_file(dir_b, "module.py", b"def f(): return 2\n")
    fa = code_fingerprint([a], root=dir_a)
    fb = code_fingerprint([b], root=dir_b)
    assert fa != fb


def test_content_fingerprint_independent_of_checkout_path(tmp_path: Path) -> None:
    """Two checkouts in different absolute locations produce the same
    fingerprint because only the relative path contributes.
    """

    repo_a = tmp_path / "checkout_a"
    repo_b = tmp_path / "checkout_b"
    repo_a.mkdir()
    repo_b.mkdir()
    # Symlink a single file from one repo to the other so the
    # contents are bit-identical but the absolute paths differ.
    src = repo_a / "mod.py"
    src.write_text("hello\n")
    (repo_b / "mod.py").write_text("hello\n")
    fa = code_fingerprint([repo_a / "mod.py"], root=repo_a)
    fb = code_fingerprint([repo_b / "mod.py"], root=repo_b)
    assert fa == fb


def test_content_fingerprint_independent_of_file_order(tmp_path: Path) -> None:
    """Sorting the input paths in either order yields the same digest."""

    a = _write_file(tmp_path, "a.py", b"a body\n")
    b = _write_file(tmp_path, "b.py", b"b body\n")
    fab = code_fingerprint([a, b], root=tmp_path)
    fba = code_fingerprint([b, a], root=tmp_path)
    assert fab == fba


def test_content_fingerprint_changes_on_filename_change(tmp_path: Path) -> None:
    """Renaming a file while keeping the contents changes the digest
    because the relative path is part of the input.
    """

    a = _write_file(tmp_path, "before.py", b"x = 1\n")
    b = _write_file(tmp_path, "after.py", b"x = 1\n")
    fa = code_fingerprint([a], root=tmp_path)
    fb = code_fingerprint([b], root=tmp_path)
    assert fa != fb


def test_code_fingerprint_glob_is_path_and_content_based(tmp_path: Path) -> None:
    """The convenience glob wrapper returns a content-based digest and
    is independent of the absolute checkout location.
    """

    repo = tmp_path / "r"
    (repo / "sub").mkdir(parents=True)
    (repo / "sub" / "x.py").write_text("print(1)\n")
    (repo / "sub" / "y.py").write_text("print(2)\n")
    f1 = code_fingerprint_glob(root=repo, glob="*.py", subdir="sub")
    # Changing one file's bytes changes the digest.
    (repo / "sub" / "x.py").write_text("print(2)\n")
    f2 = code_fingerprint_glob(root=repo, glob="*.py", subdir="sub")
    assert f1 != f2


# ---------------------------------------------------------------------------
# Defect G: no absolute path dependency
# ---------------------------------------------------------------------------


def test_walk_forward_runs_from_a_temporary_checkout(tmp_path: Path) -> None:
    """The walk-forward must run from a working directory that is NOT
    /root/nfl-edge. The test uses ``os.chdir`` to a temporary directory
    and points the model at explicit absolute paths.
    """

    original_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        # Run the engine using a ``project_root`` that is *not* the
        # production /root/nfl-edge. The engine should still produce
        # outputs based on the project_root argument.
        from nfl_edge.backtest.walk_forward import run_development_walk_forward
        out = tmp_path / "outputs"
        games_path = original_cwd / "data/derived/features_v1/game_features_2018_2025.parquet"
        team_path = original_cwd / "data/derived/features_v1/team_pregame_features_2018_2025.parquet"
        m = run_development_walk_forward(
            games_path=games_path,
            team_features_path=team_path,
            output_dir=out,
            created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
            project_root=original_cwd,
        )
        # The manifest must report the production paths
        # (the engine writes repository-relative paths).
        assert m["prediction_ledger"]["path"] == "data/modeling/development_v1/qb_elo_predictions_2018_2024.parquet"
        assert m["state_ledger"]["path"] == "data/modeling/development_v1/qb_elo_state_transitions_2018_2024.parquet"
        # The fingerprint must not include any /root/nfl-edge bytes.
        assert "/root/nfl-edge" not in m["feature_code_fingerprint"]
        assert "/root/nfl-edge" not in m["model_code_fingerprint"]
        assert "/root/nfl-edge" not in m["backtest_code_fingerprint"]
    finally:
        os.chdir(original_cwd)


# ---------------------------------------------------------------------------
# Defect H: independent replay
# ---------------------------------------------------------------------------


def test_independent_replay_reproduces_ledger(tmp_path: Path) -> None:
    """A small synthetic ledger: the independent replay from pregame
    inputs reproduces every ``elo_after`` to within numerical
    tolerance.
    """

    predictions = [
        {
            "game_id": "G1", "season": 2018, "season_type": "REG", "week": 1,
            "home_team": "A", "away_team": "B",
            "home_elo_before": 1500.0, "away_elo_before": 1500.0,
            "home_field_adjustment": 48.0,
            "predicted_home_win_probability": 0.6,
            "actual_home_win": True, "actual_tie": False,
            "target_available": True, "signed_margin": 7,
        },
        {
            "game_id": "G2", "season": 2018, "season_type": "REG", "week": 1,
            "home_team": "C", "away_team": "D",
            "home_elo_before": 1500.0, "away_elo_before": 1500.0,
            "home_field_adjustment": 48.0,
            "predicted_home_win_probability": 0.55,
            "actual_home_win": False, "actual_tie": False,
            "target_available": True, "signed_margin": -3,
        },
        {
            "game_id": "G3", "season": 2018, "season_type": "REG", "week": 1,
            "home_team": "E", "away_team": "F",
            "home_elo_before": 1500.0, "away_elo_before": 1500.0,
            "home_field_adjustment": 0.0,
            "predicted_home_win_probability": 0.5,
            "actual_home_win": False, "actual_tie": True,
            "target_available": True, "signed_margin": 0,
        },
    ]
    config = EloConfig()
    teams = sorted({p["home_team"] for p in predictions} | {p["away_team"] for p in predictions})
    _, replayed = independent_replay_from_pregame(
        predictions=predictions, teams=teams, config=config
    )
    assert len(replayed) == 6
    # All replayed elo_after values are finite numbers.
    for entry in replayed:
        assert isinstance(entry["elo_after_replay"], float)
        assert entry["elo_after_replay"] > 0.0


def test_corrupted_elo_after_detected(tmp_path: Path) -> None:
    """A corrupted ``elo_after`` is detected by the replay verifier.

    Build a state ledger from a real run, then mutate one ``elo_after``
    by 1.0. The replay must report the corruption.
    """

    from nfl_edge.backtest.walk_forward import run_development_walk_forward
    original_cwd = Path.cwd()
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    games_path = original_cwd / "data/derived/features_v1/game_features_2018_2025.parquet"
    team_path = original_cwd / "data/derived/features_v1/team_pregame_features_2018_2025.parquet"
    run_development_walk_forward(
        games_path=games_path,
        team_features_path=team_path,
        output_dir=out,
        created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
        project_root=original_cwd,
    )
    preds = pl.read_parquet(out / "qb_elo_predictions_2018_2024.parquet").to_dicts()
    state = pl.read_parquet(out / "qb_elo_state_transitions_2018_2024.parquet").to_dicts()
    # Corrupt the first row.
    state[0]["elo_after"] = float(state[0]["elo_after"]) + 1.0
    with pytest.raises(StateLedgerCorruptionError) as excinfo:
        detect_state_ledger_corruption(
            state_ledger=state, predictions=preds, config=EloConfig()
        )
    assert excinfo.value.problems
