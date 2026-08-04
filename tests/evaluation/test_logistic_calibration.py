"""Logistic recalibration diagnostic tests.

Verifies the deterministic Newton-Raphson fit for the
``logit(P(y=1)) = intercept + slope * logit(p)`` diagnostic model.

Covers:

- well-calibrated synthetic sample -> intercept ~ 0, slope ~ 1;
- overconfident predictions -> slope below 1;
- underconfident predictions -> slope above 1;
- one-class outcomes handled explicitly;
- constant-probability inputs handled explicitly;
- non-convergence handled explicitly;
- 2025 rows rejected at the boundary;
- predictions are not modified by the fit.
"""

from __future__ import annotations

import random

import polars as pl
import pytest

from nfl_edge.common.errors import SealedHoldoutAccessError
from nfl_edge.evaluation.calibration import (
    DEFAULT_BUCKET_EDGES,
    logistic_recalibration,
)


def _make_pred_frame(
    *,
    n: int,
    calibration: str = "calibrated",
    season: int = 2024,
    rng_seed: int = 0,
) -> pl.DataFrame:
    """Build a binary-scored prediction frame with controlled calibration.

    ``calibration`` in {"calibrated", "over", "under"}.
    """
    rng = random.Random(rng_seed)
    rows: list[dict[str, object]] = []
    for _ in range(n):
        p = rng.uniform(0.1, 0.9)
        if calibration == "calibrated":
            actual = rng.random() < p
        elif calibration == "over":
            # overconfident: actual win rate is close to 0.5
            # regardless of p.  We push p toward 0.5 in the y as
            # well, so the slope shrinks.
            actual = rng.random() < 0.5
        else:
            # underconfident: actual win rate is more extreme than p
            # (if p > 0.5, actual is more often 1; if p < 0.5, actual
            # is more often 0).  The fitted slope should grow.
            if p > 0.5:
                actual = rng.random() < min(0.95, p + 0.3)
            else:
                actual = rng.random() < max(0.05, p - 0.3)
        rows.append(
            {
                "predicted_home_win_probability": p,
                "actual_home_win": bool(actual),
                "actual_tie": False,
                "target_available": True,
                "season": season,
            }
        )
    return pl.DataFrame(rows).with_columns(pl.col("season").cast(pl.Int64))


def test_well_calibrated_sample_gives_intercept_zero_slope_one() -> None:
    df = _make_pred_frame(n=2000, calibration="calibrated", rng_seed=42)
    result = logistic_recalibration(df)
    assert result["calibration_converged"] is True
    assert result["calibration_fit_status"] == "converged"
    assert result["calibration_iterations"] <= 16
    assert abs(result["calibration_intercept"] - 0.0) < 0.2
    assert abs(result["calibration_slope"] - 1.0) < 0.2


def test_overconfident_predictions_give_slope_below_one() -> None:
    df = _make_pred_frame(n=2000, calibration="over", rng_seed=7)
    result = logistic_recalibration(df)
    assert result["calibration_converged"] is True
    assert result["calibration_slope"] < 1.0
    # Slope must be strictly less than 1 (not equal) for overconfident
    assert result["calibration_slope"] < 0.9


def test_underconfident_predictions_give_slope_above_one() -> None:
    df = _make_pred_frame(n=2000, calibration="under", rng_seed=11)
    result = logistic_recalibration(df)
    assert result["calibration_converged"] is True
    assert result["calibration_slope"] > 1.0
    assert result["calibration_slope"] > 1.1


def test_one_class_outcome_handled_explicitly() -> None:
    df = pl.DataFrame(
        {
            "predicted_home_win_probability": [0.3, 0.4, 0.5, 0.6, 0.7],
            "actual_home_win": [True, True, True, True, True],
            "actual_tie": [False, False, False, False, False],
            "target_available": [True] * 5,
            "season": [2024] * 5,
        }
    )
    result = logistic_recalibration(df)
    assert result["calibration_intercept"] is None
    assert result["calibration_slope"] is None
    assert result["calibration_fit_status"] == "one_class_outcome"
    assert result["calibration_converged"] is False


def test_constant_input_probability_handled_explicitly() -> None:
    df = pl.DataFrame(
        {
            "predicted_home_win_probability": [0.5] * 20,
            "actual_home_win": [True, False] * 10,
            "actual_tie": [False] * 20,
            "target_available": [True] * 20,
            "season": [2024] * 20,
        }
    )
    result = logistic_recalibration(df)
    assert result["calibration_intercept"] is None
    assert result["calibration_slope"] is None
    assert result["calibration_fit_status"] == "constant_input"
    assert result["calibration_converged"] is False


def test_non_convergence_handled_explicitly() -> None:
    # Construct data that won't converge in 1 iteration. The fit uses
    # max_iter=64 by default; we test that very high max_iter still
    # converges or the status is reported.
    df = _make_pred_frame(n=200, calibration="calibrated", rng_seed=99)
    result = logistic_recalibration(df, max_iter=1)
    if not result["calibration_converged"]:
        assert result["calibration_fit_status"] == "max_iter_reached"
        # The returned values are the last-iter values, not zero/one
        assert result["calibration_intercept"] is not None
        assert result["calibration_slope"] is not None


def test_2025_rows_rejected() -> None:
    df = pl.DataFrame(
        {
            "predicted_home_win_probability": [0.5, 0.5, 0.5, 0.5],
            "actual_home_win": [True, False, True, False],
            "actual_tie": [False, False, False, False],
            "target_available": [True, True, True, True],
            "season": [2025, 2025, 2025, 2025],
        }
    )
    with pytest.raises(SealedHoldoutAccessError):
        logistic_recalibration(df)


def test_predictions_remain_unchanged_after_fit() -> None:
    df = _make_pred_frame(n=100, calibration="calibrated", rng_seed=1)
    p_before = df["predicted_home_win_probability"].to_list()
    logistic_recalibration(df)
    p_after = df["predicted_home_win_probability"].to_list()
    assert p_before == p_after


def test_default_bucket_edges_cover_full_range() -> None:
    assert DEFAULT_BUCKET_EDGES[0] == 0.0
    assert DEFAULT_BUCKET_EDGES[-1] == 1.0
    assert len(DEFAULT_BUCKET_EDGES) == 11  # 10 buckets
    for a, b in zip(DEFAULT_BUCKET_EDGES, DEFAULT_BUCKET_EDGES[1:]):
        assert b > a
