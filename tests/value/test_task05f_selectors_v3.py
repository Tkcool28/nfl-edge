import copy

import pytest

from nfl_edge.value.selectors import select_balanced, select_high_hit_rate, select_value
from nfl_edge.value.selectors_v3 import (
    PROBABILITY_CAPABLE_MARKETS,
    VALUE_CAPABLE_MARKETS,
    select_primary_cards_v3,
)


def _row(
    cid: str,
    *,
    market: str = "moneyline",
    selection: str = "home",
    probability: float = 0.60,
    ev: float = 0.05,
    edge: float = 0.03,
    reliability: str = "MEDIUM",
    status: str = "VALUE",
    supported: bool = True,
    uncertainty: float | None = 0.02,
    season: int = 2024,
    line: float | None = None,
    raw: float | None = None,
    disagreement: float | None = -0.20,
):
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
        "actionable_probability": probability,
        "expected_value": ev,
        "evaluated_edge_probability": edge,
        "reliability": reliability,
        "price_status": status,
        "supported": supported,
        "strict_positive_value": status == "VALUE" and ev > 0.0,
        "uncertainty": uncertainty,
        "staking_probability": 0.01,
        "raw_football_output": raw,
        "model_market_disagreement": disagreement,
    }


def test_capability_registry_is_frozen_as_preregistered():
    assert PROBABILITY_CAPABLE_MARKETS == {"moneyline", "spread", "total"}
    assert VALUE_CAPABLE_MARKETS == {"spread"}


def test_high_hit_can_select_moneyline_from_probability_capability():
    ml = _row("ml", market="moneyline", probability=0.76, disagreement=-0.30)
    spread = _row("spread", market="spread", probability=0.62, line=-3.0, raw=-20.0)
    picks = select_primary_cards_v3([spread, ml])
    assert picks["HIGH_HIT_RATE"]["candidate_id"] == "ml"
    assert picks["HIGH_HIT_RATE"]["raw_football_direction_gate_applied"] is False


def test_high_hit_can_select_spread_or_total_from_probability_capability():
    spread = _row("spread", market="spread", probability=0.63, line=-3.0, raw=-20.0)
    total = _row("total", market="total", selection="over", probability=0.68, line=47.5, raw=20.0)
    picks = select_primary_cards_v3([spread, total])
    assert picks["HIGH_HIT_RATE"]["candidate_id"] == "total"


def test_high_hit_still_allows_playable():
    playable = _row("playable", market="moneyline", probability=0.80, ev=-0.004, status="PLAYABLE")
    value = _row("value", market="spread", probability=0.62, ev=0.03, line=-2.5)
    picks = select_primary_cards_v3([playable, value])
    assert picks["HIGH_HIT_RATE"]["candidate_id"] == "playable"
    assert picks["HIGH_HIT_RATE"]["price_status"] == "PLAYABLE"


def test_balanced_rejects_moneyline_and_total_without_value_capability():
    ml = _row("ml", market="moneyline", probability=0.80, ev=0.50)
    total = _row("total", market="total", selection="over", probability=0.79, ev=0.49, line=47.5)
    spread = _row("spread", market="spread", probability=0.58, ev=0.03, line=-2.5)
    picks = select_primary_cards_v3([ml, total, spread])
    assert picks["BALANCED"]["candidate_id"] == "spread"


def test_value_rejects_moneyline_and_total_without_value_capability():
    ml = _row("ml", market="moneyline", ev=0.60)
    total = _row("total", market="total", selection="under", ev=0.55, line=48.5)
    spread = _row("spread", market="spread", ev=0.04, line=3.5)
    picks = select_primary_cards_v3([ml, total, spread])
    assert picks["VALUE"]["candidate_id"] == "spread"


def test_balanced_and_value_accept_medium_or_high_strict_value_spread():
    medium = _row("medium", market="spread", probability=0.60, ev=0.04, reliability="MEDIUM", line=-2.5)
    high = _row("high", market="spread", probability=0.58, ev=0.06, reliability="HIGH", line=3.5)
    picks = select_primary_cards_v3([medium, high])
    assert picks["BALANCED"] is not None
    assert picks["VALUE"] is not None
    assert picks["BALANCED"]["market_type"] == "spread"
    assert picks["VALUE"]["market_type"] == "spread"


def test_raw_football_direction_does_not_gate_primary_cards():
    ml = _row("ml", market="moneyline", probability=0.80, disagreement=-0.50)
    spread = _row("spread", market="spread", probability=0.60, ev=0.06, line=-7.0, raw=-30.0)
    picks = select_primary_cards_v3([ml, spread])
    assert picks["HIGH_HIT_RATE"]["candidate_id"] == "ml"
    assert picks["BALANCED"]["candidate_id"] == "spread"
    assert picks["VALUE"]["candidate_id"] == "spread"


def test_v1_ranking_order_is_preserved_inside_v3_eligible_universe():
    hhr_rows = [
        _row("ml", market="moneyline", probability=0.72, ev=0.01),
        _row("spread-a", market="spread", probability=0.64, ev=0.03, line=-2.5),
        _row("total", market="total", selection="under", probability=0.68, ev=0.02, line=47.5),
    ]
    assert select_primary_cards_v3(copy.deepcopy(hhr_rows))["HIGH_HIT_RATE"]["candidate_id"] == select_high_hit_rate(copy.deepcopy(hhr_rows))["candidate_id"]

    spread_rows = [
        _row("a", market="spread", probability=0.62, ev=0.03, line=-2.5),
        _row("b", market="spread", probability=0.57, ev=0.08, line=3.5),
        _row("c", market="spread", probability=0.66, ev=0.02, line=-1.5),
    ]
    picks = select_primary_cards_v3(copy.deepcopy(spread_rows))
    assert picks["BALANCED"]["candidate_id"] == select_balanced(copy.deepcopy(spread_rows))["candidate_id"]
    assert picks["VALUE"]["candidate_id"] == select_value(copy.deepcopy(spread_rows))["candidate_id"]


def test_no_play_is_valid_for_value_or_balanced_without_value_capable_market():
    rows = [_row("ml", market="moneyline"), _row("total", market="total", selection="over", line=47.5)]
    picks = select_primary_cards_v3(rows)
    assert picks["HIGH_HIT_RATE"] is not None
    assert picks["BALANCED"] is None
    assert picks["VALUE"] is None


def test_low_and_unsupported_never_selected():
    low = _row("low", market="spread", probability=0.99, ev=0.50, reliability="LOW", line=-1.5)
    unsupported = _row("unsupported", market="spread", probability=0.98, ev=0.49, supported=False, line=2.5)
    good = _row("good", market="spread", probability=0.60, ev=0.03, line=3.5)
    picks = select_primary_cards_v3([low, unsupported, good])
    assert all(pick["candidate_id"] == "good" for pick in picks.values() if pick)


def test_duplicate_selection_is_allowed():
    spread = _row("spread", market="spread", probability=0.70, ev=0.10, line=-2.5)
    picks = select_primary_cards_v3([spread])
    assert {pick["candidate_id"] for pick in picks.values() if pick} == {"spread"}


def test_deterministic_ties_are_input_order_invariant():
    a = _row("a", market="spread", probability=0.60, ev=0.04, edge=0.03, line=-2.5)
    b = _row("b", market="spread", probability=0.60, ev=0.04, edge=0.03, line=-2.5)
    forward = select_primary_cards_v3([a, b])
    reverse = select_primary_cards_v3([b, a])
    assert forward == reverse


def test_outcome_fields_are_rejected():
    row = _row("spread", market="spread", line=-2.5)
    row["realized_profit"] = 1.0
    with pytest.raises(RuntimeError, match="forbidden outcome fields"):
        select_primary_cards_v3([row])


def test_sealed_2025_firewall():
    with pytest.raises(RuntimeError, match="sealed season"):
        select_primary_cards_v3([_row("sealed", market="spread", line=-2.5, season=2025)])
