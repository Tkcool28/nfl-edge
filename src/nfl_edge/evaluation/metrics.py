"""Scoring metrics for binary (home-win) predictions on the development ledger.

All metrics are descriptive only. They never use 2025 data and never
participate in model selection.  Functions here reject any season > 2024
to keep the 2025 sealed holdout inaccessible.
"""

from __future__ import annotations

import math

import polars as pl

from ..backtest.blocks import DEVELOPMENT_SEASON_MAX
from ..common.errors import SealedHoldoutAccessError


def _assert_development_only(predictions: pl.DataFrame) -> None:
    """Hard-fail if predictions contain any season > 2024."""
    if predictions.height == 0:
        return
    max_season = int(predictions["season"].max())
    if max_season > DEVELOPMENT_SEASON_MAX:
        raise SealedHoldoutAccessError(
            max_season,
            "evaluation.metrics",
            "predictions frame contains season > development_max",
        )


def _scored(predictions: pl.DataFrame) -> pl.DataFrame:
    """Return only rows where target_available is True and actual_home_win is not null."""
    return predictions.filter(
        pl.col("target_available") & pl.col("actual_home_win").is_not_null()
    )


def brier_score(predictions: pl.DataFrame) -> float:
    """Compute the Brier score (MSE of predicted probability vs actual 0/1)."""
    _assert_development_only(predictions)
    scored = _scored(predictions)
    if scored.height == 0:
        return 0.0
    p = scored["predicted_home_win_probability"].to_numpy()
    actual = scored["actual_home_win"].cast(pl.Int8).to_numpy()
    return float(((p - actual) ** 2).mean())


def log_loss(predictions: pl.DataFrame) -> float:
    """Compute mean log loss (binary cross-entropy) with epsilon clamping."""
    _assert_development_only(predictions)
    scored = _scored(predictions)
    if scored.height == 0:
        return 0.0
    p = scored["predicted_home_win_probability"].to_numpy()
    eps = 1e-15
    p = [max(eps, min(1.0 - eps, float(x))) for x in p]
    actual = scored["actual_home_win"].cast(pl.Int8).to_numpy()
    total = 0.0
    for pi, yi in zip(p, actual):
        total += -(yi * math.log(pi) + (1 - yi) * math.log(1 - pi))
    return total / len(p)


def descriptive_accuracy(predictions: pl.DataFrame, threshold: float = 0.5) -> float:
    """Return the fraction of predictions where the predicted side matches the
    actual outcome (home win if p >= threshold, away win otherwise)."""
    _assert_development_only(predictions)
    scored = _scored(predictions)
    if scored.height == 0:
        return 0.0
    pred_home_win = scored["predicted_home_win_probability"] >= threshold
    actual_home_win = scored["actual_home_win"]
    correct = (pred_home_win == actual_home_win).sum()
    return float(correct) / scored.height


def accuracy_in_bucket(
    predictions: pl.DataFrame,
    bucket_low: float,
    bucket_high: float,
) -> float:
    """Accuracy restricted to predictions falling in [bucket_low, bucket_high)."""
    _assert_development_only(predictions)
    scored = _scored(predictions)
    in_bucket = scored.filter(
        (pl.col("predicted_home_win_probability") >= bucket_low)
        & (pl.col("predicted_home_win_probability") < bucket_high)
    )
    if in_bucket.height == 0:
        return 0.0
    pred_home_win = in_bucket["predicted_home_win_probability"] >= 0.5
    actual_home_win = in_bucket["actual_home_win"]
    correct = (pred_home_win == actual_home_win).sum()
    return float(correct) / in_bucket.height
