from __future__ import annotations

from dataclasses import replace

import pytest

from nfl_edge.recommendation.final_selectors_v1 import (
    TrustObservation,
    ValueSelectorState,
    advance_value_state,
    family_trust,
    ml_value_frontier,
    select_balanced,
    select_headlines,
    select_hit_rate,
    select_value,
    spread_pareto_frontier,
)
from nfl_edge.recommendation.policy import NO_BALANCED_PLAY, NO_HIT_RATE_PLAY, NO_VALUE_PLAY


def row(
    cid: str,
    *,
    market: str = "moneyline",
    side: str = "away",
    book: str = "draftkings",
    line: float | None = None,
    odds: int = -110,
    q: float = 0.60,
    pinnacle: float | None = 0.58,
    ev: float = 0.04,
    edge: float = 0.03,
    reliability: str = "HIGH",
    status: str = "VALUE",
    supported: bool = True,
    model_supported: bool = True,
    support_n: int = 600,
    regions: str = "ML_DOG_VALUE_ZONE_AVG",
    model_price_gap: float = 0.06,
    cover_margin: float = 2.0,
    break_even: float = 0.52,
    settlement: str | None = None,
):
    return {
        "candidate_id": cid,
        "game_id": cid.split("|")[0],
        "season": 2024,
        "week": 1,
        "block": "2024-01",
        "market_type": market,
        "selected_side": side,
        "sportsbook": book,
        "line": line,
        "american_odds": odds,
        "supported": supported,
        "reliability": reliability,
        "model_confidence_supported": model_supported,
        "model_confidence_support_n": support_n,
        "model_confidence_probability": q,
        "pinnacle_anchor_probability": pinnacle,
        "break_even_probability": break_even,
        "expected_value": ev,
        "evaluated_edge_probability": edge,
        "price_status": status,
        "model_candidate_regions": regions,
        "model_price_gap": model_price_gap,
        "model_cover_margin_v3": cover_margin,
        "settlement": settlement,
    }


def test_hhr_half_shrink_is_model_led_and_ev_status_invariant():
    ml = row("g1|ml|away", q=0.80, pinnacle=0.60, ev=-0.20, status="LEAN")
    spread = row(
        "g2|spread|away",
        market="spread",
        line=3.0,
        q=0.71,
        pinnacle=None,
        ev=0.30,
        status="PASS",
        regions="SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4",
    )
    # ML trust = .80 - .5*(.20) = .70, so the .71 spread wins.
    assert select_hit_rate([ml, spread])["candidate_id"] == spread["candidate_id"]
    changed = dict(ml, expected_value=9.0, price_status="VALUE")
    assert select_hit_rate([changed, spread])["candidate_id"] == spread["candidate_id"]


def test_hhr_requires_price_sanity_not_positive_ev_or_value_status():
    good = row("g1|ml|away", q=0.61, ev=-0.25, status="LEAN", odds=-250)
    too_juiced = row("g2|ml|away", q=0.90, pinnacle=0.90, odds=-350)
    assert select_hit_rate([good, too_juiced])["candidate_id"] == good["candidate_id"]
    assert select_hit_rate([too_juiced]) == NO_HIT_RATE_PLAY


def test_balanced_market_half_probability_first_and_status_ev_invariant():
    ml = row("g1|ml|away", q=0.70, pinnacle=0.64, ev=0.40, status="VALUE")
    spread = row(
        "g2|spread|away",
        market="spread",
        line=2.5,
        q=0.68,
        pinnacle=None,
        ev=-0.20,
        status="LEAN",
        regions="SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4",
    )
    # ML trust = .67, so the .68 spread wins despite worse EV/status.
    assert select_balanced([ml, spread])["candidate_id"] == spread["candidate_id"]
    inverted_economics = [dict(ml, expected_value=-9.0, price_status="PASS"), dict(spread, expected_value=9.0, price_status="VALUE")]
    assert select_balanced(inverted_economics)["candidate_id"] == spread["candidate_id"]


def test_balanced_price_band_and_probability_floor_fail_closed():
    low_q = row("g1|ml|away", q=0.519, odds=-110)
    too_juiced = row("g2|ml|away", q=0.80, pinnacle=0.80, odds=-221)
    assert select_balanced([low_q, too_juiced]) == NO_BALANCED_PLAY


def test_value_requires_strict_positive_ev_value_status_and_validated_family():
    zero_ev = row("g1|ml|away", ev=0.0)
    playable = row("g2|ml|away", status="PLAYABLE")
    unsupported_family = row("g3|ml|away", ev=0.40, regions="NOT_ALLOWED")
    valid = row("g4|ml|away", ev=0.01)
    assert select_value([zero_ev, playable, unsupported_family, valid], ValueSelectorState()) == NO_VALUE_PLAY
    # Cold singleton/no-spread safety is why even the valid row passes here.
    assert ml_value_frontier([valid])["candidate_id"] == valid["candidate_id"]


def test_spread_pareto_selects_consensus_not_raw_margin_extreme():
    a = row(
        "a|spread|away",
        market="spread",
        line=3.5,
        pinnacle=None,
        regions="SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4",
        cover_margin=3.9,
        edge=0.01,
        ev=0.01,
    )
    b = row(
        "b|spread|away",
        market="spread",
        line=3.0,
        pinnacle=None,
        regions="SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4",
        cover_margin=3.0,
        edge=0.03,
        ev=0.03,
    )
    c = row(
        "c|spread|away",
        market="spread",
        line=2.5,
        pinnacle=None,
        regions="SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4",
        cover_margin=2.0,
        edge=0.05,
        ev=0.05,
    )
    selected = spread_pareto_frontier([a, b, c])
    assert selected["candidate_id"] == b["candidate_id"]
    assert selected["pareto_worst_rank"] == 2


def losing_state(n: int) -> tuple[TrustObservation, ...]:
    return tuple(TrustObservation(predicted_edge=0.05, realized_edge=-0.50) for _ in range(n))


def winning_state(n: int) -> tuple[TrustObservation, ...]:
    return tuple(TrustObservation(predicted_edge=0.05, realized_edge=0.48) for _ in range(n))


def spread_row(cid: str, *, margin: float = 2.0, edge: float = 0.03, settlement=None):
    return row(
        cid,
        market="spread",
        line=3.0,
        q=0.51,
        pinnacle=None,
        regions="SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4",
        cover_margin=margin,
        edge=edge,
        ev=0.03,
        settlement=settlement,
    )


def test_spread_nongreen_singleton_safety_passes_but_competition_stays_alive():
    state = ValueSelectorState(spread_observations=losing_state(3))
    assert family_trust(state.spread_observations).state == "AMBER"
    single = spread_row("s1|spread|away")
    assert select_value([single], state) == NO_VALUE_PLAY

    second = spread_row("s2|spread|away", margin=1.5, edge=0.04)
    assert select_value([single, second], state) != NO_VALUE_PLAY


def test_ml_cold_singleton_without_spread_passes_but_competition_is_allowed():
    single = row("m1|ml|away", q=0.60, break_even=0.50)
    assert select_value([single], ValueSelectorState()) == NO_VALUE_PLAY

    second = row("m2|ml|away", q=0.59, model_price_gap=0.05, break_even=0.50)
    assert select_value([single, second], ValueSelectorState()) != NO_VALUE_PLAY


def test_ml_mature_green_singleton_remains_eligible():
    state = ValueSelectorState(ml_observations=winning_state(3))
    trust = family_trust(state.ml_observations)
    assert trust.evidence_status == "MATURE_GREEN"
    single = row("m1|ml|away", q=0.60, break_even=0.50)
    assert select_value([single], state)["candidate_id"] == single["candidate_id"]


def test_ml_amber_singleton_without_spread_passes():
    state = ValueSelectorState(ml_observations=losing_state(3))
    trust = family_trust(state.ml_observations)
    assert trust.state == "AMBER"
    single = row("m1|ml|away", q=0.60, break_even=0.50)
    assert select_value([single], state) == NO_VALUE_PLAY


def test_ml_red_is_barred_but_spread_can_remain_eligible():
    # At n=8 and data_trust=0, frozen trust is exactly .25; RED is strictly <.25.
    state = ValueSelectorState(ml_observations=losing_state(9))
    assert family_trust(state.ml_observations).state == "RED"
    ml = row("m1|ml|away", q=0.70, break_even=0.50)
    assert select_value([ml], state) == NO_VALUE_PLAY
    spread = spread_row("s1|spread|away")
    assert select_value([ml, spread], state)["candidate_id"] == spread["candidate_id"]


def test_advance_state_observes_each_family_frontier_not_only_headline():
    ml = row("m1|ml|away", q=0.60, break_even=0.50, settlement="WIN")
    spread = spread_row("s1|spread|away", settlement="LOSS")
    next_state = advance_value_state(ValueSelectorState(), [ml, spread])
    assert len(next_state.ml_observations) == 1
    assert len(next_state.spread_observations) == 1
    assert next_state.ml_observations[0].predicted_edge == pytest.approx(0.10)
    assert next_state.spread_observations[0].predicted_edge == pytest.approx(0.03)


def test_totals_never_enter_any_final_lane():
    total = row(
        "t1|total|over",
        market="total",
        side="over",
        line=44.0,
        q=0.90,
        pinnacle=0.90,
        ev=2.0,
        regions="ML_DOG_VALUE_ZONE_AVG",
    )
    assert select_hit_rate([total]) == NO_HIT_RATE_PLAY
    assert select_balanced([total]) == NO_BALANCED_PLAY
    assert select_value([total], ValueSelectorState()) == NO_VALUE_PLAY


def test_final_headlines_are_deterministic_and_overlap_is_allowed():
    best = row("g1|ml|away", q=0.65, pinnacle=0.63, break_even=0.50)
    state = ValueSelectorState(ml_observations=winning_state(3))
    a = select_headlines([best], state)
    b = select_headlines(list(reversed([best])), state)
    assert a == b
    assert a["hit_rate"]["candidate_id"] == best["candidate_id"]
    assert a["balanced"]["candidate_id"] == best["candidate_id"]
    assert a["value"]["candidate_id"] == best["candidate_id"]
