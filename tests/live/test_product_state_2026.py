from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import polars as pl
import pytest

from nfl_edge.live import product_state_2026 as product_state
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


def test_selector_state_can_recover_legacy_pregame_proof_via_governed_replay(
    tmp_path, monkeypatch
):
    captured_at = "2026-09-09T18:00:00Z"
    run = tmp_path / "legacy-week1"
    (run / "product").mkdir(parents=True)
    (run / "run-status.json").write_text(
        json.dumps({"outcome": "SUCCESS"}), encoding="utf-8"
    )
    # Pre-PR131 proof: successful product proof exists, but no selector_evidence.
    (run / "product" / "deterministic-proof.json").write_text(
        json.dumps({"schema_validation": "PASS"}), encoding="utf-8"
    )

    calls = []

    def legacy_replay(*, repository_root, run_dir):
        calls.append((repository_root, run_dir))
        return {
            "schema_version": "NFL_EDGE_LIVE_SELECTOR_EVIDENCE_V1",
            "season": 2026,
            "week": 1,
            "captured_at_utc": captured_at,
            "games": [{
                "game_id": "2026_01_A_B",
                "kickoff_at_utc": "2026-09-10T00:20:00Z",
            }],
            "rows": [
                _selector_row(market="moneyline"),
                _selector_row(market="spread"),
            ],
        }

    monkeypatch.setattr(
        product_state,
        "_legacy_selector_evidence_from_run",
        legacy_replay,
    )
    repo_root = tmp_path / "repo"
    state = advance_live_value_state(
        entering=ValueSelectorState(),
        evidence=_evidence(),
        run_root=tmp_path,
        repository_root=repo_root,
    )

    assert calls == [(repo_root, run)]
    assert len(state.ml_observations) == 1
    assert len(state.spread_observations) == 1


def test_legacy_selector_replay_accepts_semantic_source_parity_without_whole_product_byte_replay(
    tmp_path, monkeypatch
):
    run = tmp_path / "legacy-week1"
    (run / "football").mkdir(parents=True)
    (run / "market").mkdir(parents=True)
    (run / "product").mkdir(parents=True)

    prediction_as_of = "2026-09-09T15:30:00Z"
    acquired_at = "2026-09-09T15:34:00Z"
    game_id = "2026_01_A_B"
    outputs = {
        "qb_elo": {"status": "AVAILABLE", "home_win_probability": 0.61},
        "xgboost_v2": {
            "status": "AVAILABLE_WITH_ROOF_SCENARIOS",
            "home_win_probability": None,
            "roof_scenarios": {
                "open": {"home_win_probability": 0.58},
                "closed": {"home_win_probability": 0.62},
            },
        },
    }

    football = {
        "season": 2026,
        "week": 1,
        "prediction_as_of_utc": prediction_as_of,
        "completed_football_state_version": "entering-2026:test",
        "qb_snapshot_version": "sleeper:test",
        "games": [{
            "game_id": game_id,
            "home_team": "B",
            "away_team": "A",
            "kickoff_at_utc": "2026-09-10T00:20:00Z",
            "football_outputs": outputs,
        }],
    }
    market = {
        "season": 2026,
        "week": 1,
        "acquired_at_utc": acquired_at,
        "market_snapshot_version": "market:test",
        "games": [{"game_id": game_id, "market_board": {"moneyline": [], "spread": [], "total": []}}],
    }
    original = {
        "schema_version": "NFL_EDGE_PRODUCT_API_V1",
        "product_version": "live-2026-week1-product-v1",
        "generated_at_utc": acquired_at,
        "prediction_as_of_utc": prediction_as_of,
        "season": 2026,
        "week": 1,
        "football_data_version": "entering-2026:test",
        "qb_snapshot_version": "sleeper:test",
        "market_snapshot_version": "market:test",
        "headlines": {"hit_rate": {"state": "NO_PLAY"}, "balanced": {"state": "NO_PLAY"}, "value": {"state": "NO_PLAY"}},
        "games": [{
            "game_id": game_id,
            "home_team": "B",
            "away_team": "A",
            "kickoff_at_utc": "2026-09-10T00:20:00Z",
            "market_board": {"moneyline": [], "spread": [], "total": []},
            "football_outputs": {
                "prediction_as_of_utc": prediction_as_of,
                "provenance_id": "football:test",
                "qb_elo": outputs["qb_elo"],
                "xgboost_v2": {
                    **outputs["xgboost_v2"],
                    "roof_scenario_downstream": {"status": "AGREE"},
                },
            },
        }],
    }
    original_bytes = json.dumps(original, sort_keys=True).encode()
    product_path = run / "product" / "NFL_EDGE_PRODUCT_API_V1.json"
    product_path.write_bytes(original_bytes)
    (run / "football" / "football.json").write_text(json.dumps(football), encoding="utf-8")
    (run / "market" / "NFL_EDGE_LIVE_MARKET_V1.json").write_text(json.dumps(market), encoding="utf-8")
    (run / "run-status.json").write_text(
        json.dumps({
            "outcome": "SUCCESS",
            "product_sha256": hashlib.sha256(original_bytes).hexdigest(),
        }),
        encoding="utf-8",
    )

    import nfl_edge.contracts.live_product_v1 as contract
    import nfl_edge.live.product_2026 as product_2026

    monkeypatch.setattr(contract, "validate_product_snapshot", lambda payload: payload)
    monkeypatch.setattr(product_state, "load_entering_2026_product_state", lambda path: {"value_state": ValueSelectorState()})
    selector = {
        "schema_version": "NFL_EDGE_LIVE_SELECTOR_EVIDENCE_V1",
        "season": 2026,
        "week": 1,
        "captured_at_utc": acquired_at,
        "games": [{"game_id": game_id, "kickoff_at_utc": "2026-09-10T00:20:00Z"}],
        "rows": [_selector_row(market="moneyline"), _selector_row(market="spread")],
    }
    monkeypatch.setattr(
        product_2026,
        "build_product_snapshot",
        lambda **kwargs: (
            {
                **original,
                # Deliberate harmless public-format evolution proves recovery
                # is not coupled to whole-file historical byte identity.
                "warnings": ["modern-format-only"],
            },
            {"selector_evidence": selector},
        ),
    )

    recovered = product_state._legacy_selector_evidence_from_run(
        repository_root=tmp_path,
        run_dir=run,
    )
    assert recovered == selector


def test_selector_replay_failure_reports_candidate_rejection(tmp_path, monkeypatch):
    run = tmp_path / "legacy-week1"
    (run / "product").mkdir(parents=True)
    (run / "run-status.json").write_text(json.dumps({"outcome": "SUCCESS"}), encoding="utf-8")
    (run / "product" / "deterministic-proof.json").write_text(
        json.dumps({"schema_validation": "PASS"}), encoding="utf-8"
    )

    def reject(**kwargs):
        raise Entering2026ProductStateError("headline decisions differ from original immutable product")

    monkeypatch.setattr(product_state, "_legacy_selector_evidence_from_run", reject)
    with pytest.raises(
        Entering2026ProductStateError,
        match="headline decisions differ from original immutable product",
    ):
        advance_live_value_state(
            entering=ValueSelectorState(),
            evidence=_evidence(),
            run_root=tmp_path,
            repository_root=tmp_path,
        )
