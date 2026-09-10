from __future__ import annotations

from nfl_edge.live.product_2026 import _headline, _lane_selection
from nfl_edge.recommendation.final_selectors_v1 import ValueSelectorState
from nfl_edge.value.market_math import break_even_probability


FOOTBALL_GAMES = {
    "2026_01_SF_LAR": {
        "game_id": "2026_01_SF_LAR",
        "away_team": "SF",
        "home_team": "LAR",
    }
}


def _moneyline_row(price: int, *, play_through_price: int | None) -> dict:
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
        "actionable_probability": 0.66,
        "expected_value": -0.01,
        "uncertainty": 0.02,
        "model_candidate_regions": "",
        "evaluated_edge_probability": -0.01,
        "model_price_gap": 0.01,
        "play_through_price_american": play_through_price,
    }


def test_live_balanced_uses_price_bounded_v2_not_legacy_v1_band():
    # Legacy V1 allowed this price (-220..+200). Balanced V2 moneyline must not.
    selections = _lane_selection(
        [_moneyline_row(-198, play_through_price=-187)],
        ValueSelectorState(),
    )
    assert selections["balanced"] is None


def test_play_through_is_post_selection_extension_not_a_bet_gate():
    # The selected Balanced card remains a BET even when Task05F's raw boundary
    # points to a BETTER price. That boundary is not an execution extension and
    # therefore must not be published as Play Through.
    selections = _lane_selection(
        [_moneyline_row(-120, play_through_price=-110)],
        ValueSelectorState(),
    )
    selected = selections["balanced"]
    assert selected is not None

    headline = _headline("balanced", selected, FOOTBALL_GAMES)
    assert headline["state"] == "BET"
    assert headline["american_odds"] == -120
    assert headline["recommended_units"] == 0.75
    assert headline["play_through"] is None


def test_play_through_publishes_only_when_it_stretches_the_selected_bet():
    selections = _lane_selection(
        [_moneyline_row(-120, play_through_price=-130)],
        ValueSelectorState(),
    )
    selected = selections["balanced"]
    assert selected is not None

    headline = _headline("balanced", selected, FOOTBALL_GAMES)
    assert headline["state"] == "BET"
    assert headline["american_odds"] == -120
    assert headline["play_through"] == {"line": None, "price_american": -130}
