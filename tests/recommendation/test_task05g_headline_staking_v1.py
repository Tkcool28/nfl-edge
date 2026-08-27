from __future__ import annotations

from nfl_edge.recommendation.headline_staking_v1 import (
    BALANCED_MIN_HEADLINE_UNITS,
    HHR_MIN_UNITS,
    VALUE_AT_RESCUE_UNITS,
    american_break_even_probability,
    balanced_headline_units,
    headline_actionability,
    hhr_headline_stake,
    value_headline_actionability,
)
from nfl_edge.recommendation.staking_v1 import UNIT_LADDER, dollar_stake


def _base(**overrides):
    row = {
        "supported": True,
        "model_confidence_supported": True,
        "reliability": "MEDIUM",
        "price_status": "VALUE",
        "actionable_probability": 0.60,
        "break_even_probability": 0.55,
        "expected_value": 0.03,
        "uncertainty": 0.03,
        "selector_trust": 0.66,
        "american_odds": 120,
    }
    row.update(overrides)
    return row


def test_canonical_ladder_accepts_hhr_quarter_unit_floor():
    assert HHR_MIN_UNITS == 0.25
    assert 0.25 in UNIT_LADDER
    assert dollar_stake(1000.0, "Normal", 0.25) == 2.5


def test_hhr_price_pressure_only_haircuts_after_selection_and_never_zeroes():
    row = _base(selector_trust=0.66, break_even_probability=0.75)
    decision = hhr_headline_stake(row)
    assert decision.base_units == 1.0
    assert decision.recommended_units == HHR_MIN_UNITS
    assert decision.heavily_juiced is True
    action = headline_actionability("hit_rate", row)
    assert action.published is True
    assert action.primary_action == "BET"
    assert action.current_units == HHR_MIN_UNITS


def test_balanced_selected_headline_has_positive_floor_even_when_generic_units_are_zero():
    row = _base(reliability="LOW", price_status="LEAN", expected_value=-0.02)
    assert balanced_headline_units(row) == BALANCED_MIN_HEADLINE_UNITS
    action = headline_actionability("balanced", row)
    assert action.published is True
    assert action.primary_action == "BET"
    assert action.current_units == 0.75


def test_balanced_preserves_larger_generic_stake():
    row = _base(reliability="HIGH", expected_value=0.07, actionable_probability=0.58, uncertainty=0.02)
    assert balanced_headline_units(row) == 1.5


def test_low_reliability_value_becomes_nearby_value_at_instruction():
    row = _base(
        reliability="LOW",
        price_status="VALUE",
        expected_value=0.02,
        american_odds=250,
        break_even_probability=american_break_even_probability(250),
    )
    action = value_headline_actionability(row)
    assert action.published is True
    assert action.primary_action == "VALUE_AT"
    assert action.current_units == 0.0
    assert action.action_units == VALUE_AT_RESCUE_UNITS
    assert action.value_at_price_american == 263
    assert action.value_at_break_even_improvement is not None
    assert 0.010 <= action.value_at_break_even_improvement <= 0.015


def test_normal_value_current_bet_is_unchanged():
    row = _base(reliability="MEDIUM", expected_value=0.04, actionable_probability=0.55)
    action = value_headline_actionability(row)
    assert action.published is True
    assert action.primary_action == "BET"
    assert action.current_units == 1.0
    assert action.action_units == 1.0
    assert action.value_at_price_american is None


def test_value_fail_closed_when_caller_does_not_supply_strict_value_row():
    row = _base(reliability="LOW", price_status="LEAN", expected_value=-0.01)
    action = value_headline_actionability(row)
    assert action.published is False
    assert action.primary_action == "SUPPRESSED"
    assert action.action_units == 0.0
