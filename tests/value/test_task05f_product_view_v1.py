import copy

import pytest

from nfl_edge.user.staking_profile import FlatStakeMode, StakingStrategy, UserStakingProfile
from nfl_edge.value.product_view import (
    build_explorer_views,
    build_primary_card_views,
    user_candidate_view,
)


def _row(
    cid: str,
    *,
    market: str = "spread",
    selection: str = "home",
    probability: float = 0.60,
    ev: float = 0.04,
    edge: float = 0.03,
    status: str = "VALUE",
    reliability: str = "MEDIUM",
    supported: bool = True,
    strict_value: bool | None = None,
    staking_probability: float = 0.55,
    decimal_price: float = 2.0,
):
    if strict_value is None:
        strict_value = status == "VALUE" and ev > 0
    return {
        "candidate_id": cid,
        "game_id": cid,
        "season": 2024,
        "week": 1,
        "market_type": market,
        "selection": selection,
        "actionable_book": "draftkings",
        "actionable_line": None if market == "moneyline" else -2.5,
        "actionable_price_american": 100,
        "actionable_decimal_price": decimal_price,
        "actionable_probability": probability,
        "expected_value": ev,
        "evaluated_edge_probability": edge,
        "reliability": reliability,
        "price_status": status,
        "supported": supported,
        "strict_positive_value": strict_value,
        "uncertainty": 0.02,
        "staking_probability": staking_probability,
    }


def _flat(bankroll=100.0):
    return UserStakingProfile(bankroll=bankroll, staking_strategy=StakingStrategy.FLAT)


def test_candidate_core_is_not_mutated_by_account_staking():
    row = _row("spread")
    before = copy.deepcopy(row)
    view = user_candidate_view(row, _flat())
    assert row == before
    assert view["candidate"] == before
    assert "recommended_stake" not in row
    assert view["staking"]["recommended_stake"] == pytest.approx(1.0)


def test_same_core_wager_gets_different_stake_by_user_profile_only():
    row = _row("spread", staking_probability=0.55)
    flat = user_candidate_view(row, _flat(200.0))
    quarter = user_candidate_view(
        row,
        UserStakingProfile(bankroll=200.0, staking_strategy=StakingStrategy.QUARTER_KELLY),
    )
    assert flat["candidate"] == quarter["candidate"]
    assert flat["staking"]["recommended_stake"] == pytest.approx(2.0)
    assert quarter["staking"]["recommended_stake"] == pytest.approx(5.0)


def test_primary_card_identity_is_account_independent():
    rows = [
        _row("ml", market="moneyline", probability=0.72, ev=0.02, staking_probability=0.68),
        _row("spread-a", probability=0.62, ev=0.08, staking_probability=0.58),
        _row("spread-b", probability=0.66, ev=0.03, staking_probability=0.60),
    ]
    flat_cards = build_primary_card_views(rows, _flat(100.0))
    kelly_cards = build_primary_card_views(
        rows,
        UserStakingProfile(bankroll=100.0, staking_strategy=StakingStrategy.HALF_KELLY),
    )
    for card in ("HIGH_HIT_RATE", "BALANCED", "VALUE"):
        assert flat_cards[card]["candidate"]["candidate_id"] == kelly_cards[card]["candidate"]["candidate_id"]


def test_v3_top_cards_respect_capability_policy_in_product_view():
    ml = _row("ml", market="moneyline", probability=0.75, ev=0.50)
    spread = _row("spread", market="spread", probability=0.60, ev=0.04)
    cards = build_primary_card_views([ml, spread], _flat())
    assert cards["HIGH_HIT_RATE"]["candidate"]["candidate_id"] == "ml"
    assert cards["BALANCED"]["candidate"]["candidate_id"] == "spread"
    assert cards["VALUE"]["candidate"]["candidate_id"] == "spread"


def test_explorer_keeps_pass_and_shows_zero_stake():
    value = _row("value")
    passed = _row("pass", status="PASS", ev=-0.10, strict_value=False)
    views = build_explorer_views([passed, value], _flat())
    assert [view["candidate"]["candidate_id"] for view in views] == ["pass", "value"]
    pass_view = views[0]
    assert pass_view["candidate"]["price_status"] == "PASS"
    assert pass_view["staking"]["recommended_stake"] == 0.0
    assert pass_view["staking"]["reason"] == "STATUS_NOT_ACTIONABLE"


def test_flat_global_strategy_stakes_same_amount_on_value_and_playable_explorer_rows():
    rows = [
        _row("value", status="VALUE"),
        _row("playable", status="PLAYABLE", ev=-0.003, strict_value=False),
    ]
    views = build_explorer_views(rows, _flat(300.0))
    stakes = {view["candidate"]["candidate_id"]: view["staking"]["recommended_stake"] for view in views}
    assert stakes == {"playable": 3.0, "value": 3.0}


def test_kelly_profile_surfaces_playable_but_recommends_zero_stake():
    row = _row(
        "playable",
        status="PLAYABLE",
        ev=-0.002,
        strict_value=False,
        staking_probability=0.70,
    )
    profile = UserStakingProfile(bankroll=100.0, staking_strategy=StakingStrategy.QUARTER_KELLY)
    view = user_candidate_view(row, profile)
    assert view["candidate"]["price_status"] == "PLAYABLE"
    assert view["staking"]["recommended_stake"] == 0.0
    assert view["staking"]["reason"] == "PLAYABLE_NOT_KELLY_VALUE"


def test_manual_flat_caution_flows_to_every_qualifying_view():
    profile = UserStakingProfile(
        bankroll=100.0,
        staking_strategy=StakingStrategy.FLAT,
        flat_stake_mode=FlatStakeMode.MANUAL,
        manual_flat_stake=4.0,
    )
    views = build_explorer_views([_row("a"), _row("b")], profile)
    assert all(view["staking"]["recommended_stake"] == 4.0 for view in views)
    assert all(view["staking"]["manual_flat_caution"] for view in views)


def test_product_view_rejects_historical_outcomes():
    row = _row("leak")
    row["settlement"] = "WIN"
    with pytest.raises(RuntimeError, match="historical outcome fields"):
        user_candidate_view(row, _flat())
