from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/task05g_2025_standard_evaluation_v1.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("standard_2025_runner_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical_row() -> dict[str, object]:
    return {
        "game_id": "synthetic",
        "block": "2025-01",
        "market_type": "spread",
        "selection": "home",
        "actionable_book": "draftkings",
        "actionable_line": -3.0,
        "actionable_price_american": -110,
        "supported": True,
        "settlement": "WIN",
        "conditional_nonpush_probability": 0.57,
    }


def test_history_adapter_adds_legacy_aliases_without_mutating_canonical_source():
    runner = _load_runner()
    source = _canonical_row()
    adapted = runner._legacy_prior_board_rows([source])

    assert "selected_side" not in source
    assert "line" not in source
    assert "american_odds" not in source
    assert "sportsbook" not in source

    assert adapted[0]["selected_side"] == "home"
    assert adapted[0]["line"] == -3.0
    assert adapted[0]["american_odds"] == -110
    assert adapted[0]["sportsbook"] == "draftkings"
    assert adapted[0]["selection"] == "home"
    assert adapted[0]["actionable_line"] == -3.0


def test_history_adapter_preserves_legacy_development_rows():
    runner = _load_runner()
    source = {
        "game_id": "historical",
        "market_type": "spread",
        "selected_side": "away",
        "sportsbook": "fanduel",
        "line": 2.5,
        "american_odds": -105,
    }
    adapted = runner._legacy_prior_board_rows([source])
    assert adapted == [source]
    assert adapted[0] is not source


def test_history_adapter_fails_closed_on_conflicting_aliases():
    runner = _load_runner()
    source = _canonical_row()
    source["selected_side"] = "away"
    with pytest.raises(runner.StandardEvaluationError, match="historical row alias conflict"):
        runner._legacy_prior_board_rows([source])


def test_standard_product_builder_only_adapts_temporary_history_view():
    runner = _load_runner()
    source = _canonical_row()
    captured: dict[str, object] = {}

    def frozen_builder(**kwargs):
        captured.update(kwargs)
        return {"status": "ok"}

    result = runner._standard_product_builder(
        frozen_builder,
        prior_board_rows=[source],
        sentinel="unchanged",
    )

    assert result == {"status": "ok"}
    assert captured["sentinel"] == "unchanged"
    adapted = captured["prior_board_rows"]
    assert adapted[0]["selected_side"] == "home"
    assert adapted[0]["line"] == -3.0
    assert "selected_side" not in source
    assert "line" not in source
