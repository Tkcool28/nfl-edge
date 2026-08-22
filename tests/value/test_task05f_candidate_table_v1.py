import copy

import pytest

from nfl_edge.value.candidate_table import (
    BookOfferContext,
    CandidateOfferContext,
    OUTCOME_FIELDS,
    PRESERVED_FIELDS,
    assert_preserved_fields,
    build_candidate_row,
    build_candidate_table,
    build_historical_outcome_sidecar,
    make_candidate_id,
)


def _row(**overrides):
    row = {
        "game_id": "2024_01_BAL_KC",
        "season": 2024,
        "week": "1",
        "block": "2024-01",
        "market_type": "spread",
        "selected_side": "away",
        "sportsbook": "draftkings",
        "line": 3.5,
        "american_odds": -110,
        "decimal_odds": 1.909090909,
        "market_snapshot_timestamp": "2024-09-05T22:00:00+00:00",
        "raw_model_output": 1.2,
        "pinnacle_no_vig_probability": 0.49,
        "pinnacle_anchor_probability": 0.48,
        "pinnacle_anchor_threshold": -3.0,
        "model_market_disagreement": 1.8,
        "p_win": 0.55,
        "p_push": 0.0,
        "p_loss": 0.45,
        "actionable_probability": 0.55,
        "fair_price_american": -122,
        "break_even_probability": 0.5238095238,
        "evaluated_edge_probability": 0.0261904762,
        "expected_value": 0.05,
        "strict_positive_value": True,
        "supported": True,
        "support_n": 900,
        "reason": None,
        "reliability": "MEDIUM",
        "base_reliability": "HIGH",
        "uncertainty": 0.03,
        "uncertainty_support_n": 700,
        "uncertainty_block_count": 50,
        "candidate_uncertainty_tier": "MEDIUM",
        "staking_probability": 0.535,
        "staking_expected_value": 0.021,
        "price_status": "VALUE",
        "play_through_confidence_multiplier": 0.49,
        "play_through_break_even_concession": 0.00735,
        "play_through_break_even_probability": 0.55735,
        "play_through_price_american": -126,
        "settlement": "WIN",
        "realized_profit": 0.909090909,
    }
    row.update(overrides)
    return row


def _context():
    return CandidateOfferContext(
        draftkings=BookOfferContext(3.5, -110),
        fanduel=BookOfferContext(3.0, -105),
        pinnacle=BookOfferContext(3.0, -108),
    )


def test_stable_candidate_id_ignores_offer_price_line_book_and_timestamp():
    a = build_candidate_row(_row(), _context())
    b = build_candidate_row(
        _row(
            sportsbook="fanduel",
            line=4.0,
            american_odds=-118,
            market_snapshot_timestamp="2024-09-05T23:00:00+00:00",
        ),
        _context(),
    )
    assert a["candidate_id"] == b["candidate_id"]
    assert a["offer_id"] != b["offer_id"]


def test_candidate_id_is_one_game_market_side_identity():
    assert make_candidate_id("g1", "moneyline", "home") == "g1|moneyline|home"
    assert make_candidate_id("g1", "total", "under") == "g1|total|under"
    with pytest.raises(ValueError):
        make_candidate_id("g1", "total", "home")


def test_candidate_row_exposes_all_three_book_contexts_without_changing_actionable_offer():
    candidate = build_candidate_row(_row(), _context())
    assert candidate["draftkings_line"] == 3.5
    assert candidate["draftkings_price_american"] == -110
    assert candidate["fanduel_line"] == 3.0
    assert candidate["fanduel_price_american"] == -105
    assert candidate["pinnacle_line"] == 3.0
    assert candidate["pinnacle_price_american"] == -108
    assert candidate["actionable_book"] == "draftkings"
    assert candidate["actionable_line"] == 3.5
    assert candidate["actionable_price_american"] == -110


def test_candidate_table_contains_no_historical_outcome_fields():
    candidate = build_candidate_row(_row(), _context())
    assert OUTCOME_FIELDS.isdisjoint(candidate)
    assert "settlement" not in candidate
    assert "realized_profit" not in candidate


def test_historical_outcomes_are_sidecar_only():
    source = _row()
    sidecar = build_historical_outcome_sidecar([source])
    assert sidecar == [
        {
            "candidate_id": "2024_01_BAL_KC|spread|away",
            "game_id": "2024_01_BAL_KC",
            "season": 2024,
            "week": "1",
            "market_type": "spread",
            "selection": "away",
            "settlement": "WIN",
            "realized_profit": 0.909090909,
        }
    ]
    candidate = build_candidate_table([source])
    assert "settlement" not in candidate[0]
    assert "realized_profit" not in candidate[0]


def test_unsupported_rows_are_retained_for_game_explorer():
    source = _row(
        supported=False,
        reason="out_of_support",
        reliability="UNSUPPORTED",
        price_status="PASS",
        expected_value=None,
        strict_positive_value=False,
    )
    candidates = build_candidate_table([source])
    assert len(candidates) == 1
    assert candidates[0]["supported"] is False
    assert candidates[0]["price_status"] == "PASS"


def test_duplicate_game_market_side_is_hard_failure():
    source = _row()
    duplicate = copy.deepcopy(source)
    duplicate["sportsbook"] = "fanduel"
    duplicate["american_odds"] = -105
    with pytest.raises(RuntimeError, match="duplicate candidate identity"):
        build_candidate_table([source, duplicate])


def test_candidate_table_preserves_all_upstream_decision_fields_exactly():
    source = _row()
    candidates = build_candidate_table([source])
    assert_preserved_fields([source], candidates)
    for field in PRESERVED_FIELDS:
        assert candidates[0][field] == source.get(field)


def test_book_context_is_display_only_and_cannot_change_decision_fields():
    source = _row()
    a = build_candidate_row(source, _context())
    wildly_different_context = CandidateOfferContext(
        draftkings=BookOfferContext(7.5, 140),
        fanduel=BookOfferContext(1.5, -160),
        pinnacle=BookOfferContext(4.0, -115),
    )
    b = build_candidate_row(source, wildly_different_context)
    for field in PRESERVED_FIELDS:
        assert a[field] == b[field]
    assert a["offer_id"] == b["offer_id"]


def test_football_model_name_and_output_units_are_market_specific():
    ml = build_candidate_row(
        _row(market_type="moneyline", selected_side="home", line=None, raw_model_output=0.63)
    )
    spread = build_candidate_row(_row())
    total = build_candidate_row(
        _row(market_type="total", selected_side="over", line=47.5, raw_model_output=48.8)
    )
    assert ml["football_model_name"] == "QB_ELO_XGB_EXACT_AVG"
    assert ml["raw_football_output_unit"] == "probability_home_or_away_orientation"
    assert spread["football_model_name"] == "EXPECTED_MARGIN_V1_STABLE"
    assert spread["raw_football_output_unit"] == "home_margin_points"
    assert total["football_model_name"] == "RIDGE_TOTALS_R4"
    assert total["raw_football_output_unit"] == "total_points"


def test_2025_is_hard_rejected_from_candidate_table_and_outcome_sidecar():
    sealed = _row(season=2025)
    with pytest.raises(RuntimeError, match="sealed season"):
        build_candidate_table([sealed])
    with pytest.raises(RuntimeError, match="sealed season"):
        build_historical_outcome_sidecar([sealed])
