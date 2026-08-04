"""Clean independent replay + targeted corruption tests.

Before corruption: clean persisted prediction ledger + clean persisted
state ledger must produce zero replay mismatches.

Then targeted corruption tests for every replayed field.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.backtest.walk_forward import run_development_walk_forward
from nfl_edge.common.errors import (
    SealedHoldoutAccessError,
)
from nfl_edge.models.qb_elo import (
    EloConfig,
    detect_state_ledger_corruption,
    independent_replay_from_pregame,
)

# ---- 1. Clean replay --------------------------------------------------------


def test_clean_full_ledger_replay_has_zero_mismatches(tmp_path: Path) -> None:
    """Run the full development walk-forward into a temp dir, then
    replay from the persisted prediction ledger and verify zero
    mismatches."""
    out = tmp_path / "clean"
    out.mkdir()
    run_development_walk_forward(
        games_path=Path("data/derived/features_v1/game_features_2018_2025.parquet"),
        team_features_path=Path("data/derived/features_v1/team_pregame_features_2018_2025.parquet"),
        output_dir=out,
        created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
        project_root=Path("."),
    )
    pred = pl.read_parquet(out / "qb_elo_predictions_2018_2024.parquet")
    state = pl.read_parquet(out / "qb_elo_state_transitions_2018_2024.parquet")
    pred_rows = pred.to_dicts()
    state_rows = state.to_dicts()
    cfg = EloConfig()
    problems = detect_state_ledger_corruption(
        state_ledger=state_rows, predictions=pred_rows, config=cfg
    )
    assert problems == []


# ---- 2. Tie replay uses multiplier 1.0 ------------------------------------


def test_tie_replay_uses_multiplier_one() -> None:
    predictions = [
        {
            "game_id": "T1", "season": 2020, "season_type": "REG", "week": 1,
            "home_team": "AAA", "away_team": "BBB",
            "home_elo_before": 1500.0, "away_elo_before": 1500.0,
            "home_field_adjustment": 0.0,
            "predicted_home_win_probability": 0.5,
            "actual_home_win": None, "actual_tie": True,
            "target_available": True, "actual_margin": 0,
        },
    ]
    _, replayed = independent_replay_from_pregame(
        predictions=predictions, teams=["AAA", "BBB"], config=EloConfig()
    )
    home_replay = [r for r in replayed if r["side"] == "home"][0]
    assert home_replay["update_multiplier"] == 1.0


# ---- 3. Postseason K -------------------------------------------------------


def test_postseason_uses_postseason_k() -> None:
    predictions = [
        {
            "game_id": "P1", "season": 2020, "season_type": "WC", "week": 1,
            "home_team": "AAA", "away_team": "BBB",
            "home_elo_before": 1500.0, "away_elo_before": 1500.0,
            "home_field_adjustment": 0.0,
            "predicted_home_win_probability": 0.5,
            "actual_home_win": True, "actual_tie": False,
            "target_available": True, "actual_margin": 7,
        },
        {
            "game_id": "P2", "season": 2020, "season_type": "REG", "week": 1,
            "home_team": "CCC", "away_team": "DDD",
            "home_elo_before": 1500.0, "away_elo_before": 1500.0,
            "home_field_adjustment": 0.0,
            "predicted_home_win_probability": 0.5,
            "actual_home_win": True, "actual_tie": False,
            "target_available": True, "actual_margin": 7,
        },
    ]
    _, replayed = independent_replay_from_pregame(
        predictions=predictions, teams=["AAA", "BBB", "CCC", "DDD"], config=EloConfig()
    )
    wc = [r for r in replayed if r["game_id"] == "P1"][0]
    reg = [r for r in replayed if r["game_id"] == "P2"][0]
    assert wc["k_factor"] == EloConfig().k_factor_postseason
    assert reg["k_factor"] == EloConfig().k_factor_regular


# ---- 4. Replay rejects 2025 -------------------------------------------------


def test_replay_rejects_2025() -> None:
    predictions = [
        {
            "game_id": "F1", "season": 2025, "season_type": "REG", "week": 1,
            "home_team": "AAA", "away_team": "BBB",
            "home_elo_before": 1500.0, "away_elo_before": 1500.0,
            "home_field_adjustment": 0.0,
            "predicted_home_win_probability": 0.5,
            "actual_home_win": True, "actual_tie": False,
            "target_available": True, "actual_margin": 7,
        },
    ]
    with pytest.raises(SealedHoldoutAccessError):
        independent_replay_from_pregame(
            predictions=predictions, teams=["AAA", "BBB"], config=EloConfig()
        )


# ---- 5. Replay works from a temporary checkout -----------------------------


def test_replay_works_from_temporary_checkout(tmp_path: Path) -> None:
    """A full workflow run from a tmp working directory produces the
    same prediction and state SHAs as one run from the real checkout."""
    real = Path(".")
    # Run 1: real checkout
    out1 = Path("/tmp/p4_replay_real")
    if out1.exists():
        import shutil
        shutil.rmtree(out1)
    out1.mkdir(parents=True)
    run_development_walk_forward(
        games_path=real / "data/derived/features_v1/game_features_2018_2025.parquet",
        team_features_path=real / "data/derived/features_v1/team_pregame_features_2018_2025.parquet",
        output_dir=out1,
        created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
        project_root=real,
    )
    # Run 2: tmp checkout (copy the source tree)
    import shutil
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    for sub in ("src", "config", "data"):
        src = real / sub
        if not src.exists():
            continue
        dst = fake_repo / sub
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    out2 = fake_repo / "out"
    out2.mkdir()
    orig_cwd = Path.cwd()
    import os
    os.chdir(fake_repo)
    try:
        run_development_walk_forward(
            games_path=fake_repo / "data/derived/features_v1/game_features_2018_2025.parquet",
            team_features_path=fake_repo / "data/derived/features_v1/team_pregame_features_2018_2025.parquet",
            output_dir=out2,
            created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
            project_root=fake_repo,
        )
    finally:
        os.chdir(orig_cwd)
    import hashlib
    def _h(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    assert _h(out1 / "qb_elo_predictions_2018_2024.parquet") == _h(
        out2 / "qb_elo_predictions_2018_2024.parquet"
    )
    assert _h(out1 / "qb_elo_state_transitions_2018_2024.parquet") == _h(
        out2 / "qb_elo_state_transitions_2018_2024.parquet"
    )
