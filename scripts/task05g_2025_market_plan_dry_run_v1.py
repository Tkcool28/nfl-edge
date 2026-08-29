#!/usr/bin/env python3
"""Authorized 2025 market-plan materialization with zero paid API calls.

This command is intentionally narrower than the full holdout executor. It may
open only the four frozen kickoff/schedule columns required to construct the
2025 T-60 request plan, and only after the Master authorization hash has been
verified and the prefreeze audit passes.

It never reads ODDS_API_KEY, never calls The Odds API, never reads score/outcome
columns, and never advances football/model state. Its only purpose is to freeze
the exact 2025 historical-market request plan and projected credit cap before
any paid acquisition is authorized.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from nfl_edge.holdout.market_2025 import (
    HOLDOUT_PLAN_MANIFEST_RELATIVE_PATH,
    HOLDOUT_PLAN_RELATIVE_PATH,
    build_holdout_market_plan,
    holdout_market_dry_run_report,
    write_holdout_market_plan,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "task05g_2025_acceptance_v1.yaml"
AUDIT = ROOT / "scripts" / "task05g_pre2025_freeze_audit_v1.py"
DEFAULT_SCHEDULE_PATH = (
    ROOT
    / "data/raw/source_snapshots/v1/schedules_2018_2025_frozen-baseline-v1.parquet"
)
DEFAULT_REPORT_PATH = (
    ROOT
    / "artifacts/task05g_2025_holdout_v1/market/market_plan_dry_run_2025_v1.json"
)
AUTHORIZATION_ENV = "NFL_EDGE_2025_AUTHORIZATION"
SCHEDULE_COLUMNS = ("game_id", "season", "gameday", "gametime")


class MarketPlanDryRunError(RuntimeError):
    """Raised before any paid market-data request can occur."""


def _load_authorization_hash() -> str:
    config = dict(yaml.safe_load(CONFIG_PATH.read_text()) or {})
    if str(config.get("schema_version")) != "task05g_2025_acceptance_v1":
        raise MarketPlanDryRunError("unexpected acceptance schema")
    auth = dict(config.get("authorization") or {})
    if not bool(auth.get("must_be_verified_before_any_2025_file_read")):
        raise MarketPlanDryRunError("authorization-before-read invariant missing")
    expected = str(auth.get("exact_phrase_sha256") or "")
    if len(expected) != 64:
        raise MarketPlanDryRunError("invalid frozen authorization hash")
    return expected


def _verify_authorization_before_schedule_read() -> None:
    expected = _load_authorization_hash()
    supplied = os.environ.get(AUTHORIZATION_ENV)
    if supplied is None:
        raise MarketPlanDryRunError(
            f"{AUTHORIZATION_ENV} is required; no 2025 schedule read occurred"
        )
    actual = hashlib.sha256(supplied.encode()).hexdigest()
    if actual != expected:
        raise MarketPlanDryRunError(
            "authorization mismatch; no 2025 schedule read occurred"
        )


def _run_prefreeze_audit() -> None:
    completed = subprocess.run(
        [sys.executable, str(AUDIT), "--quiet"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise MarketPlanDryRunError(f"prefreeze audit failed: {detail}")


def _read_schedule_only(path: Path) -> pl.DataFrame:
    """Read only kickoff identity/time columns; score/outcome columns stay unread."""
    if not path.exists():
        raise MarketPlanDryRunError(f"authorized schedule source missing: {path}")
    frame = pl.read_parquet(path, columns=list(SCHEDULE_COLUMNS))
    scoped = frame.filter(pl.col("season") == 2025).select(*SCHEDULE_COLUMNS)
    if scoped.height == 0:
        raise MarketPlanDryRunError("authorized schedule contains no 2025 rows")
    return scoped


def _schedule_slice_sha256(frame: pl.DataFrame) -> str:
    """Hash only the four-column 2025 schedule slice used by the plan."""
    rows: list[dict[str, Any]] = []
    for row in frame.sort(["gameday", "gametime", "game_id"]).iter_rows(named=True):
        rows.append({name: row[name] for name in SCHEDULE_COLUMNS})
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _reportable_path(path: Path) -> str:
    """Prefer repo-relative paths while allowing isolated test output locations."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def materialize_plan_only(
    *,
    schedule_path: Path = DEFAULT_SCHEDULE_PATH,
    plan_path: Path | None = None,
    manifest_path: Path | None = None,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> dict[str, object]:
    """Authorize, read schedule-only columns, persist plan/report, then stop."""
    _run_prefreeze_audit()
    _verify_authorization_before_schedule_read()

    schedule = _read_schedule_only(schedule_path)
    schedule_sha256 = _schedule_slice_sha256(schedule)
    plan = build_holdout_market_plan(schedule)

    resolved_plan = plan_path or (ROOT / HOLDOUT_PLAN_RELATIVE_PATH)
    resolved_manifest = manifest_path or (ROOT / HOLDOUT_PLAN_MANIFEST_RELATIVE_PATH)
    plan_sha256 = write_holdout_market_plan(
        plan,
        plan_path=resolved_plan,
        manifest_path=resolved_manifest,
        schedule_source_sha256=schedule_sha256,
    )

    report = dict(holdout_market_dry_run_report(plan))
    report.update(
        {
            "status": "AUTHORIZED_2025_MARKET_PLAN_FROZEN__NO_PAID_CALLS",
            "schedule_columns_read": list(SCHEDULE_COLUMNS),
            "score_or_outcome_columns_read": [],
            "schedule_slice_sha256": schedule_sha256,
            "plan_sha256": plan_sha256,
            "plan_path": _reportable_path(resolved_plan),
            "manifest_path": _reportable_path(resolved_manifest),
            "credits_spent": 0,
            "odds_api_key_read": False,
            "paid_acquisition_executed": False,
        }
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> int:
    try:
        report = materialize_plan_only()
    except (MarketPlanDryRunError, OSError, ValueError) as exc:
        print(f"MARKET_PLAN_DRY_RUN_FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
