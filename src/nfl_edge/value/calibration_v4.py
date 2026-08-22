"""Task05F ML-only V4 evaluator calibration.

V4 first calibrates Pinnacle no-vig probability itself, then optionally pools
in the frozen exact-AVG football signal using only prior proper scoring.
Formulas are locked in config/task05f_ml_v4_prereg.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .calibration_v2 import (
    MonotoneLogitCalibration,
    calibrated_probability,
    fit_monotone_logit_calibration,
)
from .calibration_v3 import (
    LogitPoolCalibration,
    fit_logit_pool_calibration,
    pooled_probability,
)


@dataclass(frozen=True)
class MlV4Calibration:
    market: MonotoneLogitCalibration
    pool: LogitPoolCalibration
    support_n: int
    supported: bool
    reason: str | None = None


def fit_ml_v4_calibration(
    rows: Iterable[tuple[float, float, int]],
    *,
    minimum_prior: int = 128,
) -> MlV4Calibration:
    """Fit the preregistered two-stage ML fair-value calibrator.

    Each row is ``(p_model_exact_avg, p_pinnacle_no_vig, home_win_binary)``.
    Both stages use only prior non-tie outcomes.  DK/FD prices, ROI, market
    buckets, and frozen Task05E membership never enter either fit.
    """
    material = [(float(pm), float(pk), int(y)) for pm, pk, y in rows]
    n = len(material)
    market_state = fit_monotone_logit_calibration(
        [(pk, y) for _, pk, y in material],
        minimum_prior=minimum_prior,
        C=1.0,
    )
    if not market_state.supported:
        empty_pool = LogitPoolCalibration(None, n, False, market_state.reason)
        return MlV4Calibration(market_state, empty_pool, n, False, market_state.reason)

    pooled_rows = [
        (pm, calibrated_probability(pk, market_state), y)
        for pm, pk, y in material
    ]
    pool_state = fit_logit_pool_calibration(
        pooled_rows,
        minimum_prior=minimum_prior,
    )
    if not pool_state.supported:
        return MlV4Calibration(market_state, pool_state, n, False, pool_state.reason)
    return MlV4Calibration(market_state, pool_state, n, True, None)


def calibrated_market_probability(
    pinnacle_no_vig_probability: float,
    state: MlV4Calibration,
) -> float:
    if not state.supported:
        raise ValueError("ML V4 calibration state is unsupported")
    return calibrated_probability(pinnacle_no_vig_probability, state.market)


def final_ml_probability(
    exact_avg_probability: float,
    pinnacle_no_vig_probability: float,
    state: MlV4Calibration,
) -> float:
    if not state.supported:
        raise ValueError("ML V4 calibration state is unsupported")
    p_market_cal = calibrated_market_probability(pinnacle_no_vig_probability, state)
    return pooled_probability(exact_avg_probability, p_market_cal, state.pool)
