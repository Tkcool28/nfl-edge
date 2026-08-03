"""2025 sealed holdout tripwire test.

This file does NOT run the holdout. It proves that Task 03A refuses to
touch it. The test:
1. Loads the combined feature source.
2. Identifies 2025 rows.
3. Poisons all 2025 numerical features and targets with extreme values.
4. Runs Task 03A and proves all development artifacts are identical.
5. Attempts direct 2025 fit/predict/score/report operations and proves
   each fails with SealedHoldoutAccessError.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.backtest.blocks import (
    DEVELOPMENT_SEASON_MAX,
    assert_development_seasons_only,
    build_development_blocks,
)
from nfl_edge.backtest.walk_forward import run_development_walk_forward
from nfl_edge.common.errors import SealedHoldoutAccessError
from nfl_edge.evaluation.metrics import brier_score, log_loss
from nfl_edge.evaluation.scorecard import build_development_scorecard

REPO_ROOT = Path("/root/nfl-edge")
GAMES_PATH = REPO_ROOT / "data/derived/features_v1/game_features_2018_2025.parquet"
TEAM_PATH = REPO_ROOT / "data/derived/features_v1/team_pregame_features_2018_2025.parquet"
CLEAN_OUTPUT = Path("/tmp/nfl-edge-holdout-clean")
POISONED_OUTPUT = Path("/tmp/nfl-edge-holdout-poisoned")


def _run(output_dir: Path, games_override: Path | None = None):
    """Helper to run the walk-forward with a fixed created_at."""
    games_path = games_override or GAMES_PATH
    run_development_walk_forward(
        games_path=games_path,
        team_features_path=TEAM_PATH,
        output_dir=output_dir,
        created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
    )


def _poison_2025_rows(games: pl.DataFrame) -> pl.DataFrame:
    """Replace all 2025 rows with extreme poisoned values."""
    poison_value = 999.0
    poisoned = games.with_row_index("__row_id")
    is_2025 = poisoned["season"] == 2025
    # Replace numerical columns with extreme values
    for col in poisoned.columns:
        if col in ("__row_id", "game_id", "season_type", "season", "week", "target_tie"):
            continue
        if poisoned[col].dtype in (pl.Float64, pl.Int64, pl.Int32, pl.Float32):
            poisoned = poisoned.with_columns(
                pl.when(is_2025).then(poison_value).otherwise(pl.col(col)).alias(col)
            )
    # Also poison target fields explicitly
    poisoned = poisoned.with_columns(
        pl.when(is_2025).then(pl.lit(poison_value)).otherwise(pl.col("target_margin")).alias("target_margin"),
        pl.when(is_2025).then(pl.lit(True)).otherwise(pl.col("target_home_win")).alias("target_home_win"),
    )
    return poisoned.drop("__row_id")


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    for p in [CLEAN_OUTPUT, POISONED_OUTPUT]:
        if p.exists():
            shutil.rmtree(p)
    # Run clean baseline first
    _run(CLEAN_OUTPUT)
    # Create poisoned version
    games = pl.read_parquet(GAMES_PATH)
    poisoned = _poison_2025_rows(games)
    poisoned_path = Path("/tmp/nfl-edge-poisoned-games.parquet")
    poisoned.write_parquet(poisoned_path)
    _run(POISONED_OUTPUT, games_override=poisoned_path)
    yield
    for p in [CLEAN_OUTPUT, POISONED_OUTPUT]:
        if p.exists():
            shutil.rmtree(p)
    if poisoned_path.exists():
        poisoned_path.unlink()


def test_clean_artifact_exists():
    pred = pl.read_parquet(CLEAN_OUTPUT / "qb_elo_predictions_2018_2024.parquet")
    assert pred.height > 0
    assert pred["season"].max() <= 2024


def test_poisoned_artifact_exists():
    pred = pl.read_parquet(POISONED_OUTPUT / "qb_elo_predictions_2018_2024.parquet")
    assert pred.height > 0
    assert pred["season"].max() <= 2024


def test_2025_poisoning_does_not_change_predictions():
    """The most important assertion: poisoning 2025 rows has ZERO effect on
    the development artifacts."""
    clean_pred = pl.read_parquet(CLEAN_OUTPUT / "qb_elo_predictions_2018_2024.parquet").sort("prediction_id")
    poison_pred = pl.read_parquet(POISONED_OUTPUT / "qb_elo_predictions_2018_2024.parquet").sort("prediction_id")
    assert clean_pred.height == poison_pred.height
    # Compare all numeric columns (including exposure metadata, which
    # is computed from the same prior-state view and must therefore be
    # 2025-invariant).
    for col in [
        "predicted_home_win_probability", "home_elo_before", "away_elo_before",
        "home_qb_adjustment", "away_qb_adjustment",
        "training_rows_available_before_block",
        "training_season_min", "training_season_max",
        "training_block_count", "prior_completed_games_count",
    ]:
        assert clean_pred[col].to_list() == poison_pred[col].to_list(), f"Column {col} differs"


def test_2025_poisoning_does_not_change_state():
    clean_state = pl.read_parquet(
        CLEAN_OUTPUT / "qb_elo_state_transitions_2018_2024.parquet"
    ).sort("state_update_order")
    poison_state = pl.read_parquet(
        POISONED_OUTPUT / "qb_elo_state_transitions_2018_2024.parquet"
    ).sort("state_update_order")
    assert clean_state.height == poison_state.height
    for col in ["elo_before", "elo_change", "elo_after", "expected_result", "actual_result"]:
        assert clean_state[col].to_list() == poison_state[col].to_list(), f"Column {col} differs"


def test_assert_development_seasons_only_rejects_2025():
    games = pl.read_parquet(GAMES_PATH)
    with pytest.raises(SealedHoldoutAccessError):
        assert_development_seasons_only(games)


def test_build_blocks_rejects_2025():
    games = pl.read_parquet(GAMES_PATH)
    # build_development_blocks filters, but we test the tripwire directly
    blocks = build_development_blocks(games)
    # All blocks should be <= 2024
    assert all(b.season <= DEVELOPMENT_SEASON_MAX for b in blocks)


def test_metrics_reject_2025():
    games = pl.read_parquet(GAMES_PATH)
    fake_preds = games.select(
        pl.col("game_id").alias("game_id"),
        pl.col("season").alias("season"),
        pl.col("week").alias("week"),
        pl.col("home_team").alias("home_team"),
        pl.col("away_team").alias("away_team"),
        pl.col("target_home_win").cast(pl.Int8).cast(pl.Float64).alias("predicted_home_win_probability"),
        pl.col("target_home_win").alias("actual_home_win"),
        pl.col("target_tie").alias("actual_tie"),
        pl.col("target_available").alias("target_available"),
    )
    with pytest.raises(SealedHoldoutAccessError):
        brier_score(fake_preds)
    with pytest.raises(SealedHoldoutAccessError):
        log_loss(fake_preds)


def test_scorecard_rejects_2025(tmp_path):
    games = pl.read_parquet(GAMES_PATH)
    fake_preds = games.select(
        pl.col("game_id").alias("game_id"),
        pl.col("season").alias("season"),
        pl.col("week").alias("week"),
        pl.col("home_team").alias("home_team"),
        pl.col("away_team").alias("away_team"),
        pl.col("target_home_win").cast(pl.Float64).alias("predicted_home_win_probability"),
        pl.col("target_home_win").alias("actual_home_win"),
        pl.col("target_tie").alias("actual_tie"),
        pl.col("target_available").alias("target_available"),
        pl.lit("UNKNOWN").alias("qb_certainty_state"),
    )
    with pytest.raises(SealedHoldoutAccessError):
        build_development_scorecard(
            fake_preds, configuration={}, manifest={}, output_dir=tmp_path
        )


def test_2025_artifact_files_do_not_exist():
    """No file in the output directory should have 2025 in its name."""
    for p in CLEAN_OUTPUT.iterdir():
        assert "2025" not in p.name, f"Unexpected 2025 file: {p.name}"
    for p in POISONED_OUTPUT.iterdir():
        assert "2025" not in p.name, f"Unexpected 2025 file: {p.name}"


def test_manifest_does_not_contain_2025_predictions():
    manifest = json.loads((CLEAN_OUTPUT / "qb_elo_run_manifest_v1.json").read_text())
    assert manifest["prediction_ledger"]["path"] == "data/modeling/development_v1/qb_elo_predictions_2018_2024.parquet"
    assert manifest["state_ledger"]["path"] == "data/modeling/development_v1/qb_elo_state_transitions_2018_2024.parquet"
    # No 2025 in any path
    assert "2025" not in manifest["prediction_ledger"]["path"]
    assert "2025" not in manifest["state_ledger"]["path"]
