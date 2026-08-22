"""Task05F staking V2.1: evaluator units without a LOW-reliability hard veto.

All V2 unit formulas, user risk styles, per-wager caps, and exposure caps remain
unchanged. The only policy correction is that a supported LOW-reliability row may
receive units when the accepted evaluator/Play Through layer calls it VALUE or
PLAYABLE. UNSUPPORTED, LEAN, and PASS remain zero.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

from nfl_edge.user.staking_profile_v2 import UserRiskProfile
from nfl_edge.value.staking_v2 import (
    GLOBAL_WAGER_CAP_FRACTION,
    MAX_UNITS,
    UnitStakeRecommendation,
    _floor_currency,
    _internal_kelly,
    _round_with_cap,
    _validate_candidate,
    playable_units,
    value_units,
)

SIZEABLE_RELIABILITY = frozenset({"HIGH", "MEDIUM", "LOW"})


def evaluator_units_v2_1(candidate: Mapping[str, Any]) -> tuple[float, str]:
    _validate_candidate(candidate)
    if not bool(candidate.get("supported")):
        return 0.0, "UNSUPPORTED"
    if str(candidate.get("reliability", "")) not in SIZEABLE_RELIABILITY:
        return 0.0, "UNSUPPORTED_RELIABILITY"

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


def recommend_stake_v2_1(
    candidate: Mapping[str, Any],
    profile: UserRiskProfile,
    *,
    current_open_exposure_amount: float | None = None,
) -> UnitStakeRecommendation:
    """Convert evaluator-owned V2.1 units to the user's selected risk style."""
    _validate_candidate(candidate)
    units, reason = evaluator_units_v2_1(candidate)
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
            return UnitStakeRecommendation(
                risk_style=profile.risk_style.value,
                bankroll=bankroll,
                price_status=str(candidate.get("price_status", "")),
                recommended_units=float(units),
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

    # Rounding may otherwise exceed an exposure capacity by one cent.
    if rounded > absolute_cap_amount + 1e-12:
        rounded = _floor_currency(absolute_cap_amount)

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


# Stable public names for downstream evaluator-board integration.
evaluator_units = evaluator_units_v2_1
recommend_stake = recommend_stake_v2_1
