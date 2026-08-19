#!/usr/bin/env python3
"""Task 05E-D2 Phase B: build NORMALIZED + CANONICAL market layers.

Reads the authoritative RAW acquisition read-only from the production runtime
tree (default /root/nfl-edge/data/market_data) and writes derived NORMALIZED /
CANONICAL artifacts to this worktree's data/market_data/.

Outcome-blind: no scores, no results, no edge values.

Usage:
    python scripts/build_market_canonical.py [--raw-root DIR] [--out-root DIR]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

from nfl_edge.market_data.canonical import build_canonical, write_canonical
from nfl_edge.market_data.manifest import (
    LEDGER_PATH,
    MANIFEST_REQUEST_PLAN_PATH,
    RAW_ROOT,
    SCHEDULE_SOURCE_PATH,
)
from nfl_edge.market_data.normalize import build_normalized

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", default=str(REPO_ROOT / RAW_ROOT))
    parser.add_argument("--out-root", default=str(REPO_ROOT / "data" / "market_data"))
    parser.add_argument("--production", action="store_true",
                        help="read RAW from the /root/nfl-edge production tree")
    args = parser.parse_args()

    if args.production:
        prod = Path("/root/nfl-edge")
        raw_root = prod / RAW_ROOT
        ledger = prod / LEDGER_PATH
        plan = prod / MANIFEST_REQUEST_PLAN_PATH
        schedule = prod / SCHEDULE_SOURCE_PATH
    else:
        raw_root = Path(args.raw_root)
        ledger = REPO_ROOT / LEDGER_PATH
        plan = REPO_ROOT / MANIFEST_REQUEST_PLAN_PATH
        schedule = REPO_ROOT / SCHEDULE_SOURCE_PATH

    out_root = Path(args.out_root)
    norm_out = out_root / "normalized"
    canon_out = out_root / "canonical"
    norm_out.mkdir(parents=True, exist_ok=True)
    canon_out.mkdir(parents=True, exist_ok=True)

    print(f"raw_root  = {raw_root}")
    print(f"ledger    = {ledger}")
    print(f"plan      = {plan}")
    print(f"schedule  = {schedule}")
    print(f"out_root  = {out_root}")

    normalized = build_normalized(raw_root, ledger, plan)
    print(f"normalized rows = {normalized.height}")
    target_rows = normalized.filter(pl.col("is_target_event") == True).height  # noqa: E712
    print(f"normalized target-event rows = {target_rows}")
    write_canonical_path = norm_out / "normalized_book_market.parquet"
    normalized.write_parquet(write_canonical_path, compression="zstd")
    print(f"wrote {write_canonical_path} ({write_canonical_path.stat().st_size} bytes)")

    schedule_df = pl.read_parquet(schedule)
    plan_df = pl.read_parquet(plan)
    games, bm = build_canonical(normalized, plan_df, schedule_df)
    print(f"canonical games: {games.height}")
    print(f"canonical book_market rows: {bm.height}")
    write_canonical(games, bm, canon_out)
    print(f"wrote {canon_out/'canonical_games.parquet'}")
    print(f"wrote {canon_out/'canonical_book_market.parquet'}")


if __name__ == "__main__":
    main()