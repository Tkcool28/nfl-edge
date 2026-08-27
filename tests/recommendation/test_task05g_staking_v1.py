from __future__ import annotations

import pytest

from nfl_edge.recommendation.staking_v1 import (
    RISK_PROFILES,
    ULTRA_CAUTION,
    cap_slate_stakes,
    dollar_stake,
    recommended_units,
    unit_dollars,
    user_wager_view,
)


def row(
    *,
    status: str = "VALUE",
    reliability: str = "HIGH",
    q: float = 0.56,
    ev: float = 0.04,
    uncertainty: float = 0.02,
    supported: bool = True,
):
    return {
        "candidate_id": "g1|moneyline|home",
        "offer_id": "offer-1",
        "game_id": "g1",
        "market_type": "moneyline",
        "selected_side": "home",
        "sportsbook": "draftkings",
        "line": None,
        "american_odds": -110,
        "supported": supported,
        "reliability": reliability,
        "price_status": status,
        "actionable_probability": q,
        "break_even_probability": 0.5238095238,
        "expected_value": ev,
        "uncertainty": uncertainty,
        "play_through_break_even_concession": 0.015,
        "play_through_break_even_probability": 0.575,
        "play_through_price_american": -135,
    }


def test_user_approved_profile_names_and_monotonic_percentages_are_frozen():
    assert [p.name for p in RISK_PROFILES] == [
        "Cautious",
        "Conservative",
        "Normal",
        "Aggressive",
        "Ultra",
    ]
    assert [p.unit_bankroll_pct for p in RISK_PROFILES] == [0.005, 0.0075, 0.01, 0.0125, 0.015]
    assert [p.unit_bankroll_pct for p in RISK_PROFILES] == sorted(p.unit_bankroll_pct for p in RISK_PROFILES)
    assert RISK_PROFILES[-1].caution == ULTRA_CAUTION
    assert "does not imply higher expected performance" in ULTRA_CAUTION


def test_unit_recommendation_ladder_and_playable_ceiling():
    assert recommended_units(row(status="PLAYABLE", q=0.56, ev=-0.005)) == 0.75
    assert recommended_units(row(status="PLAYABLE", reliability="MEDIUM", q=0.60, ev=-0.005)) == 0.5
    assert recommended_units(row(ev=0.01, q=0.50)) == 0.75
    assert recommended_units(row(ev=0.03, q=0.52)) == 1.0
    assert recommended_units(row(ev=0.045, q=0.54)) == 1.25
    assert recommended_units(row(ev=0.07, q=0.58, uncertainty=0.02)) == 1.5
    assert recommended_units(row(status="LEAN", ev=0.20, q=0.80)) == 0.0
    assert recommended_units(row(status="PASS", ev=0.20, q=0.80)) == 0.0
    assert recommended_units(row(status="UNSUPPORTED", supported=False, reliability="UNSUPPORTED")) == 0.0
    assert recommended_units(row(reliability="LOW", ev=0.20, q=0.80)) == 0.0


def test_selector_role_is_not_an_input_to_unit_sizing():
    exact = row(ev=0.03, q=0.52)
    assert recommended_units(exact) == 1.0
    for lane in ("hit_rate", "balanced", "value"):
        assert user_wager_view(exact, bankroll=1000, profile="Normal", lane=lane)["recommended_units"] == 1.0


def test_bankroll_conversion_profiles_rounding_minimum_and_caps():
    assert unit_dollars(1000, "Cautious") == pytest.approx(5.0)
    assert unit_dollars(1000, "Normal") == pytest.approx(10.0)
    assert unit_dollars(1000, "Ultra") == pytest.approx(15.0)
    assert dollar_stake(1000, "Normal", 1.25) == 12.5
    assert dollar_stake(123, "Normal", 1.0) == 1.0
    assert dollar_stake(20, "Cautious", 0.5) == 0.0
    assert dollar_stake(1000, "Ultra", 1.5) == 22.5
    with pytest.raises(ValueError):
        dollar_stake(100, "Normal", 0.6)
    with pytest.raises(ValueError):
        dollar_stake(-1, "Normal", 1.0)


def test_slate_cap_and_overlap_deduplication():
    assert cap_slate_stakes(100, [("a", 6), ("b", 6), ("a", 6)]) == {"a": 6.0, "b": 4.0}


def test_user_view_preserves_value_vs_playable_and_zero_stake_states():
    value = user_wager_view(row(status="VALUE", ev=0.03, q=0.52), bankroll=250, profile="Normal", lane="value")
    playable = user_wager_view(row(status="PLAYABLE", ev=-0.005, q=0.56), bankroll=250, profile="Normal", lane="balanced")
    lean = user_wager_view(row(status="LEAN", ev=-0.03, q=0.56), bankroll=250, profile="Normal", lane="hit_rate")
    assert value["strict_value"] is True and value["playable"] is False and value["action"] == "BET_VALUE"
    assert playable["strict_value"] is False and playable["playable"] is True and playable["action"] == "BET_PLAYABLE"
    assert lean["recommended_units"] == 0.0 and lean["recommended_stake"] == 0.0
    assert lean["action"] == "NO_RECOMMENDED_STAKE_AT_CURRENT_PRICE"


def test_ultra_changes_only_dollar_exposure_not_units_or_pick_fields():
    exact = row(ev=0.03, q=0.52)
    normal = user_wager_view(exact, bankroll=1000, profile="Normal", lane="value")
    ultra = user_wager_view(exact, bankroll=1000, profile="Ultra", lane="value")
    for field in ("candidate_id", "offer_id", "price_status", "recommended_units", "actionable_probability", "expected_value"):
        assert normal[field] == ultra[field]
    assert ultra["recommended_stake"] > normal["recommended_stake"]
    assert ultra["risk_profile_caution"] == ULTRA_CAUTION
