"""Tests for the evaluation metrics and scorecard."""

from __future__ import annotations

import polars as pl
import pytest

from nfl_edge.common.errors import SealedHoldoutAccessError
from nfl_edge.evaluation.calibration import (
    calibration_intercept_slope,
    reliability_table,
)
from nfl_edge.evaluation.metrics import (
    brier_score,
    descriptive_accuracy,
    log_loss,
)
from nfl_edge.evaluation.scorecard import build_development_scorecard


def _make_pred_frame():
    return pl.DataFrame([
        {"game_id": "g1", "season": 2023, "week": 1, "home_team": "A", "away_team": "B",
         "predicted_home_win_probability": 0.7, "actual_home_win": True, "actual_tie": False,
         "target_available": True, "qb_certainty_state": "UNKNOWN"},
        {"game_id": "g2", "season": 2023, "week": 1, "home_team": "B", "away_team": "C",
         "predicted_home_win_probability": 0.3, "actual_home_win": False, "actual_tie": False,
         "target_available": True, "qb_certainty_state": "UNKNOWN"},
        {"game_id": "g3", "season": 2023, "week": 2, "home_team": "D", "away_team": "E",
         "predicted_home_win_probability": 0.6, "actual_home_win": False, "actual_tie": False,
         "target_available": True, "qb_certainty_state": "UNKNOWN"},
    ])


def test_brier_score_perfect():
    df = _make_pred_frame()
    # Perfect predictions: g1=0.7 actual=True, g2=0.3 actual=False, g3=0.6 actual=False (wrong)
    b = brier_score(df)
    assert 0 < b < 1


def test_log_loss_decreases_with_better_predictions():
    # Same outcomes, different predictions
    df1 = pl.DataFrame([
        {"game_id": "g1", "season": 2023, "week": 1, "home_team": "A", "away_team": "B",
         "predicted_home_win_probability": 0.9, "actual_home_win": True, "actual_tie": False,
         "target_available": True, "qb_certainty_state": "UNKNOWN"},
    ])
    df2 = pl.DataFrame([
        {"game_id": "g1", "season": 2023, "week": 1, "home_team": "A", "away_team": "B",
         "predicted_home_win_probability": 0.6, "actual_home_win": True, "actual_tie": False,
         "target_available": True, "qb_certainty_state": "UNKNOWN"},
    ])
    assert log_loss(df1) < log_loss(df2)


def test_descriptive_accuracy():
    df = _make_pred_frame()
    # g1: pred=0.7 (>0.5, home win) actual=True -> correct
    # g2: pred=0.3 (<0.5, away win) actual=False -> correct
    # g3: pred=0.6 (>0.5, home win) actual=False -> wrong
    assert abs(descriptive_accuracy(df) - 2.0 / 3.0) < 1e-9


def test_metrics_reject_2025():
    df = _make_pred_frame().with_columns(pl.lit(2025).alias("season"))
    with pytest.raises(SealedHoldoutAccessError):
        brier_score(df)
    with pytest.raises(SealedHoldoutAccessError):
        log_loss(df)
    with pytest.raises(SealedHoldoutAccessError):
        descriptive_accuracy(df)


def test_reliability_table_basic():
    df = _make_pred_frame()
    table = reliability_table(df)
    assert len(table) == 10  # 10 buckets covering [0.00, 1.00]
    total = sum(r["count"] for r in table)
    assert total == 3
    # Empty buckets must report None, not 0.0
    for r in table:
        if r["count"] == 0:
            assert r["mean_predicted_probability"] is None
            assert r["actual_home_win_rate"] is None


def test_calibration_intercept_slope_runs():
    df = _make_pred_frame()
    intercept, slope = calibration_intercept_slope(df)
    assert isinstance(intercept, float)
    assert isinstance(slope, float)


def test_build_scorecard_writes_files(tmp_path):
    df = _make_pred_frame()
    manifest = {
        "run_id": "test-run",
        "model_config_sha256": "abc",
        "backtest_config_sha256": "def",
        "model_code_fingerprint": "ghi",
    }
    config = {"initial_rating": 1500.0}
    sc = build_development_scorecard(
        df, configuration=config, manifest=manifest, output_dir=tmp_path
    )
    assert (tmp_path / "qb_elo_development_scorecard.json").exists()
    assert (tmp_path / "qb_elo_development_scorecard.md").exists()
    assert (tmp_path / "qb_elo_reliability_table.csv").exists()
    assert sc["totals"]["predicted_games"] == 3
    assert sc["totals"]["binary_scored_games"] == 3
    assert sc["totals"]["ties_excluded_from_binary_metrics"] == 0
    assert sc["totals"]["warmup_excluded_games"] == 0


def test_scorecard_rejects_2025(tmp_path):
    df = _make_pred_frame().with_columns(pl.lit(2025).alias("season"))
    with pytest.raises(SealedHoldoutAccessError):
        build_development_scorecard(
            df, configuration={}, manifest={}, output_dir=tmp_path
        )
