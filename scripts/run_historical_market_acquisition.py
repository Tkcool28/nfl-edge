#!/usr/bin/env python3
"""Safe historical-market acquisition CLI (Task 05E-C3).

DRY-RUN BY DEFAULT. Running with no execution flag makes zero Odds API calls
and requires no credential. Only an explicit ``--execute`` opens the network
path (single exact env var ``ODDS_API_KEY``; never enumerated ``os.environ``).

Usage:
    python scripts/run_historical_market_acquisition.py                # dry-run
    python scripts/run_historical_market_acquisition.py --execute      # live pull
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import polars as pl

from nfl_edge.market_data.ledger import LEDGER_PATH, completed_request_ids
from nfl_edge.market_data.manifest import (
    MANIFEST_REQUEST_PLAN_PATH,
    ODDS_API_KEY_ENV,
    RAW_ROOT,
)
from nfl_edge.market_data.runner import AcquisitionStop, run_plan

REPO_ROOT = Path(__file__).resolve().parents[1]


def _fmt_report(rep: dict) -> str:
    lines = [
        "=== historical market acquisition DRY-RUN report ===",
        f"target games total        : {rep['total_target_games']}",
        f"request plan rows         : {rep['request_plan_rows']}",
        "per-season request counts : "
        + ", ".join(f"{k}={v}" for k, v in sorted(rep["per_season_request_counts"].items())),
        f"bookmaker list            : {', '.join(rep['bookmaker_list'])}",
        f"markets                   : {', '.join(rep['markets'])}",
        f"credits per request       : {rep['credits_per_request']}",
        f"expected total credits    : {rep['expected_total_credits']}",
        f"earliest planned request  : {rep['earliest_planned_request_timestamp']}",
        f"latest planned request    : {rep['latest_planned_request_timestamp']}",
        f"target games represented  : {rep['target_games_represented']}",
        f"games per cluster         : {rep['games_per_cluster']}",
        f"obs lead min/max (min)    : {rep['expected_observation_lead_minutes']}",
        f"duplicate request ids     : {rep['duplicate_request_plan_id_count']}",
        f"duplicate game assign     : {rep['duplicate_game_assignment_count']}",
        f"unassigned games          : {rep['unassigned_game_count']}",
        f"2025 row count            : {rep['nfl_season_2025_row_count']}",
        f"projected raw root        : {rep['projected_raw_output_root']}",
        f"projected raw pattern     : {rep['projected_raw_output_pattern']}",
        f"existing completed reqs   : {rep['current_existing_completed_request_count']}",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run (or dry-run) the historical market acquisition."
    )
    parser.add_argument(
        "--plan",
        default=str(REPO_ROOT / MANIFEST_REQUEST_PLAN_PATH),
        help="path to the frozen request-plan parquet",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="(default) produce the report with zero API calls / credentials",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="EXPLICIT GATE: actually call The Odds API (requires ODDS_API_KEY)",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    plan = pl.read_parquet(args.plan)
    data_root = REPO_ROOT / "data" / "market_data"
    raw_root = data_root / "raw"
    ledger_path = data_root / "ledger" / "historical_acquisition_ledger_v1.parquet"

    if not args.execute:
        rep = run_plan(plan, execute=False, raw_root=raw_root, ledger_path=ledger_path)
        print(_fmt_report(rep))
        return

    # Execution path: access ONLY the exact required secret variable.
    api_key = os.environ.get(ODDS_API_KEY_ENV)  # not an enumeration
    if not api_key:
        raise SystemExit(f"{ODDS_API_KEY_ENV} not set; refusing to execute (no key on disk).")
    rep = run_plan(
        plan,
        execute=True,
        api_key=api_key,
        raw_root=raw_root,
        ledger_path=ledger_path,
        timeout_seconds=args.timeout,
    )
    print(f"executed={rep['executed']} skipped_completed={rep['skipped_completed']}")


if __name__ == "__main__":
    main()