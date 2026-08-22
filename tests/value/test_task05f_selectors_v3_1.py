import copy

import pytest

from nfl_edge.value.selectors_v3_1 import (
    rank_balanced_v3_1,
    rank_high_hit_rate_v3_1,
    rank_value_v3_1,
    select_primary_cards_v3_1,
)


def _row(
    cid: str,
    *,
    market: str = "spread",
    probability: float = 0.60,
    ev: float = 0.04,
    edge: float = 0.03,
    status: str = "VALUE",
    reliability: str = "MEDIUM",
    supported: bool = True,
    uncertainty: float | None = 0.02,
    season: int = 2024,
):
    return {
        "candidate_id": cid,
        "game_id": cid,
        "season": season,
        "week": 1,
        "market_type": market,
        "selection": "home" if market != "total" else "over",
        "actionable_book": "draftkings",
        "actionable_line": -2.5 if market == "spread" else (47.5 if market == "total" else None),
        "actionable_price_american": -110,
        "actionable_probability": probability,
        "expected_value": ev,
        "evaluated_edge_probability": edge,
        "price_status": status,
        "strict_positive_value": status == "VALUE" and ev > 0.0,
        "reliability": reliability,
        "supported": supported,
        "uncertainty": uncertainty,
    }


def test_high_hit_allows_value_or_playable_across_probability_capable_markets():
    rows = [
        _row("ml", market="moneyline", probability=0.71, ev=-0.005, status="PLAYABLE"),
        _row("spread", market="spread", probability=0.66, ev=0.03),
        _row("total", market="total", probability=0.68, ev=-0.003, status="PLAYABLE"),
    ]
    ranked = rank_high_hit_rate_v3_1(rows)
    assert [row["candidate_id"] for row in ranked] == ["ml", "total", "spread"]


def test_balanced_allows_playable_and_does_not_require_positive_ev():
    rows = [
        _row("high_hit_bad_price", market="moneyline", probability=0.75, ev=-0.01, status="PLAYABLE"),
        _row("balanced_playable", market="total", probability=0.65, ev=-0.002, status="PLAYABLE"),
        _row("big_value_low_hit", market="spread", probability=0.48, ev=0.12, status="VALUE"),
    ]
    ranked = rank_balanced_v3_1(rows)
    assert ranked[0]["candidate_id"] == "balanced_playable"
    assert ranked[0]["price_status"] == "PLAYABLE"
    assert ranked[0]["expected_value"] < 0.0


def test_balanced_minimax_known_example():
    rows = [
        _row("hit", probability=0.70, ev=0.01),
        _row("middle", probability=0.62, ev=0.05),
        _row("value", probability=0.52, ev=0.10),
    ]
    ranked = rank_balanced_v3_1(rows)
    assert ranked[0]["candidate_id"] == "middle"
    assert ranked[0]["balanced_hit_rank"] == 2
    assert ranked[0]["balanced_price_quality_rank"] == 2
    assert ranked[0]["balanced_worst_rank"] == 2


def test_value_requires_strict_positive_spread_value_capability():
    rows = [
        _row("ml", market="moneyline", probability=0.60, ev=0.20, edge=0.10),
        _row("total", market="total", probability=0.60, ev=0.19, edge=0.09),
        _row("spread", market="spread", probability=0.55, ev=0.03, edge=0.02),
        _row("playable_spread", market="spread", probability=0.65, ev=-0.001, status="PLAYABLE"),
    ]
    ranked = rank_value_v3_1(rows)
    assert [row["candidate_id"] for row in ranked] == ["spread"]


def test_featured_cards_are_distinct_and_value_gets_first_claim():
    shared = _row("shared", probability=0.80, ev=0.20, edge=0.12)
    high_alt = _row("high_alt", market="moneyline", probability=0.75, ev=-0.002, status="PLAYABLE")
    balanced_alt = _row("balanced_alt", market="total", probability=0.64, ev=0.01, status="VALUE")
    extra = _row("extra", market="moneyline", probability=0.55, ev=0.0, status="PLAYABLE")

    picks = select_primary_cards_v3_1([shared, high_alt, balanced_alt, extra])
    assert picks["VALUE"]["candidate_id"] == "shared"
    assert picks["HIGH_HIT_RATE"]["candidate_id"] == "high_alt"
    assert picks["BALANCED"]["candidate_id"] == "balanced_alt"
    assert len({pick["candidate_id"] for pick in picks.values() if pick}) == 3


def test_card_may_be_empty_instead_of_duplicate():
    only = _row("only", probability=0.80, ev=0.20, edge=0.12)
    picks = select_primary_cards_v3_1([only])
    assert picks["VALUE"]["candidate_id"] == "only"
    assert picks["HIGH_HIT_RATE"] is None
    assert picks["BALANCED"] is None


def test_low_and_unsupported_never_selected():
    rows = [
        _row("low", probability=0.99, ev=0.50, reliability="LOW"),
        _row("unsupported", probability=0.98, ev=0.49, supported=False),
        _row("good", probability=0.60, ev=0.03),
        _row("alt", market="moneyline", probability=0.59, ev=-0.001, status="PLAYABLE"),
    ]
    picks = select_primary_cards_v3_1(rows)
    selected = {pick["candidate_id"] for pick in picks.values() if pick}
    assert "low" not in selected
    assert "unsupported" not in selected


def test_no_forced_market_diversification():
    rows = [
        _row("spread1", probability=0.70, ev=0.10),
        _row("spread2", probability=0.68, ev=0.05),
        _row("spread3", probability=0.64, ev=0.03),
    ]
    picks = select_primary_cards_v3_1(rows)
    assert all(pick is None or pick["market_type"] == "spread" for pick in picks.values())


def test_deterministic_ties_are_input_order_invariant():
    rows = [
        _row("b", probability=0.60, ev=0.04, edge=0.03),
        _row("a", probability=0.60, ev=0.04, edge=0.03),
        _row("c", market="moneyline", probability=0.59, ev=-0.001, status="PLAYABLE"),
    ]
    assert select_primary_cards_v3_1(rows) == select_primary_cards_v3_1(list(reversed(copy.deepcopy(rows))))


def test_outcome_fields_rejected():
    row = _row("x")
    row["settlement"] = "WIN"
    with pytest.raises(RuntimeError, match="forbidden outcome fields"):
        select_primary_cards_v3_1([row])


def test_sealed_2025_firewall():
    with pytest.raises(RuntimeError, match="sealed season"):
        select_primary_cards_v3_1([_row("sealed", season=2025)])
