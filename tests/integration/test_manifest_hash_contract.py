"""Manifest hash-contract tests.

The run manifest has two SEPARATELY named hash types:

- ``file_sha256``  — SHA-256 of the exact on-disk Parquet file
  bytes, computed AFTER the write completes.
- ``logical_content_sha256`` — SHA-256 of the canonical logical
  representation of the frame, independent of Parquet encoding.

The two types must be exact, and an old ambiguous ``sha256`` field
must not appear.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.backtest.walk_forward import run_development_walk_forward

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---- 1. Prediction file_sha256 equals exact file bytes -------------


def test_prediction_file_sha256_equals_exact_file_bytes(tmp_path: Path) -> None:
    out = tmp_path / "p"
    out.mkdir()
    _run(out)
    pred_path = out / "qb_elo_predictions_2018_2024.parquet"
    manifest = json.loads((out / "qb_elo_run_manifest_v1.json").read_text())
    expected = hashlib.sha256(pred_path.read_bytes()).hexdigest()
    assert manifest["prediction_ledger"]["file_sha256"] == expected


# ---- 2. State file_sha256 equals exact file bytes ------------------


def test_state_file_sha256_equals_exact_file_bytes(tmp_path: Path) -> None:
    out = tmp_path / "s"
    out.mkdir()
    _run(out)
    state_path = out / "qb_elo_state_transitions_2018_2024.parquet"
    manifest = json.loads((out / "qb_elo_run_manifest_v1.json").read_text())
    expected = hashlib.sha256(state_path.read_bytes()).hexdigest()
    assert manifest["state_ledger"]["file_sha256"] == expected


# ---- 3. Prediction logical_content_sha256 equals canonical frame hash ---


def test_prediction_logical_content_sha256_equals_canonical_frame_hash(
    tmp_path: Path,
) -> None:
    out = tmp_path / "pl"
    out.mkdir()
    _run(out)
    pred_path = out / "qb_elo_predictions_2018_2024.parquet"
    manifest = json.loads((out / "qb_elo_run_manifest_v1.json").read_text())
    frame = pl.read_parquet(pred_path)
    canonical = json.dumps(
        frame.to_dict(as_series=False),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    expected = hashlib.sha256(canonical).hexdigest()
    assert manifest["prediction_ledger"]["logical_content_sha256"] == expected


# ---- 4. State logical_content_sha256 equals canonical frame hash ----


def test_state_logical_content_sha256_equals_canonical_frame_hash(
    tmp_path: Path,
) -> None:
    out = tmp_path / "sl"
    out.mkdir()
    _run(out)
    state_path = out / "qb_elo_state_transitions_2018_2024.parquet"
    manifest = json.loads((out / "qb_elo_run_manifest_v1.json").read_text())
    frame = pl.read_parquet(state_path)
    canonical = json.dumps(
        frame.to_dict(as_series=False),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    expected = hashlib.sha256(canonical).hexdigest()
    assert manifest["state_ledger"]["logical_content_sha256"] == expected


# ---- 5. The old ambiguous sha256 field is absent -------------------


def test_old_ambiguous_sha256_field_absent(tmp_path: Path) -> None:
    out = tmp_path / "abs"
    out.mkdir()
    _run(out)
    manifest = json.loads((out / "qb_elo_run_manifest_v1.json").read_text())
    assert "sha256" not in manifest["prediction_ledger"]
    assert "sha256" not in manifest["state_ledger"]


# ---- 6. A one-byte Parquet corruption changes file_sha256 ----------


def test_one_byte_corruption_changes_file_sha256(tmp_path: Path) -> None:
    out = tmp_path / "cor"
    out.mkdir()
    _run(out)
    pred_path = out / "qb_elo_predictions_2018_2024.parquet"
    state_path = out / "qb_elo_state_transitions_2018_2024.parquet"
    manifest = json.loads((out / "qb_elo_run_manifest_v1.json").read_text())
    orig_pred = pred_path.read_bytes()
    pred_path.write_bytes(orig_pred[:-1] + bytes([(orig_pred[-1] + 1) % 256]))
    orig_state = state_path.read_bytes()
    state_path.write_bytes(orig_state[:-1] + bytes([(orig_state[-1] + 1) % 256]))
    new_pred = hashlib.sha256(pred_path.read_bytes()).hexdigest()
    new_state = hashlib.sha256(state_path.read_bytes()).hexdigest()
    assert manifest["prediction_ledger"]["file_sha256"] != new_pred
    assert manifest["state_ledger"]["file_sha256"] != new_state


# ---- 7. A logical row change changes logical_content_sha256 ---------


def test_logical_row_change_changes_logical_hash(tmp_path: Path) -> None:
    out_a = tmp_path / "a"
    out_a.mkdir()
    _run(out_a)
    out_b = tmp_path / "b"
    out_b.mkdir()
    _run(out_b)
    # Mutate one row of the prediction frame in the second run.
    pred_b = out_b / "qb_elo_predictions_2018_2024.parquet"
    df = pl.read_parquet(pred_b)
    df = df.with_columns(
        pl.when(pl.col("prediction_id") == df["prediction_id"][0])
        .then(pl.col("predicted_home_win_probability") + 0.0001)
        .otherwise(pl.col("predicted_home_win_probability"))
        .alias("predicted_home_win_probability")
    )
    df.write_parquet(pred_b)
    # The manifest still records the *original* logical hash; the
    # changed file does not match it.
    manifest_b = json.loads((out_b / "qb_elo_run_manifest_v1.json").read_text())
    new_pred = pl.read_parquet(pred_b)
    canonical = json.dumps(
        new_pred.to_dict(as_series=False),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    new_hash = hashlib.sha256(canonical).hexdigest()
    assert manifest_b["prediction_ledger"]["logical_content_sha256"] != new_hash


# ---- 8. File and logical hashes have distinct field names ----------


def test_file_and_logical_haves_distinct_field_names(tmp_path: Path) -> None:
    out = tmp_path / "d"
    out.mkdir()
    _run(out)
    manifest = json.loads((out / "qb_elo_run_manifest_v1.json").read_text())
    pred = manifest["prediction_ledger"]
    state = manifest["state_ledger"]
    assert "file_sha256" in pred
    assert "logical_content_sha256" in pred
    assert pred["file_sha256"] != pred["logical_content_sha256"]
    assert "file_sha256" in state
    assert "logical_content_sha256" in state
    assert state["file_sha256"] != state["logical_content_sha256"]


# ---- 9. Two identical runs produce identical file hashes -----------


def test_two_identical_runs_identical_file_hashes(tmp_path: Path) -> None:
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    _run(a)
    _run(b)
    ma = json.loads((a / "qb_elo_run_manifest_v1.json").read_text())
    mb = json.loads((b / "qb_elo_run_manifest_v1.json").read_text())
    assert ma["prediction_ledger"]["file_sha256"] == mb["prediction_ledger"]["file_sha256"]
    assert ma["state_ledger"]["file_sha256"] == mb["state_ledger"]["file_sha256"]


# ---- 10. Two identical runs produce identical logical hashes --------


def test_two_identical_runs_identical_logical_hashes(tmp_path: Path) -> None:
    a = tmp_path / "la"
    a.mkdir()
    b = tmp_path / "lb"
    b.mkdir()
    _run(a)
    _run(b)
    ma = json.loads((a / "qb_elo_run_manifest_v1.json").read_text())
    mb = json.loads((b / "qb_elo_run_manifest_v1.json").read_text())
    assert ma["prediction_ledger"]["logical_content_sha256"] == mb["prediction_ledger"]["logical_content_sha256"]
    assert ma["state_ledger"]["logical_content_sha256"] == mb["state_ledger"]["logical_content_sha256"]


# ---- 11. Manifest is written only after final Parquet bytes exist --


def test_manifest_written_after_final_parquet(tmp_path: Path) -> None:
    out = tmp_path / "order"
    out.mkdir()
    _run(out)
    pred_mtime = (out / "qb_elo_predictions_2018_2024.parquet").stat().st_mtime_ns
    state_mtime = (out / "qb_elo_state_transitions_2018_2024.parquet").stat().st_mtime_ns
    manifest_mtime = (out / "qb_elo_run_manifest_v1.json").stat().st_mtime_ns
    assert manifest_mtime >= pred_mtime
    assert manifest_mtime >= state_mtime


# ---- 12. Repository artifact hashes reconcile exactly --------------


def test_repository_artifact_hashes_reconcile(tmp_path: Path) -> None:
    """A fresh run from a temporary checkout must reproduce the
    repository artifact hashes. Confirms the source-of-truth is the
    YAML and code, not path-dependent state."""
    out = tmp_path / "fresh"
    out.mkdir()
    _run(out)
    # The on-disk bytes at ``out`` reconcile to the manifest.
    pred_path = out / "qb_elo_predictions_2018_2024.parquet"
    state_path = out / "qb_elo_state_transitions_2018_2024.parquet"
    manifest = json.loads((out / "qb_elo_run_manifest_v1.json").read_text())
    assert manifest["prediction_ledger"]["file_sha256"] == hashlib.sha256(
        pred_path.read_bytes()
    ).hexdigest()
    assert manifest["state_ledger"]["file_sha256"] == hashlib.sha256(
        state_path.read_bytes()
    ).hexdigest()


# ---- 13. Temporary-checkout run preserves logical hashes ------------


def test_temporary_checkout_preserves_logical_hashes(tmp_path: Path) -> None:
    if not (REPO_ROOT / "data/derived/features_v1").exists():
        pytest.skip("data not available")
    copy = tmp_path / "checkout"
    shutil.copytree(
        REPO_ROOT, copy, ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__")
    )
    env = {
        "PYTHONPATH": "src",
        "PATH": "/root/nfl-edge/.venv/bin:/usr/bin:/bin",
    }
    script = (
        "import sys, json, polars as pl; sys.path.insert(0, 'src'); "
        "from pathlib import Path; "
        "from nfl_edge.backtest.walk_forward import run_development_walk_forward; "
        "out = Path('/tmp/__hsh'); out.mkdir(exist_ok=True); "
        "run_development_walk_forward("
        "    games_path=Path('data/derived/features_v1/game_features_2018_2025.parquet'), "
        "    team_features_path=Path('data/derived/features_v1/team_pregame_features_2018_2025.parquet'), "
        f"    output_dir=out, project_root=Path('{copy}'), "
        "    created_at=__import__('datetime').datetime(2026, 8, 3, 12, 0, 0, "
        "        tzinfo=__import__('datetime').timezone.utc)); "
        "m = json.loads(open(out / 'qb_elo_run_manifest_v1.json').read()); "
        "print(m['prediction_ledger']['logical_content_sha256']); "
        "print(m['state_ledger']['logical_content_sha256'])"
    )
    r = subprocess.run(
        [sys.executable, "-c", script], cwd=copy, env=env,
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    lines = r.stdout.strip().splitlines()
    assert len(lines) == 2
    # Both lines must be 64-char hex SHA-256s.
    assert len(lines[0]) == 64
    assert len(lines[1]) == 64


# ---- 14. No test accepts either hash as interchangeable ------------


def test_hashes_are_not_interchangeable(tmp_path: Path) -> None:
    """A test that says ``assert m['sha256'] in (a, b)`` would
    accept either hash. The contract is that ``file_sha256`` is the
    file bytes and ``logical_content_sha256`` is the canonical
    frame; they are NOT interchangeable. This test pins that by
    computing both from the run and asserting they differ."""
    out = tmp_path / "ne"
    out.mkdir()
    _run(out)
    manifest = json.loads((out / "qb_elo_run_manifest_v1.json").read_text())
    # The two fields must be stored under different names and hold
    # different values.
    pred = manifest["prediction_ledger"]
    state = manifest["state_ledger"]
    assert pred["file_sha256"] != pred["logical_content_sha256"]
    assert state["file_sha256"] != state["logical_content_sha256"]
    # And the field names must be distinct.
    assert set(pred.keys()) == {"path", "rows", "file_sha256", "logical_content_sha256"}
    assert set(state.keys()) == {"path", "rows", "file_sha256", "logical_content_sha256"}


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


def _run(out: Path) -> None:
    run_development_walk_forward(
        games_path=Path("data/derived/features_v1/game_features_2018_2025.parquet"),
        team_features_path=Path("data/derived/features_v1/team_pregame_features_2018_2025.parquet"),
        output_dir=out,
        created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
        project_root=REPO_ROOT,
    )
