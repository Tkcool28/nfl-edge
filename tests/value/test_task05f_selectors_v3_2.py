import copy

import pytest

from nfl_edge.value.selectors_v3_2 import (
    model_native_strength,
    rank_balanced_v3_2,
    rank_high_hit_rate_v3_2,
    rank_value_v3_2,
    select_primary_cards_v3_2,
)


def _row(
    cid: str,
    *,
    market: str = "moneyline",
    raw: float = 0.60,
    evaluator_p: float = 0.60,
    ev: float = 0.02,
    edge: float = 0.01,
    status: str = "VALUE",
    reliability: str = "MEDIUM",
    supported: bool = True,
    line: float | None = None,
    selection: str | None = None,
    uncertainty: float | None = 0.02,
    season: int = 2024,
):
    if selection is None:
        selection = "home" if market != "total" else "over"
    if line is None and market == "spread":
        line = -2.5
    if line is None and market == "total":
        line = 47.5
    return {
        "candidate_id": cid,
        "game_id": cid,
        "season": season,
        "week": 1,
        "market_type": market,
        "selection": selection,
        "actionable_book": "draftkings",
        "actionable_line": line,
        "actionable_price_american": -110,
        "raw_football_output": raw,
        "actionable_probability": evaluator_p,
        "expected_value": ev,
        "evaluated_edge_probability": edge,
        "price_status": status,
        "strict_positive_value": status == "VALUE" and ev > 0.0,
        "reliability": reliability,
        "supported": supported,
        "uncertainty": uncertainty,
    }


def test_hhr_uses_raw_model_probability_not_evaluator_probability():
    rows = [
        _row("model_pick", raw=0.78, evaluator_p=0.58),
        _row("market_pick", raw=0.59, evaluator_p=0.82),
    ]
    ranked = rank_high_hit_rate_v3_2(rows)
    assert ranked[0]["candidate_id"] == "model_pick"
    assert ranked[0]["model_native_hit_probability"] == pytest.approx(0.78)


def test_hhr_can_select_low_unsupported_lean_or_pass_without_relabeling_price():
    rows = [
        _row("medium", raw=0.72, evaluator_p=0.75),
        _row("low_lean", raw=0.81, evaluator_p=0.55, reliability="LOW", status="LEAN", ev=-0.08),
        _row("unsupported_pass", raw=0.84, evaluator_p=0.50, reliability="UNSUPPORTED", supported=False, status="PASS", ev=-0.20),
    ]
    ranked = rank_high_hit_rate_v3_2(rows)
    assert ranked[0]["candidate_id"] == "unsupported_pass"
    assert ranked[0]["price_status"] == "PASS"
    assert ranked[0]["hhr_price_actionable"] is False
    assert ranked[1]["candidate_id"] == "low_lean"


def test_hhr_only_uses_moneyline_native_probability_capability():
    rows = [
        _row("ml", raw=0.61),
        _row("spread", market="spread", raw=14.0, line=-2.5, evaluator_p=0.90),
        _row("total", market="total", raw=55.0, line=47.5, evaluator_p=0.95),
    ]
    ranked = rank_high_hit_rate_v3_2(rows)
    assert [r["candidate_id"] for r in ranked] == ["ml"]


def test_hhr_requires_model_to_favor_selected_ml_side_semantically():
    rows = [_row("oppose", raw=0.49), _row("favor", raw=0.51)]
    assert [r["candidate_id"] for r in rank_high_hit_rate_v3_2(rows)] == ["favor"]


def test_spread_native_direction_strength_is_side_oriented():
    home = _row("home", market="spread", raw=4.0, line=-2.5, selection="home")
    away = _row("away", market="spread", raw=4.0, line=3.5, selection="away")
    assert model_native_strength(home) == pytest.approx(1.5)
    assert model_native_strength(away) == pytest.approx(-0.5)


def test_balanced_uses_raw_ml_strength_not_evaluator_probability():
    rows = [
        _row("raw_strong", raw=0.76, evaluator_p=0.55, ev=0.02),
        _row("eval_strong", raw=0.56, evaluator_p=0.80, ev=0.02),
    ]
    ranked = rank_balanced_v3_2(rows)
    assert ranked[0]["candidate_id"] == "raw_strong"
    assert ranked[0]["balanced_native_hit_rank_within_market"] == 1


def test_balanced_requires_native_model_direction():
    rows = [
        _row("ml_opposed", raw=0.49, evaluator_p=0.75, ev=0.10),
        _row("spread_opposed", market="spread", raw=1.0, line=-3.0, ev=0.10),
        _row("ml_supported", raw=0.56, evaluator_p=0.55, ev=-0.005, status="PLAYABLE"),
    ]
    ranked = rank_balanced_v3_2(rows)
    assert [r["candidate_id"] for r in ranked] == ["ml_supported"]


def test_balanced_keeps_evaluator_actionability_and_reliability_guard():
    rows = [
        _row("low", raw=0.90, reliability="LOW", ev=0.20),
        _row("lean", raw=0.88, status="LEAN", ev=-0.04),
        _row("unsupported", raw=0.87, supported=False, reliability="UNSUPPORTED", status="PASS", ev=-0.10),
        _row("good", raw=0.62, status="PLAYABLE", ev=-0.002),
    ]
    ranked = rank_balanced_v3_2(rows)
    assert [r["candidate_id"] for r in ranked] == ["good"]


def test_balanced_native_rank_is_within_market_and_price_rank_is_global():
    rows = [
        _row("ml_hit", raw=0.75, ev=0.01),
        _row("ml_middle", raw=0.65, ev=0.05),
        _row("spread_hit", market="spread", raw=7.0, line=-2.5, ev=0.01),
        _row("spread_middle", market="spread", raw=5.0, line=-2.5, ev=0.05),
        _row("spread_value", market="spread", raw=4.0, line=-2.5, ev=0.10),
    ]
    ranked = rank_balanced_v3_2(rows)
    by_id = {r["candidate_id"]: r for r in ranked}
    assert by_id["ml_hit"]["balanced_native_hit_rank_within_market"] == 1
    assert by_id["spread_hit"]["balanced_native_hit_rank_within_market"] == 1
    assert by_id["spread_value"]["balanced_price_quality_rank"] == 1
    assert ranked[0]["candidate_id"] in {"ml_middle", "spread_middle"}


def test_value_is_identical_in_semantics_to_v3_1_strict_spread_value():
    rows = [
        _row("ml", raw=0.70, ev=0.20),
        _row("spread_value", market="spread", raw=5.0, line=-2.5, ev=0.04, edge=0.03),
        _row("spread_playable", market="spread", raw=5.0, line=-2.5, ev=-0.001, status="PLAYABLE"),
    ]
    ranked = rank_value_v3_2(rows)
    assert [r["candidate_id"] for r in ranked] == ["spread_value"]
    assert ranked[0]["selector_version"] == "task05f_selectors_v3_2_native_confidence"


def test_featured_cards_stay_distinct_when_candidates_exist():
    rows = [
        _row("hhr", raw=0.82, status="PLAYABLE", ev=-0.003),
        _row("balanced_ml", raw=0.68, ev=0.03),
        _row("value_spread", market="spread", raw=6.0, line=-2.5, ev=0.08, edge=0.05),
        _row("balanced_spread", market="spread", raw=5.0, line=-2.5, ev=0.03),
    ]
    picks = select_primary_cards_v3_2(rows)
    ids = [p["candidate_id"] for p in picks.values() if p]
    assert len(ids) == len(set(ids))
    assert picks["HIGH_HIT_RATE"]["candidate_id"] == "hhr"
    assert picks["VALUE"]["candidate_id"] == "value_spread"


def test_deterministic_input_order_invariance():
    rows = [
        _row("b", raw=0.65, ev=0.03),
        _row("a", raw=0.65, ev=0.03),
        _row("spread", market="spread", raw=5.0, line=-2.5, ev=0.04),
    ]
    assert select_primary_cards_v3_2(rows) == select_primary_cards_v3_2(list(reversed(copy.deepcopy(rows))))


def test_outcome_fields_rejected():
    row = _row("x")
    row["settlement"] = "WIN"
    with pytest.raises(RuntimeError, match="forbidden outcome fields"):
        select_primary_cards_v3_2([row])


def test_sealed_2025_firewall():
    with pytest.raises(RuntimeError, match="sealed season"):
        select_primary_cards_v3_2([_row("sealed", season=2025)])
