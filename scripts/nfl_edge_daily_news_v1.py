#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from nfl_edge.news.pipeline_v1 import NewsPipelineError, run_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the governed NFL EDGE Daily News V1 pipeline.")
    parser.add_argument(
        "--evidence-root",
        default=os.getenv("NFL_EDGE_NEWS_EVIDENCE_ROOT", "/var/lib/nfl-edge/prospective_repo_v1"),
    )
    parser.add_argument(
        "--runtime-root",
        default=os.getenv("NFL_EDGE_NEWS_RUNTIME_ROOT", "/var/lib/nfl-edge/news_v1"),
    )
    parser.add_argument(
        "--research-command",
        default=os.getenv("NFL_EDGE_NEWS_RESEARCH_COMMAND", ""),
    )
    parser.add_argument(
        "--writer-command",
        default=os.getenv("NFL_EDGE_NEWS_WRITER_COMMAND", ""),
    )
    args = parser.parse_args()

    if not args.research_command:
        print("NFL_EDGE_NEWS_RESEARCH_COMMAND is required", file=sys.stderr)
        return 2
    if not args.writer_command:
        print("NFL_EDGE_NEWS_WRITER_COMMAND is required", file=sys.stderr)
        return 2

    try:
        result = run_pipeline(
            evidence_root=Path(args.evidence_root),
            runtime_root=Path(args.runtime_root),
            research_command=args.research_command,
            writer_command=args.writer_command,
        )
    except NewsPipelineError as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
