from __future__ import annotations

from types import SimpleNamespace

import pytest

import nfl_edge.recommendation.policy as policy
from nfl_edge.recommendation.policy import evaluate_policy_offer, shop_exact_offers
from nfl_edge.value.candidate_table import CandidateOfferContext, build_candidate_row
from nfl_edge.value.play_through import MAX_BREAK_EVEN_CONCESSION, assess_play_through


def row(
    cid: str,
    *,
    market="moneyline",
    side="home",
    book="draftkings",
    line=None,
    odds=-110,
):
    return {
        "candidate_id": cid,
        "game_id": cid.split("|")[0],
        "season": 2024,
        "market_type": market,
        "selected_side": side,
        "sportsbook": book,
        "line": line,
        "american_odds": odds,
    }


def test_best_book_shopping_moneyline_spread_and_totals():
    rows = [
        row("g1|moneyline|home", book="draftkings", odds=-115),
        row("g1|moneyline|home", book="fanduel", odds=-105),
        row("g2|spread|home", market="spread", line=-3.0, book="draftkings", odds=-105),
        row("g2|spread|home", market="spread", line=-2.5, book="fanduel", odds=-120),
        row("g3|total|over", market="total", side="over", line=44.5, book="draftkings"),
        row("g3|total|over", market="total", side="over", line=44.0, book="fanduel", odds=-120),
        row("g4|total|under", market="total", side="under", line=44.5, book="draftkings"),
        row("g4|total|under", market="total", side="under", line=45.0, book="fanduel", odds=-120),
    ]
    shopped = {r["game_id"]: r for r in shop_exact_offers(rows)}
    assert shopped["g1"]["sportsbook"] == "fanduel"
    assert shopped["g2"]["line"] == -2.5
    assert shopped["g3"]["line"] == 44.0
    assert shopped["g4"]["line"] == 45.0


def test_value_playable_contract_and_exact_1_5pp_maximum_corridor():
    assert MAX_BREAK_EVEN_CONCESSION == pytest.approx(0.015)
    value = assess_play_through(
        supported=True,
        strict_expected_value=0.0001,
        conditional_nonpush_probability=0.50,
        current_break_even_probability=0.50,
        reliability="HIGH",
        uncertainty_radius=0.0,
    )
    edge = assess_play_through(
        supported=True,
        strict_expected_value=-0.001,
        conditional_nonpush_probability=0.50,
        current_break_even_probability=0.515,
        reliability="HIGH",
        uncertainty_radius=0.0,
    )
    outside = assess_play_through(
        supported=True,
        strict_expected_value=-0.001,
        conditional_nonpush_probability=0.50,
        current_break_even_probability=0.515001,
        reliability="HIGH",
        uncertainty_radius=0.0,
    )
    assert value.status == "VALUE"
    assert edge.status == "PLAYABLE"
    assert edge.break_even_concession == pytest.approx(0.015)
    assert outside.status == "LEAN"


def test_exact_offer_policy_adapter_uses_same_offer_and_canonical_units(monkeypatch):
    exact_offer = object()
    seen = {}

    def fake_evaluate(game, offer, state, anchor, reliability_state):
        seen["offer"] = offer
        return SimpleNamespace(
            supported=True,
            expected_value=0.03,
            conditional_nonpush_probability=0.55,
            break_even_probability=0.52,
            reliability="HIGH",
            uncertainty=0.02,
            actionable_probability=0.55,
        )

    monkeypatch.setattr(policy, "evaluate_offer", fake_evaluate)
    result = evaluate_policy_offer(object(), exact_offer, object(), object(), object())
    assert seen["offer"] is exact_offer
    assert result.price_status == "VALUE"
    assert result.recommended_units == 1.0


def test_manual_and_full_board_policy_are_source_agnostic(monkeypatch):
    calls = []

    def fake_evaluate(game, offer, state, anchor, reliability_state):
        calls.append(offer)
        return SimpleNamespace(
            supported=True,
            expected_value=0.025,
            conditional_nonpush_probability=0.53,
            break_even_probability=0.51,
            reliability="MEDIUM",
            uncertainty=0.04,
            actionable_probability=0.53,
        )

    monkeypatch.setattr(policy, "evaluate_offer", fake_evaluate)
    manual = SimpleNamespace(source="manual", line=-2.5, price_american=-105)
    board = SimpleNamespace(source="stored", line=-2.5, price_american=-105)
    a = evaluate_policy_offer(object(), manual, object(), object(), object())
    b = evaluate_policy_offer(object(), board, object(), object(), object())
    assert a.price_status == b.price_status == "VALUE"
    assert a.recommended_units == b.recommended_units == 1.0
    assert calls == [manual, board]


def test_policy_module_does_not_reintroduce_competing_task05g_apis():
    forbidden = {
        "select_hit_rate",
        "select_balanced",
        "select_value",
        "select_headlines",
        "recommended_units",
        "dollar_stake",
        "cap_slate_stakes",
        "RiskProfile",
        "RISK_PROFILES",
        "RISK_PROFILE_BY_NAME",
    }
    assert not [name for name in forbidden if hasattr(policy, name)]


def test_candidate_contract_rejects_2025_before_task05g():
    upstream = {
        "game_id": "sealed",
        "season": 2025,
        "market_type": "moneyline",
        "selected_side": "home",
        "american_odds": -110,
        "sportsbook": "draftkings",
    }
    with pytest.raises(RuntimeError, match="sealed season 2025"):
        build_candidate_row(upstream, CandidateOfferContext())
