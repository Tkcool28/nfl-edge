#!/usr/bin/env python3
"""2020-24-only deterministic replay wrapper for pre-2025 freeze proof.

This wrapper deliberately avoids the mixed `games_2018_2025.parquet` source.
It reuses the accepted Task05F/V2/V3/product implementations while substituting
only the outcome lookup surface with the tracked 2018-2024-only totals modeling
table. No selector/evaluator/confidence/staking semantics are changed.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SAFE_OUTCOMES = ROOT / "data" / "derived" / "totals_v1_modeling_table_2018_2024.parquet"
DEV = [2020, 2021, 2022, 2023, 2024]
ALL_HISTORY = [2018, 2019, 2020, 2021, 2022, 2023, 2024]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _safe_task05f_inputs(root: Path) -> dict[str, dict]:
    allowed = pl.col("season").cast(pl.Int64).is_in(DEV)
    qbelo = (
        pl.scan_parquet(root / "data/modeling/development_v1/qb_elo_predictions_2018_2024.parquet")
        .select(["game_id", "season", "week", "predicted_home_win_probability"])
        .filter(allowed)
        .rename({"predicted_home_win_probability": "qbelo_home"})
    )
    xgb = (
        pl.scan_parquet(root / "data/modeling/development_v1/chronology_corrected/xgboost_candidate_predictions_2018_2024.parquet")
        .select(["candidate_id", "game_id", "season", "week", "warmup", "prediction_probability"])
        .filter((pl.col("candidate_id") == "conservative") & allowed)
        .with_columns(
            pl.when(pl.col("warmup")).then(None).otherwise(pl.col("prediction_probability")).alias("xgb_home")
        )
        .select(["game_id", "xgb_home"])
    )
    expected_margin = (
        pl.scan_parquet(root / "data/modeling/development_v1/expected_margin_predictions_2018_2024.parquet")
        .select(["candidate_id", "game_id", "season", "week", "expected_home_margin"])
        .filter((pl.col("candidate_id") == "stable") & allowed)
        .select(["game_id", "expected_home_margin"])
    )
    ridge = (
        pl.scan_parquet(root / "reports/task05d/task05d_ridge_predictions.parquet")
        .select(["candidate_id", "game_id", "season", "week", "predicted_total"])
        .filter((pl.col("candidate_id") == "R4") & allowed)
        .select(["game_id", "predicted_total"])
    )
    outcomes = (
        pl.scan_parquet(SAFE_OUTCOMES)
        .select(["game_id", "season", "home_score", "away_score"])
        .filter(allowed)
    )
    df = (
        qbelo.join(xgb, on="game_id", how="left")
        .join(expected_margin, on="game_id", how="left")
        .join(ridge, on="game_id", how="left")
        .join(outcomes, on=["game_id", "season"], how="inner")
        .collect()
    )
    seasons = sorted(int(x) for x in df["season"].unique().to_list())
    if seasons != DEV:
        raise RuntimeError(f"safe Task05F seasons mismatch: {seasons}")
    return {str(row["game_id"]): row for row in df.to_dicts()}


def _safe_v2_scan(root: Path) -> pl.DataFrame:
    allowed = pl.col("season").cast(pl.Int64).is_in(ALL_HISTORY)
    qbelo = (
        pl.scan_parquet(root / "data/modeling/development_v1/qb_elo_predictions_2018_2024.parquet")
        .select(["game_id", "season", "week", "predicted_home_win_probability"])
        .filter(allowed)
        .rename({"predicted_home_win_probability": "qbelo_home"})
    )
    xgb = (
        pl.scan_parquet(root / "data/modeling/development_v1/chronology_corrected/xgboost_candidate_predictions_2018_2024.parquet")
        .select(["candidate_id", "game_id", "season", "week", "warmup", "prediction_probability"])
        .filter((pl.col("candidate_id") == "conservative") & allowed)
        .with_columns(
            pl.when(pl.col("warmup")).then(None).otherwise(pl.col("prediction_probability")).alias("xgb_home")
        )
        .select(["game_id", "xgb_home"])
    )
    margin = (
        pl.scan_parquet(root / "data/modeling/development_v1/expected_margin_predictions_2018_2024.parquet")
        .select(["candidate_id", "game_id", "season", "week", "expected_home_margin"])
        .filter((pl.col("candidate_id") == "stable") & allowed)
        .select(["game_id", "expected_home_margin"])
    )
    outcomes = (
        pl.scan_parquet(SAFE_OUTCOMES)
        .select(["game_id", "season", "home_score", "away_score"])
        .filter(allowed)
    )
    df = qbelo.join(xgb, on="game_id", how="left").join(margin, on="game_id", how="left").join(
        outcomes, on=["game_id", "season"], how="inner"
    ).collect()
    seasons = {int(x) for x in df["season"].unique().to_list()}
    if 2025 in seasons or not seasons.issubset(set(ALL_HISTORY)):
        raise RuntimeError(f"safe V2 history season mismatch: {sorted(seasons)}")
    return df


def run(out_root: Path) -> None:
    task05f = _load("safe_task05f", ROOT / "scripts/task05f_evaluator_final_runner.py")
    task05f.build_inputs = _safe_task05f_inputs
    upstream = out_root / "upstream"
    task05f.run(ROOT, ROOT / "config/task05f_evaluator_final_v1.yaml", upstream)

    board = pl.read_parquet(upstream / "historical_evaluator_board.parquet")
    seasons = sorted(int(x) for x in board["season"].unique().to_list())
    if seasons != DEV:
        raise RuntimeError(f"safe evaluator board seasons mismatch: {seasons}")

    v2_core = _load("safe_v2_core", ROOT / "scripts/task05g_model_confidence_v2_runner.py")
    v2_entry = _load("safe_v2_entry", ROOT / "scripts/task05g_model_confidence_v2_entrypoint.py")
    v2_core._scan_model_inputs = _safe_v2_scan
    v2_core._summary = v2_entry._safe_summary_factory(v2_core)
    v2_entry._fail_closed_on_nonfinite_history(v2_core)
    v2_entry._scope_full_dict_schema_inference_to_candidate_write(v2_core)
    v2_out = out_root / "v2"
    v2_core.run(
        ROOT,
        upstream / "historical_evaluator_board.parquet",
        v2_out,
        ROOT / "docs/task05g_model_confidence_v2_preregistration.md",
    )

    v3_core = _load("safe_v3_core", ROOT / "scripts/task05g_spread_confidence_v3_runner.py")
    v3_out = out_root / "v3"
    v3_core.run(
        ROOT,
        v2_out / "v2_candidate_table.parquet",
        v3_out,
        ROOT / v3_core.PREREG_PATH,
    )

    product = _load("safe_product", ROOT / "scripts/task05g_canonical_product_replay_v1.py")
    product.run(
        v3_out / "v3_candidate_table.parquet",
        ROOT / "reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv",
        ROOT / "reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv",
        out_root / "product",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", type=Path, required=True)
    args = parser.parse_args()
    run(args.out_root)
