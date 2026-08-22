"""Task05F evaluator-only V2 calibration primitives.

These functions calibrate frozen football outputs downstream. They do not alter
football-model features, parameters, training data, or predictions. Candidate
formulas are preregistered in config/task05f_evaluator_rebuild_v2_prereg.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import numpy as np
from sklearn.linear_model import LogisticRegression


@dataclass(frozen=True)
class MonotoneLogitCalibration:
    intercept: float | None
    slope: float | None
    support_n: int
    supported: bool
    reason: str | None = None


@dataclass(frozen=True)
class AnchorSlopeCalibration:
    beta_raw: float | None
    beta: float | None
    support_n: int
    residuals: tuple[float, ...]
    supported: bool
    reason: str | None = None


def _clip_p(p: float) -> float:
    return min(0.99, max(0.01, float(p)))


def _logit(p: float) -> float:
    q = _clip_p(p)
    return math.log(q / (1.0 - q))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def fit_monotone_logit_calibration(
    rows: Iterable[tuple[float, int]],
    *,
    minimum_prior: int = 128,
    C: float = 1.0,
) -> MonotoneLogitCalibration:
    """Fit the preregistered one-feature ML probability calibrator.

    Each row is ``(raw_exact_avg_probability, home_win_binary)``. Ties are
    excluded by the caller and handled separately by wager settlement logic.
    A non-positive fitted slope fails closed rather than reversing model order.
    """
    material = [(float(p), int(y)) for p, y in rows]
    n = len(material)
    if n < int(minimum_prior):
        return MonotoneLogitCalibration(None, None, n, False, "insufficient_prior_support")
    ys = np.asarray([y for _, y in material], dtype=int)
    if len(set(ys.tolist())) < 2:
        return MonotoneLogitCalibration(None, None, n, False, "single_class_prior")
    X = np.asarray([[_logit(p)] for p, _ in material], dtype=float)
    model = LogisticRegression(C=float(C), max_iter=2000, solver="lbfgs")
    model.fit(X, ys)
    intercept = float(model.intercept_[0])
    slope = float(model.coef_[0][0])
    if not math.isfinite(intercept) or not math.isfinite(slope):
        return MonotoneLogitCalibration(None, None, n, False, "nonfinite_fit")
    if slope <= 0.0:
        return MonotoneLogitCalibration(intercept, slope, n, False, "nonpositive_calibration_slope")
    return MonotoneLogitCalibration(intercept, slope, n, True, None)


def calibrated_probability(raw_probability: float, state: MonotoneLogitCalibration) -> float:
    if not state.supported or state.intercept is None or state.slope is None:
        raise ValueError("monotone logit calibration state is unsupported")
    return _sigmoid(float(state.intercept) + float(state.slope) * _logit(raw_probability))


def fit_anchor_slope_calibration(
    rows: Iterable[tuple[float, float, float]],
    *,
    minimum_prior: int = 128,
) -> AnchorSlopeCalibration:
    """Fit the preregistered continuous Pinnacle-anchor slope calibration.

    Each row is ``(frozen_model_value, pinnacle_market_value, actual_value)``.
    With ``d = model-market`` and ``y = actual-market``:

        beta_raw = sum(d*y) / sum(d*d)
        beta = clip(beta_raw, 0, 1)
        calibrated_mean = market + beta*d

    Residuals are then ``actual-calibrated_mean`` using the same fitted beta.
    No sportsbook price or ROI enters the fit.
    """
    material = [(float(model), float(market), float(actual)) for model, market, actual in rows]
    n = len(material)
    if n < int(minimum_prior):
        return AnchorSlopeCalibration(None, None, n, tuple(), False, "insufficient_prior_support")
    d = np.asarray([model - market for model, market, _ in material], dtype=float)
    y = np.asarray([actual - market for _, market, actual in material], dtype=float)
    denom = float(np.dot(d, d))
    if not math.isfinite(denom) or denom <= 1e-12:
        return AnchorSlopeCalibration(None, None, n, tuple(), False, "degenerate_disagreement_variance")
    beta_raw = float(np.dot(d, y) / denom)
    if not math.isfinite(beta_raw):
        return AnchorSlopeCalibration(None, None, n, tuple(), False, "nonfinite_fit")
    beta = min(1.0, max(0.0, beta_raw))
    residuals = tuple(
        actual - (market + beta * (model - market))
        for model, market, actual in material
    )
    return AnchorSlopeCalibration(beta_raw, beta, n, residuals, True, None)


def calibrated_point_mean(model_value: float, market_value: float, state: AnchorSlopeCalibration) -> float:
    if not state.supported or state.beta is None:
        raise ValueError("anchor slope calibration state is unsupported")
    model = float(model_value)
    market = float(market_value)
    return market + float(state.beta) * (model - market)
