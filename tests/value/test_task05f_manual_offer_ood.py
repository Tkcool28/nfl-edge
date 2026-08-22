from nfl_edge.value.contracts import (
    GameState,
    MarketAnchor,
    NormalizedOffer,
    PointV3State,
    ReliabilityState,
    SupportFeature,
)
from nfl_edge.value.evaluators import evaluate_offer


def test_extreme_manual_spread_line_fails_closed_out_of_support():
    state = PointV3State(
        market_type="spread",
        sigma=13.0,
        beta=0.2,
        residuals=(-2.0, -1.0, 0.0, 1.0, 2.0) * 130,
        training_n=650,
        support_features=(
            SupportFeature("model_market_gap", 0.0, 20.0, 20.0),
            SupportFeature("anchor_threshold_magnitude", 0.0, 20.0, 20.0),
        ),
        config_sha256="x",
        version="spread_v3",
    )
    game = GameState("g", 2026, "1", None, expected_home_margin=4.5)
    anchor = MarketAnchor(
        "spread",
        threshold=3.0,
        probability_above_nonpush=0.52,
        push_possible=True,
    )
    reliability = ReliabilityState(radius=0.02, support_n=600, block_count=50, stable=True)
    offer = NormalizedOffer("spread", "home", "manual", -110, -100.0, source="manual")
    result = evaluate_offer(game, offer, state, anchor, reliability)
    assert result.supported is False
    assert result.reliability == "UNSUPPORTED"
    assert result.reason == "out_of_support"
