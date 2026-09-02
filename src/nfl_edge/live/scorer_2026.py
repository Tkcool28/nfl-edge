"""Deterministic market-independent 2026 Week 1 football scorer."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import polars as pl

from nfl_edge.contracts.common_v1 import MODEL_OUTPUT_STATUSES, SUPPORT_STATES
from nfl_edge.contracts.runtime_interfaces_v1 import LiveScorerRequest
from nfl_edge.live.features_2026 import QB_SCOREABLE_STATES, LiveWeek1Features, build_live_week1_features
from nfl_edge.live.model_adapters import (
    build_live_block,
    predict_expected_margin_block,
    predict_qb_elo_block,
    predict_ridge_totals_r4_block,
    predict_xgboost_v2_block,
)
from nfl_edge.live.qb_inputs import build_qb_adjustment_resolver, build_totals_qb_surface
from nfl_edge.live.sleeper_qb import SleeperExpectedQBResolver
from nfl_edge.live.state_2026 import Entering2026FootballState, bootstrap_entering_2026_state
from nfl_edge.live.totals_features import materialize_live_totals_feature_block
from nfl_edge.live.week1_2026 import load_week1_schedule

SNAPSHOT_SCHEMA = "NFL_EDGE_LIVE_FOOTBALL_SNAPSHOT_V1"
MODEL_VERSIONS = {
    "qb_elo": "qb-elo-v1.0.0",
    "xgboost_v2": "post-v5-v2-conservative-adaptive-tail",
    "expected_margin": "expected-margin-v1-stable",
    "ridge_totals_r4": "ridge-totals-r4-alpha100",
}
QB_FRESHNESS_USABLE = frozenset({"FRESH", "AGING"})


class LiveScoringError(RuntimeError):
    pass


def _sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _model_output(
    *,
    status: str,
    prediction: float | None,
    support: str,
    input_identity: str,
    artifact_version: str,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    if status not in MODEL_OUTPUT_STATUSES:
        raise LiveScoringError(f"unknown model status {status}")
    if support not in SUPPORT_STATES:
        raise LiveScoringError(f"unknown model support {support}")
    if status == "AVAILABLE" and prediction is None:
        raise LiveScoringError("AVAILABLE model output requires a prediction")
    if prediction is not None:
        prediction = float(prediction)
    return {
        "status": status,
        "prediction": prediction,
        "support": support,
        "input_identity": input_identity,
        "artifact_version": artifact_version,
        "warnings": list(warnings or []),
    }


def _current_expected_frame(features: LiveWeek1Features) -> pl.DataFrame:
    return features.current_games.with_columns(
        pl.lit(None, dtype=pl.Float64).alias("target_margin"),
        pl.lit(None, dtype=pl.Boolean).alias("target_home_win"),
        pl.lit(None, dtype=pl.Boolean).alias("target_tie"),
    )


def _qb_usable_game_ids(features: LiveWeek1Features) -> tuple[str, ...]:
    usable: list[str] = []
    for game in features.current_games.sort("game_id").to_dicts():
        gid = str(game["game_id"])
        sides = (
            features.resolutions[(gid, str(game["home_team"]))],
            features.resolutions[(gid, str(game["away_team"]))],
        )
        if all(
            side.resolution_status in QB_SCOREABLE_STATES
            and side.freshness_state in QB_FRESHNESS_USABLE
            for side in sides
        ):
            usable.append(gid)
    return tuple(usable)


def _unavailable_reason(features: LiveWeek1Features, game: dict[str, Any]) -> tuple[str, list[str]]:
    gid = str(game["game_id"])
    sides = (
        features.resolutions[(gid, str(game["home_team"]))],
        features.resolutions[(gid, str(game["away_team"]))],
    )
    if any(side.freshness_state in {"STALE", "UNAVAILABLE"} for side in sides):
        return "STALE_INPUT", ["Expected-QB source is stale or unavailable; QB-dependent scoring suppressed."]
    labels = [
        f"{side.team}:{side.resolution_status}"
        for side in sides
        if side.resolution_status not in QB_SCOREABLE_STATES
    ]
    return "UNAVAILABLE", ["Expected-QB identity is not scoreable: " + ", ".join(labels)]


def _prediction_identity(
    *, state_version: str, game_id: str, model: str, qb_provenance: list[str] | None = None
) -> str:
    payload = {
        "state_version": state_version,
        "game_id": game_id,
        "model": model,
        "qb_provenance": sorted(qb_provenance or []),
    }
    return f"football-input:{_sha(payload)[:24]}"


def score_week1(
    *,
    repository_root: str | Path,
    prediction_as_of_utc: str,
    resolver: SleeperExpectedQBResolver,
    entering_state: Entering2026FootballState | None = None,
) -> dict[str, Any]:
    """Score the real 16-game Week 1 schedule without reading any market data."""
    root = Path(repository_root).resolve()
    state = entering_state or bootstrap_entering_2026_state(root)
    features = build_live_week1_features(
        repository_root=root,
        prediction_as_of_utc=prediction_as_of_utc,
        resolver=resolver,
    )
    schedule = load_week1_schedule(root / "data/live/2026/week1_schedule_v1.json")
    if len(schedule["games"]) != 16 or features.current_games.height != 16:
        raise LiveScoringError("Week 1 schedule coverage drift")

    resolved_identity = {
        f"{gid}:{team}": resolution.provenance_id
        for (gid, team), resolution in sorted(features.resolutions.items())
    }
    request = LiveScorerRequest(
        schedule_version=str(schedule["schedule_version"]),
        prediction_as_of_utc=prediction_as_of_utc,
        completed_football_state_version=state.state_version,
        history_complete_through_utc=state.history_complete_through_utc,
        qb_state_version=f"{state.state_version}:qb-elo",
        qb_snapshot_version=resolver.source.snapshot_id,
        resolved_expected_qb_version=f"resolved-qb:{_sha(resolved_identity)[:24]}",
        frozen_model_artifact_versions=MODEL_VERSIONS,
        feature_state_versions={
            "live_football_features": "features-v1+live-2026-week1-v1",
            "totals": "totals-v1-exact90",
        },
    ).validate()

    current_expected = _current_expected_frame(features)
    expected_result = predict_expected_margin_block(
        history_games=state.expected_history,
        current_games=current_expected,
        prior_oos_predictions=list(state.expected_oos),
        block=features.block,
        candidate=state.expected_candidate,
        shared=state.expected_shared,
        run_id="live_2026_week1_v1",
        created_at=features.block.as_of_utc,
    )
    expected_by = {
        str(row["game_id"]): float(row["expected_home_margin"])
        for row in expected_result["predictions"]
    }

    usable_ids = _qb_usable_game_ids(features)
    qb_by: dict[str, float] = {}
    xgb_by: dict[str, float] = {}
    totals_by: dict[str, float] = {}
    xgb_warmup = False
    xgb_warmup_reason: str | None = None
    if usable_ids:
        current_usable = current_expected.filter(pl.col("game_id").is_in(list(usable_ids)))
        usable_block = build_live_block(current_usable)
        qb_resolver = build_qb_adjustment_resolver(
            features.qb_features,
            game_ids=usable_ids,
            config_path=root / "config/qb_elo_v1.yaml",
        )
        qb_result = predict_qb_elo_block(
            history_games=state.expected_history,
            current_games=current_usable,
            block=usable_block,
            state=state.qb_state,
            config=state.qb_config,
            qb_adjustment_resolver=qb_resolver,
            run_id="live_2026_week1_v1",
            created_at=usable_block.as_of_utc,
        )
        qb_by = {
            str(row["game_id"]): float(row["predicted_home_win_probability"])
            for row in qb_result["predictions"]
        }

        current_xgb = features.xgboost_surface.filter(pl.col("game_id").is_in(list(usable_ids)))
        xgb_result = predict_xgboost_v2_block(
            development_reference=state.xgb_development,
            prior_history=state.xgb_history,
            current_games=current_xgb,
            block=usable_block,
            feature_cols=list(state.xgb_feature_cols),
        )
        xgb_warmup = bool(xgb_result.get("warmup"))
        xgb_warmup_reason = xgb_result.get("warmup_reason")
        if not xgb_warmup:
            xgb_by = {
                str(gid): float(probability)
                for gid, probability in zip(
                    xgb_result["game_ids"], xgb_result["probabilities"], strict=True
                )
            }

        totals_qb = build_totals_qb_surface(features.qb_features, game_ids=usable_ids)
        totals_current = features.game_features.filter(pl.col("game_id").is_in(list(usable_ids)))
        totals_frozen = materialize_live_totals_feature_block(
            state=state.totals_state,
            current_games=totals_current,
            qb_surface=totals_qb,
            block=usable_block,
        )
        totals_result = predict_ridge_totals_r4_block(
            prior_history=state.totals_training,
            current_games=totals_frozen.model_frame,
            block=usable_block,
        )
        totals_by = {
            str(gid): float(value)
            for gid, value in zip(
                totals_result["game_ids"], totals_result["predicted_totals"], strict=True
            )
        }

    schedule_by = {str(row["game_id"]): row for row in schedule["games"]}
    game_rows: list[dict[str, Any]] = []
    for game in features.current_games.sort("scheduled_start_utc", "game_id").to_dicts():
        gid = str(game["game_id"])
        home_team, away_team = str(game["home_team"]), str(game["away_team"])
        home_qb = features.qb_contexts[(gid, home_team)]
        away_qb = features.qb_contexts[(gid, away_team)]
        qb_provenance = [home_qb["provenance_id"], away_qb["provenance_id"]]
        base_identity = {
            model: _prediction_identity(
                state_version=state.state_version,
                game_id=gid,
                model=model,
                qb_provenance=qb_provenance if model != "expected_margin" else None,
            )
            for model in MODEL_VERSIONS
        }
        if gid in usable_ids:
            qb_output = _model_output(
                status="AVAILABLE", prediction=qb_by[gid], support="SUPPORTED",
                input_identity=base_identity["qb_elo"], artifact_version=MODEL_VERSIONS["qb_elo"],
            )
            if xgb_warmup:
                xgb_output = _model_output(
                    status="UNSUPPORTED", prediction=None, support="UNSUPPORTED",
                    input_identity=base_identity["xgboost_v2"], artifact_version=MODEL_VERSIONS["xgboost_v2"],
                    warnings=[f"Frozen XGBoost V2 warmup: {xgb_warmup_reason}"],
                )
            else:
                xgb_output = _model_output(
                    status="AVAILABLE", prediction=xgb_by[gid], support="SUPPORTED",
                    input_identity=base_identity["xgboost_v2"], artifact_version=MODEL_VERSIONS["xgboost_v2"],
                )
            totals_output = _model_output(
                status="AVAILABLE", prediction=totals_by[gid], support="SUPPORTED",
                input_identity=base_identity["ridge_totals_r4"], artifact_version=MODEL_VERSIONS["ridge_totals_r4"],
            )
        else:
            status, warnings = _unavailable_reason(features, game)
            support = "UNSUPPORTED" if status in {"UNAVAILABLE", "STALE_INPUT"} else "PARTIAL"
            qb_output = _model_output(
                status=status, prediction=None, support=support,
                input_identity=base_identity["qb_elo"], artifact_version=MODEL_VERSIONS["qb_elo"], warnings=warnings,
            )
            xgb_output = _model_output(
                status=status, prediction=None, support=support,
                input_identity=base_identity["xgboost_v2"], artifact_version=MODEL_VERSIONS["xgboost_v2"], warnings=warnings,
            )
            totals_output = _model_output(
                status=status, prediction=None, support=support,
                input_identity=base_identity["ridge_totals_r4"], artifact_version=MODEL_VERSIONS["ridge_totals_r4"], warnings=warnings,
            )
        expected_output = _model_output(
            status="AVAILABLE", prediction=expected_by[gid], support="SUPPORTED",
            input_identity=base_identity["expected_margin"], artifact_version=MODEL_VERSIONS["expected_margin"],
        )
        schedule_row = schedule_by[gid]
        game_rows.append(
            {
                "game_id": gid,
                "season": 2026,
                "week": 1,
                "away_team": away_team,
                "home_team": home_team,
                "kickoff_at_utc": str(schedule_row["scheduled_start_utc"]),
                "neutral_site": bool(schedule_row["neutral_site"]),
                "venue": schedule_row["venue"],
                "quarterbacks": {"home": home_qb, "away": away_qb},
                "football_outputs": {
                    "qb_elo": qb_output,
                    "xgboost_v2": xgb_output,
                    "expected_margin": expected_output,
                    "ridge_totals_r4": totals_output,
                },
            }
        )

    resolution_counts = Counter(
        resolution.resolution_status for resolution in features.resolutions.values()
    )
    model_counts = {
        model: dict(Counter(game["football_outputs"][model]["status"] for game in game_rows))
        for model in MODEL_VERSIONS
    }
    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA,
        "generated_at_utc": prediction_as_of_utc,
        "prediction_as_of_utc": prediction_as_of_utc,
        "season": 2026,
        "week": 1,
        "schedule_version": request.schedule_version,
        "completed_football_state_version": request.completed_football_state_version,
        "history_complete_through_utc": request.history_complete_through_utc,
        "qb_snapshot_version": request.qb_snapshot_version,
        "resolved_expected_qb_version": request.resolved_expected_qb_version,
        "model_versions": dict(MODEL_VERSIONS),
        "sleeper_source": {
            "path": str(resolver.source.audit_root),
            "snapshot_id": resolver.source.snapshot_id,
            "observed_at_utc": resolver.source.observed_at_utc,
            "freshness_state": resolver.source.freshness_state,
            "staleness_threshold_seconds": resolver.source.staleness_threshold_seconds,
        },
        "qb_resolution_counts": dict(sorted(resolution_counts.items())),
        "model_scoring_counts": {
            model: dict(sorted(counts.items())) for model, counts in sorted(model_counts.items())
        },
        "override_audit_count": len(features.override_audits),
        "games": game_rows,
        "guardrails": {
            "market_data_read": False,
            "odds_api_called": False,
            "methodology_changed": False,
            "tuning_performed": False,
            "current_outcomes_read": False,
            "xgboost_chronological_refit_preserved": True,
            "expected_margin_chronological_refit_preserved": True,
            "ridge_r4_chronological_refit_preserved": True,
        },
    }
    if len(snapshot["games"]) != 16:
        raise LiveScoringError("football snapshot must contain exactly 16 Week 1 games")
    snapshot["snapshot_sha256"] = _sha(snapshot)
    return snapshot


def canonical_snapshot_bytes(snapshot: dict[str, Any]) -> bytes:
    return (json.dumps(snapshot, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
