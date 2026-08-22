from __future__ import annotations

from types import SimpleNamespace

import pytest

import nfl_edge.recommendation.policy as policy
from nfl_edge.recommendation.policy import (
    NO_BALANCED_PLAY,
    NO_HIT_RATE_PLAY,
    NO_VALUE_PLAY,
    RISK_PROFILES,
    cap_slate_stakes,
    dollar_stake,
    evaluate_policy_offer,
    recommended_units,
    select_balanced,
    select_headlines,
    select_hit_rate,
    select_value,
    shop_exact_offers,
)
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
    q=0.56,
    ev=0.04,
    edge=0.04,
    reliability="HIGH",
    status="VALUE",
    support_n=600,
    support_distance=0.02,
    uncertainty=0.02,
    supported=True,
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
        "actionable_probability": q,
        "expected_value": ev,
        "evaluated_edge_probability": edge,
        "reliability": reliability,
        "price_status": status,
        "support_n": support_n,
        "support_distance": support_distance,
        "uncertainty": uncertainty,
        "supported": supported,
    }


def test_hit_rate_deterministic_probability_first():
    a = row("g1|moneyline|home", q=0.61, ev=0.02, reliability="MEDIUM")
    b = row("g2|spread|away", market="spread", side="away", line=3.0, q=0.60, ev=0.10)
    assert select_hit_rate([b, a])["candidate_id"] == a["candidate_id"]
    assert select_hit_rate([a, b])["candidate_id"] == a["candidate_id"]


def test_balanced_prefers_value_then_reliability_then_ev():
    playable = row("g1|moneyline|home", q=0.65, ev=-0.01, status="PLAYABLE")
    value = row("g2|total|under", market="total", side="under", line=44.5, q=0.51, ev=0.025)
    assert select_balanced([playable, value])["candidate_id"] == value["candidate_id"]


def test_value_is_market_agnostic():
    ml = row("g1|moneyline|home", ev=0.04)
    total = row("g2|total|over", market="total", side="over", line=42.5, odds=120, q=0.50, ev=0.09, edge=0.06)
    assert select_value([ml, total])["market_type"] == "total"


def test_no_play_codes_are_valid():
    bad = row("g1|moneyline|home", reliability="LOW")
    assert select_hit_rate([bad]) == NO_HIT_RATE_PLAY
    assert select_balanced([bad]) == NO_BALANCED_PLAY
    assert select_value([bad]) == NO_VALUE_PLAY


def test_longshot_guardrail_blocks_plus_500_even_positive_ev():
    longshot = row("g1|moneyline|home", odds=500, q=0.15, ev=0.03)
    normal = row("g2|moneyline|away", odds=180, q=0.38, ev=0.025)
    assert select_value([longshot, normal])["candidate_id"] == normal["candidate_id"]
    assert select_value([longshot]) == NO_VALUE_PLAY


def test_unsupported_and_low_reliability_never_headline():
    unsupported = row("g1|moneyline|home", supported=False, reliability="UNSUPPORTED", status="UNSUPPORTED")
    low = row("g2|moneyline|home", reliability="LOW")
    assert select_headlines([unsupported, low]) == {
        "hit_rate": NO_HIT_RATE_PLAY,
        "balanced": NO_BALANCED_PLAY,
        "value": NO_VALUE_PLAY,
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


def test_selector_overlap_is_allowed_not_forced_apart():
    best = row("g1|moneyline|home", q=0.62, ev=0.08, odds=-120)
    heads = select_headlines([best])
    assert heads["hit_rate"]["candidate_id"] == best["candidate_id"]
    assert heads["balanced"]["candidate_id"] == best["candidate_id"]
    assert heads["value"]["candidate_id"] == best["candidate_id"]


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


def test_unit_ladder_monotonic_and_playable_ceiling():
    playable = row("g0|moneyline|home", status="PLAYABLE", ev=-0.005, q=0.56)
    weak = row("g1|moneyline|home", ev=0.01, q=0.50)
    solid = row("g2|moneyline|home", ev=0.03, q=0.52)
    strong = row("g3|moneyline|home", ev=0.045, q=0.54)
    maxed = row("g4|moneyline|home", ev=0.07, q=0.58, uncertainty=0.02)
    assert [recommended_units(x) for x in [playable, weak, solid, strong, maxed]] == [0.75, 0.75, 1.0, 1.25, 1.5]
    assert recommended_units(row("g5|moneyline|home", reliability="LOW", ev=0.20, q=0.80)) == 0.0
    assert recommended_units(row("g6|moneyline|home", status="PASS", ev=0.20, q=0.80)) == 0.0


def test_five_risk_profiles_are_ordered_and_do_not_change_units():
    assert [p.name for p in RISK_PROFILES] == ["Cautious", "Steady", "Balanced", "Bold", "High Gear"]
    assert [p.unit_bankroll_pct for p in RISK_PROFILES] == sorted(p.unit_bankroll_pct for p in RISK_PROFILES)
    exact = row("g1|moneyline|home", ev=0.03, q=0.52)
    assert recommended_units(exact) == 1.0


def test_bankroll_conversion_rounding_minimum_and_caps():
    assert dollar_stake(1000, "Balanced", 1.25) == 12.5
    assert dollar_stake(123, "Balanced", 1.0) == 1.0
    assert dollar_stake(20, "Cautious", 0.5) == 0.0
    assert dollar_stake(1000, "High Gear", 1.5) == 22.5
    capped = cap_slate_stakes(100, [("a", 6), ("b", 6), ("a", 6)])
    assert capped == {"a": 6.0, "b": 4.0}


def test_exact_offer_policy_adapter_uses_same_offer(monkeypatch):
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


def test_deterministic_replay():
    rows = [
        row("g1|moneyline|home", q=0.58, ev=0.05),
        row("g2|total|under", market="total", side="under", line=45.0, odds=130, q=0.45, ev=0.08),
    ]
    assert select_headlines(rows) == select_headlines(list(reversed(list(reversed(rows)))))
