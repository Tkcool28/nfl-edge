"""Global Task05F Play Through price/presentation policy.

Play Through is downstream of the locked evaluator and Phase F reliability.
It never changes evaluator probability, expected value, strict VALUE, football
model output, or staking probability. Formula is preregistered in
config/task05f_play_through_v1_prereg.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from .locked_reliability import RELIABILITY_HAIRCUT, uncertainty_factor


STATUSES = ("VALUE", "PLAYABLE", "LEAN", "PASS")
MAX_BREAK_EVEN_CONCESSION = 0.01


@dataclass(frozen=True)
class PlayThroughAssessment:
    confidence_multiplier: float
    break_even_concession: float
    play_through_break_even_probability: float | None
    play_through_decimal_price: float | None
    play_through_price_american: int | None
    status: str


def confidence_multiplier(reliability: str, uncertainty_radius: float | None) -> float:
    """Confidence scalar already implied by the accepted Phase F haircuts."""
    if reliability not in RELIABILITY_HAIRCUT:
        raise ValueError(f"unknown reliability {reliability}")
    return float(RELIABILITY_HAIRCUT[reliability]) * uncertainty_factor(uncertainty_radius)


def conservative_american_threshold(decimal_price: float) -> int:
    """Minimum integer American price that is never worse than decimal_price.

    American odds are monotone in bettor quality: +105 > +100 and -105 > -110.
    We therefore round the continuous American threshold upward, not to nearest.
    """
    dec = float(decimal_price)
    if dec <= 1.0:
        raise ValueError("decimal odds must exceed 1")
    raw = (dec - 1.0) * 100.0 if dec >= 2.0 else -100.0 / (dec - 1.0)
    return int(math.ceil(raw - 1e-12))


def play_through_limit(
    conditional_nonpush_probability: float,
    reliability: str,
    uncertainty_radius: float | None,
    *,
    maximum_concession: float = MAX_BREAK_EVEN_CONCESSION,
) -> tuple[float, float, float, int]:
    """Return confidence, concession, maximum break-even, and display price."""
    q = float(conditional_nonpush_probability)
    if not 0.0 < q < 1.0:
        raise ValueError("conditional non-push probability must be in (0,1)")
    if maximum_concession < 0.0:
        raise ValueError("maximum concession cannot be negative")
    confidence = confidence_multiplier(reliability, uncertainty_radius)
    concession = float(maximum_concession) * confidence
    q_play = min(0.99, q + concession)
    decimal_play = 1.0 / q_play
    american_play = conservative_american_threshold(decimal_play)
    return confidence, concession, q_play, american_play


def assess_play_through(
    *,
    supported: bool,
    strict_expected_value: float | None,
    conditional_nonpush_probability: float | None,
    current_break_even_probability: float | None,
    reliability: str,
    uncertainty_radius: float | None,
    maximum_concession: float = MAX_BREAK_EVEN_CONCESSION,
) -> PlayThroughAssessment:
    """Classify VALUE / PLAYABLE / LEAN / PASS without redefining Value."""
    if (
        not supported
        or reliability == "UNSUPPORTED"
        or strict_expected_value is None
        or conditional_nonpush_probability is None
        or current_break_even_probability is None
    ):
        return PlayThroughAssessment(0.0, 0.0, None, None, None, "PASS")

    confidence, concession, q_play, price = play_through_limit(
        float(conditional_nonpush_probability),
        reliability,
        uncertainty_radius,
        maximum_concession=maximum_concession,
    )
    decimal_play = 1.0 / q_play
    ev = float(strict_expected_value)
    current_be = float(current_break_even_probability)
    if ev > 0.0:
        status = "VALUE"
    elif current_be <= q_play + 1e-12:
        status = "PLAYABLE"
    else:
        status = "LEAN"
    return PlayThroughAssessment(
        confidence,
        concession,
        q_play,
        decimal_play,
        price,
        status,
    )
