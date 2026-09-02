from __future__ import annotations

from types import SimpleNamespace

import pytest

from nfl_edge.holdout import standard_product_compat_2025 as compat
from nfl_edge.value.contracts import NormalizedOffer


class FakeTask05F:
    @staticmethod
    def _moneyline_anchor(index, gid):
        return SimpleNamespace(home_no_vig_probability=0.5595)

    @staticmethod
    def _spread_anchor(index, gid):
        return SimpleNamespace(threshold=1.0)

    @staticmethod
    def _best(index, gid, market, side, books=("draftkings", "fanduel")):
        offers = [offer for book in books for offer in index.get((gid, market, side, book), [])]
        return max(offers, key=lambda offer: offer.price_american, default=None)


def _offer(market: str, side: str, book: str, price: int, line: float | None = None):
    return NormalizedOffer(
        market_type=market,
        side=side,
        book=book,
        price_american=price,
        line=line,
        snapshot_utc="2025-09-01T00:00:00Z",
    )


def _canonical_current_row() -> dict[str, object]:
    return {
        "game_id": "synthetic",
        "market_type": "moneyline",
        "selection": "away",
        "actionable_book": "draftkings",
        "actionable_line": None,
        "actionable_price_american": 150,
        "raw_football_output": 0.45,
    }


def test_current_aliases_are_added_without_mutating_source():
    source = _canonical_current_row()
    adapted = compat.legacy_current_rows([source])[0]

    assert adapted["selected_side"] == "away"
    assert adapted["sportsbook"] == "draftkings"
    assert adapted["line"] is None
    assert adapted["american_odds"] == 150
    assert adapted["raw_model_output"] == 0.45
    assert not compat.TEMPORARY_LEGACY_KEYS.intersection(source)


def test_current_aliases_fail_closed_on_conflict():
    source = _canonical_current_row()
    source["sportsbook"] = "fanduel"
    with pytest.raises(compat.StandardProductCompatibilityError, match="alias conflict"):
        compat.legacy_current_rows([source])


def test_strip_product_aliases_removes_only_temporary_legacy_keys():
    canonical = _canonical_current_row()
    legacy = compat.legacy_current_rows([canonical])[0]
    legacy.update({"model_candidate": True, "model_candidate_regions": "ML_DOG_VALUE_ZONE_AVG"})
    product = {
        "board_rows": [legacy],
        "headlines": [legacy],
        "unique_exposure": [legacy],
        "sentinel": "preserved",
    }

    clean = compat.strip_product_aliases(product)
    assert clean["sentinel"] == "preserved"
    for key in ("board_rows", "headlines", "unique_exposure"):
        row = clean[key][0]
        assert not compat.TEMPORARY_LEGACY_KEYS.intersection(row)
        assert row["selection"] == "away"
        assert row["actionable_book"] == "draftkings"
        assert row["actionable_price_american"] == 150
        assert row["raw_football_output"] == 0.45
        assert row["model_candidate_regions"] == "ML_DOG_VALUE_ZONE_AVG"


def test_outcome_blind_registry_recreates_all_four_locked_regions():
    gid = "synthetic"
    index = {
        (gid, "moneyline", "away", "draftkings"): [_offer("moneyline", "away", "draftkings", 150)],
        (gid, "moneyline", "away", "fanduel"): [_offer("moneyline", "away", "fanduel", 145)],
        (gid, "spread", "home", "draftkings"): [_offer("spread", "home", "draftkings", -110, -1.0)],
        (gid, "spread", "home", "fanduel"): [_offer("spread", "home", "fanduel", -108, -0.5)],
    }
    games = {
        gid: {
            "game_id": gid,
            "season": 2025,
            "qbelo_home": 0.55,
            "xgb_home": 0.55,
            "expected_home_margin": 2.5,
            "home_score": None,
            "away_score": None,
            "target_margin": None,
            "target_home_win": None,
            "target_total_points": None,
            "target_available": False,
        }
    }

    registry = compat.build_current_candidate_registry(
        task05f=FakeTask05F(), current_games=games, market_index=index
    )

    assert set(registry[(gid, "moneyline", "away")]) == {
        "ML_DOG_VALUE_ZONE_AVG",
        "ML_DOG_VALUE_ZONE_CORROB",
        "ML_AVG_DISAGREEMENT_AVG_0_2",
    }
    assert registry[(gid, "spread", "home")] == (
        "SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4",
    )


def test_registry_rejects_outcome_leakage():
    games = {
        "synthetic": {
            "game_id": "synthetic",
            "season": 2025,
            "qbelo_home": 0.55,
            "xgb_home": 0.55,
            "expected_home_margin": 2.5,
            "home_score": 24,
            "away_score": None,
            "target_available": False,
        }
    }
    with pytest.raises(compat.StandardProductCompatibilityError, match="outcome leakage"):
        compat.build_current_candidate_registry(
            task05f=FakeTask05F(), current_games=games, market_index={}
        )


def test_attach_regions_keys_on_canonical_or_legacy_side():
    registry = {("synthetic", "moneyline", "away"): ("ML_DOG_VALUE_ZONE_AVG",)}
    canonical = _canonical_current_row()
    attached = compat.attach_current_candidate_regions([canonical], registry)[0]
    assert attached["model_candidate"] is True
    assert attached["model_candidate_regions"] == "ML_DOG_VALUE_ZONE_AVG"


def test_value_state_adapter_supplies_legacy_view_without_mutating_settled_rows():
    source = _canonical_current_row()
    source.update({"settlement": "WIN", "break_even_probability": 0.40})
    captured = {}

    def frozen_advance(state, rows):
        material = list(rows)
        captured["rows"] = material
        return "next-state"

    result = compat.advance_value_state_with_compat(frozen_advance, "state", [source])
    assert result == "next-state"
    assert captured["rows"][0]["selected_side"] == "away"
    assert captured["rows"][0]["american_odds"] == 150
    assert "selected_side" not in source
    assert "american_odds" not in source


def test_confidence_liveness_rejects_silent_all_unsupported_market():
    rows = [
        {
            "market_type": "moneyline",
            "supported": True,
            "model_confidence_supported": False,
        }
    ]
    with pytest.raises(compat.StandardProductCompatibilityError, match="zero supported current rows"):
        compat._assert_confidence_live(rows)


def test_simple_builder_path_preserves_existing_history_adapter_behavior():
    source = _canonical_current_row()
    historical = {
        "game_id": "historical",
        "market_type": "spread",
        "selected_side": "home",
        "sportsbook": "draftkings",
        "line": -3.0,
        "american_odds": -110,
    }
    captured = {}

    def builder(**kwargs):
        captured.update(kwargs)
        return {"board_rows": [source]}

    result = compat.build_product_with_compat(
        builder,
        prior_board_rows_adapter=lambda rows: rows,
        prior_board_rows=[historical],
    )
    assert result == {"board_rows": [source]}
    assert captured["prior_board_rows"] == [historical]
