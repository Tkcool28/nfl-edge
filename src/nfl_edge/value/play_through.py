"""Frozen global Play Through presentation policy (1.5pp maximum concession)."""
from __future__ import annotations

from dataclasses import dataclass
import math

from .reliability import RELIABILITY_HAIRCUT, uncertainty_factor

MAX_BREAK_EVEN_CONCESSION = 0.015
STATUSES = ("VALUE", "PLAYABLE", "LEAN", "PASS", "UNSUPPORTED")


@dataclass(frozen=True)
class PlayThroughAssessment:
    confidence_multiplier: float
    break_even_concession: float
    play_through_break_even_probability: float | None
    play_through_decimal_price: float | None
    play_through_price_american: int | None
    status: str


def confidence_multiplier(reliability: str, uncertainty_radius: float | None) -> float:
    if reliability not in RELIABILITY_HAIRCUT:
        raise ValueError(f"unknown reliability {reliability}")
    return float(RELIABILITY_HAIRCUT[reliability]) * uncertainty_factor(uncertainty_radius)


def conservative_american_threshold(decimal_price: float) -> int:
    dec = float(decimal_price)
    if dec <= 1.0:
        raise ValueError("decimal odds must exceed 1")
    raw = (dec - 1.0) * 100.0 if dec >= 2.0 else -100.0 / (dec - 1.0)
    return int(math.ceil(raw - 1e-12))


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
    if not supported or reliability == "UNSUPPORTED":
        return PlayThroughAssessment(0.0, 0.0, None, None, None, "UNSUPPORTED")
    if (
        strict_expected_value is None
        or conditional_nonpush_probability is None
        or current_break_even_probability is None
    ):
        return PlayThroughAssessment(0.0, 0.0, None, None, None, "PASS")
    q = float(conditional_nonpush_probability)
    if not 0.0 < q < 1.0:
        raise ValueError("conditional non-push probability must be in (0,1)")
    confidence = confidence_multiplier(reliability, uncertainty_radius)
    concession = float(maximum_concession) * confidence
    q_play = min(0.99, q + concession)
    decimal_play = 1.0 / q_play
    price = conservative_american_threshold(decimal_play)
    ev = float(strict_expected_value)
    current_be = float(current_break_even_probability)
    if ev > 0.0:
        status = "VALUE"
    elif current_be <= q_play + 1e-12:
        status = "PLAYABLE"
    else:
        status = "LEAN"
    return PlayThroughAssessment(confidence, concession, q_play, decimal_play, price, status)
