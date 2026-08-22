"""Task05F evaluator-only V3 calibration primitives.

V3 uses the complete Pinnacle market anchor (line plus no-vig price) while
keeping all football models frozen.  Formulas are preregistered in
config/task05f_evaluator_rebuild_v3_prereg.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import NormalDist
from typing import Iterable

import numpy as np


_NORMAL = NormalDist()


@dataclass(frozen=True)
class LogitPoolCalibration:
    weight: float | None
    support_n: int
    supported: bool
    reason: str | None = None


@dataclass(frozen=True)
class PriceAwarePointCalibration:
    sigma: float | None
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
    if x >= 0.0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _pool_probability(model_probability: float, market_probability: float, weight: float) -> float:
    a = _logit(market_probability)
    d = _logit(model_probability) - a
    return _sigmoid(a + float(weight) * d)


def fit_logit_pool_calibration(
    rows: Iterable[tuple[float, float, int]],
    *,
    minimum_prior: int = 128,
) -> LogitPoolCalibration:
    """Fit the preregistered scalar proper-scoring ML pool.

    Rows are ``(p_model, p_market, y)`` for prior non-tie home outcomes.  The
    binary log-loss objective is convex in ``w`` for

        logit(p) = logit(p_market) + w*(logit(p_model)-logit(p_market)).

    The derivative is monotone, so deterministic bisection finds the bounded
    optimum without a hyperparameter grid or ROI objective.
    """
    material = [(float(pm), float(pk), int(y)) for pm, pk, y in rows]
    n = len(material)
    if n < int(minimum_prior):
        return LogitPoolCalibration(None, n, False, "insufficient_prior_support")
    if len({y for _, _, y in material}) < 2:
        return LogitPoolCalibration(None, n, False, "single_class_prior")

    triples = [(_logit(pk), _logit(pm) - _logit(pk), y) for pm, pk, y in material]

    def grad(w: float) -> float:
        return float(
            np.mean([
                d * (_sigmoid(a + float(w) * d) - y)
                for a, d, y in triples
            ])
        )

    g0 = grad(0.0)
    g1 = grad(1.0)
    if not math.isfinite(g0) or not math.isfinite(g1):
        return LogitPoolCalibration(None, n, False, "nonfinite_fit")
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
    return LogitPoolCalibration(float(weight), n, True, None)


def pooled_probability(
    model_probability: float,
    market_probability: float,
    state: LogitPoolCalibration,
) -> float:
    if not state.supported or state.weight is None:
        raise ValueError("logit pool calibration state is unsupported")
    return _pool_probability(model_probability, market_probability, state.weight)


def robust_market_scale(residuals_to_market_threshold: Iterable[float]) -> float | None:
    """Prior-only robust score scale preregistered for point-market anchoring."""
    vals = np.asarray([float(x) for x in residuals_to_market_threshold], dtype=float)
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


def market_implied_mean(
    market_threshold: float,
    market_probability_above_threshold: float,
    sigma: float,
) -> float:
    """Convert a Pinnacle line+no-vig probability into a continuous market mean.

    If X ~ Normal(mu, sigma), then P(X > threshold)=p implies
    ``mu = threshold + sigma*Phi^-1(p)``.  The no-vig Pinnacle probability is
    interpreted conditional on non-push; explicit push mass is handled later by
    the existing integer-lattice wager economics.
    """
    p = _clip_p(market_probability_above_threshold)
    return float(market_threshold) + float(sigma) * float(_NORMAL.inv_cdf(p))


def fit_price_aware_point_calibration(
    rows: Iterable[tuple[float, float, float, float]],
    *,
    minimum_prior: int = 128,
) -> PriceAwarePointCalibration:
    """Fit the preregistered line+price market anchor with one model slope.

    Each row is ``(model_value, market_threshold, p_above_threshold, actual)``.
    A robust prior-only scale first converts Pinnacle line+price into a market
    mean.  The frozen model then receives one globally fitted coefficient beta,
    constrained to [0,1], using squared-error geometry only.  ROI and actionable
    sportsbook prices never enter the fit.
    """
    material = [
        (float(model), float(threshold), float(p_market), float(actual))
        for model, threshold, p_market, actual in rows
    ]
    n = len(material)
    if n < int(minimum_prior):
        return PriceAwarePointCalibration(None, None, None, n, tuple(), False, "insufficient_prior_support")

    sigma = robust_market_scale(actual - threshold for _, threshold, _, actual in material)
    if sigma is None:
        return PriceAwarePointCalibration(None, None, None, n, tuple(), False, "invalid_robust_scale")

    market_means = [
        market_implied_mean(threshold, p_market, sigma)
        for _, threshold, p_market, _ in material
    ]
    d = np.asarray([
        model - mu_market
        for (model, _, _, _), mu_market in zip(material, market_means)
    ], dtype=float)
    y = np.asarray([
        actual - mu_market
        for (_, _, _, actual), mu_market in zip(material, market_means)
    ], dtype=float)
    denom = float(np.dot(d, d))
    if not math.isfinite(denom) or denom <= 1e-12:
        return PriceAwarePointCalibration(sigma, None, None, n, tuple(), False, "degenerate_disagreement_variance")
    beta_raw = float(np.dot(d, y) / denom)
    if not math.isfinite(beta_raw):
        return PriceAwarePointCalibration(sigma, None, None, n, tuple(), False, "nonfinite_fit")
    beta = min(1.0, max(0.0, beta_raw))
    residuals = tuple(
        actual - (mu_market + beta * (model - mu_market))
        for (model, _, _, actual), mu_market in zip(material, market_means)
    )
    return PriceAwarePointCalibration(sigma, beta_raw, beta, n, residuals, True, None)


def calibrated_point_mean(
    model_value: float,
    market_threshold: float,
    market_probability_above_threshold: float,
    state: PriceAwarePointCalibration,
) -> float:
    if not state.supported or state.sigma is None or state.beta is None:
        raise ValueError("price-aware point calibration state is unsupported")
    mu_market = market_implied_mean(
        market_threshold,
        market_probability_above_threshold,
        state.sigma,
    )
    return mu_market + float(state.beta) * (float(model_value) - mu_market)
