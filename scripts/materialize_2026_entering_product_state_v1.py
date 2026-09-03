#!/usr/bin/env python3
"""Materialize frozen entering-2026 evaluator/confidence state from accepted evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from nfl_edge.live.product_state_2026 import materialize_entering_2026_product_state

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data/live/2026/entering_product_state_v1.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    payload = materialize_entering_2026_product_state(ROOT)
    raw = (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(raw)
    print(
        json.dumps(
            {
                "status": "ENTERING_2026_PRODUCT_STATE_MATERIALIZED",
                "output": str(args.output),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "historical_parity": payload["source_evidence"]["reconstructed_2024_state_parity"],
                "prior_games": payload["source_evidence"]["combined_prior_games"],
                "accepted_2025_games": payload["source_evidence"]["accepted_2025_games"],
                "methodology_changed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
