"""Task05F evaluator-unit staking V2.

The evaluator assigns wager units. The user selects only a global bankroll risk
style. PLAYABLE wagers receive a reduced nonzero stake inside the frozen Play
Through corridor; strict VALUE wagers receive 1-2 units from existing confidence
and relative positive edge. Historical outcomes are never inputs.

Contract: config/task05f_staking_v2_units_prereg.yaml
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
import math
from typing import Any, Mapping

from nfl_edge.user.staking_profile_v2 import UserRiskProfile
from nfl_edge.value.candidate_table import OUTCOME_FIELDS
from nfl_edge.value.staking import full_kelly_fraction


ALLOWED_RELIABILITY = frozenset({"HIGH", "MEDIUM"})
GLOBAL_WAGER_CAP_FRACTION = 0.05
MAX_UNITS = 2.0


@dataclass(frozen=True)
class UnitStakeRecommendation:
    risk_style: str
    bankroll: float
    price_status: str
    recommended_units: float
    unit_fraction_of_bankroll: float
    raw_stake_fraction: float
    recommended_stake_fraction: float
    recommended_stake: float
    unit_reason: str
    exposure_cap_fraction: float
    current_open_exposure_amount: float | None
    exposure_capacity_remaining: float | None
    exposure_cap_applied: bool
    style_warning: str | None
    internal_full_kelly_fraction: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finite(value: Any) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _clip(value: float, low: float, high: float) -> float:
    return min(high, max(low, float(value)))


def _round_half_up(value: float) -> float:
    return float(Decimal(str(float(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _floor_currency(value: float) -> float:
    return float(Decimal(str(max(0.0, float(value)))).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _round_with_cap(value: float, cap_amount: float) -> float:
    rounded = _round_half_up(min(float(value), float(cap_amount)))
    if rounded <= float(cap_amount) + 1e-12:
        return rounded
    return _floor_currency(cap_amount)


def _validate_candidate(candidate: Mapping[str, Any]) -> None:
    leaked = OUTCOME_FIELDS.intersection(candidate)
    if leaked:
        raise RuntimeError(f"staking v2 candidate contains forbidden outcome fields: {sorted(leaked)}")
    season = candidate.get("season")
    if season is not None and int(season) == 2025:
        raise RuntimeError("sealed season 2025 cannot enter staking v2 development")


def playable_units(candidate: Mapping[str, Any]) -> float:
    current = candidate.get("break_even_probability")
    fair = candidate.get("actionable_probability")
    through = candidate.get("play_through_break_even_probability")
    if not all(_finite(value) for value in (current, fair, through)):
        raise ValueError("PLAYABLE requires current, fair, and Play Through break-even probabilities")
    current_f = float(current)
    fair_f = float(fair)
    through_f = float(through)
    width = through_f - fair_f
    if width <= 0.0:
        raise ValueError("invalid Play Through corridor")
    position = _clip((current_f - fair_f) / width, 0.0, 1.0)
    return 1.0 - 0.5 * position


def value_units(candidate: Mapping[str, Any]) -> float:
    edge = candidate.get("evaluated_edge_probability")
    confidence = candidate.get("play_through_confidence_multiplier")
    concession = candidate.get("play_through_break_even_concession")
    if not all(_finite(value) for value in (edge, confidence, concession)):
        raise ValueError("VALUE requires edge, confidence, and Play Through concession")
    edge_f = max(0.0, float(edge))
    confidence_f = _clip(float(confidence), 0.0, 1.0)
    concession_f = max(0.0, float(concession))
    if edge_f <= 0.0:
        raise ValueError("VALUE unit calculation requires positive evaluated edge")
    denominator = edge_f + concession_f
    edge_share = 1.0 if denominator <= 0.0 else edge_f / denominator
    return _clip(1.0 + confidence_f * edge_share, 1.0, MAX_UNITS)


def evaluator_units(candidate: Mapping[str, Any]) -> tuple[float, str]:
    _validate_candidate(candidate)
    if not bool(candidate.get("supported")):
        return 0.0, "UNSUPPORTED"
    if str(candidate.get("reliability", "")) not in ALLOWED_RELIABILITY:
        return 0.0, "LOW_RELIABILITY"

    status = str(candidate.get("price_status", ""))
    if status == "PLAYABLE":
        try:
            return playable_units(candidate), "STAKE_RECOMMENDED_PLAYABLE"
        except ValueError:
            return 0.0, "INVALID_PLAY_THROUGH_CORRIDOR"
    if status == "VALUE":
        if candidate.get("strict_positive_value") is not True:
            return 0.0, "STATUS_NOT_ACTIONABLE"
        try:
            return value_units(candidate), "STAKE_RECOMMENDED_VALUE"
        except ValueError:
            return 0.0, "STATUS_NOT_ACTIONABLE"
    return 0.0, "STATUS_NOT_ACTIONABLE"


def _internal_kelly(candidate: Mapping[str, Any]) -> float | None:
    p = candidate.get("staking_probability")
    price = candidate.get("actionable_decimal_price")
    if not _finite(p) or not _finite(price):
        return None
    try:
        return float(full_kelly_fraction(float(price), float(p)))
    except ValueError:
        return None


def recommend_stake_v2(
    candidate: Mapping[str, Any],
    profile: UserRiskProfile,
    *,
    current_open_exposure_amount: float | None = None,
) -> UnitStakeRecommendation:
    """Convert evaluator-owned units to one user-specific dollar recommendation."""
    _validate_candidate(candidate)
    units, reason = evaluator_units(candidate)
    bankroll = float(profile.bankroll)
    unit_fraction = float(profile.fraction_of_bankroll_per_unit)
    exposure_cap_fraction = float(profile.open_slate_exposure_cap_fraction)
    internal_kelly = _internal_kelly(candidate)

    if current_open_exposure_amount is not None:
        exposure = float(current_open_exposure_amount)
        if not math.isfinite(exposure) or exposure < 0.0:
            raise ValueError("current_open_exposure_amount must be finite and nonnegative")
        if exposure > bankroll:
            raise ValueError("current_open_exposure_amount cannot exceed bankroll")
        capacity = max(0.0, exposure_cap_fraction * bankroll - exposure)
    else:
        exposure = None
        capacity = None

    raw_fraction = max(0.0, units * unit_fraction)
    style_two_unit_cap = MAX_UNITS * unit_fraction
    final_fraction = min(raw_fraction, style_two_unit_cap, GLOBAL_WAGER_CAP_FRACTION)
    raw_amount = bankroll * final_fraction
    absolute_cap_amount = bankroll * min(style_two_unit_cap, GLOBAL_WAGER_CAP_FRACTION)
    exposure_applied = False

    if capacity is not None:
        if capacity <= 0.0:
            units_out = units
            return UnitStakeRecommendation(
                risk_style=profile.risk_style.value,
                bankroll=bankroll,
                price_status=str(candidate.get("price_status", "")),
                recommended_units=float(units_out),
                unit_fraction_of_bankroll=unit_fraction,
                raw_stake_fraction=raw_fraction,
                recommended_stake_fraction=0.0,
                recommended_stake=0.0,
                unit_reason="EXPOSURE_CAP_REACHED",
                exposure_cap_fraction=exposure_cap_fraction,
                current_open_exposure_amount=exposure,
                exposure_capacity_remaining=0.0,
                exposure_cap_applied=True,
                style_warning=profile.style_warning,
                internal_full_kelly_fraction=internal_kelly,
            )
        if capacity < raw_amount:
            exposure_applied = True
        absolute_cap_amount = min(absolute_cap_amount, capacity)

    if units <= 0.0 or raw_amount <= 0.0:
        return UnitStakeRecommendation(
            risk_style=profile.risk_style.value,
            bankroll=bankroll,
            price_status=str(candidate.get("price_status", "")),
            recommended_units=float(units),
            unit_fraction_of_bankroll=unit_fraction,
            raw_stake_fraction=raw_fraction,
            recommended_stake_fraction=0.0,
            recommended_stake=0.0,
            unit_reason=reason,
            exposure_cap_fraction=exposure_cap_fraction,
            current_open_exposure_amount=exposure,
            exposure_capacity_remaining=capacity,
            exposure_cap_applied=False,
            style_warning=profile.style_warning,
            internal_full_kelly_fraction=internal_kelly,
        )

    rounded = _round_with_cap(raw_amount, absolute_cap_amount)
    if rounded <= 0.0:
        final_reason = "EXPOSURE_CAP_REACHED" if exposure_applied else "ROUNDED_TO_ZERO"
        return UnitStakeRecommendation(
            risk_style=profile.risk_style.value,
            bankroll=bankroll,
            price_status=str(candidate.get("price_status", "")),
            recommended_units=float(units),
            unit_fraction_of_bankroll=unit_fraction,
            raw_stake_fraction=raw_fraction,
            recommended_stake_fraction=0.0,
            recommended_stake=0.0,
            unit_reason=final_reason,
            exposure_cap_fraction=exposure_cap_fraction,
            current_open_exposure_amount=exposure,
            exposure_capacity_remaining=capacity,
            exposure_cap_applied=exposure_applied,
            style_warning=profile.style_warning,
            internal_full_kelly_fraction=internal_kelly,
        )

    return UnitStakeRecommendation(
        risk_style=profile.risk_style.value,
        bankroll=bankroll,
        price_status=str(candidate.get("price_status", "")),
        recommended_units=float(units),
        unit_fraction_of_bankroll=unit_fraction,
        raw_stake_fraction=raw_fraction,
        recommended_stake_fraction=float(rounded / bankroll),
        recommended_stake=rounded,
        unit_reason=reason,
        exposure_cap_fraction=exposure_cap_fraction,
        current_open_exposure_amount=exposure,
        exposure_capacity_remaining=capacity,
        exposure_cap_applied=exposure_applied,
        style_warning=profile.style_warning,
        internal_full_kelly_fraction=internal_kelly,
    )
