#!/usr/bin/env python3
"""Build the frozen historical-market acquisition manifest + request plan.

Reproduces, deterministically, the T-60 natural-kickoff cluster request plan
from the frozen nflverse schedule and persists:

* ``data/manifests/historical_market_acquisition_v1.json`` — the frozen
  market-source manifest (books, markets, credit contract, source hashes).
* ``data/manifests/historical_market_request_plan_v1.parquet`` — the 575-row
  deterministic request plan.
* ``data/manifests/historical_market_request_plan_v1.json`` — SHA-256 + meta.

This script performs NO API calls and reads no credentials. It fails closed
(raises) if the plan does not reproduce the frozen acceptance counts.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import polars as pl

from nfl_edge.market_data.manifest import (
    MANIFEST_REQUEST_PLAN_JSON,
    MANIFEST_REQUEST_PLAN_PATH,
    SCHEDULE_SOURCE_PATH,
    build_schedule_source_metadata,
    write_manifest,
)
from nfl_edge.market_data.plan import build_request_plan, write_request_plan

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    meta = build_schedule_source_metadata(SCHEDULE_SOURCE_PATH)
    schedule_sha = meta["source_file_sha256"]
    plan, clusters = build_request_plan(SCHEDULE_SOURCE_PATH)

    # Frozen acquisition manifest (single source of truth serialized),
    # including the full-file SHA-256 and the deterministic schema fingerprint.
    write_manifest(
        REPO_ROOT / "data/manifests/historical_market_acquisition_v1.json",
        schedule_source_meta=meta,
    )

    plan = plan.with_columns(pl.lit(schedule_sha).alias("schedule_source_sha256"))
    digest = write_request_plan(
        plan,
        plan_path=REPO_ROOT / MANIFEST_REQUEST_PLAN_PATH,
        json_path=REPO_ROOT / MANIFEST_REQUEST_PLAN_JSON,
        schedule_sha256=schedule_sha,
        schedule_path=SCHEDULE_SOURCE_PATH,
    )

    by_season = dict(sorted(Counter(c.season for c in clusters).items()))
    print(f"source sha256          : {schedule_sha}")
    print(f"plan rows              : {plan.height}")
    print(f"clusters by season     : {by_season}")
    print(f"plan parquet           : {MANIFEST_REQUEST_PLAN_PATH}")
    print(f"plan sha256            : {digest}")
    print(f"acquisition manifest   : data/manifests/historical_market_acquisition_v1.json")


if __name__ == "__main__":
    main()
