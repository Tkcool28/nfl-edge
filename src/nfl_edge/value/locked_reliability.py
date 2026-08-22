"""Candidate-specific reliability/uncertainty for the locked Task05F evaluator.

This module is downstream of the frozen probability evaluator. It never
changes p_win/p_push/p_loss, fair price, expected value, or strict Value.

The formulas are preregistered in the Task05F Phase F reliability contracts.
The v1.1 correction requires point-market staking anchors to represent the
same exact actionable wager event rather than Pinnacle probability at a
possibly different line.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist
from typing import Iterable, Literal

from .calibration_v3 import market_implied_mean
from .uncertainty import block_bootstrap_calibration_radius


_NORMAL = NormalDist()

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


def exact_point_market_anchor_probability(
    pinnacle_threshold: float,
    pinnacle_probability_above: float,
    market_scale: float,
    actionable_threshold: float,
    direction: Literal["above", "below"],
    *,
    push_possible: bool,
) -> float:
    """Translate the V3 sharp-market distribution to one exact point wager.

    V3 stores a price-aware Pinnacle threshold, the no-vig probability of the
    score being above that threshold, and a prior-only score scale. Together
    they imply a continuous sharp-market mean. This function evaluates that
    SAME distribution at the actionable DK/FD threshold.

    The return value is conditional on a non-push settlement, matching the
    staking-probability contract. Integer lines reserve the one-score push cell
    [threshold-0.5, threshold+0.5); half-point lines have no push mass.
    """
    sigma = float(market_scale)
    if sigma <= 0.0:
        raise ValueError("market scale must be positive")
    if direction not in {"above", "below"}:
        raise ValueError("direction must be above or below")

    mu = market_implied_mean(
        float(pinnacle_threshold),
        float(pinnacle_probability_above),
        sigma,
    )
    threshold = float(actionable_threshold)

    if not push_possible:
        p_below = float(_NORMAL.cdf((threshold - mu) / sigma))
        p_above = 1.0 - p_below
        return p_above if direction == "above" else p_below

    lo = threshold - 0.5
    hi = threshold + 0.5
    cdf_lo = float(_NORMAL.cdf((lo - mu) / sigma))
    cdf_hi = float(_NORMAL.cdf((hi - mu) / sigma))
    if direction == "above":
        p_win = 1.0 - cdf_hi
        p_loss = cdf_lo
    else:
        p_win = cdf_lo
        p_loss = 1.0 - cdf_hi
    den = p_win + p_loss
    if den <= 0.0:
        raise ValueError("exact-offer market anchor has zero non-push mass")
    return p_win / den


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

    Probabilities here are conditional on a non-push settlement. The market
    anchor MUST represent the same wager event as evaluator_probability. This
    function reduces the magnitude of evaluator disagreement; it does not
    create evaluator edge.
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
