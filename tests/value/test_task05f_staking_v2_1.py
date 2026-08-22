import copy

import pytest

from nfl_edge.user.staking_profile_v2 import RiskStyle, UserRiskProfile
from nfl_edge.value.staking_v2 import evaluator_units as evaluator_units_v2
from nfl_edge.value.staking_v2_1 import evaluator_units_v2_1, recommend_stake_v2_1


def _row(*, reliability="MEDIUM", status="VALUE", supported=True, season=2024):
    return {
        "season": season,
        "supported": supported,
        "reliability": reliability,
        "price_status": status,
        "strict_positive_value": status == "VALUE",
        "evaluated_edge_probability": 0.03,
        "play_through_confidence_multiplier": 0.35 if reliability == "LOW" else 0.70,
        "play_through_break_even_concession": 0.006,
        "break_even_probability": 0.505,
        "actionable_probability": 0.50,
        "play_through_break_even_probability": 0.51,
        "actionable_decimal_price": 1.91,
        "staking_probability": 0.54,
    }


def test_high_and_medium_match_v2_units():
    for reliability in ("HIGH", "MEDIUM"):
        for status in ("VALUE", "PLAYABLE"):
            row = _row(reliability=reliability, status=status)
            assert evaluator_units_v2_1(row) == evaluator_units_v2(row)


def test_low_playable_gets_positive_units():
    units, reason = evaluator_units_v2_1(_row(reliability="LOW", status="PLAYABLE"))
    assert 0.5 <= units <= 1.0
    assert reason == "STAKE_RECOMMENDED_PLAYABLE"


def test_low_value_gets_positive_units():
    units, reason = evaluator_units_v2_1(_row(reliability="LOW", status="VALUE"))
    assert 1.0 <= units <= 2.0
    assert reason == "STAKE_RECOMMENDED_VALUE"


def test_unsupported_and_nonactionable_are_zero():
    assert evaluator_units_v2_1(_row(supported=False))[0] == 0.0
    for status in ("LEAN", "PASS"):
        row = _row(status=status)
        row["strict_positive_value"] = False
        assert evaluator_units_v2_1(row)[0] == 0.0


def test_risk_style_still_converts_units_and_caps():
    row = _row(reliability="LOW", status="VALUE")
    profile = UserRiskProfile(bankroll=100.0, risk_style=RiskStyle.VERY_AGGRESSIVE)
    rec = recommend_stake_v2_1(row, profile)
    assert rec.recommended_units > 0.0
    assert rec.recommended_stake_fraction <= 0.05
    assert rec.recommended_stake <= 5.0


def test_exposure_cap_unchanged():
    row = _row(reliability="LOW", status="VALUE")
    profile = UserRiskProfile(bankroll=100.0, risk_style=RiskStyle.STANDARD)
    rec = recommend_stake_v2_1(row, profile, current_open_exposure_amount=7.0)
    assert rec.recommended_stake == 0.0
    assert rec.unit_reason == "EXPOSURE_CAP_REACHED"


def test_outcome_firewall():
    row = _row()
    row["settlement"] = "WIN"
    with pytest.raises(RuntimeError, match="forbidden outcome fields"):
        evaluator_units_v2_1(row)


def test_sealed_2025_firewall():
    with pytest.raises(RuntimeError, match="sealed season 2025"):
        evaluator_units_v2_1(_row(season=2025))
