#!/usr/bin/env python3
"""Execute the frozen 2025 historical-market acquisition contract.

This entrypoint is intentionally thin. It does not implement HTTP, retry,
ledger, raw-persistence, bookmaker, market, or cost semantics. Those remain in
the frozen holdout adapter and generic market-data runner.

Execution order:
1. Re-materialize the authorized schedule-only request plan.
2. Require byte-identical plan/schedule identities from the accepted dry run.
3. Refuse to proceed if the one-shot holdout marker already exists.
4. Read only ODDS_API_KEY from the execution environment.
5. Delegate to run_holdout_market_acquisition().

The valid authorization phrase and API key are execution-time inputs only and
must never be printed, committed, serialized, or passed as command-line args.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import polars as pl

from nfl_edge.holdout.market_2025 import (
    HOLDOUT_LEDGER_PATH,
    HOLDOUT_LOCK_DIR,
    HOLDOUT_PLAN_MANIFEST_RELATIVE_PATH,
    HOLDOUT_PLAN_RELATIVE_PATH,
    HOLDOUT_RAW_ROOT,
    run_holdout_market_acquisition,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# Import after ROOT/src is available when the script is run without installation.
from task05g_2025_market_plan_dry_run_v1 import materialize_plan_only  # noqa: E402

EXPECTED_PLAN_SHA256 = "d1b1eace49177bf01a22db9c2d9d991d07fe8144d165a9a8a67ba1f29f481425"
EXPECTED_SCHEDULE_SLICE_SHA256 = "de36585a681bc79824b8427168ec4a74103fead35e2efc980590077d3eb20228"
EXPECTED_REQUEST_ROWS = 123
EXPECTED_TARGET_GAMES = 285
EXPECTED_CREDIT_CAP = 3690
ODDS_API_KEY_ENV = "ODDS_API_KEY"
SPEND_MARKER = ROOT / "artifacts/task05g_2025_holdout_v1/HOLDOUT_SPENT.json"


class HoldoutMarketAcquireError(RuntimeError):
    """Fail-closed wrapper error raised before or around frozen acquisition."""


def _verify_frozen_plan() -> tuple[pl.DataFrame, dict[str, object]]:
    report = dict(materialize_plan_only())
    checks = {
        "status": report.get("status") == "AUTHORIZED_2025_MARKET_PLAN_FROZEN__NO_PAID_CALLS",
        "plan_sha256": report.get("plan_sha256") == EXPECTED_PLAN_SHA256,
        "schedule_slice_sha256": report.get("schedule_slice_sha256") == EXPECTED_SCHEDULE_SLICE_SHA256,
        "request_plan_rows": int(report.get("request_plan_rows", -1)) == EXPECTED_REQUEST_ROWS,
        "target_games": int(report.get("target_games", -1)) == EXPECTED_TARGET_GAMES,
        "planned_credit_cap": int(report.get("planned_credit_cap", -1)) == EXPECTED_CREDIT_CAP,
        "network_calls": int(report.get("network_calls", -1)) == 0,
        "credential_reads": int(report.get("credential_reads", -1)) == 0,
        "credits_spent": int(report.get("credits_spent", -1)) == 0,
        "odds_api_key_read": report.get("odds_api_key_read") is False,
        "paid_acquisition_executed": report.get("paid_acquisition_executed") is False,
        "score_or_outcome_columns_read": report.get("score_or_outcome_columns_read") == [],
    }
    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        raise HoldoutMarketAcquireError(
            "frozen 2025 market-plan identity mismatch before credential read: "
            + ", ".join(failed)
        )

    plan_path = ROOT / HOLDOUT_PLAN_RELATIVE_PATH
    if not plan_path.exists():
        raise HoldoutMarketAcquireError(f"frozen plan missing after materialization: {plan_path}")
    return pl.read_parquet(plan_path), report


def execute() -> dict[str, object]:
    if SPEND_MARKER.exists():
        raise HoldoutMarketAcquireError(
            "HOLDOUT_SPENT marker exists; refusing historical-market acquisition"
        )

    # Authorization and all plan-identity checks happen before ODDS_API_KEY is read.
    plan, report = _verify_frozen_plan()

    api_key = os.environ.get(ODDS_API_KEY_ENV)
    if not api_key:
        raise HoldoutMarketAcquireError(
            "ODDS_API_KEY is required for paid acquisition; no paid request executed"
        )

    result = run_holdout_market_acquisition(
        plan,
        plan_path=ROOT / HOLDOUT_PLAN_RELATIVE_PATH,
        plan_sha256=EXPECTED_PLAN_SHA256,
        api_key=api_key,
        raw_root=ROOT / HOLDOUT_RAW_ROOT,
        ledger_path=ROOT / HOLDOUT_LEDGER_PATH,
        lock_dir=ROOT / HOLDOUT_LOCK_DIR,
    )

    # Never include the credential or an unredacted URL in output.
    return {
        "status": "2025_HISTORICAL_MARKET_ACQUISITION_ATTEMPT_COMPLETE",
        "plan_sha256": EXPECTED_PLAN_SHA256,
        "schedule_slice_sha256": EXPECTED_SCHEDULE_SLICE_SHA256,
        "request_plan_rows": EXPECTED_REQUEST_ROWS,
        "target_games": EXPECTED_TARGET_GAMES,
        "credit_cap": EXPECTED_CREDIT_CAP,
        "plan_path": str(HOLDOUT_PLAN_RELATIVE_PATH),
        "plan_manifest_path": str(HOLDOUT_PLAN_MANIFEST_RELATIVE_PATH),
        "ledger_path": str(HOLDOUT_LEDGER_PATH),
        "raw_root": str(HOLDOUT_RAW_ROOT),
        "dry_run_status": report.get("status"),
        "acquisition": result,
    }


def main() -> int:
    try:
        result = execute()
    except Exception as exc:  # fail closed while preserving runner-written evidence
        print(f"2025_MARKET_ACQUISITION_STOP: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
