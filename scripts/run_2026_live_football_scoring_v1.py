#!/usr/bin/env python3
"""Run the market-independent NFL EDGE 2026 Week 1 football scorer.

The command consumes the already-collected Sleeper audit artifacts under
``data/source_audits/sleeper_qb_v1``.  It never acquires sportsbook data and
never calls The Odds API.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nfl_edge.live.scorer_2026 import canonical_snapshot_bytes, score_week1
from nfl_edge.live.sleeper_qb import (
    DEFAULT_OVERRIDES,
    SleeperExpectedQBResolver,
    SleeperQBSource,
    load_overrides,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prediction-as-of-utc",
        required=True,
        help="Explicit RFC3339 UTC cutoff, e.g. 2026-09-02T18:00:00Z",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = SleeperQBSource.load(
        ROOT,
        prediction_as_of_utc=args.prediction_as_of_utc,
    )
    overrides = load_overrides(ROOT / DEFAULT_OVERRIDES)
    resolver = SleeperExpectedQBResolver(source, overrides=overrides)
    snapshot = score_week1(
        repository_root=ROOT,
        prediction_as_of_utc=args.prediction_as_of_utc,
        resolver=resolver,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_snapshot_bytes(snapshot))
    print(json.dumps(
        {
            "status": "2026_LIVE_FOOTBALL_SCORING_READY",
            "output": str(args.output),
            "snapshot_sha256": snapshot["snapshot_sha256"],
            "games": len(snapshot["games"]),
            "qb_resolution_counts": snapshot["qb_resolution_counts"],
            "model_scoring_counts": snapshot["model_scoring_counts"],
            "odds_api_called": False,
        },
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
