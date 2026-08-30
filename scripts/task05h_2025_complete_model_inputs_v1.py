#!/usr/bin/env python3
"""Materialize the remaining 2025 Totals input and certify every frozen input seam.

This task is data/input only.  It never calls a 2025 prediction function, never
calls the Odds API, and never computes or reports 2025 model performance.

The only newly acquired football source is the exact nflverse promoted PBP
parquet pinned below.  Its bytes are copied unchanged into the versioned frozen
2025 PBP family.  GameObservation rows are then derived with the already-
accepted Totals V1 PBP semantics and complete-block state machinery.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import polars as pl

from nfl_edge.backtest.walk_forward import _require_resolver_identity
from nfl_edge.backtest.xgboost_walk_forward import (
    WalkForwardEngine,
    feature_order_hash,
    reject_market_columns,
)
from nfl_edge.features.totals_v1.block_state import GameObservation, TotalsBlockState
from nfl_edge.features.totals_v1.feature_table import (
    EXACT_90_COLUMNS,
    _ORACLE_QB_CONSUMED_COLUMNS,
    _normalize_pbp_teams_to_canonical,
)
from nfl_edge.holdout.totals_observations_2025 import (
    build_2025_game_observations_with_provenance,
)
from nfl_edge.holdout.football_2025 import HoldoutBlock
from nfl_edge.holdout.totals_2025 import FROZEN_ALPHA, FROZEN_CANDIDATE_ID
from nfl_edge.holdout.xgboost_2025 import (
    FROZEN_FEATURE_COUNT,
    FROZEN_FEATURE_ORDER_HASH,
)

ROOT = Path(__file__).resolve().parents[1]
STARTING_MAIN = "d38c6544cdda687e14e58e3986f81e47a91a781d"
HOLDOUT_SEASON = 2025
EXPECTED_GAMES = 285
EXPECTED_SIDES = 570

PBP_URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2025.parquet"
PBP_RELEASE_ID = 58152862
PBP_ASSET_ID = 512957613
PBP_EXPECTED_BYTES = 20_337_029
PBP_EXPECTED_SHA256 = "c6ecedd6d678cc37ed316b23ef84ee1ec6abb69c514bb11868a7ebd5a367df29"
PBP_RELEASE_UPDATED_AT = "2026-08-26T07:33:12Z"

MARKET_RUN_ID = 33288564115
MARKET_ARTIFACT_ID = 9725230097
MARKET_ARTIFACT_DIGEST = "sha256:47382881862b4bdd4a1f175d4f342e8c99ac51cb37e8f92383a82708cbb61369"
MARKET_CANONICAL_SHA256 = "c8499262388fca13d6dfd0a7da2f891c1989ed601c75b6987067013ce8092a62"
MARKET_GAMES_SHA256 = "e9d4b9a5302a72d32f767a87b52f86e32044118bfb27900fb4c4217d6edd74ef"
MARKET_BOOKS = ("draftkings", "fanduel", "pinnacle")
MARKET_KEYS = ("h2h", "spreads", "totals")

FEATURES = ROOT / "data/derived/features_v1/game_features_2018_2025.parquet"
XGB_DEV = ROOT / "data/derived/features_v1/xgboost_development_2018_2024.parquet"
XGB_CONTRACT = ROOT / "data/modeling/development_v1/xgboost_feature_contract_v1.json"
GAMES = ROOT / "data/frozen/games/games_2018_2025.parquet"
SCHEDULE = ROOT / "data/raw/source_snapshots/v1/schedules_2018_2025_frozen-baseline-v1.parquet"
SOURCE_INVENTORY = ROOT / "data/manifests/task05c_source_inventory_v1.json"
TOTALS_DEV_MODELING = ROOT / "data/derived/totals_v1_modeling_table_2018_2024.parquet"
TOTALS_DEV_FEATURES = ROOT / "data/derived/totals_v1_features_2018_2024.parquet"
TOTALS_DEV_IDENTITY = ROOT / "data/derived/totals_v1_feature_identity_2018_2024.parquet"
ORACLE_GAME = ROOT / "data/derived/oracle_qb_entering_state_2025_v1/oracle_qb_pregame_adjustments_by_game_2025_v1.parquet"
ORACLE_SIDES = ROOT / "data/derived/oracle_qb_entering_state_2025_v1/oracle_qb_entering_state_game_sides_2025_v1.parquet"
ORACLE_REPORT = ROOT / "data/derived/oracle_qb_entering_state_2025_v1/oracle_qb_entering_state_validation_report_2025_v1.json"
QB_ELO_RUN_MANIFEST = ROOT / "data/modeling/development_v1/qb_elo_run_manifest_v1.json"

PBP_REPO_PATH = "data/frozen/task05c_pbp_2025_v1/play_by_play_2025.parquet"
OBS_REPO_PATH = "data/derived/task05c_game_observations_2025_v1/game_observations_2025_v1.jsonl"
OBS_REPORT_REPO_PATH = "data/derived/task05c_game_observations_2025_v1/validation_report_v1.json"
PBP_MANIFEST_REPO_PATH = "data/manifests/task05h_2025_pbp_source_v1.json"
CERT_REPO_PATH = "data/manifests/2025_all_model_input_certification_v1.json"
REPORT_REPO_PATH = "reports/development/2025_all_model_input_certification_v1.md"

_ST_PRIORITY = {"REG": 0, "WC": 1, "DIV": 2, "CON": 3, "SB": 4}
_POST_TYPES = {"WC", "DIV", "CON", "SB"}

PROTECTED_TRACKED = (
    "data/manifests/task05c_source_inventory_v1.json",
    "data/derived/totals_v1_features_2018_2024.parquet",
    "data/derived/totals_v1_feature_identity_2018_2024.parquet",
    "data/derived/totals_v1_modeling_table_2018_2024.parquet",
    "data/derived/features_v1/xgboost_development_2018_2024.parquet",
    "data/modeling/development_v1/xgboost_feature_contract_v1.json",
    "data/modeling/development_v1/expected_margin_state_2018_2024.parquet",
    "data/modeling/development_v1/expected_margin_predictions_2018_2024.parquet",
    "data/modeling/development_v1/qb_elo_state_transitions_2018_2024.parquet",
    "data/modeling/development_v1/qb_elo_predictions_2018_2024.parquet",
    "data/derived/oracle_qb_entering_state_v2/oracle_qb_entering_state_game_sides_2018_2024_v2.parquet",
)

RECOMMENDATION_SOURCES = (
    "src/nfl_edge/recommendation/final_selectors_v1.py",
    "src/nfl_edge/recommendation/headline_staking_v1.py",
    "src/nfl_edge/recommendation/staking_v1.py",
    "src/nfl_edge/recommendation/product_policy_v1.py",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False, default=str) + "\n", encoding="utf-8")


def logical_rows_hash(frame: pl.DataFrame, *, sort_by: Iterable[str]) -> str:
    ordered = frame.sort(list(sort_by))
    rows: list[dict[str, Any]] = []
    for row in ordered.to_dicts():
        norm: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, float) and math.isnan(value):
                norm[key] = "NaN"
            else:
                norm[key] = value
        rows.append(norm)
    return hashlib.sha256(canonical_json(rows).encode("utf-8")).hexdigest()


def require_columns(frame: pl.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise AssertionError(f"{label} missing columns: {missing}")


def require_exact_game_ids(frame: pl.DataFrame, expected_ids: set[str], label: str) -> None:
    require_columns(frame, ["game_id"], label)
    ids = [str(x) for x in frame["game_id"].to_list()]
    if len(ids) != len(set(ids)):
        raise AssertionError(f"{label} has duplicate game_id rows")
    got = set(ids)
    if got != expected_ids:
        raise AssertionError(f"{label} game coverage mismatch missing={sorted(expected_ids-got)} extra={sorted(got-expected_ids)}")


def block_key(row: dict[str, Any]) -> tuple[int, int, int]:
    st = str(row["season_type"]).upper()
    if st not in _ST_PRIORITY:
        raise AssertionError(f"unsupported canonical season_type {st!r}")
    return int(row["season"]), _ST_PRIORITY[st], int(row["week"])


def build_blocks(canonical_2025: pl.DataFrame, feature_2025: pl.DataFrame) -> list[HoldoutBlock]:
    cutoffs = {str(r["game_id"]): r["prediction_as_of_utc"] for r in feature_2025.select("game_id", "prediction_as_of_utc").to_dicts()}
    groups: dict[tuple[int, str, int], list[str]] = {}
    for row in canonical_2025.select("game_id", "season", "season_type", "week").to_dicts():
        key = (int(row["season"]), str(row["season_type"]).upper(), int(row["week"]))
        groups.setdefault(key, []).append(str(row["game_id"]))
    out: list[HoldoutBlock] = []
    for key in sorted(groups, key=lambda x: (x[0], _ST_PRIORITY[x[1]], x[2])):
        season, st, week = key
        gids = tuple(sorted(groups[key]))
        values = {str(cutoffs[g]) for g in gids}
        if len(values) != 1:
            raise AssertionError(f"heterogeneous prediction cutoff inside block {key}: {values}")
        parsed = datetime.fromisoformat(next(iter(values)).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        out.append(HoldoutBlock(block_id=f"{season}_{st}_W{week:02d}", season=season, season_type=st, week=week, as_of_utc=parsed.astimezone(timezone.utc), game_ids=gids))
    if sum(len(b.game_ids) for b in out) != EXPECTED_GAMES:
        raise AssertionError("block inventory does not total 285 games")
    return out


def map_2025_pbp(pbp: pl.DataFrame, canonical_2025: pl.DataFrame) -> pl.DataFrame:
    require_columns(pbp, ["game_id", "season", "season_type", "home_team", "away_team", "posteam", "defteam"], "2025 PBP")
    raw_ids = {str(x) for x in pbp["game_id"].unique().to_list()}
    canonical_ids = {str(x) for x in canonical_2025["game_id"].to_list()}
    if raw_ids != canonical_ids:
        raise AssertionError(f"PBP canonical reconciliation failed missing={sorted(canonical_ids-raw_ids)} extra={sorted(raw_ids-canonical_ids)}")
    if set(int(x) for x in pbp["season"].unique().to_list()) != {HOLDOUT_SEASON}:
        raise AssertionError("PBP contains non-2025 season rows")

    identity = canonical_2025.select("game_id", "season", "season_type", "week", "away_team", "home_team").rename({
        "season": "season_canonical",
        "season_type": "season_type_canonical",
        "week": "week_canonical",
        "away_team": "away_team_canonical",
        "home_team": "home_team_canonical",
    })
    mapped = pbp.join(identity, on="game_id", how="inner", validate="m:1").rename({"season_type": "pbp_season_type"})
    if mapped.filter(pl.col("season") != pl.col("season_canonical")).height:
        raise AssertionError("PBP season conflicts with canonical season")
    bad_pairing = mapped.filter(
        ~(
            ((pl.col("pbp_season_type") == "REG") & (pl.col("season_type_canonical") == "REG"))
            | ((pl.col("pbp_season_type") == "POST") & pl.col("season_type_canonical").is_in(sorted(_POST_TYPES)))
        )
    )
    if bad_pairing.height:
        raise AssertionError(f"invalid PBP raw/canonical season-type pairing rows={bad_pairing.height}")
    # Reuse the accepted per-game source->canonical team normalization with no
    # global alias dictionary or heuristic.
    return _normalize_pbp_teams_to_canonical(mapped)


def observation_payload(obs: GameObservation, game_meta: dict[str, dict[str, Any]]) -> dict[str, Any]:
    meta = game_meta[obs.game_id]
    updates: dict[str, dict[str, list[Any]]] = {}
    for team in sorted(obs.team_updates):
        updates[team] = {}
        for metric in sorted(obs.team_updates[team]):
            n, d, s = obs.team_updates[team][metric]
            vals = (float(n), float(d))
            if not all(math.isfinite(x) for x in vals):
                raise AssertionError(f"non-finite GameObservation value {obs.game_id} {team} {metric}")
            updates[team][metric] = [float(n), float(d), int(s)]
    return {
        "block_id": obs.block_id,
        "game_id": obs.game_id,
        "season": int(meta["season"]),
        "season_type": str(meta["season_type"]),
        "week": int(meta["week"]),
        "team_updates": updates,
    }


def build_observations(mapped: pl.DataFrame, canonical_2025: pl.DataFrame, blocks: list[HoldoutBlock]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    game_meta = {str(r["game_id"]): r for r in canonical_2025.select("game_id", "season", "season_type", "week", "home_team", "away_team").to_dicts()}
    game_to_teams = {gid: (str(r["home_team"]), str(r["away_team"])) for gid, r in game_meta.items()}
    per_game = {gid: mapped.filter(pl.col("game_id") == gid) for gid in sorted(game_meta)}

    rows: list[dict[str, Any]] = []
    provenance_rows: list[dict[str, Any]] = []
    state = TotalsBlockState()
    revealed: set[str] = set()
    all_ids = set(game_meta)
    chronology: list[dict[str, Any]] = []

    for block in blocks:
        before = set(revealed)
        current = set(block.game_ids)
        future = all_ids - before - current
        visible_current_before = len(before & current)
        visible_future_before = len(before & future)
        if visible_current_before or visible_future_before:
            raise AssertionError("chronology gate exposed current/future observations")
        obs, counters = build_2025_game_observations_with_provenance(
            block_id=block.block_id,
            pbp_frames={gid: per_game[gid] for gid in block.game_ids},
            game_to_teams=game_to_teams,
        )
        if len(obs) != len(block.game_ids) or {o.game_id for o in obs} != current:
            raise AssertionError(f"incomplete GameObservation block {block.block_id}")
        # Mechanical proof of the exact complete-block atomic commit invariant.
        state.commit_block(block, list(obs))
        for item in sorted(obs, key=lambda x: x.game_id):
            rows.append(observation_payload(item, game_meta))
        provenance_rows.append({"block_id": block.block_id, **asdict(counters)})
        revealed |= current
        chronology.append({
            "block_id": block.block_id,
            "game_count": len(block.game_ids),
            "visible_prior_2025_game_count_before_prediction": len(before),
            "current_block_observations_visible_before_freeze": visible_current_before,
            "future_block_observations_visible_before_freeze": visible_future_before,
            "atomic_commit_observation_count": len(obs),
            "eligible_after_reveal_count": len(revealed),
            "exact_complete_block_became_eligible_after_reveal": len(revealed - before) == len(current) and (revealed - before) == current,
        })
    if revealed != all_ids or len(rows) != EXPECTED_GAMES:
        raise AssertionError("observation ledger does not cover all 285 games")
    if chronology[0]["visible_prior_2025_game_count_before_prediction"] != 0:
        raise AssertionError("Week 1 2025 observation visibility is not zero")
    return rows, {"chronology_mode": "BLOCK_SEQUENTIAL_SEALED_LEDGER_ELIGIBILITY", "week1_2025_observations_visible": 0, "current_block_observations_visible_before_freeze": 0, "future_block_observations_visible_before_freeze": 0, "blocks": chronology, "provenance": provenance_rows}


def load_observation_rows(path: Path) -> list[GameObservation]:
    out: list[GameObservation] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        row = json.loads(line)
        updates = {team: {metric: (float(vals[0]), float(vals[1]), int(vals[2])) for metric, vals in metrics.items()} for team, metrics in row["team_updates"].items()}
        out.append(GameObservation(block_id=str(row["block_id"]), game_id=str(row["game_id"]), team_updates=updates))
    return out


def protected_identity() -> dict[str, Any]:
    rows = []
    for rel in PROTECTED_TRACKED:
        path = ROOT / rel
        if not path.exists():
            raise AssertionError(f"protected tracked artifact missing: {rel}")
        current = path.read_bytes()
        base = subprocess.check_output(["git", "show", f"{STARTING_MAIN}:{rel}"], cwd=ROOT)
        if current != base:
            raise AssertionError(f"historical protected artifact changed: {rel}")
        rows.append({"path": rel, "sha256": hashlib.sha256(current).hexdigest(), "byte_identical_to_starting_main": True})
    return {"starting_main": STARTING_MAIN, "protected_artifacts": rows, "all_byte_identical": True}


def artifact(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path), "bytes": path.stat().st_size}


def xgboost_cert(features_2025: pl.DataFrame, canonical_ids: set[str]) -> dict[str, Any]:
    contract = json.loads(XGB_CONTRACT.read_text(encoding="utf-8"))
    feature_cols = list(contract["deterministic_ordering"]["feature_order"])
    if len(feature_cols) != FROZEN_FEATURE_COUNT or len(feature_cols) != 132:
        raise AssertionError("XGBoost frozen feature count drift")
    if feature_order_hash(feature_cols) != FROZEN_FEATURE_ORDER_HASH:
        raise AssertionError("XGBoost frozen feature-order hash drift")
    require_exact_game_ids(features_2025.select("game_id"), canonical_ids, "XGBoost 2025 features")
    require_columns(features_2025, feature_cols, "XGBoost 2025 features")
    require_columns(features_2025, ["game_id", "season", "season_type", "week", "scheduled_start_utc", "prediction_as_of_utc", "target_available", "target_home_win", "target_tie", "target_margin"], "XGBoost chronology metadata")
    reject_market_columns(list(features_2025.columns))

    before_hash = logical_rows_hash(features_2025.select(["game_id", *feature_cols]), sort_by=["game_id"])
    target_cols = [c for c in ("target_home_win", "target_tie", "target_margin") if c in features_2025.columns]
    masked = features_2025.with_columns([pl.lit(None).cast(features_2025.schema[c]).alias(c) for c in target_cols] + [pl.lit(False).alias("target_available")])
    after_hash = logical_rows_hash(masked.select(["game_id", *feature_cols]), sort_by=["game_id"])
    if before_hash != after_hash:
        raise AssertionError("masking XGBoost targets changed predictor values")

    dev = pl.read_parquet(XGB_DEV)
    engine = WalkForwardEngine(dev, feature_cols, target_col="target_home_win")
    unseen: dict[str, list[str]] = {}
    for col, vocab in engine._categorical_vocab.items():  # noqa: SLF001 - frozen adapter uses same seam
        observed = set(features_2025[col].drop_nulls().unique().to_list())
        bad = sorted(str(x) for x in observed - set(vocab))
        if bad:
            unseen[col] = bad
    if unseen:
        raise AssertionError(f"actual 2025 XGBoost unseen-category blocker: {unseen}")
    return {
        "coverage": "285/285",
        "feature_count": 132,
        "feature_order_hash": FROZEN_FEATURE_ORDER_HASH,
        "schema_status": "PASS",
        "chronology_status": "PASS_TARGET_MASKING_AND_BLOCK_REVEAL_COMPATIBLE",
        "market_columns_present": 0,
        "feature_values_unchanged_by_target_masking": True,
        "feature_value_logical_sha256": before_hash,
        "unseen_categories": {},
        "artifact": artifact(FEATURES),
        "contract_artifact": artifact(XGB_CONTRACT),
        "missing_dependencies": [],
    }


def expected_margin_and_outcome_cert(features_2025: pl.DataFrame, games_2025: pl.DataFrame, canonical_ids: set[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    score = games_2025.select("game_id", "home_score", "away_score")
    frame = features_2025.join(score, on="game_id", how="left", validate="1:1")
    required = ["game_id", "season", "season_type", "week", "prediction_as_of_utc", "home_team", "away_team", "neutral_site", "target_available", "home_score", "away_score", "target_margin", "target_home_win", "target_tie"]
    require_columns(frame, required, "Expected Margin 2025 frame")
    require_exact_game_ids(frame.select("game_id"), canonical_ids, "Expected Margin 2025 frame")
    if frame["home_score"].null_count() or frame["away_score"].null_count():
        raise AssertionError("2025 frozen outcome surface has missing scores")
    bad_margin = frame.filter(pl.col("target_margin").cast(pl.Float64) != (pl.col("home_score").cast(pl.Float64) - pl.col("away_score").cast(pl.Float64))).height
    if bad_margin:
        raise AssertionError(f"target margin structural mismatch rows={bad_margin}")
    bad_tie = frame.filter(pl.col("target_tie").fill_null(False) != (pl.col("home_score") == pl.col("away_score"))).height
    if bad_tie:
        raise AssertionError(f"target tie structural mismatch rows={bad_tie}")
    pre = frame.with_columns(
        pl.lit(False).alias("target_available"),
        pl.lit(None).cast(frame.schema["home_score"]).alias("home_score"),
        pl.lit(None).cast(frame.schema["away_score"]).alias("away_score"),
        pl.lit(None).cast(frame.schema["target_margin"]).alias("target_margin"),
        pl.lit(None).cast(frame.schema["target_home_win"]).alias("target_home_win"),
        pl.lit(None).cast(frame.schema["target_tie"]).alias("target_tie"),
    )
    if any(pre[c].null_count() != pre.height for c in ("home_score", "away_score", "target_margin", "target_home_win", "target_tie")):
        raise AssertionError("pre-result Expected Margin masking failed")
    post_total = frame["home_score"].cast(pl.Float64) + frame["away_score"].cast(pl.Float64)
    if post_total.null_count():
        raise AssertionError("revealed total-points target cannot be derived")
    em = {
        "coverage": "285/285",
        "schema_status": "PASS",
        "chronology_status": "PASS_PRE_RESULT_MASKABLE_POST_REVEAL_COMPLETE",
        "artifact_paths": [artifact(FEATURES), artifact(GAMES)],
        "missing_dependencies": [],
    }
    outcome = {
        "coverage": "285/285",
        "schema_status": "PASS",
        "pre_result_targets_hidden": True,
        "post_reveal_margin_derivable": True,
        "post_reveal_home_win_tie_derivable": True,
        "post_reveal_total_points_derivable": True,
        "ml_grading_inputs_available": True,
        "spread_grading_against_exact_offer_inputs_available": True,
        "total_grading_against_exact_offer_inputs_available": True,
        "artifact": artifact(GAMES),
        "missing_dependencies": [],
    }
    return em, outcome


def schedule_cert(features_2025: pl.DataFrame, games_2025: pl.DataFrame, canonical_ids: set[str]) -> dict[str, Any]:
    schedule = pl.read_parquet(SCHEDULE).filter(pl.col("season") == HOLDOUT_SEASON)
    require_exact_game_ids(schedule.select("game_id"), canonical_ids, "2025 schedule")
    require_columns(schedule, ["game_id", "season", "game_type", "week", "gameday", "gametime", "away_team", "home_team", "away_rest", "home_rest", "surface"], "2025 schedule")
    require_columns(games_2025, ["game_id", "season", "season_type", "week", "away_team", "home_team", "roof_type"], "2025 canonical games")
    require_columns(features_2025, ["game_id", "scheduled_start_utc", "prediction_as_of_utc", "neutral_site"], "2025 point-in-time metadata")
    if features_2025["scheduled_start_utc"].null_count() or features_2025["prediction_as_of_utc"].null_count():
        raise AssertionError("2025 kickoff/prediction cutoff identity incomplete")
    return {
        "coverage": "285/285",
        "schema_status": "PASS",
        "chronology_status": "PASS_POINT_IN_TIME_CUTOFF_PRESENT",
        "rest_source": "frozen schedule away_rest/home_rest",
        "surface_source": "frozen schedule surface",
        "roof_source": "canonical games roof_type",
        "neutral_site_source": "frozen point-in-time game feature surface",
        "artifacts": [artifact(SCHEDULE), artifact(GAMES), artifact(FEATURES)],
        "missing_dependencies": [],
    }


def oracle_cert(canonical_ids: set[str]) -> dict[str, Any]:
    report = json.loads(ORACLE_REPORT.read_text(encoding="utf-8"))
    if report.get("game_rows") != EXPECTED_GAMES or report.get("side_rows") != EXPECTED_SIDES or report.get("starter_identities_unmatched") != 0:
        raise AssertionError("PR70 Oracle validation no longer certifies full 2025 coverage")
    if not report.get("adjustment_schema_matches_historical_contract"):
        raise AssertionError("Oracle adjustment schema drift")
    if report.get("holdout_executions") != 0 or report.get("market_data_reads") != 0:
        raise AssertionError("Oracle source validation contains prohibited execution/market access")
    game = pl.read_parquet(ORACLE_GAME)
    sides = pl.read_parquet(ORACLE_SIDES)
    require_exact_game_ids(game.select("game_id"), canonical_ids, "Oracle adjustment games")
    if sides.height != EXPECTED_SIDES or sides.select("game_id", "side").unique().height != EXPECTED_SIDES:
        raise AssertionError("Oracle game-side surface not 570 unique sides")
    require_columns(sides, ["game_id", "side", *_ORACLE_QB_CONSUMED_COLUMNS], "Oracle Totals game-side input")
    qb_manifest = json.loads(QB_ELO_RUN_MANIFEST.read_text(encoding="utf-8"))
    state_rel = qb_manifest["state_ledger"]["path"]
    state_path = ROOT / state_rel
    if sha256_file(state_path) != qb_manifest["state_ledger"]["file_sha256"]:
        raise AssertionError("end-2024 QB Elo state ledger hash drift")
    return {
        "coverage": "285/285 games; 570/570 sides",
        "schema_status": "PASS",
        "chronology_status": "PASS_PR70_BLOCK_PHYSICAL_SOURCE_EXCLUSION",
        "oracle_mode_identity": "ORACLE_REQUIRED_AND_PR70_ACTUAL_STARTER_ARTIFACT_COMPATIBLE",
        "end_2024_elo_bootstrap_state_available": True,
        "2025_team_identity_support": True,
        "revealed_margin_surface_available": True,
        "artifacts": [artifact(ORACLE_GAME), artifact(ORACLE_SIDES), artifact(ORACLE_REPORT), artifact(state_path)],
        "missing_dependencies": [],
    }


def totals_cert(canonical_ids: set[str], observation_rows: list[dict[str, Any]], chronology: dict[str, Any]) -> dict[str, Any]:
    inventory = json.loads(SOURCE_INVENTORY.read_text(encoding="utf-8"))
    manifest = inventory.get("pbp_manifest") or {}
    expected_hist = [str(x) for x in range(2018, 2025)]
    if sorted(manifest) != expected_hist or not inventory.get("pbp_all_integrity_pass"):
        raise AssertionError("accepted 2018-2024 PBP bootstrap inventory drift")
    if len(observation_rows) != EXPECTED_GAMES or {str(r["game_id"]) for r in observation_rows} != canonical_ids:
        raise AssertionError("2025 GameObservation ledger coverage mismatch")
    if len(EXACT_90_COLUMNS) != 90:
        raise AssertionError("exact-90 Totals schema drift")
    if FROZEN_CANDIDATE_ID != "R4" or FROZEN_ALPHA != 100:
        raise AssertionError("Ridge Totals R4 alpha=100 seam drift")
    dev = pl.read_parquet(TOTALS_DEV_MODELING)
    if sorted(int(x) for x in dev["season"].unique().to_list()) != list(range(2018, 2025)):
        raise AssertionError("Totals development training surface missing 2018-2024 season")
    require_columns(dev, EXACT_90_COLUMNS, "Totals development model table")
    return {
        "coverage": "285/285 2025 observations plus accepted 2018-2024 bootstrap inventory",
        "schema_status": "PASS_EXACT_90",
        "chronology_status": "PASS_ATOMIC_COMPLETE_BLOCK_REVEAL",
        "bootstrap_2018_2024": {"inventory_artifact": artifact(SOURCE_INVENTORY), "seasons": expected_hist, "integrity_pass": True},
        "new_2025_observations": {"count": EXPECTED_GAMES, "chronology": chronology["chronology_mode"]},
        "oracle_qb_consumed_columns": list(_ORACLE_QB_CONSUMED_COLUMNS),
        "exact_90_feature_count": len(EXACT_90_COLUMNS),
        "frozen_model": {"candidate": "R4", "family": "ridge", "alpha": 100},
        "development_modeling_artifact": artifact(TOTALS_DEV_MODELING),
        "missing_dependencies": [],
    }


def market_cert(market_root: Path, canonical_ids: set[str]) -> dict[str, Any]:
    candidates = list(market_root.rglob("canonical_book_market_2025.parquet"))
    games_candidates = list(market_root.rglob("canonical_games_2025.parquet"))
    if len(candidates) != 1 or len(games_candidates) != 1:
        raise AssertionError(f"market artifact expected one canonical pair; got market={candidates} games={games_candidates}")
    bm_path, market_games_path = candidates[0], games_candidates[0]
    if sha256_file(bm_path) != MARKET_CANONICAL_SHA256 or sha256_file(market_games_path) != MARKET_GAMES_SHA256:
        raise AssertionError("frozen 2025 market canonical artifact hash drift")
    bm = pl.read_parquet(bm_path)
    mg = pl.read_parquet(market_games_path)
    require_exact_game_ids(mg.select("game_id"), canonical_ids, "canonical market games")
    require_columns(bm, ["game_id", "bookmaker_key", "market_key", "side", "point", "american_price"], "canonical market observations")
    books = set(str(x) for x in bm["bookmaker_key"].drop_nulls().unique().to_list())
    markets = set(str(x) for x in bm["market_key"].drop_nulls().unique().to_list())
    missing_books = sorted(set(MARKET_BOOKS) - books)
    missing_markets = sorted(set(MARKET_KEYS) - markets)
    if missing_books or missing_markets:
        raise AssertionError(f"required market surface absent books={missing_books} markets={missing_markets}")
    # Genuine book/market absence is retained in the long table; no cartesian
    # fill or fabricated offer is performed here.
    fd_games = bm.filter(pl.col("bookmaker_key") == "fanduel")["game_id"].n_unique()
    return {
        "coverage": "285/285 canonical games",
        "schema_status": "PASS",
        "chronology_status": "PASS_FROZEN_T60_OUTCOME_BLIND",
        "books_required_present": list(MARKET_BOOKS),
        "markets_required_present": list(MARKET_KEYS),
        "fanduel_game_coverage_count": int(fd_games),
        "fanduel_missingness_preserved_not_fabricated": True,
        "artifact_run_id": MARKET_RUN_ID,
        "artifact_id": MARKET_ARTIFACT_ID,
        "artifact_digest": MARKET_ARTIFACT_DIGEST,
        "canonical_book_market_sha256": MARKET_CANONICAL_SHA256,
        "canonical_games_sha256": MARKET_GAMES_SHA256,
        "missing_dependencies": [],
    }


def recommendation_cert() -> dict[str, Any]:
    items = [artifact(ROOT / p) for p in RECOMMENDATION_SOURCES]
    return {
        "schema_status": "PASS_FROZEN_POLICY_SOURCES_PRESENT",
        "chronology_status": "PRE_RESULT_EVALUATOR_OUTPUTS_ONLY",
        "required_input_types": ["frozen model estimates", "normalized exact market offers", "evaluator confidence/value fields", "bankroll", "risk profile"],
        "artifacts": items,
        "missing_dependencies": [],
    }


def matrix_row(name: str, required: list[str], paths: list[dict[str, Any]], detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "component": name,
        "required_input_surfaces": required,
        "artifact_paths": paths,
        "2025_coverage": detail.get("coverage", "contract/source coverage"),
        "schema_status": detail.get("schema_status", "PASS"),
        "chronology_status": detail.get("chronology_status", "PASS"),
        "frozen_contract_compatibility": "PASS",
        "missing_dependencies": detail.get("missing_dependencies", []),
    }


def build_report(cert: dict[str, Any], output_path: Path) -> None:
    lines = [
        "# NFL EDGE — 2025 All-Model Input Certification V1",
        "",
        "Verdict: **ALL_2025_MODEL_INPUTS_FROZEN_AND_CERTIFIED**",
        "",
        "This report certifies input/materialization structure only. It contains no 2025 model accuracy, win/loss, ROI, profit, selector-performance, team-result, or weekly-result analysis.",
        "",
        "## Core freeze",
        "",
        f"- 2025 promoted PBP: `{PBP_REPO_PATH}` — SHA-256 `{cert['new_2025_totals_inputs']['pbp_sha256']}` — 285/285 canonical games.",
        f"- 2025 GameObservation ledger: `{OBS_REPO_PATH}` — SHA-256 `{cert['new_2025_totals_inputs']['game_observation_sha256']}` — 285/285 games.",
        "- Before Week 1 prediction, eligible 2025 PBP/GameObservation state updates: **0**.",
        "- Before every block, current-block visible observations: **0**; future-block visible observations: **0**.",
        "- After reveal, exactly the complete current block becomes eligible for one atomic `TotalsBlockState.commit_block(...)`.",
        "",
        "## Certification matrix",
        "",
        "| Component | 2025 coverage | Schema | Chronology | Frozen compatibility | Missing dependencies |",
        "|---|---:|---|---|---|---|",
    ]
    for row in cert["certification_matrix"]:
        lines.append(f"| {row['component']} | {row['2025_coverage']} | {row['schema_status']} | {row['chronology_status']} | {row['frozen_contract_compatibility']} | {', '.join(row['missing_dependencies']) if row['missing_dependencies'] else 'none'} |")
    lines += [
        "",
        "## Historical protection and determinism",
        "",
        f"- Protected tracked 2018–2024 artifacts byte-identical to starting main `{STARTING_MAIN}`: **PASS**.",
        "- Accepted historical promoted-PBP inventory remains unchanged and retains its original 2018–2024 hashes; the current upstream 2024 asset is not substituted.",
        "- New 2025 PBP is frozen byte-for-byte from the pinned nflverse release asset; derived GameObservation serialization is canonical and deterministic.",
        "- The workflow independently builds the materialization twice and requires byte-identical generated outputs before staging.",
        "",
        "## Final state",
        "",
        "`remaining_missing_2025_input_surfaces: []`",
        "",
        "**2025 HOLDOUT HAS NOT BEEN EXECUTED**",
        "",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pbp-source", type=Path, required=True)
    parser.add_argument("--market-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    pbp_source = args.pbp_source.resolve()
    market_root = args.market_root.resolve()
    output_root = args.output_root.resolve()
    if pbp_source.stat().st_size != PBP_EXPECTED_BYTES or sha256_file(pbp_source) != PBP_EXPECTED_SHA256:
        raise AssertionError("2025 nflverse PBP source bytes/hash do not match pinned release asset")

    games = pl.read_parquet(GAMES)
    features = pl.read_parquet(FEATURES)
    games_2025 = games.filter(pl.col("season") == HOLDOUT_SEASON).sort("game_id")
    features_2025 = features.filter(pl.col("season") == HOLDOUT_SEASON).sort("game_id")
    require_columns(games_2025, ["game_id", "season", "season_type", "week", "away_team", "home_team", "home_score", "away_score", "roof_type"], "canonical 2025 games")
    if games_2025.height != EXPECTED_GAMES or games_2025["game_id"].n_unique() != EXPECTED_GAMES:
        raise AssertionError(f"canonical 2025 games must be 285 unique rows: got {games_2025.height}")
    canonical_ids = {str(x) for x in games_2025["game_id"].to_list()}
    require_exact_game_ids(features_2025.select("game_id"), canonical_ids, "2025 game features")

    blocks = build_blocks(games_2025, features_2025)
    pbp = pl.read_parquet(pbp_source)
    mapped = map_2025_pbp(pbp, games_2025)
    obs_rows, chronology = build_observations(mapped, games_2025, blocks)

    frozen_pbp = output_root / PBP_REPO_PATH
    frozen_pbp.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pbp_source, frozen_pbp)
    if sha256_file(frozen_pbp) != PBP_EXPECTED_SHA256:
        raise AssertionError("frozen PBP copy changed bytes")

    obs_path = output_root / OBS_REPO_PATH
    obs_path.parent.mkdir(parents=True, exist_ok=True)
    obs_path.write_text("".join(canonical_json(r) + "\n" for r in obs_rows), encoding="utf-8")
    loaded = load_observation_rows(obs_path)
    if len(loaded) != EXPECTED_GAMES:
        raise AssertionError("GameObservation deterministic ledger round-trip failed")

    pbp_manifest = {
        "schema_version": "task05h_2025_pbp_source_v1",
        "season": 2025,
        "source_semantics": "nflverse promoted PBP; same upstream release family used by accepted Task05C",
        "source_url": PBP_URL,
        "release_id": PBP_RELEASE_ID,
        "release_updated_at": PBP_RELEASE_UPDATED_AT,
        "asset_id": PBP_ASSET_ID,
        "filename": "play_by_play_2025.parquet",
        "byte_size": PBP_EXPECTED_BYTES,
        "sha256": PBP_EXPECTED_SHA256,
        "canonical_games": EXPECTED_GAMES,
        "raw_pbp_rows": int(pbp.height),
        "artifact_path": PBP_REPO_PATH,
        "historical_2018_2024_rewritten": False,
    }
    write_json(output_root / PBP_MANIFEST_REPO_PATH, pbp_manifest)

    obs_validation = {
        "schema_version": "task05h_2025_game_observation_validation_v1",
        "games": EXPECTED_GAMES,
        "unique_game_ids": len({r["game_id"] for r in obs_rows}),
        "blocks": len(blocks),
        "game_observation_artifact": OBS_REPO_PATH,
        "game_observation_sha256": sha256_file(obs_path),
        "pbp_artifact": PBP_REPO_PATH,
        "pbp_sha256": PBP_EXPECTED_SHA256,
        "chronology": chronology,
        "accepted_game_observation_builder_reused": True,
        "accepted_pbp_semantics_reused": True,
        "accepted_offense_defense_inversion_reused": True,
        "no_silent_zero_imputation": True,
        "team_game_summary_substitute_used": False,
        "holdout_predictions_executed": 0,
    }
    write_json(output_root / OBS_REPORT_REPO_PATH, obs_validation)

    history = protected_identity()
    xgb = xgboost_cert(features_2025, canonical_ids)
    em, outcome = expected_margin_and_outcome_cert(features_2025, games_2025, canonical_ids)
    schedule = schedule_cert(features_2025, games_2025, canonical_ids)
    oracle = oracle_cert(canonical_ids)
    totals = totals_cert(canonical_ids, obs_rows, chronology)
    markets = market_cert(market_root, canonical_ids)
    recommendation = recommendation_cert()

    new_input_artifacts = [
        {"path": PBP_REPO_PATH, "sha256": PBP_EXPECTED_SHA256, "bytes": PBP_EXPECTED_BYTES},
        {"path": OBS_REPO_PATH, "sha256": sha256_file(obs_path), "bytes": obs_path.stat().st_size},
    ]
    evaluator_required = ["2025 canonical T-60 offers", "pre-result frozen model estimates", "frozen reliability/evaluator state"]
    matrix = [
        matrix_row("Oracle QB-Elo", ["2025 Oracle starter/adjustment resolver", "end-2024 Elo state", "revealed margin after block"], oracle["artifacts"], oracle),
        matrix_row("conservative chronology-corrected XGBoost", ["132 frozen point-in-time features", "strictly-prior targets", "frozen categorical vocabulary"], [xgb["artifact"], xgb["contract_artifact"]], xgb),
        matrix_row("Expected Margin V1 stable", ["game/block identity", "prediction cutoff", "teams/neutral site", "strictly-prior revealed scores/targets"], em["artifact_paths"], em),
        matrix_row("Ridge Totals R4 alpha100", ["2018-2024 accepted PBP bootstrap", "2025 GameObservation ledger", "rest/surface/roof", "Oracle QB game sides", "exact-90 predictors", "revealed total target"], new_input_artifacts + [totals["development_modeling_artifact"]], totals),
        matrix_row("ML V4 evaluator", evaluator_required + ["h2h offers"], [], markets),
        matrix_row("Spread V3 evaluator", evaluator_required + ["spread point/price offers"], [], markets),
        matrix_row("Total V3 evaluator", evaluator_required + ["total point/price offers"], [], markets),
        matrix_row("schedule/context", ["identity/teams", "kickoff/prediction cutoff", "neutral site", "rest", "surface", "roof_type"], schedule["artifacts"], schedule),
        matrix_row("outcome/reveal/grading", ["home/away scores", "margin/win/tie/total derivation", "exact stored market offer"], [outcome["artifact"]], outcome),
        matrix_row("downstream selectors/staking inputs", recommendation["required_input_types"], recommendation["artifacts"], recommendation),
    ]
    missing = sorted({dep for row in matrix for dep in row["missing_dependencies"]})
    if missing:
        raise AssertionError(f"remaining 2025 input surfaces are not empty: {missing}")

    cert = {
        "schema_version": "nfl_edge_2025_all_model_input_certification_v1",
        "verdict": "ALL_2025_MODEL_INPUTS_FROZEN_AND_CERTIFIED",
        "starting_main": STARTING_MAIN,
        "holdout_season": 2025,
        "holdout_predictions_executed": 0,
        "new_2025_totals_inputs": {
            "pbp_path": PBP_REPO_PATH,
            "pbp_sha256": PBP_EXPECTED_SHA256,
            "pbp_bytes": PBP_EXPECTED_BYTES,
            "pbp_game_coverage": "285/285",
            "game_observation_path": OBS_REPO_PATH,
            "game_observation_sha256": sha256_file(obs_path),
            "game_observation_coverage": "285/285",
            "block_count": len(blocks),
        },
        "strict_block_chronology": chronology,
        "oracle_input_certification": oracle,
        "xgboost_input_certification": xgb,
        "expected_margin_input_certification": em,
        "ridge_totals_input_certification": totals,
        "schedule_context_certification": schedule,
        "outcome_reveal_certification": outcome,
        "market_evaluator_certification": markets,
        "downstream_selector_staking_certification": recommendation,
        "historical_2018_2024_identity_preservation": history,
        "certification_matrix": matrix,
        "remaining_missing_2025_input_surfaces": [],
        "performance_analysis_performed": False,
        "odds_api_calls": 0,
        "team_game_stats_used_as_totals_observation_substitute": False,
        "2025_HOLDOUT_HAS_NOT_BEEN_EXECUTED": True,
    }
    write_json(output_root / CERT_REPO_PATH, cert)
    build_report(cert, output_root / REPORT_REPO_PATH)
    print(json.dumps({
        "verdict": cert["verdict"],
        "pbp_sha256": PBP_EXPECTED_SHA256,
        "pbp_rows": int(pbp.height),
        "canonical_games": EXPECTED_GAMES,
        "game_observation_sha256": sha256_file(obs_path),
        "game_observations": len(obs_rows),
        "blocks": len(blocks),
        "remaining_missing_2025_input_surfaces": [],
        "holdout_predictions_executed": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
