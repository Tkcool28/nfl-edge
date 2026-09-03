#!/usr/bin/env python3
"""Validate and atomically publish one complete NFL_EDGE_PRODUCT_API_V1 snapshot."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nfl_edge.backend.publication import ProductStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--publication-dir", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.candidate.read_text(encoding="utf-8"))
    store = ProductStore(args.publication_dir)
    store.load_latest(required=False)
    immutable = store.publish(payload)
    print(
        json.dumps(
            {
                "status": "NFL_EDGE_PRODUCT_PUBLISHED",
                "product_version": payload["product_version"],
                "generated_at_utc": payload["generated_at_utc"],
                "immutable_snapshot": str(immutable),
                "latest": str(store.latest_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())