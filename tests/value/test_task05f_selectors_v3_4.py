import copy

import pytest

from nfl_edge.value.selectors_v3_4 import (
    rank_balanced_v3_4,
    rank_high_hit_rate_v3_4,
    rank_value_v3_4,
    select_primary_cards_v3_4,
)


def _row(
    cid,
    *,
    market="moneyline",
    confidence=0.60,
    proxy=0.70,
    ev=0.03,
    units=1.0,
    status="VALUE",
    reliability="MEDIUM",
    actionable=True,
    season=2024,
):
    return {
        "candidate_id": cid,
        "offer_id": f"offer-{cid}",
        "game_id": cid,
        "season": season,
        "market_type": market,
        "selection": "home" if market != "total" else "over",
        "football_confidence_z": confidence,
        "football_cash_confidence_proxy": proxy,
        "evaluator_recommended_units": units,
        "evaluator_actionable": actionable,
        "price_status": status,
        "expected_value": ev,
        "strict_positive_value": status == "VALUE" and ev > 0,
        "reliability": reliability,
        "uncertainty": 0.03,
    }


def test_selector_requires_precomputed_board_fields():
    row = _row("x")
    del row["football_confidence_z"]
    with pytest.raises(RuntimeError, match="requires evaluated-wager board fields"):
        select_primary_cards_v3_4([row])


def test_hhr_ranks_evaluator_approved_wagers_by_football_confidence():
    rows = [
        _row("a", market="spread", confidence=0.40, proxy=0.66),
        _row("b", market="moneyline", confidence=0.90, proxy=0.82, status="PLAYABLE", ev=-0.002),
        _row("c", market="total", confidence=0.65, proxy=0.74),
    ]
    assert rank_high_hit_rate_v3_4(rows)[0]["candidate_id"] == "b"


def test_hhr_rejects_lean_pass_and_zero_unit_rows():
    rows = [
        _row("lean", confidence=1.2, proxy=0.88, status="LEAN", ev=-0.05, units=0.0, actionable=False),
        _row("zero", confidence=1.1, proxy=0.86, units=0.0, actionable=False),
        _row("good", confidence=0.5, proxy=0.69),
    ]
    assert [r["candidate_id"] for r in rank_high_hit_rate_v3_4(rows)] == ["good"]


def test_balanced_minimax_uses_confidence_and_ev():
    rows = [
        _row("hit", confidence=0.90, proxy=0.82, ev=0.01),
        _row("middle", confidence=0.60, proxy=0.73, ev=0.05),
        _row("value", confidence=0.10, proxy=0.54, ev=0.10),
    ]
    ranked = rank_balanced_v3_4(rows)
    assert ranked[0]["candidate_id"] == "middle"
    assert ranked[0]["balanced_hit_rank"] == 2
    assert ranked[0]["balanced_price_quality_rank"] == 2


def test_value_requires_strict_positive_ev():
    rows = [
        _row("playable", ev=-0.002, status="PLAYABLE", units=0.7),
        _row("best", market="total", ev=0.10, units=1.2),
        _row("other", market="spread", ev=0.04, units=1.5),
    ]
    assert [r["candidate_id"] for r in rank_value_v3_4(rows)] == ["best", "other"]


def test_market_type_never_changes_rank_for_equal_inputs():
    base = _row("a", market="moneyline", confidence=0.7, proxy=0.76, ev=0.04)
    rows = [
        base,
        dict(base, candidate_id="b", offer_id="offer-b", game_id="b", market_type="spread"),
        dict(base, candidate_id="c", offer_id="offer-c", game_id="c", market_type="total", selection="over"),
    ]
    # Exact ties resolve only by deterministic identity, not by market preference.
    assert [r["candidate_id"] for r in rank_high_hit_rate_v3_4(rows)] == ["a", "b", "c"]
    assert [r["candidate_id"] for r in rank_value_v3_4(rows)] == ["a", "b", "c"]


def test_low_reliability_is_not_an_eligibility_veto():
    low = _row("low", reliability="LOW", confidence=0.8, proxy=0.79, units=0.8, actionable=True)
    assert rank_high_hit_rate_v3_4([low])[0]["candidate_id"] == "low"
    assert rank_balanced_v3_4([low])[0]["candidate_id"] == "low"
    assert rank_value_v3_4([low])[0]["candidate_id"] == "low"


def test_distinct_primary_cards():
    rows = [
        _row("a", confidence=1.0, proxy=0.84, ev=0.12, units=1.5),
        _row("b", market="spread", confidence=0.8, proxy=0.79, ev=0.08, units=1.3),
        _row("c", market="total", confidence=0.7, proxy=0.76, ev=0.05, units=1.2),
    ]
    picks = select_primary_cards_v3_4(rows)
    ids = [p["candidate_id"] for p in picks.values() if p]
    assert len(ids) == 3
    assert len(set(ids)) == 3


def test_deterministic_input_order_invariant():
    rows = [
        _row("a", confidence=0.7, proxy=0.76, ev=0.04),
        _row("b", market="spread", confidence=0.7, proxy=0.76, ev=0.04),
        _row("c", market="total", confidence=0.7, proxy=0.76, ev=0.04),
    ]
    assert select_primary_cards_v3_4(rows) == select_primary_cards_v3_4(list(reversed(copy.deepcopy(rows))))


def test_outcome_firewall():
    row = _row("x")
    row["settlement"] = "WIN"
    with pytest.raises(RuntimeError, match="forbidden outcome fields"):
        select_primary_cards_v3_4([row])


def test_sealed_2025_firewall():
    with pytest.raises(RuntimeError, match="sealed season"):
        select_primary_cards_v3_4([_row("x", season=2025)])
