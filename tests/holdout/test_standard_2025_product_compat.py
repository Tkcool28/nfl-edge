from __future__ import annotations

from copy import deepcopy

import pytest

from nfl_edge.holdout import standard_product_compat_2025 as compat
from nfl_edge.recommendation.final_selectors_v1 import ValueSelectorState


def _canonical_current_row() -> dict[str, object]:
    return {
        "game_id": "synthetic",
        "season": 2025,
        "block": "2025-01",
        "market_type": "moneyline",
        "selection": "away",
        "actionable_book": "draftkings",
        "actionable_line": None,
        "actionable_price_american": 150,
        "raw_football_output": {"qbelo_home": 0.55, "xgb_home": 0.55},
        "supported": True,
        "model_confidence_supported": True,
        "model_confidence_support_n": 300,
        "model_confidence_probability": 0.56,
        "pinnacle_anchor_probability": 0.45,
        "break_even_probability": 0.40,
        "evaluated_edge_probability": 0.10,
        "expected_value": 0.05,
        "price_status": "VALUE",
        "reliability": "HIGH",
        "settlement": "WIN",
    }


def _current_game(*, xgb_home: float | None = 0.55) -> dict[str, object]:
    return {
        "game_id": "synthetic",
        "season": 2025,
        "week": 3,
        "qbelo_home": 0.55,
        "xgb_home": xgb_home,
        "expected_home_margin": 2.5,
        "home_score": None,
        "away_score": None,
        "target_margin": None,
        "target_home_win": None,
        "target_total_points": None,
        "target_available": False,
    }


def test_current_aliases_are_added_without_mutating_canonical_source():
    source = _canonical_current_row()
    before = deepcopy(source)
    adapted = compat.legacy_current_rows([source])

    assert source == before
    row = adapted[0]
    assert row["selected_side"] == "away"
    assert row["sportsbook"] == "draftkings"
    assert row["line"] is None
    assert row["american_odds"] == 150
    assert row["raw_model_output"] == source["raw_football_output"]


def test_current_aliases_fail_closed_on_conflict():
    source = _canonical_current_row()
    source["selected_side"] = "home"
    with pytest.raises(compat.StandardProductCompatibilityError, match="alias conflict"):
        compat.legacy_current_rows([source])


def test_region_attachment_is_identity_only_and_canonical_safe():
    source = _canonical_current_row()
    registry = {
        ("synthetic", "moneyline", "away"): (
            "ML_DOG_VALUE_ZONE_AVG",
            "ML_DOG_VALUE_ZONE_CORROB",
        )
    }
    enriched = compat.attach_current_candidate_regions([source], registry)

    assert "model_candidate" not in source
    assert "model_candidate_regions" not in source
    assert enriched[0]["model_candidate"] is True
    assert enriched[0]["model_candidate_regions"] == (
        "ML_DOG_VALUE_ZONE_AVG;ML_DOG_VALUE_ZONE_CORROB"
    )


def test_strip_product_aliases_removes_only_temporary_legacy_keys():
    row = compat.legacy_current_rows([_canonical_current_row()])[0]
    product = {
        "board_rows": [dict(row)],
        "headlines": [dict(row)],
        "unique_exposure": [dict(row)],
        "other": "preserved",
    }
    clean = compat.strip_product_aliases(product)

    assert clean["other"] == "preserved"
    for key in ("board_rows", "headlines", "unique_exposure"):
        out = clean[key][0]
        assert not compat.TEMPORARY_LEGACY_KEYS.intersection(out)
        assert out["selection"] == "away"
        assert out["actionable_book"] == "draftkings"
        assert out["actionable_price_american"] == 150
        assert "raw_football_output" in out


def test_confidence_contract_allows_frozen_spread_unsupported_state():
    row = {
        "game_id": "synthetic",
        "market_type": "spread",
        "selection": "home",
        "actionable_line": -1.0,
        "supported": True,
        "model_confidence_supported": False,
        "model_confidence_source": "EXPECTED_MARGIN_DIRECT_LOGISTIC_V3",
        "model_cover_margin_v3": 1.5,
        "spread_calibration_intercept_v3": 0.02,
        "spread_calibration_slope_v3": -0.001,
    }
    compat._assert_confidence_contract([row], {"synthetic": _current_game()})


def test_confidence_contract_allows_ml_unavailable_during_xgb_warmup():
    row = {
        "game_id": "synthetic",
        "market_type": "moneyline",
        "selection": "away",
        "supported": True,
        "model_confidence_supported": False,
    }
    compat._assert_confidence_contract(
        [row], {"synthetic": _current_game(xgb_home=None)}
    )


def test_confidence_contract_rejects_live_ml_inputs_with_zero_support():
    row = {
        "game_id": "synthetic",
        "market_type": "moneyline",
        "selection": "away",
        "supported": True,
        "model_confidence_supported": False,
    }
    with pytest.raises(
        compat.StandardProductCompatibilityError,
        match="moneyline confidence inputs are live",
    ):
        compat._assert_confidence_contract(
            [row], {"synthetic": _current_game(xgb_home=0.55)}
        )


def test_confidence_contract_rejects_missing_spread_v3_wiring():
    row = {
        "game_id": "synthetic",
        "market_type": "spread",
        "selection": "home",
        "actionable_line": -1.0,
        "supported": True,
        "model_confidence_supported": False,
        "model_confidence_source": None,
        "model_cover_margin_v3": None,
    }
    with pytest.raises(
        compat.StandardProductCompatibilityError,
        match="spread confidence wiring incomplete",
    ):
        compat._assert_confidence_contract([row], {"synthetic": _current_game()})


def test_value_state_adapter_supplies_legacy_settled_view_without_mutating_source():
    source = _canonical_current_row()
    before = deepcopy(source)
    captured: dict[str, object] = {}

    def frozen_advance(state, rows):
        captured["state"] = state
        captured["rows"] = list(rows)
        return "advanced"

    state = ValueSelectorState()
    result = compat.advance_value_state_with_compat(frozen_advance, state, [source])

    assert result == "advanced"
    assert source == before
    row = captured["rows"][0]
    assert row["selected_side"] == "away"
    assert row["sportsbook"] == "draftkings"
    assert row["american_odds"] == 150
    assert row["raw_model_output"] == source["raw_football_output"]


def test_stub_product_builder_behavior_is_unchanged_except_prior_history_adapter():
    prior = [{
        "game_id": "historical",
        "market_type": "spread",
        "selection": "home",
        "actionable_book": "draftkings",
        "actionable_line": -3.0,
        "actionable_price_american": -110,
        "supported": True,
        "settlement": "WIN",
        "conditional_nonpush_probability": 0.57,
    }]
    captured: dict[str, object] = {}

    def history_adapter(rows):
        out = []
        for source in rows:
            row = dict(source)
            row["selected_side"] = row["selection"]
            row["sportsbook"] = row["actionable_book"]
            row["line"] = row["actionable_line"]
            row["american_odds"] = row["actionable_price_american"]
            out.append(row)
        return out

    def stub_builder(**kwargs):
        captured.update(kwargs)
        return {"board_rows": []}

    result = compat.build_product_with_compat(
        stub_builder,
        prior_board_rows_adapter=history_adapter,
        prior_board_rows=prior,
        sentinel="unchanged",
    )

    assert result == {"board_rows": []}
    assert captured["sentinel"] == "unchanged"
    assert captured["prior_board_rows"][0]["selected_side"] == "home"
    assert "selected_side" not in prior[0]
