import copy

import pytest

from nfl_edge.value.selectors import select_primary_cards
from nfl_edge.value.selectors_v2 import football_signal_support, select_primary_cards_v2


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
    disagreement: float | None = 0.02,
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


def test_ml_negative_or_zero_football_disagreement_is_ineligible():
    positive = _row("positive", probability=0.60, disagreement=0.001)
    zero = _row("zero", probability=0.99, ev=0.50, disagreement=0.0)
    negative = _row("negative", probability=0.98, ev=0.49, disagreement=-0.01)

    assert football_signal_support(zero).supported is False
    assert football_signal_support(negative).supported is False
    picks = select_primary_cards_v2([zero, negative, positive])
    assert all(pick["candidate_id"] == "positive" for pick in picks.values() if pick)


def test_ml_positive_football_disagreement_is_eligible():
    row = _row("ml", disagreement=1e-9)
    support = football_signal_support(row)
    assert support.supported is True
    assert support.margin == pytest.approx(1e-9)
    picks = select_primary_cards_v2([row])
    assert all(pick["candidate_id"] == "ml" for pick in picks.values() if pick)


def test_spread_home_and_away_exact_line_support_math():
    home = _row(
        "home",
        market="spread",
        selection="home",
        line=-2.5,
        raw=3.0,
        disagreement=None,
    )
    away = _row(
        "away",
        market="spread",
        selection="away",
        line=3.5,
        raw=3.0,
        disagreement=None,
    )
    home_support = football_signal_support(home)
    away_support = football_signal_support(away)
    assert home_support.supported is True
    assert home_support.margin == pytest.approx(0.5)
    assert away_support.supported is True
    assert away_support.margin == pytest.approx(0.5)


def test_spread_unfavorable_side_is_rejected():
    home = _row(
        "home",
        market="spread",
        selection="home",
        line=-3.5,
        raw=3.0,
        disagreement=None,
    )
    away = _row(
        "away",
        market="spread",
        selection="away",
        line=2.5,
        raw=3.0,
        disagreement=None,
    )
    assert football_signal_support(home).margin == pytest.approx(-0.5)
    assert football_signal_support(home).supported is False
    assert football_signal_support(away).margin == pytest.approx(-0.5)
    assert football_signal_support(away).supported is False


def test_total_over_and_under_exact_line_support_math():
    over = _row(
        "over",
        market="total",
        selection="over",
        line=47.5,
        raw=49.0,
        disagreement=None,
    )
    under = _row(
        "under",
        market="total",
        selection="under",
        line=50.5,
        raw=49.0,
        disagreement=None,
    )
    assert football_signal_support(over).supported is True
    assert football_signal_support(over).margin == pytest.approx(1.5)
    assert football_signal_support(under).supported is True
    assert football_signal_support(under).margin == pytest.approx(1.5)


def test_exact_zero_support_is_ineligible_for_point_markets():
    spread = _row(
        "spread",
        market="spread",
        selection="home",
        line=-3.0,
        raw=3.0,
        disagreement=None,
    )
    total = _row(
        "total",
        market="total",
        selection="over",
        line=47.0,
        raw=47.0,
        disagreement=None,
    )
    assert football_signal_support(spread).margin == pytest.approx(0.0)
    assert football_signal_support(spread).supported is False
    assert football_signal_support(total).margin == pytest.approx(0.0)
    assert football_signal_support(total).supported is False


def test_missing_signal_fails_closed():
    ml = _row("ml", disagreement=None)
    spread = _row(
        "spread",
        market="spread",
        selection="home",
        line=-3.0,
        raw=None,
        disagreement=None,
    )
    total = _row(
        "total",
        market="total",
        selection="under",
        line=47.0,
        raw=None,
        disagreement=None,
    )
    assert football_signal_support(ml).supported is False
    assert football_signal_support(spread).supported is False
    assert football_signal_support(total).supported is False
    assert select_primary_cards_v2([ml, spread, total]) == {
        "HIGH_HIT_RATE": None,
        "BALANCED": None,
        "VALUE": None,
    }


def test_v1_rank_order_is_unchanged_when_every_candidate_passes_gate():
    rows = [
        _row("a", probability=0.67, ev=0.02, edge=0.03, disagreement=0.01),
        _row("b", probability=0.59, ev=0.08, edge=0.06, disagreement=0.02),
        _row("c", probability=0.72, ev=-0.004, edge=-0.01, status="PLAYABLE", disagreement=0.03),
    ]
    v1 = select_primary_cards(copy.deepcopy(rows))
    v2 = select_primary_cards_v2(copy.deepcopy(rows))
    for card in ("HIGH_HIT_RATE", "BALANCED", "VALUE"):
        assert v1[card]["candidate_id"] == v2[card]["candidate_id"]


def test_unsupported_and_low_reliability_still_never_selected_after_gate():
    rows = [
        _row("unsupported", probability=0.99, ev=0.50, supported=False, disagreement=0.20),
        _row("low", probability=0.98, ev=0.49, reliability="LOW", disagreement=0.20),
        _row("medium", probability=0.60, ev=0.04, reliability="MEDIUM", disagreement=0.01),
    ]
    picks = select_primary_cards_v2(rows)
    assert all(pick["candidate_id"] == "medium" for pick in picks.values() if pick)


def test_balanced_and_value_still_require_strict_value():
    playable = _row(
        "playable",
        probability=0.80,
        ev=-0.002,
        edge=-0.001,
        status="PLAYABLE",
        disagreement=0.05,
    )
    value = _row("value", probability=0.60, ev=0.03, edge=0.02, disagreement=0.01)
    picks = select_primary_cards_v2([playable, value])
    assert picks["HIGH_HIT_RATE"]["candidate_id"] == "playable"
    assert picks["BALANCED"]["candidate_id"] == "value"
    assert picks["VALUE"]["candidate_id"] == "value"


def test_selected_pick_exposes_support_diagnostic_but_not_rank_magnitude():
    lower_probability_large_support = _row(
        "large",
        probability=0.60,
        ev=0.03,
        disagreement=0.20,
    )
    higher_probability_small_support = _row(
        "small",
        probability=0.70,
        ev=0.02,
        disagreement=0.001,
    )
    pick = select_primary_cards_v2([lower_probability_large_support, higher_probability_small_support])[
        "HIGH_HIT_RATE"
    ]
    assert pick["candidate_id"] == "small"
    assert pick["football_signal_supports_wager"] is True
    assert pick["football_signal_support_margin"] == pytest.approx(0.001)


def test_determinism_is_input_order_invariant_after_gate():
    rows = [
        _row("a", probability=0.61, ev=0.03, disagreement=0.01),
        _row("b", probability=0.58, ev=0.08, disagreement=0.02),
        _row("c", probability=0.64, ev=-0.004, status="PLAYABLE", disagreement=0.03),
    ]
    assert select_primary_cards_v2(rows) == select_primary_cards_v2(list(reversed(copy.deepcopy(rows))))


def test_v2_selector_rejects_outcome_fields():
    row = _row("a")
    row["settlement"] = "WIN"
    with pytest.raises(RuntimeError, match="forbidden outcome fields"):
        select_primary_cards_v2([row])


def test_v2_sealed_2025_firewall():
    with pytest.raises(RuntimeError, match="sealed season"):
        select_primary_cards_v2([_row("sealed", season=2025)])
