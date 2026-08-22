import copy

import pytest

from nfl_edge.value.selectors_v3_3 import (
    football_confidence_z,
    rank_balanced_v3_3,
    rank_high_hit_rate_v3_3,
    rank_value_v3_3,
    select_primary_cards_v3_3,
)


def _row(
    cid: str,
    *,
    market: str,
    raw: float,
    line: float | None,
    selection: str,
    ev: float = 0.03,
    status: str = "VALUE",
    supported: bool = True,
    reliability: str = "MEDIUM",
    season: int = 2024,
    uncertainty: float = 0.02,
):
    return {
        "candidate_id": cid,
        "game_id": cid,
        "season": season,
        "week": 1,
        "market_type": market,
        "selection": selection,
        "raw_football_output": raw,
        "actionable_book": "draftkings",
        "actionable_line": line,
        "actionable_price_american": -110,
        "expected_value": ev,
        "evaluated_edge_probability": ev / 2,
        "strict_positive_value": status == "VALUE" and ev > 0,
        "price_status": status,
        "supported": supported,
        "reliability": reliability,
        "uncertainty": uncertainty,
    }


def test_all_three_markets_can_win_high_hit_rate():
    ml = _row("ml", market="moneyline", raw=0.70, line=None, selection="home")
    spread = _row("spread", market="spread", raw=7.0, line=-1.0, selection="home")
    total = _row("total", market="total", raw=53.0, line=47.0, selection="over")

    assert rank_high_hit_rate_v3_3([ml, spread, total])[0]["candidate_id"] == "ml"

    spread2 = dict(spread, raw_football_output=12.0)
    assert rank_high_hit_rate_v3_3([ml, spread2, total])[0]["candidate_id"] == "spread"

    total2 = dict(total, raw_football_output=60.0)
    assert rank_high_hit_rate_v3_3([ml, spread, total2])[0]["candidate_id"] == "total"


def test_hhr_ignores_evaluator_support_reliability_and_price_status_as_gates():
    strong = _row(
        "strong",
        market="moneyline",
        raw=0.82,
        line=None,
        selection="home",
        ev=-0.20,
        status="LEAN",
        supported=False,
        reliability="LOW",
    )
    weak = _row("weak", market="moneyline", raw=0.66, line=None, selection="home")
    ranked = rank_high_hit_rate_v3_3([weak, strong])
    assert ranked[0]["candidate_id"] == "strong"


def test_balanced_is_cross_market_not_within_market_ranked():
    rows = [
        _row("ml", market="moneyline", raw=0.70, line=None, selection="home", ev=0.01),
        _row("spread", market="spread", raw=8.0, line=-3.0, selection="home", ev=0.05),
        _row("total", market="total", raw=50.0, line=47.0, selection="over", ev=0.10),
    ]
    ranked = rank_balanced_v3_3(rows)
    assert {r["market_type"] for r in ranked} == {"moneyline", "spread", "total"}
    assert ranked[0]["candidate_id"] in {"ml", "spread", "total"}


def test_balanced_rejects_side_football_model_opposes():
    opposed = _row(
        "opposed",
        market="spread",
        raw=7.0,
        line=3.0,
        selection="away",
        ev=0.20,
    )
    favored = _row(
        "favored",
        market="moneyline",
        raw=0.60,
        line=None,
        selection="home",
        ev=0.01,
    )
    ranked = rank_balanced_v3_3([opposed, favored])
    assert [r["candidate_id"] for r in ranked] == ["favored"]


def test_low_reliability_is_penalty_not_exclusion_for_balanced():
    low = _row(
        "low",
        market="total",
        raw=55.0,
        line=47.0,
        selection="over",
        ev=0.04,
        reliability="LOW",
    )
    assert rank_balanced_v3_3([low])[0]["candidate_id"] == "low"


def test_all_three_markets_can_win_value():
    for market, raw, line, selection in [
        ("moneyline", 0.60, None, "home"),
        ("spread", 4.0, -2.5, "home"),
        ("total", 50.0, 47.0, "over"),
    ]:
        winner = _row("winner", market=market, raw=raw, line=line, selection=selection, ev=0.12)
        other = _row("other", market="spread", raw=3.0, line=-2.5, selection="home", ev=0.02)
        assert rank_value_v3_3([other, winner])[0]["candidate_id"] == "winner"


def test_value_requires_supported_strict_positive_ev_but_not_market_type():
    bad = _row(
        "bad",
        market="moneyline",
        raw=0.70,
        line=None,
        selection="home",
        ev=-0.01,
        status="PLAYABLE",
    )
    unsupported = _row(
        "unsupported",
        market="total",
        raw=55.0,
        line=47.0,
        selection="over",
        ev=0.30,
        supported=False,
    )
    good = _row("good", market="moneyline", raw=0.62, line=None, selection="home", ev=0.03)
    assert [r["candidate_id"] for r in rank_value_v3_3([bad, unsupported, good])] == ["good"]


def test_distinct_primary_cards():
    rows = [
        _row("a", market="moneyline", raw=0.80, line=None, selection="home", ev=0.20),
        _row("b", market="spread", raw=8.0, line=-3.0, selection="home", ev=0.10),
        _row("c", market="total", raw=55.0, line=47.0, selection="over", ev=0.05),
    ]
    picks = select_primary_cards_v3_3(rows)
    ids = [p["candidate_id"] for p in picks.values() if p]
    assert len(ids) == len(set(ids))


def test_deterministic_input_order_invariant():
    rows = [
        _row("a", market="moneyline", raw=0.70, line=None, selection="home", ev=0.03),
        _row("b", market="spread", raw=6.0, line=-3.0, selection="home", ev=0.03),
        _row("c", market="total", raw=50.0, line=47.0, selection="over", ev=0.03),
    ]
    assert select_primary_cards_v3_3(rows) == select_primary_cards_v3_3(list(reversed(copy.deepcopy(rows))))


def test_outcome_fields_rejected():
    row = _row("x", market="moneyline", raw=0.70, line=None, selection="home")
    row["settlement"] = "WIN"
    with pytest.raises(RuntimeError, match="forbidden outcome fields"):
        select_primary_cards_v3_3([row])


def test_sealed_2025_firewall():
    row = _row("x", market="moneyline", raw=0.70, line=None, selection="home", season=2025)
    with pytest.raises(RuntimeError, match="sealed season"):
        select_primary_cards_v3_3([row])


def test_confidence_scale_preserves_native_direction():
    assert football_confidence_z(
        _row("ml", market="moneyline", raw=0.70, line=None, selection="home")
    ) > 0
    assert football_confidence_z(
        _row("sp", market="spread", raw=5.0, line=-3.0, selection="home")
    ) > 0
    assert football_confidence_z(
        _row("tot", market="total", raw=50.0, line=47.0, selection="over")
    ) > 0
