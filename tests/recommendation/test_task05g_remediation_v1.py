from __future__ import annotations

import pytest

from nfl_edge.recommendation.policy import NO_BALANCED_PLAY, NO_HIT_RATE_PLAY, NO_VALUE_PLAY
from nfl_edge.recommendation.remediation_provenance_v1 import (
    build_candidate_registry,
    enrich_board_rows,
)
from nfl_edge.recommendation.remediation_v1 import (
    robust_expected_value,
    select_balanced,
    select_headlines,
    select_hit_rate,
    select_value,
)


def row(
    cid: str,
    *,
    market="moneyline",
    side="home",
    book="draftkings",
    line=None,
    odds=-110,
    q=0.60,
    q_nonpush=None,
    p_push=0.0,
    ev=0.08,
    reliability="HIGH",
    status="VALUE",
    support_n=600,
    support_distance=0.02,
    uncertainty=0.02,
    supported=True,
    model_candidate=True,
    regions="ML_DOG_VALUE_ZONE_AVG",
):
    if q_nonpush is None:
        q_nonpush = q
    return {
        "candidate_id": cid,
        "game_id": cid.split("|")[0],
        "season": 2024,
        "market_type": market,
        "selected_side": side,
        "sportsbook": book,
        "line": line,
        "american_odds": odds,
        "actionable_probability": q,
        "conditional_nonpush_probability": q_nonpush,
        "p_push": p_push,
        "expected_value": ev,
        "evaluated_edge_probability": 0.04,
        "reliability": reliability,
        "price_status": status,
        "support_n": support_n,
        "support_distance": support_distance,
        "uncertainty": uncertainty,
        "supported": supported,
        "model_candidate": model_candidate,
        "model_candidate_regions": regions,
    }


def test_robust_ev_moneyline_matches_preregistered_formula():
    candidate = row("g1|moneyline|home", odds=120, q=0.52, uncertainty=0.02, p_push=0.0)
    # q_lower=.50, decimal=2.2 -> .50*2.2 - 1 = .10
    assert robust_expected_value(candidate) == pytest.approx(0.10)


def test_robust_ev_point_market_keeps_push_refund():
    candidate = row(
        "g1|spread|home",
        market="spread",
        line=-3.0,
        odds=-110,
        q=0.55,
        q_nonpush=0.55,
        p_push=0.06,
        uncertainty=0.03,
    )
    q_lower = 0.52
    decimal_odds = 1 + 100 / 110
    expected = (1 - 0.06) * q_lower * decimal_odds + 0.06 - 1
    assert robust_expected_value(candidate) == pytest.approx(expected)


def test_robust_ev_fails_closed_on_missing_inputs():
    candidate = row("g1|moneyline|home")
    candidate["uncertainty"] = None
    assert robust_expected_value(candidate) is None
    assert select_headlines([candidate]) == {
        "hit_rate": NO_HIT_RATE_PLAY,
        "balanced": NO_BALANCED_PLAY,
        "value": NO_VALUE_PLAY,
    }


def test_probability_uncertainty_penalty_is_larger_at_longer_odds():
    short = row("g1|moneyline|home", odds=-110, q=0.60, uncertainty=0.03)
    long = row("g2|moneyline|home", odds=200, q=0.60, uncertainty=0.03)
    short_no_unc = row("g3|moneyline|home", odds=-110, q=0.60, uncertainty=0.0)
    long_no_unc = row("g4|moneyline|home", odds=200, q=0.60, uncertainty=0.0)
    short_penalty = robust_expected_value(short_no_unc) - robust_expected_value(short)
    long_penalty = robust_expected_value(long_no_unc) - robust_expected_value(long)
    assert long_penalty > short_penalty > 0


def test_generic_full_board_value_cannot_create_candidate():
    generic = row("g1|moneyline|away", odds=180, q=0.42, ev=0.20, model_candidate=False, regions="")
    assert select_value([generic]) == NO_VALUE_PLAY
    assert select_hit_rate([generic]) == NO_HIT_RATE_PLAY
    assert select_balanced([generic]) == NO_BALANCED_PLAY


def test_balanced_is_probability_first_not_value_status_first():
    playable = row("g1|moneyline|home", q=0.66, ev=-0.01, status="PLAYABLE", odds=-150)
    value = row("g2|moneyline|away", q=0.54, ev=0.10, status="VALUE", odds=130)
    assert select_balanced([value, playable])["candidate_id"] == playable["candidate_id"]


def test_value_ranks_robust_ev_instead_of_max_point_ev():
    # A has the larger point EV but a larger uncertainty penalty at +250.
    max_point = row("g1|moneyline|away", odds=250, q=0.35, uncertainty=0.045, ev=0.225)
    robust = row("g2|moneyline|away", odds=120, q=0.52, uncertainty=0.02, ev=0.144)
    assert robust_expected_value(max_point) == pytest.approx(0.0675)
    assert robust_expected_value(robust) == pytest.approx(0.10)
    assert select_value([max_point, robust])["candidate_id"] == robust["candidate_id"]


def test_value_requires_positive_robust_ev_even_when_point_ev_positive():
    noisy = row("g1|moneyline|away", odds=-180, q=0.66, uncertainty=0.045, ev=0.03)
    # q_lower=.615 at decimal 1.555..., so downside EV is negative.
    assert robust_expected_value(noisy) < 0
    assert select_value([noisy]) == NO_VALUE_PLAY


def test_hit_rate_still_probability_first_inside_model_candidates():
    high_q = row("g1|moneyline|home", q=0.65, ev=0.01, status="PLAYABLE", odds=-200)
    high_ev = row("g2|moneyline|away", q=0.58, ev=0.20, status="VALUE", odds=150)
    assert select_hit_rate([high_ev, high_q])["candidate_id"] == high_q["candidate_id"]


def test_totals_have_no_candidate_provenance_family():
    ledger = [
        {
            "game_id": "g1",
            "season": 2024,
            "family": "TOTAL_R4_DISAGREEMENT",
            "model": "RIDGE_R4",
            "bucket": "0-1",
            "selected_side": "over",
            "profit": 1000.0,
        }
    ]
    assert build_candidate_registry(ledger) == {}


def test_registry_uses_frozen_regions_and_dedupes_overlapping_candidate_side():
    ledger = [
        {"game_id": "g1", "season": 2021, "family": "ML_DOG_VALUE_ZONE", "model": "AVG", "bucket": "ZONE", "selected_side": "away", "profit": -1.0},
        {"game_id": "g1", "season": 2021, "family": "ML_AVG_DISAGREEMENT", "model": "AVG", "bucket": "0-2", "selected_side": "away", "profit": 9.0},
        {"game_id": "g2", "season": 2022, "family": "SPREAD_DISAGREEMENT", "model": "EXPECTED_MARGIN", "bucket": "3-4", "selected_side": "home", "profit": -1.0},
        {"game_id": "g3", "season": 2022, "family": "SPREAD_DISAGREEMENT", "model": "EXPECTED_MARGIN", "bucket": "4+", "selected_side": "away", "profit": 100.0},
    ]
    registry = build_candidate_registry(ledger)
    assert registry[("g1", "moneyline", "away")] == (
        "ML_AVG_DISAGREEMENT_AVG_0_2",
        "ML_DOG_VALUE_ZONE_AVG",
    )
    assert registry[("g2", "spread", "home")] == ("SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4",)
    assert ("g3", "spread", "away") not in registry


def test_registry_outcome_fields_cannot_change_candidate_eligibility():
    base = {"game_id": "g1", "season": 2020, "family": "ML_DOG_VALUE_ZONE", "model": "AVG", "bucket": "ZONE", "selected_side": "away"}
    winner = {**base, "w": 1, "profit": 100.0, "p_push": 0.0, "price_american": 999}
    loser = {**base, "w": 0, "profit": -100.0, "p_push": 1.0, "price_american": -999}
    assert build_candidate_registry([winner]) == build_candidate_registry([loser])


def test_historical_line_and_price_are_not_candidate_identity():
    ledger = [{"game_id": "g1", "season": 2022, "family": "SPREAD_DISAGREEMENT", "model": "EXPECTED_MARGIN", "bucket": "2-3", "selected_side": "home", "reconstructed_line": -3.5, "price_american": -120}]
    registry = build_candidate_registry(ledger)
    board = [row("g1|spread|home", market="spread", side="home", line=-2.5, odds=105, model_candidate=False, regions="")]
    enriched = enrich_board_rows(board, registry)
    assert enriched[0]["model_candidate"] is True
    assert enriched[0]["model_candidate_regions"] == "SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4"


def test_registry_and_board_hard_reject_2025():
    sealed_ledger = [{"game_id": "sealed", "season": 2025, "family": "ML_DOG_VALUE_ZONE", "model": "AVG", "bucket": "ZONE", "selected_side": "away"}]
    with pytest.raises(RuntimeError, match="2025 firewall"):
        build_candidate_registry(sealed_ledger)
    sealed_board = [row("sealed|moneyline|home")]
    sealed_board[0]["season"] = 2025
    with pytest.raises(RuntimeError, match="2025 firewall"):
        enrich_board_rows(sealed_board, {})


def test_deterministic_replay():
    rows = [
        row("g1|moneyline|home", q=0.63, odds=-160, status="PLAYABLE", ev=-0.005),
        row("g2|spread|away", market="spread", side="away", line=2.5, q=0.56, odds=-105, ev=0.06, regions="SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4"),
    ]
    assert select_headlines(rows) == select_headlines(list(reversed(list(reversed(rows)))))
