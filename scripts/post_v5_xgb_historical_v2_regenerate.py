#!/usr/bin/env python3
"""Diagnostic historical XGBoost V2 regeneration using the canonical V1 runner.

This does not create a new training implementation. It executes the preserved
Task03C canonical selected-model runner twice:

1. untouched V1 as a reproduction control;
2. the same runner with ONLY the module-level ``construct_split`` seam swapped
   to the merged adaptive strictly-prior V2 split.

The control must logically match the accepted canonical V1 prediction artifact
before V2 output is considered valid. The V2 output remains diagnostic and is
written outside frozen model directories.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

import nfl_edge.backtest.xgboost_walk_forward as wf
from nfl_edge.backtest.xgboost_walk_forward_v2 import construct_adaptive_split
from nfl_edge.models.run_xgboost_v1 import XgboostV1CanonicalRunner, logical_hash_predictions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.out
    control_dir = out / "v1_control"
    v2_dir = out / "v2_adaptive"

    runner = XgboostV1CanonicalRunner(workspace_root=root)

    # 1) Untouched canonical control.
    control_manifest = runner.run(control_dir, silent=True)
    control = pl.read_parquet(control_dir / "xgboost_v1_predictions.parquet")
    accepted_path = root / "data/modeling/development_v1/chronology_corrected/canonical_runner/xgboost_v1_predictions.parquet"
    accepted = pl.read_parquet(accepted_path)
    control_hash = logical_hash_predictions(control, "game_id")
    accepted_hash = logical_hash_predictions(accepted, "game_id")
    if control_hash != accepted_hash:
        raise RuntimeError(f"canonical V1 reproduction drift: {control_hash} != {accepted_hash}")

    # 2) Same canonical runner; only split construction is replaced.
    extraction = pl.read_parquet(runner.extraction_path)
    original_construct_split = wf.construct_split

    def adaptive_proxy(all_block_keys, current_block):
        # The preserved engine calls construct_split(block_keys, current_block).
        # V2 additionally needs row counts, so use the exact canonical extraction
        # already verified by runner authority checks. No outcomes/performance are
        # consulted in selecting the tail.
        return construct_adaptive_split(extraction, current_block)

    wf.construct_split = adaptive_proxy
    try:
        v2_manifest = runner.run(v2_dir, silent=True)
    finally:
        wf.construct_split = original_construct_split

    v2 = pl.read_parquet(v2_dir / "xgboost_v1_predictions.parquet")
    if v2.height != accepted.height:
        raise RuntimeError(f"V2 row count drift: {v2.height} != {accepted.height}")
    if set(v2["game_id"].to_list()) != set(accepted["game_id"].to_list()):
        raise RuntimeError("V2 game identity drift")

    summary = {
        "status": "CANONICAL_V1_CONTROL_REPRODUCED__HISTORICAL_XGB_V2_GENERATED",
        "control_logical_hash": control_hash,
        "accepted_logical_hash": accepted_hash,
        "control_matches_accepted": True,
        "row_count": v2.height,
        "v1_warmup_rows": int(accepted.filter(pl.col("warmup") == True).height),  # noqa: E712
        "v2_warmup_rows": int(v2.filter(pl.col("warmup") == True).height),  # noqa: E712
        "v1_live_rows": int(accepted.filter(pl.col("warmup") == False).height),  # noqa: E712
        "v2_live_rows": int(v2.filter(pl.col("warmup") == False).height),  # noqa: E712
        "v2_prediction_logical_hash": logical_hash_predictions(v2, "game_id"),
        "split_change_only": True,
        "thresholds_retuned": False,
        "model_parameters_retuned": False,
        "control_manifest": control_manifest,
        "v2_manifest": v2_manifest,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "historical_xgb_v2_regeneration_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
