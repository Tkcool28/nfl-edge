"""Reconstruct the deterministic football-only state entering the 2026 season.

This module advances the already-accepted 2025 football chronology only far
enough to make settled 2025 information available as strictly-prior history for
prospective 2026 scoring.  It never builds markets, candidates, selectors,
staking, or product recommendations and it performs no model selection or
hyperparameter tuning.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from nfl_edge.backtest.blocks import build_development_blocks
from nfl_edge.features.totals_v1.feature_table import (
    _normalize_pbp_teams_to_canonical,
    _split_pbp_by_game,
)
from nfl_edge.features.totals_v1.game_observations import build_game_observations_with_provenance
from nfl_edge.features.totals_v1.manifest import load_pbp_frames
from nfl_edge.features.totals_v1.mapping import map_pbp_to_canonical
from nfl_edge.holdout import executor_runtime_2025 as runtime
from nfl_edge.holdout.expected_margin_2025 import predict_expected_margin_block
from nfl_edge.holdout.football_2025 import (
    build_holdout_blocks,
    predict_oracle_qb_elo_block,
    reveal_and_update_qb_elo_block,
)
from nfl_edge.holdout.oracle_qb_game_resolver_2025 import FrozenOracleQBGameResolver2025
from nfl_edge.holdout.totals_features_2025 import (
    bootstrap_totals_state,
    materialize_totals_feature_block,
    reveal_and_commit_totals_block,
)
from nfl_edge.models.qb_elo import EloState

ENTERING_STATE_SCHEMA = "nfl-edge-entering-2026-football-state-v1"
DEFAULT_PBP_ROOT = Path("data/frozen/task05c_pbp_v1")
RUN_ID = "live_2026_entering_state_bootstrap_v1"


class Entering2026StateError(RuntimeError):
    """Raised when the frozen 2025 -> 2026 football state cannot be rebuilt."""


def _canonical_sha(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _repo_file(root: Path, runtime_path: Path) -> Path:
    """Translate a runtime absolute repo path to the caller's checkout."""
    try:
        relative = runtime_path.resolve().relative_to(runtime.ROOT.resolve())
    except ValueError as exc:
        raise Entering2026StateError(f"runtime path escaped repository: {runtime_path}") from exc
    return root / relative


def _development_totals_state(root: Path, pbp_root: Path):
    """Exact runtime bootstrap, but with the repository-tracked PBP family."""
    games_path = _repo_file(root, runtime.GAMES)
    features_path = _repo_file(root, runtime.FEATURES)
    pbp = load_pbp_frames(pbp_root)
    canonical = (
        pl.scan_parquet(games_path)
        .filter(pl.col("season") <= 2024)
        .select("game_id", "season", "season_type", "week", "away_team", "home_team")
        .collect()
    )
    chronology = (
        pl.scan_parquet(features_path)
        .filter(pl.col("season") <= 2024)
        .select("game_id", "season", "season_type", "week", "prediction_as_of_utc")
        .collect()
    )
    blocks = build_development_blocks(chronology)
    mapped = pl.concat(
        [map_pbp_to_canonical(pbp[season], canonical) for season in sorted(pbp)],
        how="vertical_relaxed",
    )
    mapped = _normalize_pbp_teams_to_canonical(mapped)
    per_game = _split_pbp_by_game(mapped)
    game_to_teams = {
        str(row["game_id"]): (str(row["home_team"]), str(row["away_team"]))
        for row in canonical.to_dicts()
    }
    observations = {}
    for block in blocks:
        obs, _ = build_game_observations_with_provenance(
            block_id=block.block_id,
            pbp_frames={gid: per_game[gid] for gid in block.game_ids},
            game_to_teams=game_to_teams,
        )
        observations[block.block_id] = tuple(obs)
    return bootstrap_totals_state(blocks=blocks, observations_by_block=observations)


@dataclass(frozen=True)
class Entering2026FootballState:
    qb_state: EloState
    qb_config: Any
    qb_update_order: int
    xgb_development: pl.DataFrame
    xgb_history: pl.DataFrame
    xgb_feature_cols: tuple[str, ...]
    expected_history: pl.DataFrame
    expected_oos: tuple[dict[str, Any], ...]
    expected_shared: Any
    expected_candidate: Any
    totals_state: Any
    totals_training: pl.DataFrame
    completed_2025_blocks: tuple[str, ...]
    history_complete_through_utc: str
    state_version: str
    schema_version: str = ENTERING_STATE_SCHEMA

    def summary(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state_version": self.state_version,
            "completed_2025_blocks": list(self.completed_2025_blocks),
            "history_complete_through_utc": self.history_complete_through_utc,
            "qb_state_season": self.qb_state.current_season,
            "qb_team_count": len(self.qb_state.teams),
            "xgb_development_rows": self.xgb_development.height,
            "xgb_prior_rows": self.xgb_history.height,
            "expected_margin_prior_rows": self.expected_history.height,
            "expected_margin_oos_rows": len(self.expected_oos),
            "totals_prior_rows": self.totals_training.height,
        }


def bootstrap_entering_2026_state(
    repo_root: str | Path,
    *,
    pbp_root: str | Path = DEFAULT_PBP_ROOT,
) -> Entering2026FootballState:
    """Advance accepted football state through every settled 2025 block."""
    root = Path(repo_root).resolve()
    pbp = Path(pbp_root)
    if not pbp.is_absolute():
        pbp = root / pbp

    feature_cols, base_features = runtime._xgb_contract()
    xgb_dev = pl.read_parquet(_repo_file(root, runtime.XGB_DEV))
    if xgb_dev.height == 0 or int(xgb_dev["season"].max()) > 2024:
        raise Entering2026StateError("XGBoost development reference is not 2018-2024 only")
    xgb_history = xgb_dev.clone()

    expected_history = runtime._development_expected_margin()
    if root != runtime.ROOT.resolve():
        features_path = _repo_file(root, runtime.FEATURES)
        games_path = _repo_file(root, runtime.GAMES)
        predictors = (
            pl.scan_parquet(features_path)
            .filter(pl.col("season") <= 2024)
            .select(
                "game_id", "season", "season_type", "week", "prediction_as_of_utc",
                "home_team", "away_team", "neutral_site", "target_available",
                "target_margin", "target_home_win", "target_tie",
            )
        )
        scores = (
            pl.scan_parquet(games_path)
            .filter(pl.col("season") <= 2024)
            .select("game_id", "home_score", "away_score")
        )
        expected_history = predictors.join(scores, on="game_id", how="left").collect().sort(
            ["season", "week", "game_id"]
        ).select(list(runtime._EM_SCHEMA))

    expected_oos = pl.read_parquet(_repo_file(root, runtime.EXPECTED_MARGIN_PREDICTIONS)).to_dicts()
    expected_shared, expected_candidate = runtime._expected_margin_config()
    qb_config = runtime._qb_config()
    qb_state = runtime._end_2024_elo_state()
    qb_update_order = 0
    totals_state = _development_totals_state(root, pbp)
    totals_training = pl.read_parquet(_repo_file(root, runtime.TOTALS_DEV_MODELING))

    context, xgb_all = runtime._pre_result_frames(feature_cols, base_features)
    if root != runtime.ROOT.resolve():
        raise Entering2026StateError(
            "entering-state bootstrap must run from the active repository checkout"
        )
    blocks = build_holdout_blocks(context)
    resolver = FrozenOracleQBGameResolver2025(
        _repo_file(root, runtime.ORACLE_GAME), repo_root=root
    )
    oracle_sides = pl.read_parquet(_repo_file(root, runtime.ORACLE_SIDES))
    observations = runtime._ObservationCursor(_repo_file(root, runtime.OBSERVATIONS_2025))
    completed: list[str] = []

    for block in blocks:
        current = context.filter(pl.col("game_id").is_in(list(block.game_ids)))
        current_xgb = xgb_all.filter(pl.col("game_id").is_in(list(block.game_ids)))

        qb_frozen = predict_oracle_qb_elo_block(
            history_games=expected_history,
            current_games=current,
            block=block,
            state=qb_state,
            config=qb_config,
            qb_adjustment_resolver=resolver,
            run_id=RUN_ID,
            created_at=block.as_of_utc,
        )
        expected_frozen = predict_expected_margin_block(
            history_games=expected_history,
            current_games=current.select(list(runtime._EM_SCHEMA)),
            prior_oos_predictions=expected_oos,
            block=block,
            candidate=expected_candidate,
            shared=expected_shared,
            run_id=RUN_ID,
            created_at=block.as_of_utc,
        )
        totals_frozen = materialize_totals_feature_block(
            state=totals_state,
            current_games=current,
            oracle_qb=oracle_sides,
            block=block,
        )

        revealed = runtime._revealed_block(block, context)
        block_observations = observations.take(block)
        qb_update = reveal_and_update_qb_elo_block(
            frozen_prediction=qb_frozen,
            revealed_games=revealed,
            config=qb_config,
            run_id=RUN_ID,
            update_order_start=qb_update_order,
        )
        qb_state = qb_update["new_state"]
        qb_update_order = int(qb_update["next_update_order"])

        totals_update = reveal_and_commit_totals_block(
            frozen=totals_frozen,
            state=totals_state,
            revealed_games=revealed,
            observations=block_observations,
        )
        totals_training = pl.concat(
            [totals_training, totals_update["graded_model_rows"]], how="diagonal_relaxed"
        )

        xgb_revealed = (
            current_xgb.drop("target_home_win", "target_available")
            .join(
                revealed.select("game_id", "target_home_win"),
                on="game_id", how="left", validate="1:1",
            )
            .with_columns(pl.lit(True).alias("target_available"))
        )
        xgb_history = pl.concat([xgb_history, xgb_revealed], how="diagonal_relaxed")
        expected_history = pl.concat(
            [expected_history, revealed.select(list(runtime._EM_SCHEMA))],
            how="diagonal_relaxed",
        )
        outcome = {
            str(row["game_id"]): row
            for row in revealed.select(
                "game_id", "target_margin", "target_home_win", "target_tie"
            ).to_dicts()
        }
        for source in expected_frozen["predictions"]:
            row = dict(source)
            actual = outcome[str(source["game_id"])]
            row.update(
                {
                    "actual_margin": int(actual["target_margin"]),
                    "actual_home_win": actual["target_home_win"],
                    "actual_tie": bool(actual["target_tie"]),
                    "target_available": True,
                }
            )
            expected_oos.append(row)
        completed.append(block.block_id)

    observations.assert_exhausted()
    if len(completed) != len(blocks) or xgb_history.filter(pl.col("season") == 2025).height != 285:
        raise Entering2026StateError("2025 football history did not advance completely")
    if expected_history.filter(pl.col("season") == 2025).height != 285:
        raise Entering2026StateError("Expected Margin 2025 history coverage drift")
    if totals_training.filter(pl.col("season") == 2025).height != 285:
        raise Entering2026StateError("Totals R4 2025 training coverage drift")
    if qb_state.current_season != 2025:
        raise Entering2026StateError(f"QB-Elo terminal season drift: {qb_state.current_season}")

    latest = context["scheduled_start_utc"].max()
    if not isinstance(latest, datetime):
        raise Entering2026StateError("2025 scheduled_start_utc terminal value is not datetime")
    if latest.tzinfo is None or latest.utcoffset() is None:
        latest = latest.replace(tzinfo=timezone.utc)
    history_complete = latest.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    identity = {
        "completed_2025_blocks": completed,
        "history_complete_through_utc": history_complete,
        "qb_ratings": {team: float(value.rating) for team, value in sorted(qb_state.teams.items())},
        "xgb_prior_game_ids": sorted(str(x) for x in xgb_history["game_id"].to_list()),
        "expected_prior_game_ids": sorted(str(x) for x in expected_history["game_id"].to_list()),
        "expected_oos_game_ids": sorted(str(row.get("game_id")) for row in expected_oos),
        "totals_prior_game_ids": sorted(str(x) for x in totals_training["game_id"].to_list()),
    }
    state_version = f"entering-2026:{_canonical_sha(identity)[:24]}"
    return Entering2026FootballState(
        qb_state=qb_state,
        qb_config=qb_config,
        qb_update_order=qb_update_order,
        xgb_development=xgb_dev,
        xgb_history=xgb_history,
        xgb_feature_cols=tuple(feature_cols),
        expected_history=expected_history,
        expected_oos=tuple(dict(row) for row in expected_oos),
        expected_shared=expected_shared,
        expected_candidate=expected_candidate,
        totals_state=totals_state,
        totals_training=totals_training,
        completed_2025_blocks=tuple(completed),
        history_complete_through_utc=history_complete,
        state_version=state_version,
    )
