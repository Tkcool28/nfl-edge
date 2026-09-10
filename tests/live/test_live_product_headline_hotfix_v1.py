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
    current_be = break_even_probability(price)
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
        "break_even_probability": current_be,
        "pinnacle_anchor_probability": 0.62,
        "reliability": "HIGH",
        "price_status": "LEAN",
        "actionable_probability": evaluator_probability,
        "conditional_nonpush_probability": evaluator_probability,
        "expected_value": expected_value,
        "uncertainty": 0.02,
        "model_candidate_regions": "",
        "evaluated_edge_probability": evaluator_probability - current_be,
        "model_price_gap": 0.01,
        # This absolute Task05F field is deliberately present to prove headline
        # execution does not reuse it after a selector has chosen a different
        # accepted current price.
        "play_through_price_american": play_through_price,
        # This is the frozen Task05F output: max 1.5pp already scaled by the
        # reliability/uncertainty confidence multiplier.
        "play_through_break_even_concession": concession,
    }


def test_live_balanced_uses_price_bounded_v2_not_legacy_v1_band():
    # Legacy V1 allowed this price (-220..+200). Balanced V2 moneyline must not.
    selections = _lane_selection(
        [_moneyline_row(-198, play_through_price=-187)],
        ValueSelectorState(),
    )
    assert selections["balanced"] is None


def test_balanced_corridor_is_anchored_to_selected_price_after_selection():
    # The raw evaluator threshold (-110) is better than the selected -120 and
    # therefore cannot be the headline's Play Through. The already-computed
    # 1.5pp concession is instead applied downstream to the selected -120.
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


def test_hhr_uses_same_post_selection_corridor_without_value_gate():
    # HHR is probability-first. Once -198 is selected, its execution corridor
    # starts at -198 even though the raw evaluator threshold was a better -187.
    selected = _lane_selection(
        [_moneyline_row(-198, play_through_price=-187, concession=0.015)],
        ValueSelectorState(),
    )["hit_rate"]
    assert selected is not None

    headline = _headline("hit_rate", selected, FOOTBALL_GAMES)
    assert headline["state"] == "BET"
    assert headline["american_odds"] == -198
    assert headline["play_through"] == {"line": None, "price_american": -211}


def test_headline_corridor_consumes_evaluator_concession_instead_of_hardcoding_1_5pp():
    row = _moneyline_row(-120, concession=0.006)
    assert _post_selection_play_through(row, lane="balanced", state="BET") == {
        "line": None,
        "price_american": -122,
    }


def test_zero_frozen_concession_means_no_execution_extension():
    row = _moneyline_row(-120, concession=0.0)
    assert _post_selection_play_through(row, lane="balanced", state="BET") is None


def test_value_through_uses_selected_price_corridor_but_stops_before_zero_ev():
    # At -112 this evaluator q is only narrowly above break-even. The generic
    # selected-price corridor could stretch farther, but Value Through must stop
    # at the last integer price that remains strict positive EV.
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


def test_value_through_is_omitted_when_no_worse_integer_price_remains_strict_value():
    current = -112
    row = _moneyline_row(
        current,
        concession=0.015,
        evaluator_probability=(break_even_probability(current) + break_even_probability(-113)) / 2.0,
        expected_value=0.0001,
    )
    assert _post_selection_play_through(row, lane="value", state="BET") is None
