"""Candidate-specific reliability/uncertainty for the locked Task05F evaluator.

This module is downstream of the frozen probability evaluator.  It never
changes p_win/p_push/p_loss, fair price, expected value, or strict Value.

The formulas are preregistered in
config/task05f_reliability_uncertainty_v1_prereg.yaml and reuse the original
Task05F block-bootstrap and reliability-haircut design.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .uncertainty import block_bootstrap_calibration_radius


RELIABILITY_ORDER = {
    "HIGH": 0,
    "MEDIUM": 1,
    "LOW": 2,
    "UNSUPPORTED": 3,
}
RELIABILITY_HAIRCUT = {
    "HIGH": 1.0,
    "MEDIUM": 0.70,
    "LOW": 0.35,
    "UNSUPPORTED": 0.0,
}


@dataclass(frozen=True)
class CandidateUncertaintyState:
    radius: float | None
    support_n: int
    block_count: int
    tier: str
    stable: bool


def conditional_nonpush_probability(p_win: float, p_push: float, p_loss: float) -> float:
    """Selected-side win probability conditional on a non-push settlement."""
    win = float(p_win)
    push = float(p_push)
    loss = float(p_loss)
    if min(win, push, loss) < 0.0:
        raise ValueError("outcome probabilities cannot be negative")
    den = win + loss
    if den <= 0.0:
        raise ValueError("conditional non-push probability undefined with zero non-push mass")
    return win / den


def fit_candidate_uncertainty(
    rows: Iterable[tuple[str, float, int]],
    *,
    minimum_rows: int = 128,
    minimum_blocks: int = 4,
    replicates: int = 1000,
    seed: int = 20260820,
    quantile: float = 0.90,
    stability_max_radius: float = 0.05,
) -> CandidateUncertaintyState:
    """Fit prior-OOS market-level calibration uncertainty.

    Each input row is ``(season_week_block, conditional_nonpush_probability,
    observed_win_binary)`` and must already be strictly prior/out-of-sample.
    """
    material = [(str(b), float(p), int(y)) for b, p, y in rows]
    n = len(material)
    blocks = len({b for b, _, _ in material})
    if n < int(minimum_rows):
        return CandidateUncertaintyState(None, n, blocks, "LOW", False)

    radius = float(
        block_bootstrap_calibration_radius(
            material,
            replicates=int(replicates),
            seed=int(seed),
            quantile=float(quantile),
        )
    )
    stable = blocks >= int(minimum_blocks) and radius <= float(stability_max_radius)
    if stable and n >= 512 and 0.0 < radius <= 0.025:
        tier = "HIGH"
    elif stable and n >= 256 and 0.0 < radius <= 0.045:
        tier = "MEDIUM"
    else:
        tier = "LOW"
    return CandidateUncertaintyState(radius, n, blocks, tier, stable)


def cap_reliability(base_reliability: str, candidate_tier: str) -> str:
    """Candidate uncertainty may only preserve or lower the base support tier."""
    if base_reliability not in RELIABILITY_ORDER:
        raise ValueError(f"unknown base reliability {base_reliability}")
    if candidate_tier not in RELIABILITY_ORDER:
        raise ValueError(f"unknown candidate reliability {candidate_tier}")
    return max(
        (base_reliability, candidate_tier),
        key=lambda value: RELIABILITY_ORDER[value],
    )


def uncertainty_factor(radius: float | None, *, scale: float = 0.10) -> float:
    """Original Task05F deterministic uncertainty haircut factor."""
    if radius is None:
        return 0.0
    if scale <= 0.0:
        raise ValueError("uncertainty scale must be positive")
    return max(0.0, 1.0 - min(1.0, float(radius) / float(scale)))


def conservative_staking_probability(
    evaluator_probability: float,
    market_anchor_probability: float,
    reliability: str,
    radius: float | None,
    *,
    clip_low: float = 0.01,
    clip_high: float = 0.99,
) -> float:
    """Shrink evaluator edge toward the market for bankroll sizing.

    Probabilities here are conditional on a non-push settlement.  The market
    anchor is the selected-side sharp-market benchmark.  This function reduces
    the magnitude of evaluator disagreement; it does not create evaluator edge.
    """
    q = float(evaluator_probability)
    anchor = float(market_anchor_probability)
    if not 0.0 <= q <= 1.0 or not 0.0 <= anchor <= 1.0:
        raise ValueError("staking probabilities must be in [0,1]")
    if reliability not in RELIABILITY_HAIRCUT:
        raise ValueError(f"unknown reliability {reliability}")
    h = RELIABILITY_HAIRCUT[reliability]
    u = uncertainty_factor(radius)
    value = anchor + h * u * (q - anchor)
    return min(float(clip_high), max(float(clip_low), value))


def staking_outcome_probabilities(
    staking_probability: float,
    p_push: float,
) -> tuple[float, float, float]:
    """Return staking WIN/PUSH/LOSS mass while preserving evaluator push mass."""
    q = float(staking_probability)
    push = float(p_push)
    if not 0.0 <= q <= 1.0 or not 0.0 <= push <= 1.0:
        raise ValueError("probabilities must be in [0,1]")
    nonpush = 1.0 - push
    return nonpush * q, push, nonpush * (1.0 - q)


def expected_value_from_decimal(
    p_win: float,
    p_loss: float,
    decimal_odds: float,
) -> float:
    """Expected one-unit profit with push contributing zero."""
    dec = float(decimal_odds)
    if dec <= 1.0:
        raise ValueError("decimal odds must exceed 1")
    return float(p_win) * (dec - 1.0) - float(p_loss)
