"""Calibration diagnostics only. No recalibration is performed in Task 03A.

We compute the reliability (calibration) table and the intercept/slope of
a logistic recalibration fit on the development predictions. This is
diagnostic information only; the predictions themselves are not
transformed.
"""

from __future__ import annotations

import math
from typing import Sequence

import polars as pl

from .metrics import _assert_development_only, _scored


def reliability_table(
    predictions: pl.DataFrame,
    bucket_edges: Sequence[float] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9),
) -> list[dict[str, float]]:
    """Bucket the scored predictions and report mean predicted probability and
    actual home-win rate per bucket.  Buckets are [low, high)."""
    _assert_development_only(predictions)
    scored = _scored(predictions)
    rows: list[dict[str, float]] = []
    for low, high in zip(bucket_edges, list(bucket_edges[1:]) + [1.01]):
        bucket = scored.filter(
            (pl.col("predicted_home_win_probability") >= low)
            & (pl.col("predicted_home_win_probability") < high)
        )
        if bucket.height == 0:
            rows.append({
                "bucket_low": float(low),
                "bucket_high": float(high),
                "count": 0,
                "mean_predicted_probability": 0.0,
                "actual_home_win_rate": 0.0,
            })
            continue
        rows.append({
            "bucket_low": float(low),
            "bucket_high": float(high),
            "count": int(bucket.height),
            "mean_predicted_probability": float(bucket["predicted_home_win_probability"].mean()),
            "actual_home_win_rate": float(bucket["actual_home_win"].cast(pl.Float64).mean()),
        })
    return rows


def calibration_intercept_slope(predictions: pl.DataFrame) -> tuple[float, float]:
    """Fit a logistic recalibration on log(p/(1-p)) and report the intercept
    and slope.  This is diagnostic only; the fitted model is not applied to
    predictions in Task 03A.

    Returns (intercept, slope).  Perfectly calibrated predictions: (0.0, 1.0).
    """
    _assert_development_only(predictions)
    scored = _scored(predictions)
    if scored.height < 2:
        return 0.0, 1.0

    p = [float(x) for x in scored["predicted_home_win_probability"].to_list()]
    y = [float(int(x)) for x in scored["actual_home_win"].to_list()]

    eps = 1e-9
    logits = []
    for pi in p:
        pi_c = max(eps, min(1.0 - eps, pi))
        logits.append(math.log(pi_c / (1.0 - pi_c)))

    # Simple OLS on logits via numpy-free closed form
    n = len(logits)
    mean_x = sum(logits) / n
    mean_y = sum(y) / n
    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(logits, y))
    den = sum((xi - mean_x) ** 2 for xi in logits)
    if den == 0:
        return 0.0, 1.0
    slope = num / den
    intercept = mean_y - slope * mean_x
    return float(intercept), float(slope)
