#!/usr/bin/env python3
"""Task05H corrected all-model input certification driver.

The underlying Task05H materializer remains unchanged.  This driver replaces
only certification hooks whose authoritative input is split across accepted
source tables:

* XGBoost uses the exact Task03C game-features + candidate-rank-1 QB join.
* Kickoff/context uses frozen-schedule ``gameday``/``gametime`` for kickoff
  identity and game features for the point-in-time prediction cutoff.

No prediction function is called.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import polars as pl

from nfl_edge.holdout.xgboost_inputs_2025 import (
    assemble_candidate1_xgboost_surface,
    assert_development_assembly_parity,
)
from nfl_edge.market_data.kickoffs import gameday_gametime_to_utc

ROOT = Path(__file__).resolve().parents[1]
BASE_SCRIPT = ROOT / "scripts" / "task05h_2025_complete_model_inputs_v1.py"
QB_FEATURES = ROOT / "data" / "derived" / "features_v1" / "qb_pregame_features_2018_2025.parquet"


def _load_base():
    spec = importlib.util.spec_from_file_location("task05h_base", BASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {BASE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _build_xgboost_certifier(task):
    def xgboost_cert(features_2025: pl.DataFrame, canonical_ids: set[str]) -> dict[str, Any]:
        contract = json.loads(task.XGB_CONTRACT.read_text(encoding="utf-8"))
        feature_cols = list(contract["deterministic_ordering"]["feature_order"])
        if len(feature_cols) != task.FROZEN_FEATURE_COUNT or len(feature_cols) != 132:
            raise AssertionError("XGBoost frozen feature count drift")
        if task.feature_order_hash(feature_cols) != task.FROZEN_FEATURE_ORDER_HASH:
            raise AssertionError("XGBoost frozen feature-order hash drift")

        all_game_features = pl.read_parquet(task.FEATURES)
        all_qb_features = pl.read_parquet(QB_FEATURES)
        frozen_dev = pl.read_parquet(task.XGB_DEV)
        parity_sha = assert_development_assembly_parity(
            all_game_features,
            all_qb_features,
            frozen_dev,
            feature_cols,
        )

        combined = assemble_candidate1_xgboost_surface(
            features_2025,
            all_qb_features,
            season_min=task.HOLDOUT_SEASON,
            season_max=task.HOLDOUT_SEASON,
        )
        task.require_exact_game_ids(combined.select("game_id"), canonical_ids, "XGBoost 2025 assembled features")
        task.require_columns(combined, feature_cols, "XGBoost 2025 assembled features")
        task.require_columns(
            combined,
            [
                "game_id", "season", "season_type", "week", "scheduled_start_utc",
                "prediction_as_of_utc", "target_available", "target_home_win",
                "target_tie", "target_margin",
            ],
            "XGBoost chronology metadata",
        )
        task.reject_market_columns(list(combined.columns))

        qb_2025 = all_qb_features.filter(
            (pl.col("season") == task.HOLDOUT_SEASON) & (pl.col("candidate_rank") == 1)
        )
        task.require_columns(
            qb_2025,
            ["game_id", "side", "candidate_rank", "feature_as_of_utc", "source_available_at_utc"],
            "XGBoost 2025 QB chronology",
        )
        if qb_2025.height != task.EXPECTED_SIDES:
            raise AssertionError(f"XGBoost 2025 QB candidate-rank-1 coverage must be 570 rows: {qb_2025.height}")
        if qb_2025.select("game_id", "side").unique().height != task.EXPECTED_SIDES:
            raise AssertionError("XGBoost 2025 QB candidate-rank-1 game/side identity is not unique")
        cutoffs = features_2025.select("game_id", "prediction_as_of_utc")
        qb_timing = qb_2025.join(cutoffs, on="game_id", how="left", validate="m:1")
        if qb_timing.filter(pl.col("feature_as_of_utc") != pl.col("prediction_as_of_utc")).height:
            raise AssertionError("XGBoost 2025 QB feature cutoff differs from game prediction cutoff")
        if qb_timing.filter(
            pl.col("source_available_at_utc").is_not_null()
            & (pl.col("source_available_at_utc") > pl.col("feature_as_of_utc"))
        ).height:
            raise AssertionError("XGBoost 2025 QB source availability occurs after feature cutoff")

        before_hash = task.logical_rows_hash(
            combined.select(["game_id", *feature_cols]), sort_by=["game_id"]
        )
        target_cols = [c for c in ("target_home_win", "target_tie", "target_margin") if c in combined.columns]
        masked = combined.with_columns(
            [pl.lit(None).cast(combined.schema[c]).alias(c) for c in target_cols]
            + [pl.lit(False).alias("target_available")]
        )
        after_hash = task.logical_rows_hash(
            masked.select(["game_id", *feature_cols]), sort_by=["game_id"]
        )
        if before_hash != after_hash:
            raise AssertionError("masking XGBoost targets changed predictor values")

        engine = task.WalkForwardEngine(frozen_dev, feature_cols, target_col="target_home_win")
        unseen: dict[str, list[str]] = {}
        for col, vocab in engine._categorical_vocab.items():  # noqa: SLF001 - exact frozen adapter seam
            observed = set(combined[col].drop_nulls().unique().to_list())
            bad = sorted(str(x) for x in observed - set(vocab))
            if bad:
                unseen[col] = bad
        if unseen:
            raise AssertionError(f"actual 2025 XGBoost unseen-category blocker: {unseen}")

        return {
            "coverage": "285/285 games; 570/570 candidate-rank-1 QB sides",
            "feature_count": 132,
            "feature_order_hash": task.FROZEN_FEATURE_ORDER_HASH,
            "schema_status": "PASS_EXACT_TASK03C_GAME_PLUS_QB_ASSEMBLY",
            "chronology_status": "PASS_QB_CUTOFF_TARGET_MASKING_AND_BLOCK_REVEAL_COMPATIBLE",
            "market_columns_present": 0,
            "feature_values_unchanged_by_target_masking": True,
            "feature_value_logical_sha256": before_hash,
            "development_assembly_parity": True,
            "development_assembly_parity_logical_sha256": parity_sha,
            "qb_candidate_rank": 1,
            "qb_side_rows": task.EXPECTED_SIDES,
            "qb_cutoff_alignment": "PASS",
            "unseen_categories": {},
            "artifact": task.artifact(task.FEATURES),
            "qb_artifact": task.artifact(QB_FEATURES),
            "contract_artifact": task.artifact(task.XGB_CONTRACT),
            "source_artifacts": [task.artifact(task.FEATURES), task.artifact(QB_FEATURES)],
            "missing_dependencies": [],
        }

    return xgboost_cert


def _build_schedule_certifier(task):
    def schedule_cert(
        features_2025: pl.DataFrame,
        games_2025: pl.DataFrame,
        canonical_ids: set[str],
    ) -> dict[str, Any]:
        schedule = pl.read_parquet(task.SCHEDULE).filter(pl.col("season") == task.HOLDOUT_SEASON)
        task.require_exact_game_ids(schedule.select("game_id"), canonical_ids, "2025 schedule")
        task.require_columns(
            schedule,
            [
                "game_id", "season", "game_type", "week", "gameday", "gametime",
                "away_team", "home_team", "away_rest", "home_rest", "surface",
            ],
            "2025 schedule",
        )
        task.require_columns(
            games_2025,
            ["game_id", "season", "season_type", "week", "away_team", "home_team", "roof_type"],
            "2025 canonical games",
        )
        task.require_columns(
            features_2025,
            ["game_id", "prediction_as_of_utc", "neutral_site"],
            "2025 point-in-time metadata",
        )
        if schedule["gameday"].null_count() or schedule["gametime"].null_count():
            raise AssertionError("2025 frozen schedule has missing gameday/gametime kickoff identity")
        if schedule["home_team"].null_count() or schedule["away_team"].null_count():
            raise AssertionError("2025 frozen schedule has missing source team identity")
        if features_2025["prediction_as_of_utc"].null_count():
            raise AssertionError("2025 point-in-time prediction cutoff is incomplete")

        canonical = games_2025.select(
            "game_id", "season", "season_type", "week", "away_team", "home_team"
        ).rename(
            {
                "season": "canonical_season",
                "season_type": "canonical_season_type",
                "week": "canonical_week",
                "away_team": "canonical_away_team",
                "home_team": "canonical_home_team",
            }
        )
        joined = schedule.join(canonical, on="game_id", how="left", validate="1:1")
        identity_bad = joined.filter(
            (pl.col("season") != pl.col("canonical_season"))
            | (pl.col("week") != pl.col("canonical_week"))
            | (pl.col("game_type").cast(pl.Utf8).str.to_uppercase()
               != pl.col("canonical_season_type").cast(pl.Utf8).str.to_uppercase())
        )
        if identity_bad.height:
            bad_ids = identity_bad["game_id"].head(12).to_list()
            raise AssertionError(f"2025 frozen schedule/canonical block identity drift: {bad_ids}")

        # Follow the accepted Totals source->canonical rule: team abbreviations
        # are normalized per game and per side, never through a global alias
        # dictionary.  This safely accommodates nflverse source identities such
        # as LAR while the canonical NFL Edge identity is LA.
        collapsed = joined.filter(
            (pl.col("home_team") == pl.col("away_team"))
            | (pl.col("canonical_home_team") == pl.col("canonical_away_team"))
        )
        if collapsed.height:
            raise AssertionError(
                f"2025 schedule contains collapsed two-team identity: {collapsed['game_id'].head(12).to_list()}"
            )
        swapped = joined.filter(
            (pl.col("home_team") == pl.col("canonical_away_team"))
            & (pl.col("away_team") == pl.col("canonical_home_team"))
        )
        if swapped.height:
            raise AssertionError(
                f"2025 schedule source teams are side-swapped vs canonical identity: {swapped['game_id'].head(12).to_list()}"
            )
        aliases = joined.filter(
            (pl.col("home_team") != pl.col("canonical_home_team"))
            | (pl.col("away_team") != pl.col("canonical_away_team"))
        )
        alias_examples = aliases.select(
            "game_id", "away_team", "canonical_away_team", "home_team", "canonical_home_team"
        ).head(12).to_dicts()

        kickoff_rows = []
        for row in schedule.select("game_id", "gameday", "gametime").to_dicts():
            kickoff_rows.append(
                {
                    "game_id": str(row["game_id"]),
                    "kickoff_time_utc": gameday_gametime_to_utc(
                        str(row["gameday"]), str(row["gametime"])
                    ),
                }
            )
        kickoff = pl.DataFrame(kickoff_rows).with_columns(
            pl.col("kickoff_time_utc").cast(pl.Datetime("us", "UTC"))
        )
        task.require_exact_game_ids(kickoff.select("game_id"), canonical_ids, "derived 2025 kickoff clock")
        timing = features_2025.select("game_id", "prediction_as_of_utc").join(
            kickoff,
            on="game_id",
            how="left",
            validate="1:1",
        )
        if timing["kickoff_time_utc"].null_count():
            raise AssertionError("derived 2025 kickoff clock is incomplete")
        late = timing.filter(pl.col("prediction_as_of_utc") >= pl.col("kickoff_time_utc"))
        if late.height:
            raise AssertionError(
                f"2025 prediction cutoff is not strictly pre-kickoff for games={late['game_id'].head(12).to_list()}"
            )

        return {
            "coverage": "285/285",
            "schema_status": "PASS_AUTHORITATIVE_SOURCE_SPLIT",
            "chronology_status": "PASS_SCHEDULE_KICKOFF_PLUS_POINT_IN_TIME_CUTOFF",
            "kickoff_source": "frozen schedule gameday/gametime via accepted DST-aware derivation",
            "prediction_cutoff_source": "game_features prediction_as_of_utc",
            "scheduled_start_utc_feature_field_required": False,
            "all_prediction_cutoffs_strictly_before_kickoff": True,
            "schedule_team_identity_mapping": "PER_GAME_PER_SIDE_SOURCE_TO_CANONICAL_NO_GLOBAL_ALIAS_DICTIONARY",
            "schedule_team_alias_game_count": aliases.height,
            "schedule_team_alias_examples": alias_examples,
            "rest_source": "frozen schedule away_rest/home_rest",
            "surface_source": "frozen schedule surface",
            "roof_source": "canonical games roof_type",
            "neutral_site_source": "frozen point-in-time game feature surface",
            "artifacts": [task.artifact(task.SCHEDULE), task.artifact(task.GAMES), task.artifact(task.FEATURES)],
            "missing_dependencies": [],
        }

    return schedule_cert


def main() -> int:
    task = _load_base()
    task.xgboost_cert = _build_xgboost_certifier(task)
    task.schedule_cert = _build_schedule_certifier(task)
    original_matrix_row = task.matrix_row

    def matrix_row(name, required, paths, detail):
        if "XGBoost" in name and detail.get("qb_artifact"):
            paths = [*paths, detail["qb_artifact"]]
        return original_matrix_row(name, required, paths, detail)

    task.matrix_row = matrix_row
    return int(task.main())


if __name__ == "__main__":
    raise SystemExit(main())
