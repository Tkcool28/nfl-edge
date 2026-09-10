from __future__ import annotations

from nfl_edge.live.product_2026 import _headline, _lane_selection, _post_selection_play_through
from nfl_edge.recommendation.final_selectors_v1 import ValueSelectorState
from nfl_edge.value.market_math import break_even_probability


FOOTBALL_GAMES = {
    "2026_01_SF_LAR": {
        "game_id": "2026_01_SF_LAR",
        "away_team": "SF",
        "home_team": "LAR",
    }
}


def _moneyline_row(
    price: int,
    *,
    play_through_price: int | None = None,
    concession: float = 0.015,
    evaluator_probability: float = 0.70,
    expected_value: float = -0.01,
) -> dict:
    return {
        "candidate_id": f"2026_01_SF_LAR|moneyline|home|draftkings|{price}",
        "game_id": "2026_01_SF_LAR",
        "market_type": "moneyline",
        "selected_side": "home",
        "sportsbook": "draftkings",
        "line": None,
        "american_odds": int(price),
        "supported": True,
        "model_confidence_supported": True,
        "model_confidence_support_n": 512,
        "model_confidence_probability": 0.66,
        "break_even_probability": break_even_probability(price),
        "pinnacle_anchor_probability": 0.62,
        "reliability": "HIGH",
        "price_status": "LEAN",
        "actionable_probability": evaluator_probability,
        "conditional_nonpush_probability": evaluator_probability,
        "expected_value": expected_value,
        "uncertainty": 0.02,
        "model_candidate_regions": "",
        "evaluated_edge_probability": evaluator_probability - break_even_probability(price),
        "model_price_gap": 0.01,
        # Raw Task05F absolute threshold remains available as provenance, but
        # headline composition consumes only Task05F's already-computed concession.
        "play_through_price_american": play_through_price,
        "play_through_break_even_concession": concession,
    }


def test_live_balanced_uses_price_bounded_v2_not_legacy_v1_band():
    # Legacy V1 allowed this price (-220..+200). Balanced V2 moneyline must not.
    selections = _lane_selection(
        [_moneyline_row(-198, play_through_price=-187)],
        ValueSelectorState(),
    )
    assert selections["balanced"] is None


def test_balanced_play_through_consumes_frozen_concession_after_selection():
    # Task05F's 1.5pp concession is not recalculated or used as a selector gate.
    # Once -120 wins Balanced, the same 1.5pp concession extends the accepted
    # break-even point to the conservative integer boundary -127.
    selected = _lane_selection(
        [_moneyline_row(-120, play_through_price=-110, concession=0.015)],
        ValueSelectorState(),
    )["balanced"]
    assert selected is not None
    headline = _headline("balanced", selected, FOOTBALL_GAMES)
    assert headline["state"] == "BET"
    assert headline["american_odds"] == -120
    assert headline["recommended_units"] == 0.75
    assert headline["play_through"] == {"line": None, "price_american": -127}


def test_hhr_keeps_a_worse_price_play_through_even_when_raw_absolute_threshold_is_better():
    # HHR selection is probability-first. A raw Task05F absolute threshold can be
    # better than an already-accepted HHR price; the headline still consumes the
    # frozen concession after selection rather than dropping the execution range.
    row = _moneyline_row(-198, play_through_price=-187, concession=0.015)
    selected = _lane_selection([row], ValueSelectorState())["hit_rate"]
    assert selected is not None
    headline = _headline("hit_rate", selected, FOOTBALL_GAMES)
    assert headline["state"] == "BET"
    assert headline["american_odds"] == -198
    assert headline["play_through"] == {"line": None, "price_american": -211}


def test_zero_frozen_concession_publishes_no_headline_extension():
    row = _moneyline_row(-120, concession=0.0)
    assert _post_selection_play_through(row, lane="balanced", state="BET") is None


def test_value_through_boundary_never_crosses_zero_ev():
    # At -112 the evaluator is just above break-even. A 1.5pp generic corridor
    # would stretch much farther, but Value must stop at the last integer price
    # whose break-even probability remains strictly below evaluator q.
    row = _moneyline_row(
        -112,
        concession=0.015,
        evaluator_probability=0.5316,
        expected_value=0.0062,
    )
    boundary = _post_selection_play_through(row, lane="value", state="BET")
    assert boundary == {"line": None, "price_american": -113}
    assert break_even_probability(boundary["price_american"]) < row["conditional_nonpush_probability"]
    assert break_even_probability(-114) >= row["conditional_nonpush_probability"]


def test_value_through_is_omitted_when_no_strictly_worse_integer_price_stays_positive_ev():
    current = -112
    row = _moneyline_row(
        current,
        concession=0.015,
        evaluator_probability=(break_even_probability(current) + break_even_probability(-113)) / 2.0,
        expected_value=0.0001,
    )
    assert _post_selection_play_through(row, lane="value", state="BET") is None
