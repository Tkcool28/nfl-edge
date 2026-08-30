#!/usr/bin/env python3
"""Task05H driver that fixes the XGBoost input certification source join.

The underlying Task05H materializer remains unchanged.  This driver replaces
only its XGBoost certification hook so the check uses the exact accepted
Task03C source assembly: game features + candidate-rank-1 QB pregame features.
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


def main() -> int:
    task = _load_base()
    task.xgboost_cert = _build_xgboost_certifier(task)
    original_matrix_row = task.matrix_row

    def matrix_row(name, required, paths, detail):
        if "XGBoost" in name and detail.get("qb_artifact"):
            paths = [*paths, detail["qb_artifact"]]
        return original_matrix_row(name, required, paths, detail)

    task.matrix_row = matrix_row
    return int(task.main())


if __name__ == "__main__":
    raise SystemExit(main())
