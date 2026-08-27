"""Task05G headline-card staking and actionability policy V1.

This module is strictly downstream of the existing frozen HHR/Balanced/Value
selectors. It never selects, re-ranks, or filters candidates before selection.
Its only job is to turn an already-selected headline row into an actionable
headline recommendation.

Current tested contract:
- HHR: every selected headline is a BET; selector_trust sets base units and
  break-even price pressure may only haircut size to a 0.25u floor. +8pp price
  pressure exposes HEAVILY_JUICED.
- Balanced: every selected headline is a BET; preserve any larger generic stake
  but floor the headline at 0.75u so the 0.50u Playable Through extension stays
  visibly smaller than the primary recommendation.
- Value: keep normal positive generic stakes. If a selected strict-Value row is
  otherwise 0u because of LOW reliability, publish only when a same-line better
  price improves break-even by at least 1.0pp and no more than 1.5pp. That
  nearby Value-at rescue is 0.50u; otherwise suppress the Value headline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from nfl_edge.recommendation.staking_v1 import recommended_units

HHR_MIN_UNITS = 0.25
HHR_HEAVILY_JUICED_PRESSURE = 0.08
BALANCED_MIN_HEADLINE_UNITS = 0.75
BALANCED_PLAYABLE_THROUGH_UNITS = 0.50
VALUE_AT_REQUIRED_BREAK_EVEN_IMPROVEMENT = 0.010
VALUE_AT_MAX_BREAK_EVEN_IMPROVEMENT = 0.015
VALUE_AT_RESCUE_UNITS = 0.50


@dataclass(frozen=True)
class HHRStakeDecision:
    base_units: float
    price_pressure: float
    haircut_units: float
    recommended_units: float
    heavily_juiced: bool


@dataclass(frozen=True)
class HeadlineActionability:
    lane: str
    published: bool
    primary_action: str
    current_units: float
    action_units: float
    value_at_price_american: int | None = None
    value_at_break_even_improvement: float | None = None
    heavily_juiced: bool = False


def _float(row: Mapping[str, Any], key: str) -> float:
    value = row.get(key)
    if value is None:
        raise ValueError(f"missing required headline staking field {key!r}")
    return float(value)


def _american_odds(row: Mapping[str, Any]) -> int:
    value = row.get("american_odds")
    if value is None:
        value = row.get("actionable_price_american")
    if value is None:
        raise ValueError("missing American odds on selected headline")
    return int(value)


def american_break_even_probability(odds: int) -> float:
    odds = int(odds)
    if odds <= -100:
        return (-odds) / ((-odds) + 100.0)
    if odds >= 100:
        return 100.0 / (odds + 100.0)
    raise ValueError(f"invalid American odds {odds}")


def _hhr_base_units(selector_trust: float) -> float:
    q = float(selector_trust)
    if q >= 0.70:
        return 1.25
    if q >= 0.65:
        return 1.00
    if q >= 0.60:
        return 0.75
    return 0.50


def hhr_headline_stake(row: Mapping[str, Any]) -> HHRStakeDecision:
    """Stake an already-selected HHR card without changing its selection.

    Price may only haircut the stake after the selector has chosen the card. It
    can never turn the selected HHR card into NO/PASS/0u.
    """
    if not bool(row.get("supported")) or not bool(row.get("model_confidence_supported")):
        raise ValueError("HHR headline staking requires a supported already-selected HHR row")
    trust = _float(row, "selector_trust")
    break_even = _float(row, "break_even_probability")
    pressure = break_even - trust
    base = _hhr_base_units(trust)

    if pressure <= 0.0:
        haircut = 0.0
        units = base
    elif pressure <= 0.04:
        haircut = 0.25
        units = max(HHR_MIN_UNITS, base - haircut)
    elif pressure <= 0.08:
        haircut = 0.50
        units = max(HHR_MIN_UNITS, base - haircut)
    elif pressure <= 0.10:
        haircut = 0.75
        units = max(HHR_MIN_UNITS, base - haircut)
    else:
        haircut = max(0.0, base - HHR_MIN_UNITS)
        units = HHR_MIN_UNITS

    return HHRStakeDecision(
        base_units=base,
        price_pressure=pressure,
        haircut_units=haircut,
        recommended_units=units,
        heavily_juiced=pressure >= HHR_HEAVILY_JUICED_PRESSURE,
    )


def balanced_headline_units(row: Mapping[str, Any]) -> float:
    """Return positive units for an already-selected Balanced headline."""
    if not bool(row.get("supported")) or not bool(row.get("model_confidence_supported")):
        raise ValueError("Balanced headline staking requires a supported already-selected row")
    return max(BALANCED_MIN_HEADLINE_UNITS, float(recommended_units(row)))


def first_better_value_at_price(
    current_odds: int,
    *,
    required_improvement: float = VALUE_AT_REQUIRED_BREAK_EVEN_IMPROVEMENT,
) -> tuple[int | None, float | None]:
    """Return first better American price meeting a break-even improvement.

    This is same-line price movement only. Different spread/total lines remain
    different exact offers and must be evaluated separately elsewhere.
    """
    current = int(current_odds)
    starting_break_even = american_break_even_probability(current)
    if current <= -100:
        candidates = list(range(current + 1, -99)) + list(range(100, 5001))
    else:
        candidates = list(range(current + 1, 5001))

    for odds in candidates:
        improvement = starting_break_even - american_break_even_probability(odds)
        if improvement + 1e-12 >= float(required_improvement):
            return odds, improvement
    return None, None


def value_headline_actionability(row: Mapping[str, Any]) -> HeadlineActionability:
    """Create a current BET or nearby Value-at instruction for selected Value."""
    generic_units = float(recommended_units(row))
    if generic_units > 0.0:
        return HeadlineActionability(
            lane="value",
            published=True,
            primary_action="BET",
            current_units=generic_units,
            action_units=generic_units,
        )

    # The final Value selector is strict +EV. Fail closed if a caller supplies a
    # row that does not satisfy those downstream assumptions.
    if (
        not bool(row.get("supported"))
        or str(row.get("price_status") or "").upper() != "VALUE"
        or row.get("expected_value") is None
        or float(row["expected_value"]) <= 0.0
    ):
        return HeadlineActionability(
            lane="value",
            published=False,
            primary_action="SUPPRESSED",
            current_units=0.0,
            action_units=0.0,
        )

    target, improvement = first_better_value_at_price(_american_odds(row))
    if (
        target is not None
        and improvement is not None
        and improvement <= VALUE_AT_MAX_BREAK_EVEN_IMPROVEMENT + 1e-12
    ):
        return HeadlineActionability(
            lane="value",
            published=True,
            primary_action="VALUE_AT",
            current_units=0.0,
            action_units=VALUE_AT_RESCUE_UNITS,
            value_at_price_american=int(target),
            value_at_break_even_improvement=float(improvement),
        )

    return HeadlineActionability(
        lane="value",
        published=False,
        primary_action="SUPPRESSED",
        current_units=0.0,
        action_units=0.0,
    )


def headline_actionability(lane: str, row: Mapping[str, Any]) -> HeadlineActionability:
    """Return actionable presentation state for an already-selected headline."""
    normalized = str(lane).strip().lower()
    if normalized == "hit_rate":
        stake = hhr_headline_stake(row)
        return HeadlineActionability(
            lane=normalized,
            published=True,
            primary_action="BET",
            current_units=stake.recommended_units,
            action_units=stake.recommended_units,
            heavily_juiced=stake.heavily_juiced,
        )
    if normalized == "balanced":
        units = balanced_headline_units(row)
        return HeadlineActionability(
            lane=normalized,
            published=True,
            primary_action="BET",
            current_units=units,
            action_units=units,
        )
    if normalized == "value":
        return value_headline_actionability(row)
    raise ValueError(f"unknown headline lane {lane!r}")
