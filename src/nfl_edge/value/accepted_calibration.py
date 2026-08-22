"""Accepted ML V4 and point-market V3 calibration primitives.

The point-market implementation corrects the integer-line semantics from the
experimental branch: paired Pinnacle no-vig prices are conditional on a
non-push settlement. Integer anchors therefore solve that conditional equation
while reserving the one-point push cell instead of treating the quoted
probability as unconditional P(score > line).
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import NormalDist
from typing import Iterable

import numpy as np
from sklearn.linear_model import LogisticRegression

_NORMAL = NormalDist()
MIN_PRIOR = 128


@dataclass(frozen=True)
class MlV4Fit:
    market_intercept: float | None
    market_slope: float | None
    model_weight: float | None
    support_n: int
    supported: bool
    reason: str | None = None


@dataclass(frozen=True)
class PointV3Fit:
    sigma: float | None
    beta_raw: float | None
    beta: float | None
    residuals: tuple[float, ...]
    support_n: int
    supported: bool
    reason: str | None = None


def _clip_p(p: float) -> float:
    return min(0.99, max(0.01, float(p)))


def _logit(p: float) -> float:
    q = _clip_p(p)
    return math.log(q / (1.0 - q))


def _sigmoid(x: float) -> float:
    if x >= 0.0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def calibrated_market_probability(raw_pinnacle_probability: float, fit: MlV4Fit) -> float:
    if not fit.supported or fit.market_intercept is None or fit.market_slope is None:
        raise ValueError("ML V4 state is unsupported")
    return _sigmoid(float(fit.market_intercept) + float(fit.market_slope) * _logit(raw_pinnacle_probability))


def pooled_probability(model_probability: float, calibrated_market: float, weight: float) -> float:
    market_logit = _logit(calibrated_market)
    delta = _logit(model_probability) - market_logit
    return _sigmoid(market_logit + float(weight) * delta)


def fit_ml_v4(rows: Iterable[tuple[float, float, int]], *, minimum_prior: int = MIN_PRIOR) -> MlV4Fit:
    """Fit ML V4 using strictly prior rows: (exact_avg, Pinnacle no-vig, home_win)."""
    material = [(float(pm), float(pk), int(y)) for pm, pk, y in rows]
    n = len(material)
    if n < int(minimum_prior):
        return MlV4Fit(None, None, None, n, False, "insufficient_prior_support")
    ys = np.asarray([y for _, _, y in material], dtype=int)
    if len(set(ys.tolist())) < 2:
        return MlV4Fit(None, None, None, n, False, "single_class_prior")

    X = np.asarray([[_logit(pk)] for _, pk, _ in material], dtype=float)
    market = LogisticRegression(C=1.0, max_iter=2000, solver="lbfgs")
    market.fit(X, ys)
    intercept = float(market.intercept_[0])
    slope = float(market.coef_[0][0])
    if not math.isfinite(intercept) or not math.isfinite(slope):
        return MlV4Fit(intercept, slope, None, n, False, "nonfinite_market_calibration")
    if slope <= 0.0:
        return MlV4Fit(intercept, slope, None, n, False, "nonpositive_market_calibration_slope")

    triples: list[tuple[float, float, int]] = []
    for p_model, p_pin, y in material:
        p_market_cal = _sigmoid(intercept + slope * _logit(p_pin))
        triples.append((_logit(p_market_cal), _logit(p_model) - _logit(p_market_cal), y))

    def grad(weight: float) -> float:
        return float(np.mean([d * (_sigmoid(a + weight * d) - y) for a, d, y in triples]))

    g0 = grad(0.0)
    g1 = grad(1.0)
    if not math.isfinite(g0) or not math.isfinite(g1):
        return MlV4Fit(intercept, slope, None, n, False, "nonfinite_model_pool_fit")
    if g0 >= 0.0:
        weight = 0.0
    elif g1 <= 0.0:
        weight = 1.0
    else:
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = (lo + hi) / 2.0
            if grad(mid) <= 0.0:
                lo = mid
            else:
                hi = mid
        weight = (lo + hi) / 2.0
    return MlV4Fit(intercept, slope, float(weight), n, True, None)


def final_ml_home_probability(exact_avg_home: float, raw_pinnacle_home: float, fit: MlV4Fit) -> float:
    if not fit.supported or fit.model_weight is None:
        raise ValueError("ML V4 state is unsupported")
    p_market = calibrated_market_probability(raw_pinnacle_home, fit)
    return pooled_probability(exact_avg_home, p_market, fit.model_weight)


def robust_market_scale(residuals_to_threshold: Iterable[float]) -> float | None:
    vals = np.asarray([float(x) for x in residuals_to_threshold], dtype=float)
    if vals.size < 2:
        return None
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals - med)))
    sigma = 1.4826 * mad
    if not math.isfinite(sigma) or sigma <= 1e-9:
        sigma = float(np.std(vals, ddof=1))
    if not math.isfinite(sigma) or sigma <= 1e-9:
        return None
    return sigma


def conditional_above_probability(
    mu: float,
    threshold: float,
    sigma: float,
    *,
    push_possible: bool,
) -> float:
    """P(above | non-push) under the continuous score-location approximation."""
    if sigma <= 0.0:
        raise ValueError("sigma must be positive")
    t = float(threshold)
    if not push_possible:
        return 1.0 - float(_NORMAL.cdf((t - float(mu)) / float(sigma)))
    lo = t - 0.5
    hi = t + 0.5
    p_loss = float(_NORMAL.cdf((lo - float(mu)) / float(sigma)))
    p_win = 1.0 - float(_NORMAL.cdf((hi - float(mu)) / float(sigma)))
    den = p_win + p_loss
    if den <= 0.0:
        raise ValueError("zero non-push mass")
    return p_win / den


def market_implied_mean(
    threshold: float,
    probability_above_nonpush: float,
    sigma: float,
    *,
    push_possible: bool,
) -> float:
    """Infer the sharp-market mean from paired no-vig odds at one exact line."""
    p = _clip_p(probability_above_nonpush)
    t = float(threshold)
    s = float(sigma)
    if s <= 0.0:
        raise ValueError("sigma must be positive")
    if not push_possible:
        return t + s * float(_NORMAL.inv_cdf(p))

    # q(mu)=P(above|non-push) is strictly increasing in mu. Wide deterministic
    # bounds avoid optimizer/grid choices and recover the unique mean.
    lo = t - 12.0 * s
    hi = t + 12.0 * s
    for _ in range(100):
        mid = (lo + hi) / 2.0
        q = conditional_above_probability(mid, t, s, push_possible=True)
        if q < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def fit_point_v3(
    rows: Iterable[tuple[float, float, float, bool, float]],
    *,
    minimum_prior: int = MIN_PRIOR,
) -> PointV3Fit:
    """Fit corrected V3 rows: (model, threshold, q_above_nonpush, push_possible, actual)."""
    material = [
        (float(model), float(threshold), float(q), bool(push_possible), float(actual))
        for model, threshold, q, push_possible, actual in rows
    ]
    n = len(material)
    if n < int(minimum_prior):
        return PointV3Fit(None, None, None, tuple(), n, False, "insufficient_prior_support")
    sigma = robust_market_scale(actual - threshold for _, threshold, _, _, actual in material)
    if sigma is None:
        return PointV3Fit(None, None, None, tuple(), n, False, "invalid_robust_scale")

    market_means = [
        market_implied_mean(threshold, q, sigma, push_possible=push_possible)
        for _, threshold, q, push_possible, _ in material
    ]
    d = np.asarray([model - mu for (model, _, _, _, _), mu in zip(material, market_means)], dtype=float)
    y = np.asarray([actual - mu for (_, _, _, _, actual), mu in zip(material, market_means)], dtype=float)
    denom = float(np.dot(d, d))
    if not math.isfinite(denom) or denom <= 1e-12:
        return PointV3Fit(sigma, None, None, tuple(), n, False, "degenerate_disagreement_variance")
    beta_raw = float(np.dot(d, y) / denom)
    if not math.isfinite(beta_raw):
        return PointV3Fit(sigma, beta_raw, None, tuple(), n, False, "nonfinite_fit")
    beta = min(1.0, max(0.0, beta_raw))
    residuals = tuple(
        actual - (mu + beta * (model - mu))
        for (model, _, _, _, actual), mu in zip(material, market_means)
    )
    return PointV3Fit(sigma, beta_raw, beta, residuals, n, True, None)


def calibrated_point_mean(
    model_value: float,
    threshold: float,
    probability_above_nonpush: float,
    push_possible: bool,
    fit: PointV3Fit,
) -> tuple[float, float]:
    if not fit.supported or fit.sigma is None or fit.beta is None:
        raise ValueError("point V3 state is unsupported")
    mu_market = market_implied_mean(
        threshold,
        probability_above_nonpush,
        fit.sigma,
        push_possible=push_possible,
    )
    mu = mu_market + float(fit.beta) * (float(model_value) - mu_market)
    return mu, mu_market
