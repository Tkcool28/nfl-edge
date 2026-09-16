"""Chronologically advance the entering-2026 model state through settled REG weeks."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import polars as pl

from nfl_edge.features.totals_v1.game_observations import build_game_observations_with_provenance
from nfl_edge.features.totals_v1.pbp_semantics import annotate_live_settled_pbp_semantics
from nfl_edge.holdout.totals_features_2025 import reveal_and_commit_totals_block
from nfl_edge.live.evidence_2026 import SettledActualQBResolver, SettledSeasonEvidence
from nfl_edge.live.features_2026 import build_live_week_features
from nfl_edge.live.model_adapters import (
    predict_expected_margin_block,
    predict_qb_elo_block,
    reveal_and_update_qb_elo_block,
)
from nfl_edge.live.qb_inputs import build_qb_adjustment_resolver, build_totals_qb_surface
from nfl_edge.live.schedule_2026 import load_schedule, rollover_at_utc
from nfl_edge.live.state_2026 import Entering2026FootballState, bootstrap_entering_2026_state
from nfl_edge.live.totals_features import materialize_live_totals_feature_block

_EM_SCHEMA = (
    "game_id","season","season_type","week","prediction_as_of_utc","home_team",
    "away_team","neutral_site","target_available","home_score","away_score",
    "target_margin","target_home_win","target_tie",
)


class StateAdvancementError(RuntimeError):
    pass


def _iso(dt) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _reveal(features, settled: pl.DataFrame) -> pl.DataFrame:
    cols = [
        "game_id","home_score","away_score","target_margin","target_home_win",
        "target_tie","target_total_points","roof_actual",
    ]
    frame = features.current_games.drop("home_score","away_score","target_available").join(
        settled.select(cols), on="game_id", how="left", validate="1:1"
    )
    if frame["home_score"].null_count() or frame["away_score"].null_count():
        raise StateAdvancementError("settled block is missing final scores")
    return frame.with_columns(pl.lit(True).alias("target_available")).sort("game_id")


def _completed_context(features, settled: pl.DataFrame):
    roofs = settled.select("game_id","roof_actual")
    gf = features.game_features.join(roofs,on="game_id",how="left",validate="1:1")
    gf = gf.with_columns(
        pl.when(pl.col("roof_actual").is_in(["open","closed","dome","outdoors"]))
        .then(pl.col("roof_actual")).otherwise(pl.col("roof_type")).alias("roof_type")
    ).drop("roof_actual")
    xgb = features.xgboost_surface.join(roofs,on="game_id",how="left",validate="1:1")
    actual = pl.col("roof_actual").is_in(["open","closed","dome","outdoors"])
    xgb = xgb.with_columns(
        pl.when(actual).then(pl.col("roof_actual")).otherwise(pl.col("roof_category")).alias("roof_category"),
        pl.when(actual).then(pl.lit(False)).otherwise(pl.col("roof_missing")).alias("roof_missing"),
    ).drop("roof_actual")
    return gf, xgb


def _version(state: Entering2026FootballState, evidence: SettledSeasonEvidence) -> str:
    payload = {
        "base": state.state_version,
        "completed": list(state.completed_2026_blocks),
        "evidence": evidence.manifest,
        "qb_update_order": state.qb_update_order,
        "xgb_rows": state.xgb_history.height,
        "expected_rows": state.expected_history.height,
        "totals_rows": state.totals_training.height,
    }
    raw = json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode()
    return "live-2026-state:" + hashlib.sha256(raw).hexdigest()[:24]


def advance_entering_state_through_settled_weeks(
    *,
    repository_root: str | Path,
    active_schedule_path: str | Path,
    evidence: SettledSeasonEvidence,
    entering_state: Entering2026FootballState | None = None,
) -> Entering2026FootballState:
    root = Path(repository_root).resolve()
    active = load_schedule(active_schedule_path)
    active_week = int(active["week"])
    if evidence.through_week != active_week - 1:
        raise StateAdvancementError(
            f"evidence through Week {evidence.through_week} cannot feed active Week {active_week}"
        )
    state = entering_state or bootstrap_entering_2026_state(root)
    if active_week == 1:
        return replace(state, completed_2026_blocks=())

    live_inputs = evidence.feature_inputs()
    completed: list[str] = []
    for week in range(1, active_week):
        schedule_path = evidence.root / f"week{week}_schedule_v1.json"
        schedule = load_schedule(schedule_path)
        boundary = rollover_at_utc(schedule) + timedelta(days=7)
        settled = evidence.games.filter(pl.col("week") == week).sort("game_id")
        if settled.height != len(schedule["games"]):
            raise StateAdvancementError(f"Week {week} settled/schedule coverage differs")

        features = build_live_week_features(
            repository_root=root,
            prediction_as_of_utc=_iso(boundary),
            resolver=SettledActualQBResolver(settled, observed_at_utc=_iso(boundary)),
            schedule_path=schedule_path,
            prior_live_inputs=live_inputs,
        )
        revealed = _reveal(features,settled)
        current = features.current_games.with_columns(
            pl.lit(None,dtype=pl.Float64).alias("target_margin"),
            pl.lit(None,dtype=pl.Boolean).alias("target_home_win"),
            pl.lit(None,dtype=pl.Boolean).alias("target_tie"),
        )
        expected = predict_expected_margin_block(
            history_games=state.expected_history,current_games=current,
            prior_oos_predictions=list(state.expected_oos),block=features.block,
            candidate=state.expected_candidate,shared=state.expected_shared,
            run_id=f"live_2026_state_week{week}",created_at=features.block.as_of_utc,
        )
        qb_adjustment = build_qb_adjustment_resolver(
            features.qb_features,game_ids=features.block.game_ids,
            config_path=root/"config/qb_elo_v1.yaml",
        )
        qb_frozen = predict_qb_elo_block(
            history_games=state.expected_history,current_games=current,block=features.block,
            state=state.qb_state,config=state.qb_config,qb_adjustment_resolver=qb_adjustment,
            run_id=f"live_2026_state_week{week}",created_at=features.block.as_of_utc,
        )
        qb_update = reveal_and_update_qb_elo_block(
            frozen_prediction=qb_frozen,revealed_games=revealed,config=state.qb_config,
            run_id=f"live_2026_state_week{week}",update_order_start=state.qb_update_order,
        )

        completed_gf, completed_xgb = _completed_context(features,settled)
        xgb_revealed = completed_xgb.drop("target_home_win","target_available").join(
            revealed.select("game_id","target_home_win"),on="game_id",how="left",validate="1:1"
        ).with_columns(pl.lit(True).alias("target_available"))

        totals_qb = build_totals_qb_surface(features.qb_features,game_ids=features.block.game_ids)
        frozen_totals = materialize_live_totals_feature_block(
            state=state.totals_state,current_games=completed_gf,
            qb_surface=totals_qb,block=features.block,
        )
        pbp_frames = {
            gid:evidence.pbp.filter(pl.col("game_id").cast(pl.Utf8)==gid)
            for gid in features.block.game_ids
        }
        if any(frame.is_empty() for frame in pbp_frames.values()):
            raise StateAdvancementError(f"Week {week} PBP coverage incomplete")
        teams = {
            str(row["game_id"]):(str(row["home_team"]),str(row["away_team"]))
            for row in features.current_games.to_dicts()
        }
        observations,_ = build_game_observations_with_provenance(
            block_id=features.block.block_id,
            pbp_frames=pbp_frames,
            game_to_teams=teams,
            annotation_fn=annotate_live_settled_pbp_semantics,
        )
        totals_update = reveal_and_commit_totals_block(
            frozen=frozen_totals,state=state.totals_state,revealed_games=revealed,
            observations=observations,
        )

        expected_history = pl.concat(
            [state.expected_history,revealed.select(list(_EM_SCHEMA))],how="diagonal_relaxed"
        )
        outcomes = {
            str(r["game_id"]):r for r in revealed.select(
                "game_id","target_margin","target_home_win","target_tie"
            ).to_dicts()
        }
        expected_oos = list(state.expected_oos)
        for source in expected["predictions"]:
            row = dict(source)
            actual = outcomes[str(source["game_id"])]
            row.update(
                actual_margin=int(actual["target_margin"]),
                actual_home_win=actual["target_home_win"],
                actual_tie=bool(actual["target_tie"]),
                target_available=True,
            )
            expected_oos.append(row)

        completed.append(features.block.block_id)
        state = replace(
            state,
            qb_state=qb_update["new_state"],
            qb_update_order=int(qb_update["next_update_order"]),
            xgb_history=pl.concat([state.xgb_history,xgb_revealed],how="diagonal_relaxed"),
            expected_history=expected_history,
            expected_oos=tuple(expected_oos),
            totals_training=pl.concat(
                [state.totals_training,totals_update["graded_model_rows"]],how="diagonal_relaxed"
            ),
            completed_2026_blocks=tuple(completed),
            history_complete_through_utc=_iso(boundary),
        )
    return replace(state,state_version=_version(state,evidence))
