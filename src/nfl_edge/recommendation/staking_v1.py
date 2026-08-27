"""Canonical Task05G unit/risk-profile staking policy V1.

This module is downstream of the frozen Task05G selector contract. It does not
select wagers and does not alter model/evaluator outputs. It assigns a bounded
account-independent recommended unit size to one exact evaluated offer, then
converts those units to a user-specific dollar stake using one global risk
profile.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Mapping, Sequence

# 0.25u is reserved for the HHR headline minimum after selection. Generic
# exact-offer recommendations remain on the pre-existing 0.50u+ ladder.
UNIT_LADDER = (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5)
PER_WAGER_BANKROLL_CAP_PCT = 0.025
SLATE_BANKROLL_CAP_PCT = 0.10
MINIMUM_STAKE_DOLLARS = 0.50
ROUNDING_QUANTUM_DOLLARS = 0.50
ULTRA_CAUTION = (
    "Ultra is the highest staking exposure setting. It does not imply higher "
    "expected performance, better picks, greater model confidence, or any "
    "increase in predictive edge."
)


@dataclass(frozen=True)
class RiskProfile:
    name: str
    unit_bankroll_pct: float
    caution: str | None = None


RISK_PROFILES = (
    RiskProfile("Cautious", 0.0050),
    RiskProfile("Conservative", 0.0075),
    RiskProfile("Normal", 0.0100),
    RiskProfile("Aggressive", 0.0125),
    RiskProfile("Ultra", 0.0150, ULTRA_CAUTION),
)
RISK_PROFILE_BY_NAME = {profile.name: profile for profile in RISK_PROFILES}
ALLOWED_STAKING_RELIABILITY = frozenset({"HIGH", "MEDIUM"})


def _field(row: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return default


def _float(row: Mapping[str, Any], *names: str) -> float | None:
    value = _field(row, *names)
    return None if value is None else float(value)


def _status(row: Mapping[str, Any]) -> str:
    return str(_field(row, "price_status", default="UNSUPPORTED")).upper()


def _reliability(row: Mapping[str, Any]) -> str:
    return str(_field(row, "reliability", default="UNSUPPORTED")).upper()


def recommended_units(row: Mapping[str, Any]) -> float:
    """Return the generic discrete recommendation for one exact offer.

    Headline-role overrides are intentionally handled in headline_staking_v1.
    This function remains the default/game-detail/manual exact-offer policy.
    """
    if not bool(_field(row, "supported", default=False)):
        return 0.0
    reliability = _reliability(row)
    if reliability not in ALLOWED_STAKING_RELIABILITY:
        return 0.0

    status = _status(row)
    q = _float(row, "actionable_probability")
    ev = _float(row, "expected_value")
    uncertainty = _float(row, "uncertainty")

    if status in {"UNSUPPORTED", "PASS", "LEAN"} or q is None or ev is None:
        return 0.0

    if status == "PLAYABLE":
        return 0.75 if reliability == "HIGH" and q >= 0.55 else 0.5

    if status != "VALUE" or ev <= 0.0:
        return 0.0

    if (
        reliability == "HIGH"
        and ev >= 0.06
        and q >= 0.55
        and uncertainty is not None
        and uncertainty <= 0.025
    ):
        return 1.5
    if reliability == "HIGH" and ev >= 0.04 and q >= 0.52:
        return 1.25
    if ev >= 0.025 and q >= 0.50:
        return 1.0
    return 0.75


def risk_profile(profile: RiskProfile | str) -> RiskProfile:
    if isinstance(profile, RiskProfile):
        return profile
    try:
        return RISK_PROFILE_BY_NAME[str(profile)]
    except KeyError as exc:
        raise ValueError(f"unknown risk profile {profile!r}; expected {tuple(RISK_PROFILE_BY_NAME)}") from exc


def unit_dollars(bankroll: float, profile: RiskProfile | str) -> float:
    bankroll_d = Decimal(str(bankroll))
    if bankroll_d < 0:
        raise ValueError("bankroll must be non-negative")
    selected = risk_profile(profile)
    return float(bankroll_d * Decimal(str(selected.unit_bankroll_pct)))


def dollar_stake(bankroll: float, profile: RiskProfile | str, units: float) -> float:
    """Convert units to dollars without rounding above the wager cap."""
    bankroll_d = Decimal(str(bankroll))
    if bankroll_d < 0:
        raise ValueError("bankroll must be non-negative")
    if float(units) not in UNIT_LADDER:
        raise ValueError(f"units must be on frozen ladder {UNIT_LADDER}")

    selected = risk_profile(profile)
    raw = bankroll_d * Decimal(str(selected.unit_bankroll_pct)) * Decimal(str(float(units)))
    cap = bankroll_d * Decimal(str(PER_WAGER_BANKROLL_CAP_PCT))
    bounded = min(raw, cap)
    quantum = Decimal(str(ROUNDING_QUANTUM_DOLLARS))
    rounded = (bounded / quantum).to_integral_value(rounding=ROUND_FLOOR) * quantum
    if rounded < Decimal(str(MINIMUM_STAKE_DOLLARS)):
        return 0.0
    return float(rounded)


def cap_slate_stakes(bankroll: float, proposed: Sequence[tuple[str, float]]) -> dict[str, float]:
    """Apply the frozen 10% slate cap in stable order with offer deduplication."""
    if float(bankroll) < 0:
        raise ValueError("bankroll must be non-negative")
    limit = float(bankroll) * SLATE_BANKROLL_CAP_PCT
    remaining = limit
    output: dict[str, float] = {}
    quantum = Decimal(str(ROUNDING_QUANTUM_DOLLARS))
    for offer_id, stake in proposed:
        key = str(offer_id)
        if key in output:
            continue
        allowed = min(max(0.0, float(stake)), remaining)
        rounded = float((Decimal(str(allowed)) / quantum).to_integral_value(rounding=ROUND_FLOOR) * quantum)
        output[key] = rounded
        remaining = max(0.0, remaining - rounded)
    return output


def _presentation_action(row: Mapping[str, Any], units: float) -> tuple[str, str]:
    """Return an unambiguous user action plus deterministic reason code."""
    if not bool(_field(row, "supported", default=False)) or _reliability(row) == "UNSUPPORTED":
        return "UNSUPPORTED", "UNSUPPORTED_EVIDENCE"

    reliability = _reliability(row)
    status = _status(row)
    if units <= 0.0:
        if reliability not in ALLOWED_STAKING_RELIABILITY:
            return "INFORMATIONAL_NO_STAKE", "RELIABILITY_INFORMATIONAL_ONLY"
        if status in {"LEAN", "PASS"}:
            return "NO_RECOMMENDED_STAKE_AT_CURRENT_PRICE", "CURRENT_PRICE_OUTSIDE_ACTIONABLE_CORRIDOR"
        return "INFORMATIONAL_NO_STAKE", "ZERO_UNITS_BY_FROZEN_STAKING_POLICY"

    if status == "VALUE":
        return "BET_VALUE", "STRICT_POSITIVE_VALUE"
    if status == "PLAYABLE":
        return "BET_PLAYABLE", "PLAY_THROUGH_BOUNDED_ACTION"
    return "INFORMATIONAL_NO_STAKE", "ZERO_UNITS_BY_FROZEN_STAKING_POLICY"


def user_wager_view(
    row: Mapping[str, Any],
    *,
    bankroll: float,
    profile: RiskProfile | str,
    lane: str | None = None,
) -> dict[str, Any]:
    """Build the backend presentation contract for one exact evaluated offer."""
    selected_profile = risk_profile(profile)
    units = recommended_units(row)
    stake = dollar_stake(bankroll, selected_profile, units)
    status = _status(row)
    action, action_reason = _presentation_action(row, units)

    return {
        "lane": lane,
        "candidate_id": _field(row, "candidate_id"),
        "offer_id": _field(row, "offer_id"),
        "game_id": _field(row, "game_id"),
        "market_type": _field(row, "market_type"),
        "selection": _field(row, "selected_side", "selection"),
        "sportsbook": _field(row, "sportsbook", "actionable_book"),
        "line": _field(row, "line", "actionable_line"),
        "american_odds": _field(row, "american_odds", "actionable_price_american"),
        "price_status": status,
        "strict_value": status == "VALUE",
        "playable": status == "PLAYABLE",
        "action": action,
        "action_reason": action_reason,
        "model_confidence_probability": _float(row, "model_confidence_probability"),
        "actionable_probability": _float(row, "actionable_probability"),
        "break_even_probability": _float(row, "break_even_probability"),
        "expected_value": _float(row, "expected_value"),
        "reliability": _reliability(row),
        "recommended_units": units,
        "risk_profile": selected_profile.name,
        "unit_bankroll_pct": selected_profile.unit_bankroll_pct,
        "bankroll": float(bankroll),
        "unit_dollars": unit_dollars(bankroll, selected_profile),
        "recommended_stake": stake,
        "play_through_break_even_concession": _float(row, "play_through_break_even_concession"),
        "play_through_break_even_probability": _float(row, "play_through_break_even_probability"),
        "play_through_price_american": _field(row, "play_through_price_american"),
        "risk_profile_caution": selected_profile.caution,
    }
