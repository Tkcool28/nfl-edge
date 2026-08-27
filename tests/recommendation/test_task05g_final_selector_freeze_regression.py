from __future__ import annotations

from nfl_edge.recommendation.final_selectors_v1 import (
    ml_value_frontier,
    select_balanced,
    select_hit_rate,
)
from nfl_edge.recommendation.policy import NO_BALANCED_PLAY, NO_HIT_RATE_PLAY


def _low_reliability_supported_row(*, supported: bool = True) -> dict[str, object]:
    return {
        "candidate_id": "regression|ml|away|draftkings|-110",
        "game_id": "regression",
        "season": 2024,
        "week": 1,
        "block": "2024-01",
        "market_type": "moneyline",
        "selected_side": "away",
        "sportsbook": "draftkings",
        "line": None,
        "american_odds": -110,
        "supported": supported,
        "reliability": "LOW",
        "model_confidence_supported": True,
        "model_confidence_support_n": 600,
        "model_confidence_probability": 0.60,
        "pinnacle_anchor_probability": 0.58,
        "break_even_probability": 0.5238095238,
        "expected_value": 0.04,
        "evaluated_edge_probability": 0.03,
        "price_status": "VALUE",
        "model_candidate_regions": "ML_DOG_VALUE_ZONE_AVG",
        "model_price_gap": 0.06,
        "model_cover_margin_v3": None,
    }


def test_supported_low_reliability_is_not_an_extra_eligibility_veto():
    """Regression for the integrated-freeze translation defect.

    The accepted remediation protocol uses Task05F ``supported`` as the
    eligibility signal. Reliability remains a ranking/support diagnostic and a
    deterministic tie-break; LOW is not silently converted into UNSUPPORTED.
    """

    low = _low_reliability_supported_row()
    assert select_hit_rate([low])["candidate_id"] == low["candidate_id"]
    assert select_balanced([low])["candidate_id"] == low["candidate_id"]
    assert ml_value_frontier([low])["candidate_id"] == low["candidate_id"]


def test_task05f_unsupported_still_fails_closed():
    unsupported = _low_reliability_supported_row(supported=False)
    assert select_hit_rate([unsupported]) == NO_HIT_RATE_PLAY
    assert select_balanced([unsupported]) == NO_BALANCED_PLAY
    assert ml_value_frontier([unsupported]) is None
