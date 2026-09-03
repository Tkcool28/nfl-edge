from __future__ import annotations

from nfl_edge.live.roof_scenarios import compare_moneyline_roof_scenarios
from nfl_edge.value.contracts import (
    GameState,
    MarketAnchor,
    MoneylineV4State,
    NormalizedOffer,
    ReliabilityState,
    SupportFeature,
)


def _state() -> MoneylineV4State:
    return MoneylineV4State(
        market_intercept=0.0,
        market_slope=1.0,
        model_weight=0.5,
        training_n=600,
        prior_ties=3,
        prior_games=600,
        support_features=(
            SupportFeature("pinnacle_extremity", 0.0, 0.5, 0.5),
            SupportFeature("model_market_gap", 0.0, 0.5, 0.5),
            SupportFeature("constituent_gap", 0.0, 0.5, 0.5),
        ),
        config_sha256="test-state",
    )


def _inputs() -> dict[str, object]:
    return {
        "game": GameState("game", 2026, "1", None, qbelo_home=0.58),
        "offer": NormalizedOffer("moneyline", "home", "draftkings", -110),
        "evaluator_state": _state(),
        "anchor": MarketAnchor("moneyline", home_no_vig_probability=0.57),
        "reliability_state": ReliabilityState(0.02, 600, 50, True),
    }


def test_roof_scenario_adapter_exposes_shared_frozen_state_on_agreement():
    result = compare_moneyline_roof_scenarios(
        **_inputs(), open_xgb_home=0.60, closed_xgb_home=0.60
    )
    assert result["status"] == "EVALUATED"
    assert result["agreement_status"] == "AGREE"
    assert result["open_state"] == result["closed_state"] == result["shared_state"]


def test_roof_scenario_adapter_marks_roof_sensitive_without_shared_state():
    result = compare_moneyline_roof_scenarios(
        **_inputs(), open_xgb_home=0.51, closed_xgb_home=0.70
    )
    assert result["status"] == "ROOF_SENSITIVE"
    assert result["agreement_status"] == "ROOF_SENSITIVE"
    assert result["open_state"] != result["closed_state"]
    assert result["shared_state"] is None


def test_roof_scenario_adapter_keeps_models_visible_without_evaluator_evidence():
    result = compare_moneyline_roof_scenarios(
        game=GameState("game", 2026, "1", None, qbelo_home=0.58),
        open_xgb_home=0.51,
        closed_xgb_home=0.70,
    )
    assert result == {
        "status": "NOT_EVALUATED_MISSING_EVIDENCE",
        "agreement_status": "NOT_EVALUABLE",
        "open_state": None,
        "closed_state": None,
        "shared_state": None,
    }
