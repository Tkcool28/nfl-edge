#!/usr/bin/env python3
"""Materialize the active NFL EDGE 2026 regular-season schedule."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nfl_edge.live.schedule_materializer_2026 import materialize_active_schedule  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--active-as-of-utc")
    args = parser.parse_args()

    path, payload = materialize_active_schedule(
        output_dir=args.output_dir,
        season=args.season,
        active_as_of_utc=args.active_as_of_utc,
    )
    print(json.dumps({
        "status": "ACTIVE_SCHEDULE_MATERIALIZED",
        "season": payload["season"],
        "week": payload["week"],
        "schedule_version": payload["schedule_version"],
        "games": len(payload["games"]),
        "path": str(path),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
