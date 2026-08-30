from __future__ import annotations

import pytest

from nfl_edge.holdout.evaluator_2025 import (
    evaluate_authorized_holdout_offer,
    prove_shadow_parity,
)
from nfl_edge.holdout.one_shot_2025 import HoldoutOneShotError
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
        prior_ties=2,
        prior_games=600,
        support_features=(
            SupportFeature("pinnacle_extremity", 0.0, 0.5, 0.5),
            SupportFeature("model_market_gap", 0.0, 0.5, 0.5),
            SupportFeature("constituent_gap", 0.0, 0.5, 0.5),
        ),
        config_sha256="synthetic",
    )


def _offer() -> NormalizedOffer:
    return NormalizedOffer("moneyline", "home", "draftkings", -110)


def _anchor() -> MarketAnchor:
    return MarketAnchor("moneyline", home_no_vig_probability=0.54)


def _rel() -> ReliabilityState:
    return ReliabilityState(radius=0.01, support_n=600, block_count=40, stable=True)


def test_shadow_parity_is_exact_on_exposed_development_input():
    game = GameState("dev", 2024, "18", None, qbelo_home=0.58, xgb_home=0.56)
    prove_shadow_parity(game, _offer(), _state(), _anchor(), _rel())


def test_authorized_holdout_seam_returns_frozen_evaluator_result():
    game = GameState("synthetic_2025", 2025, "1", None, qbelo_home=0.58, xgb_home=0.56)
    result = evaluate_authorized_holdout_offer(game, _offer(), _state(), _anchor(), _rel())
    assert result.evaluator_version == "ml_v4"
    assert result.support_n == 600
    assert result.evidence["raw_exact_avg_probability"] == pytest.approx(0.57)


def test_authorized_holdout_seam_rejects_non_2025_input():
    game = GameState("dev", 2024, "18", None, qbelo_home=0.58, xgb_home=0.56)
    with pytest.raises(HoldoutOneShotError):
        evaluate_authorized_holdout_offer(game, _offer(), _state(), _anchor(), _rel())
