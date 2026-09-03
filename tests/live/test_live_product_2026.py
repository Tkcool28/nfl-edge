from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from nfl_edge.contracts.product_api_v1 import validate_product_snapshot
from nfl_edge.live.markets_2026 import normalize_market_snapshot
from nfl_edge.live.product_2026 import build_product_snapshot, product_snapshot_bytes
from nfl_edge.live.product_state_2026 import (
    load_entering_2026_product_state,
    materialize_entering_2026_product_state,
)
from nfl_edge.live.week1_2026 import load_week1_schedule
from tests.live.odds_api_week1_fixture import build_synthetic_week1_response

ROOT = Path(__file__).resolve().parents[2]
SCHEDULE = ROOT / "data/live/2026/week1_schedule_v1.json"
SCHEMA = ROOT / "schemas/NFL_EDGE_PRODUCT_API_V1.schema.json"
PREDICTION_AT = "2026-09-03T17:55:00Z"
ACQUIRED_AT = "2026-09-03T18:00:00Z"


def _freshness(observed: str, age: float, threshold: float = 21600.0):
    return {
        "state": "FRESH",
        "observed_at_utc": observed,
        "age_seconds": age,
        "threshold_seconds": threshold,
    }


def _qb(gid: str, team: str, side: str):
    return {
        "team": team,
        "game_id": gid,
        "expected_starter": f"Synthetic {team} QB",
        "sleeper_player_id": f"sleeper-{gid}-{side}",
        "canonical_qb_id": f"canonical-{gid}-{side}",
        "gsis_id": f"gsis-{gid}-{side}",
        "depth_designation": "DEPTH_CHART_EXPECTED_HEALTHY",
        "injury_status": None,
        "source": "synthetic-test",
        "source_snapshot_at_utc": "2026-09-03T17:50:00Z",
        "provenance_id": f"qb-prov-{gid}-{side}",
        "resolution_status": "RESOLVED",
        "freshness": _freshness("2026-09-03T17:50:00Z", 300.0),
        "warning_state": None,
        "last_changed_at_utc": "2026-09-03T17:50:00Z",
    }


def _output(prediction: float, model: str):
    return {
        "status": "AVAILABLE",
        "prediction": prediction,
        "support": "SUPPORTED",
        "input_identity": f"synthetic-{model}-inputs",
        "artifact_version": f"synthetic-{model}-artifact",
        "warnings": [],
    }


def _football_snapshot(schedule):
    games = []
    for index, row in enumerate(schedule["games"]):
        gid = str(row["game_id"])
        home = str(row["home_team"])
        away = str(row["away_team"])
        outputs = {
            "qb_elo": _output(0.50 + ((index % 7) - 3) * 0.012, "qb-elo"),
            "xgboost_v2": _output(0.51 + ((index % 5) - 2) * 0.014, "xgb"),
            "expected_margin": _output(((index % 9) - 4) * 1.2, "expected-margin"),
            "ridge_totals_r4": _output(43.0 + (index % 7), "ridge-r4"),
        }
        if index == 0:
            outputs["xgboost_v2"] = {
                "status": "AVAILABLE_WITH_ROOF_SCENARIOS",
                "prediction": None,
                "support": "PARTIAL",
                "input_identity": "synthetic-xgb-roof-inputs",
                "artifact_version": "synthetic-xgb-artifact",
                "warnings": ["Synthetic pending roof for contract test."],
                "roof_resolution_status": "PENDING",
                "roof_selected_scenario": None,
                "xgboost_open_probability": 0.49,
                "xgboost_closed_probability": 0.54,
                "xgboost_scenario_delta": 0.05,
                "roof_scenario_downstream": {
                    "status": "NOT_EVALUATED_MISSING_EVIDENCE",
                    "agreement_status": "NOT_EVALUABLE",
                    "open_state": None,
                    "closed_state": None,
                    "shared_state": None,
                },
            }
        games.append(
            {
                "game_id": gid,
                "season": 2026,
                "week": 1,
                "away_team": away,
                "home_team": home,
                "kickoff_at_utc": str(row["scheduled_start_utc"]),
                "neutral_site": bool(row["neutral_site"]),
                "venue": row["venue"],
                "roof": {"synthetic": True},
                "quarterbacks": {
                    "home": _qb(gid, home, "home"),
                    "away": _qb(gid, away, "away"),
                },
                "football_outputs": outputs,
            }
        )
    snapshot = {
        "schema_version": "NFL_EDGE_LIVE_SCORER_V1",
        "generated_at_utc": PREDICTION_AT,
        "prediction_as_of_utc": PREDICTION_AT,
        "season": 2026,
        "week": 1,
        "completed_football_state_version": "synthetic-entering-2026-football-state",
        "qb_snapshot_version": "synthetic-sleeper-snapshot",
        "model_versions": {
            "qb_elo": "frozen-production",
            "xgboost_v2": "post-v5-v2",
            "expected_margin": "v1",
            "ridge_totals_r4": "r4",
        },
        "games": games,
    }
    identity = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    snapshot["snapshot_sha256"] = hashlib.sha256(identity).hexdigest()
    return snapshot


def _market_snapshot(schedule):
    events = build_synthetic_week1_response(schedule, observed_at_utc=ACQUIRED_AT)
    raw = (json.dumps(events, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return normalize_market_snapshot(
        schedule=schedule,
        events=events,
        acquired_at_utc=ACQUIRED_AT,
        response_sha256=hashlib.sha256(raw).hexdigest(),
        credits_consumed=0,
        credits_remaining=None,
    )


def test_entering_2026_state_reconstructs_accepted_2024_parity_and_resets_value(tmp_path):
    payload = materialize_entering_2026_product_state(ROOT)
    assert payload["source_evidence"]["reconstructed_2024_state_parity"] == "PASS"
    assert payload["source_evidence"]["accepted_2025_games"] == 285
    assert payload["source_evidence"]["accepted_2025_blocks"] == 22
    assert payload["value_selector_state"] == {
        "reset_for_new_season": True,
        "ml_observations": 0,
        "spread_observations": 0,
    }
    path = tmp_path / "entering-2026.json"
    path.write_text(json.dumps(payload, sort_keys=True, allow_nan=False) + "\n")
    loaded = load_entering_2026_product_state(path)
    assert loaded["value_state"].ml_observations == ()
    assert loaded["value_state"].spread_observations == ()


def test_full_fixture_product_validates_and_replays_identically(tmp_path):
    state_payload = materialize_entering_2026_product_state(ROOT)
    state_path = tmp_path / "entering-2026.json"
    state_path.write_text(json.dumps(state_payload, sort_keys=True, allow_nan=False) + "\n")
    state = load_entering_2026_product_state(state_path)
    schedule = load_week1_schedule(SCHEDULE)
    football = _football_snapshot(schedule)
    markets = _market_snapshot(schedule)

    first, first_proof = build_product_snapshot(
        root=ROOT,
        football_snapshot=football,
        market_snapshot=markets,
        decision_state=state,
    )
    second, second_proof = build_product_snapshot(
        root=ROOT,
        football_snapshot=football,
        market_snapshot=markets,
        decision_state=state,
    )
    validate_product_snapshot(first)
    schema = json.loads(SCHEMA.read_text())
    Draft202012Validator(schema).validate(first)
    assert len(first["games"]) == 16
    assert first_proof["schema_validation"] == "PASS"
    assert first_proof["evaluator_by_market"].get("moneyline", 0) > 0
    assert first_proof["evaluator_by_market"].get("spread", 0) > 0
    assert first_proof["evaluator_by_market"].get("total", 0) > 0
    assert product_snapshot_bytes(first) == product_snapshot_bytes(second)
    assert first_proof == second_proof
    pending = first["games"][0]["football_outputs"]["xgboost_v2"]["roof_scenario_downstream"]
    assert pending["status"] in {"EVALUATED", "ROOF_SENSITIVE"}
    if pending["status"] == "ROOF_SENSITIVE":
        assert pending["shared_state"] is None
        assert pending["open_state"] != pending["closed_state"]
    else:
        assert pending["open_state"] == pending["closed_state"] == pending["shared_state"]
    assert all(headline["market"] != "TOTAL" for headline in first["headlines"].values() if headline["market"])
