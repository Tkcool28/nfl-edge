from __future__ import annotations

import json
from types import SimpleNamespace

import polars as pl
import pytest

from nfl_edge.live.product_state_2026 import (
    Entering2026ProductStateError,
    advance_live_value_state,
)
from nfl_edge.recommendation.final_selectors_v1 import ValueSelectorState


def _selector_row(*, market: str, game_id: str = "2026_01_A_B") -> dict[str, object]:
    return {
        "candidate_id": f"{game_id}|{market}|home",
        "game_id": game_id,
        "season": 2026,
        "week": 1,
        "market_type": market,
        "selected_side": "home",
        "sportsbook": "draftkings",
        "line": None if market == "moneyline" else -2.5,
        "american_odds": -110,
        "supported": True,
        "reliability": "HIGH",
        "model_confidence_supported": True,
        "model_confidence_support_n": 512,
        "model_confidence_probability": 0.62,
        "pinnacle_anchor_probability": 0.58,
        "break_even_probability": 0.52,
        "expected_value": 0.08,
        "evaluated_edge_probability": 0.10,
        "price_status": "VALUE",
        "model_candidate_regions": (
            "ML_DOG_VALUE_ZONE_AVG" if market == "moneyline" else "SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4"
        ),
        "model_price_gap": 0.05,
        "model_cover_margin_v3": 2.0,
    }


def _write_proof(root, *, captured_at: str, outcome: str = "SUCCESS") -> None:
    run = root / captured_at.replace(":", "")
    (run / "product").mkdir(parents=True)
    (run / "run-status.json").write_text(json.dumps({"outcome": outcome}), encoding="utf-8")
    (run / "product" / "deterministic-proof.json").write_text(
        json.dumps(
            {
                "selector_evidence": {
                    "schema_version": "NFL_EDGE_LIVE_SELECTOR_EVIDENCE_V1",
                    "season": 2026,
                    "week": 1,
                    "captured_at_utc": captured_at,
                    "games": [{"game_id": "2026_01_A_B", "kickoff_at_utc": "2026-09-10T00:20:00Z"}],
                    "rows": [_selector_row(market="moneyline"), _selector_row(market="spread")],
                }
            }
        ),
        encoding="utf-8",
    )


def _evidence():
    return SimpleNamespace(
        through_week=1,
        games=pl.DataFrame(
            [{"game_id": "2026_01_A_B", "home_score": 24, "away_score": 17}]
        ),
    )


def test_selector_state_advances_from_latest_successful_pregame_week(tmp_path):
    _write_proof(tmp_path, captured_at="2026-09-09T18:00:00Z")
    # A later in-progress refresh is deliberately not allowed to overwrite the
    # causal pregame board used to settle selector-family trust.
    _write_proof(tmp_path, captured_at="2026-09-10T00:20:00Z")

    state = advance_live_value_state(entering=ValueSelectorState(), evidence=_evidence(), run_root=tmp_path)

    assert len(state.ml_observations) == 1
    assert len(state.spread_observations) == 1
    assert state.ml_observations[0].realized_edge > 0
    assert state.spread_observations[0].realized_edge > 0


def test_selector_state_requires_successful_pregame_evidence(tmp_path):
    _write_proof(tmp_path, captured_at="2026-09-09T18:00:00Z", outcome="MATERIALIZATION_FAILED")

    with pytest.raises(Entering2026ProductStateError, match="strictly pre-kickoff"):
        advance_live_value_state(entering=ValueSelectorState(), evidence=_evidence(), run_root=tmp_path)
