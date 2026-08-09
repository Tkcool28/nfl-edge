#!/usr/bin/env python3
"""Validate and concatenate the preserved Stathead Task 04A raw partitions.

This is a structural-only stage. It does not decide who the actual starting QB was,
does not remove BYEs or duplicate team-game candidates, and does not touch any
existing frozen historical dataset.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

EXPECTED_HEADER = [
    "Rk",
    "Player",
    "Day",
    "G#",
    "Week",
    "Date",
    "Age",
    "Team",
    "",
    "Opp",
    "Result",
    "Pos.",
    "Player-additional",
]
EXPECTED_MIN_RANK = 1
EXPECTED_MAX_RANK = 3921


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/raw/stathead_actual_starters_v1/chat_pastes"),
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=Path(
            "data/derived/stathead_actual_starters_v1/stage00_structural/"
            "stathead_qb_started_2018_2024_raw_combined.csv"
        ),
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=Path(
            "data/derived/stathead_actual_starters_v1/stage00_structural/"
            "validation_report.json"
        ),
    )
    return parser.parse_args()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    args = parse_args()
    parts = sorted(args.input_dir.glob("ranks_*.csv"))
    if not parts:
        raise SystemExit(f"No raw partitions found under {args.input_dir}")

    rows_by_rank: dict[int, str] = {}
    malformed_rows: list[dict[str, object]] = []
    duplicate_ranks: list[int] = []
    partition_summary: list[dict[str, object]] = []

    for path in parts:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        lines = text.splitlines()
        if not lines:
            raise SystemExit(f"Empty partition: {path}")

        header = next(csv.reader([lines[0]]))
        if header != EXPECTED_HEADER:
            raise SystemExit(
                f"Unexpected header in {path}: {header!r}; expected {EXPECTED_HEADER!r}"
            )

        ranks_in_part: list[int] = []
        for line_number, line in enumerate(lines[1:], start=2):
            if not line.strip():
                continue
            parsed = next(csv.reader([line]))
            if len(parsed) != len(EXPECTED_HEADER):
                malformed_rows.append(
                    {
                        "partition": str(path),
                        "line_number": line_number,
                        "column_count": len(parsed),
                        "raw_line": line,
                    }
                )
                continue
            try:
                rank = int(parsed[0])
            except ValueError:
                malformed_rows.append(
                    {
                        "partition": str(path),
                        "line_number": line_number,
                        "column_count": len(parsed),
                        "raw_line": line,
                        "error": "non_integer_rank",
                    }
                )
                continue

            ranks_in_part.append(rank)
            if rank in rows_by_rank:
                duplicate_ranks.append(rank)
            else:
                # Keep the exact literal row text; no CSV reserialization here.
                rows_by_rank[rank] = line

        partition_summary.append(
            {
                "path": str(path),
                "sha256": sha256_bytes(raw),
                "row_count_excluding_header": len(ranks_in_part),
                "rank_min": min(ranks_in_part) if ranks_in_part else None,
                "rank_max": max(ranks_in_part) if ranks_in_part else None,
            }
        )

    observed_ranks = sorted(rows_by_rank)
    expected_ranks = list(range(EXPECTED_MIN_RANK, EXPECTED_MAX_RANK + 1))
    missing_ranks = sorted(set(expected_ranks) - set(observed_ranks))
    out_of_range_ranks = [
        r for r in observed_ranks if r < EXPECTED_MIN_RANK or r > EXPECTED_MAX_RANK
    ]

    structural_ok = not (
        malformed_rows
        or duplicate_ranks
        or missing_ranks
        or out_of_range_ranks
        or observed_ranks != expected_ranks
    )

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.parent.mkdir(parents=True, exist_ok=True)

    if structural_ok:
        header_line = ",".join(EXPECTED_HEADER)
        combined_text = header_line + "\n" + "\n".join(rows_by_rank[r] for r in expected_ranks) + "\n"
        args.output_csv.write_text(combined_text, encoding="utf-8", newline="")
        combined_sha256 = sha256_bytes(combined_text.encode("utf-8"))
    else:
        combined_sha256 = None

    report = {
        "stage": "stage00_structural_raw_validation",
        "structural_ok": structural_ok,
        "semantic_cleaning_performed": False,
        "starter_adjudication_performed": False,
        "source_partition_count": len(parts),
        "expected_rank_min": EXPECTED_MIN_RANK,
        "expected_rank_max": EXPECTED_MAX_RANK,
        "expected_row_count": EXPECTED_MAX_RANK - EXPECTED_MIN_RANK + 1,
        "observed_unique_rank_count": len(observed_ranks),
        "missing_ranks": missing_ranks,
        "duplicate_ranks": sorted(set(duplicate_ranks)),
        "out_of_range_ranks": out_of_range_ranks,
        "malformed_rows": malformed_rows,
        "partitions": partition_summary,
        "combined_output_csv": str(args.output_csv) if structural_ok else None,
        "combined_output_sha256": combined_sha256,
        "guardrails": [
            "Raw partition files are read-only evidence.",
            "No BYE rows are removed in this stage.",
            "No multiple-candidate team-games are resolved in this stage.",
            "No target-game performance statistic is used.",
            "No existing frozen historical file is modified.",
            "No 2025 NFL-season starter/performance data is accessed.",
        ],
    }
    args.report_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if structural_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
