from __future__ import annotations

import pytest

from nfl_edge.value.accepted_calibration import (
    conditional_above_probability,
    market_implied_mean,
)
from nfl_edge.value.candidate_table import CandidateOfferContext, build_candidate_row
from nfl_edge.value.contracts import (
    GameState,
    MarketAnchor,
    MoneylineV4State,
    NormalizedOffer,
    PointV3State,
    ReliabilityState,
    SupportFeature,
)
from nfl_edge.value.evaluators import evaluate_offer
from nfl_edge.value.play_through import MAX_BREAK_EVEN_CONCESSION, assess_play_through
from nfl_edge.value.reliability import ReliabilityEvidence, reliability_tier
from nfl_edge.value.state_io import load_frozen_state, write_frozen_state
from nfl_edge.value.wager_economics import OutcomeProbabilities, expected_value_three_way


def _feature(name: str, lo: float = 0.0, hi: float = 10.0) -> SupportFeature:
    return SupportFeature(name, lo, hi, hi - lo)


def _reliability() -> ReliabilityState:
    return ReliabilityState(radius=0.02, support_n=600, block_count=50, stable=True)


def test_half_point_market_mean_retains_closed_form_semantics():
    mu = 4.2
    threshold = 3.5
    sigma = 13.0
    q = conditional_above_probability(mu, threshold, sigma, push_possible=False)
    recovered = market_implied_mean(threshold, q, sigma, push_possible=False)
    assert recovered == pytest.approx(mu, abs=1e-10)


def test_integer_market_mean_inverts_conditional_nonpush_probability():
    mu = 4.2
    threshold = 3.0
    sigma = 13.0
    q = conditional_above_probability(mu, threshold, sigma, push_possible=True)
    recovered = market_implied_mean(threshold, q, sigma, push_possible=True)
    assert recovered == pytest.approx(mu, abs=1e-9)


def test_integer_and_naive_unconditional_inversion_are_not_silently_equated():
    threshold = 3.0
    sigma = 13.0
    q = 0.57
    corrected = market_implied_mean(threshold, q, sigma, push_possible=True)
    half_point_formula = market_implied_mean(threshold, q, sigma, push_possible=False)
    assert abs(corrected - half_point_formula) > 1e-4


def test_three_way_ev_treats_push_as_refund():
    prob = OutcomeProbabilities(0.50, 0.05, 0.45)
    assert expected_value_three_way(prob, 100) == pytest.approx(0.05)


def test_reliability_is_single_accepted_family_evidence_not_worse_of_two_tiers():
    evidence = ReliabilityEvidence(
        support_n=600,
        uncertainty=0.02,
        support_distance=0.0,
        constituent_disagreement=0.02,
        stable_blocks=True,
    )
    assert reliability_tier(evidence) == "HIGH"


def test_ml_v4_arbitrary_manual_offer_parity():
    state = MoneylineV4State(
        market_intercept=0.0,
        market_slope=1.0,
        model_weight=0.5,
        training_n=600,
        prior_ties=3,
        prior_games=600,
        support_features=(
            _feature("pinnacle_extremity", 0.0, 0.5),
            _feature("model_market_gap", 0.0, 0.5),
            _feature("constituent_gap", 0.0, 0.5),
        ),
        config_sha256="x",
    )
    game = GameState("g", 2026, "1", None, qbelo_home=0.64, xgb_home=0.60)
    anchor = MarketAnchor("moneyline", home_no_vig_probability=0.61)
    stored = NormalizedOffer("moneyline", "home", "draftkings", -155)
    manual = NormalizedOffer("moneyline", "home", "manual", -155, source="manual")
    assert evaluate_offer(game, stored, state, anchor, _reliability()) == evaluate_offer(
        game, manual, state, anchor, _reliability()
    )


def test_spread_v3_arbitrary_manual_offer_parity_and_push_mass():
    state = PointV3State(
        market_type="spread",
        sigma=13.0,
        beta=0.25,
        residuals=(-2.0, -1.0, 0.0, 1.0, 2.0) * 130,
        training_n=650,
        support_features=(
            _feature("model_market_gap", 0.0, 20.0),
            _feature("anchor_threshold_magnitude", 0.0, 20.0),
        ),
        config_sha256="x",
        version="spread_v3",
    )
    game = GameState("g", 2026, "1", None, expected_home_margin=4.5)
    anchor = MarketAnchor("spread", threshold=3.0, probability_above_nonpush=0.52, push_possible=True)
    stored = NormalizedOffer("spread", "home", "fanduel", -110, -3.0)
    manual = NormalizedOffer("spread", "home", "manual", -110, -3.0, source="manual")
    a = evaluate_offer(game, stored, state, anchor, _reliability())
    b = evaluate_offer(game, manual, state, anchor, _reliability())
    assert a == b
    assert a.supported
    assert a.p_push is not None and a.p_push > 0.0


def test_2025_is_fail_closed():
    state = MoneylineV4State(
        0.0,
        1.0,
        0.0,
        600,
        1,
        600,
        (
            _feature("pinnacle_extremity", 0.0, 0.5),
            _feature("model_market_gap", 0.0, 0.5),
            _feature("constituent_gap", 0.0, 0.5),
        ),
        "x",
    )
    game = GameState("g", 2025, "1", None, qbelo_home=0.6, xgb_home=0.6)
    with pytest.raises(RuntimeError):
        evaluate_offer(
            game,
            NormalizedOffer("moneyline", "home", "manual", -110, source="manual"),
            state,
            MarketAnchor("moneyline", home_no_vig_probability=0.55),
            _reliability(),
        )


def test_frozen_state_roundtrip_includes_point_residuals(tmp_path):
    ml = MoneylineV4State(
        0.0,
        1.0,
        0.0,
        600,
        2,
        600,
        (
            _feature("pinnacle_extremity", 0.0, 0.5),
            _feature("model_market_gap", 0.0, 0.5),
            _feature("constituent_gap", 0.0, 0.5),
        ),
        "x",
    )
    spread = PointV3State(
        "spread",
        13.0,
        0.2,
        (-1.0, 0.0, 1.0),
        600,
        (_feature("model_market_gap"), _feature("anchor_threshold_magnitude")),
        "x",
        "spread_v3",
    )
    total = PointV3State(
        "total",
        14.0,
        0.1,
        (-2.0, 0.0, 2.0),
        600,
        (_feature("model_market_gap"), _feature("anchor_threshold_magnitude", 0.0, 60.0)),
        "x",
        "total_v3",
    )
    path = tmp_path / "state.json"
    write_frozen_state(
        path,
        moneyline=ml,
        spread=spread,
        total=total,
        reliability={"moneyline": _reliability(), "spread": _reliability(), "total": _reliability()},
        metadata={"sealed_season": 2025},
    )
    loaded = load_frozen_state(path)
    assert loaded["moneyline"] == ml
    assert loaded["spread"] == spread
    assert loaded["total"] == total


def test_candidate_table_contains_no_historical_outcomes():
    upstream = {
        "game_id": "g",
        "season": 2026,
        "week": "1",
        "block": "2026-01",
        "market_type": "moneyline",
        "selected_side": "home",
        "sportsbook": "draftkings",
        "line": None,
        "american_odds": -150,
        "market_snapshot_timestamp": "t",
        "supported": True,
        "strict_positive_value": False,
    }
    row = build_candidate_row(upstream, CandidateOfferContext())
    assert "settlement" not in row
    assert "realized_profit" not in row


def test_play_through_policy_is_frozen_at_one_and_a_half_points():
    assert MAX_BREAK_EVEN_CONCESSION == pytest.approx(0.015)
    assessment = assess_play_through(
        supported=True,
        strict_expected_value=-0.01,
        conditional_nonpush_probability=0.60,
        current_break_even_probability=0.61,
        reliability="HIGH",
        uncertainty_radius=0.0,
    )
    assert assessment.break_even_concession == pytest.approx(0.015)
    assert assessment.status == "PLAYABLE"
