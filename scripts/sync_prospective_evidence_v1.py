#!/usr/bin/env python3
"""Sync/finalize NFL EDGE prospective evidence without performing Git operations."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nfl_edge.prospective.persistence_v1 import (  # noqa: E402
    finalize_ready_weeks,
    finalize_week_evidence,
    sync_runtime_evidence,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="copy immutable runtime observations into an isolated checkout")
    sync.add_argument("--runtime-root", type=Path, required=True)
    sync.add_argument("--evidence-root", type=Path, required=True)
    sync.add_argument("--production-worktree", type=Path, required=True)

    ready = sub.add_parser("finalize-ready", help="finalize captured weeks whose full slate has crossed kickoff")
    ready.add_argument("--evidence-root", type=Path, required=True)
    ready.add_argument("--as-of-utc", required=True)

    finalize = sub.add_parser("finalize-week", help="freeze official pre-kick evidence after the full week")
    finalize.add_argument("--evidence-root", type=Path, required=True)
    finalize.add_argument("--season", type=int, required=True)
    finalize.add_argument("--week", type=int, required=True)
    finalize.add_argument("--finalized-at-utc", required=True)
    finalize.add_argument("--week-last-kickoff-at-utc", required=True)

    args = parser.parse_args(argv)
    if args.command == "sync":
        result = sync_runtime_evidence(
            runtime_root=args.runtime_root,
            evidence_root=args.evidence_root,
            production_worktree=args.production_worktree,
        )
    elif args.command == "finalize-ready":
        result = finalize_ready_weeks(
            evidence_root=args.evidence_root,
            as_of_utc=args.as_of_utc,
        )
    else:
        result = finalize_week_evidence(
            evidence_root=args.evidence_root,
            season=args.season,
            week=args.week,
            finalized_at_utc=args.finalized_at_utc,
            week_last_kickoff_at_utc=args.week_last_kickoff_at_utc,
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
