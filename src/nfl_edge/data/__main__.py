"""Command-line entry point for the bounded baseline audit."""

from __future__ import annotations

import argparse
from pathlib import Path

from .audit import DEFAULT_SEASONS, build_frozen_baseline, retrieve_sources


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", default="data/raw/source_snapshots/v1")
    parser.add_argument("--manifest-dir", default="data/manifests")
    parser.add_argument("--output-root", default="data/frozen")
    parser.add_argument("--seasons", nargs="+", type=int, default=list(DEFAULT_SEASONS))
    parser.add_argument("--retrieved-at-utc", default=None)
    parser.add_argument("--created-at-utc", default=None)
    parser.add_argument("--retrieve", action="store_true")
    parser.add_argument("--normalize", action="store_true")
    args = parser.parse_args()
    if args.retrieve:
        retrieve_sources(args.seasons, Path(args.raw_dir), Path(args.manifest_dir), args.retrieved_at_utc)
    if args.normalize:
        build_frozen_baseline(Path(args.raw_dir), Path(args.output_root), Path(args.manifest_dir), args.created_at_utc)


if __name__ == "__main__":
    main()
