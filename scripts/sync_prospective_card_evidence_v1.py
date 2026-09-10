#!/usr/bin/env python3
"""Persist one prospective season/week from runtime staging into an evidence worktree."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nfl_edge.prospective.persist_v1 import sync_runtime_week


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--evidence-repo-root", type=Path, required=True)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = sync_runtime_week(
        runtime_root=args.runtime_root,
        evidence_repo_root=args.evidence_repo_root,
        season=args.season,
        week=args.week,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
