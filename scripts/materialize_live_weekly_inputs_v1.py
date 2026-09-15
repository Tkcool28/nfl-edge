#!/usr/bin/env python3
"""Materialize active 2026 schedule plus settled prior-week football evidence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nfl_edge.live.evidence_2026 import materialize_settled_evidence  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--active-as-of-utc", required=True)
    args = parser.parse_args()
    evidence = materialize_settled_evidence(
        output_dir=args.output_dir,
        active_as_of_utc=args.active_as_of_utc,
    )
    print(json.dumps({
        "status": "LIVE_WEEKLY_INPUTS_MATERIALIZED",
        "season": 2026,
        "active_week": int(evidence.manifest["active_week"]),
        "settled_through_week": evidence.through_week,
        "observed_at_utc": evidence.observed_at_utc,
        "row_counts": evidence.manifest["row_counts"],
        "output_dir": str(evidence.root),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
