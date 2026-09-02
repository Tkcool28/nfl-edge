#!/usr/bin/env python3
"""Diagnostic-only 2025 rerun using merged post-V5 V2 seams.

This wrapper does not alter the frozen V1/V5 implementation. It loads the
standard 2025 evaluation entry point and swaps only the two successor seams
approved in PR #93:

- XGBoost block prediction -> xgboost_2025_v2.predict_xgboost_block
- Balanced selector -> final_selectors_v2.select_balanced

HHR, Value, Task05F, QB-Elo, Expected Margin, totals, staking, Play Through,
market data, settlement, and all other standard-run semantics stay unchanged.
2025 is already exposed, so this output is diagnostic only and MUST NOT be used
to tune thresholds or model parameters.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

from nfl_edge.holdout import executor_runtime_2025 as runtime
from nfl_edge.holdout import product_2025
from nfl_edge.holdout.xgboost_2025_v2 import predict_xgboost_block as predict_xgboost_block_v2
from nfl_edge.recommendation.final_selectors_v2 import select_balanced as select_balanced_v2

ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "scripts/task05g_2025_standard_evaluation_v1.py"


def _load_standard():
    spec = importlib.util.spec_from_file_location("post_v5_v2_standard_eval", STANDARD)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load standard evaluation runner: {STANDARD}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--pbp-root", type=Path, required=True)
    parser.add_argument("--market-root", type=Path, required=True)
    parser.add_argument("--historical-board", type=Path, required=True)
    parser.add_argument("--output-base", type=Path, default=ROOT / "artifacts/post_v5_v2_all_years/runs")
    args = parser.parse_args()

    standard = _load_standard()

    old_xgb = runtime.predict_xgboost_block
    old_balanced = product_2025.select_balanced
    runtime.predict_xgboost_block = predict_xgboost_block_v2
    product_2025.select_balanced = select_balanced_v2
    try:
        output = standard.execute(
            run_id=args.run_id,
            pbp_root=args.pbp_root,
            market_root=args.market_root,
            historical_board=args.historical_board,
            output_base=args.output_base,
        )
    finally:
        runtime.predict_xgboost_block = old_xgb
        product_2025.select_balanced = old_balanced

    print(f"POST_V5_V2_2025_DIAGNOSTIC_COMPLETE={output}")
    print("RETUNING_AUTHORIZED=FALSE")
    print("ODDS_API_CALLS=0")


if __name__ == "__main__":
    main()
