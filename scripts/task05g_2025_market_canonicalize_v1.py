#!/usr/bin/env python3
"""Canonicalize the frozen paid 2025 market acquisition without outcomes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nfl_edge.holdout.market_canonical_2025 import (
    canonicalize_acquisition_bundle,
    default_schedule_path,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "task05g_2025_holdout_v1" / "market_canonicalization_v1"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bundle-root",
        required=True,
        help="root of the extracted frozen acquisition artifact",
    )
    parser.add_argument(
        "--schedule-path",
        default=str(default_schedule_path(REPO_ROOT)),
    )
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    report = canonicalize_acquisition_bundle(
        args.bundle_root,
        schedule_path=args.schedule_path,
        output_root=args.output_root,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
