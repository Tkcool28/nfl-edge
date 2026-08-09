#!/usr/bin/env python3
"""Validate and concatenate preserved Stathead Task 04A raw partitions.

This is a structural-only stage. It neither decides actual starting QBs nor
removes BYEs or duplicate team-game candidates.  A documented Stathead raw
BYE export shape omits the empty location field: it has 12 physical CSV fields
rather than the ordinary 13 logical fields.  That shape alone is expanded in
memory and in the derived combined output; raw source bytes remain untouched.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

EXPECTED_HEADER = [
    "Rk", "Player", "Day", "G#", "Week", "Date", "Age", "Team", "", "Opp",
    "Result", "Pos.", "Player-additional",
]
EXPECTED_MIN_RANK = 1
EXPECTED_MAX_RANK = 3921
BYE_RAW_FIELD_COUNT = 12


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir", type=Path,
        default=Path("data/raw/stathead_actual_starters_v1/chat_pastes"),
    )
    parser.add_argument(
        "--output-csv", type=Path,
        default=Path("data/derived/stathead_actual_starters_v1/stage00_structural/"
                     "stathead_qb_started_2018_2024_raw_combined.csv"),
    )
    parser.add_argument(
        "--report-json", type=Path,
        default=Path("data/derived/stathead_actual_starters_v1/stage00_structural/"
                     "validation_report.json"),
    )
    return parser.parse_args()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalize_raw_row(parsed: list[str]) -> tuple[list[str], bool]:
    """Return 13 logical fields, accepting only the documented raw BYE shape.

    Raw BYE exports place ``BYE`` immediately after ``Team`` and omit the
    empty location field.  They must otherwise have the fixed suffix
    ``BYE,\"\",QB,<player-id>``.  No other 12-field row is normalized.
    """
    if len(parsed) == len(EXPECTED_HEADER):
        return parsed, False
    if (
        len(parsed) == BYE_RAW_FIELD_COUNT
        and parsed[8] == "BYE"
        and parsed[9] == ""
        and parsed[10] == "QB"
        and bool(parsed[11])
    ):
        return [*parsed[:8], "", *parsed[8:]], True
    raise ValueError(
        f"expected {len(EXPECTED_HEADER)} fields or recognised raw BYE "
        f"shape, got {len(parsed)}"
    )


def csv_line(fields: list[str]) -> str:
    """Serialize a normalized derived-only row without changing source bytes."""
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="").writerow(fields)
    return buffer.getvalue()


def validate_and_concatenate(
    input_dir: Path, output_csv: Path, report_json: Path
) -> dict[str, Any]:
    """Validate raw partitions and write derived outputs/report; never edit input."""
    parts = sorted(input_dir.glob("ranks_*.csv"))
    if not parts:
        raise SystemExit(f"No raw partitions found under {input_dir}")

    rows_by_rank: dict[int, str] = {}
    malformed_rows: list[dict[str, object]] = []
    duplicate_ranks: list[int] = []
    bye_shape_rows: list[dict[str, object]] = []
    partition_summary: list[dict[str, object]] = []
    physical_raw_row_count = 0

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
        for line_number, source_raw_line in enumerate(lines[1:], start=2):
            if not source_raw_line.strip():
                continue
            physical_raw_row_count += 1
            parsed = next(csv.reader([source_raw_line]))
            try:
                logical_fields, is_bye_shape = normalize_raw_row(parsed)
            except ValueError as exc:
                malformed_rows.append({
                    "partition": str(path), "line_number": line_number,
                    "column_count": len(parsed), "raw_line": source_raw_line,
                    "error": str(exc),
                })
                continue
            try:
                rank = int(logical_fields[0])
            except ValueError:
                malformed_rows.append({
                    "partition": str(path), "line_number": line_number,
                    "column_count": len(parsed), "raw_line": source_raw_line,
                    "error": "non_integer_rank",
                })
                continue

            ranks_in_part.append(rank)
            output_line = csv_line(logical_fields) if is_bye_shape else source_raw_line
            if is_bye_shape:
                bye_shape_rows.append({
                    "partition": str(path), "line_number": line_number, "rank": rank,
                    "source_raw_line": source_raw_line,
                    "normalized_output_line": output_line,
                })
            if rank in rows_by_rank:
                duplicate_ranks.append(rank)
            else:
                rows_by_rank[rank] = output_line

        partition_summary.append({
            "path": str(path), "sha256": sha256_bytes(raw),
            "row_count_excluding_header": len(ranks_in_part),
            "rank_min": min(ranks_in_part) if ranks_in_part else None,
            "rank_max": max(ranks_in_part) if ranks_in_part else None,
        })

    observed_ranks = sorted(rows_by_rank)
    expected_ranks = list(range(EXPECTED_MIN_RANK, EXPECTED_MAX_RANK + 1))
    missing_ranks = sorted(set(expected_ranks) - set(observed_ranks))
    out_of_range_ranks = [
        rank for rank in observed_ranks
        if rank < EXPECTED_MIN_RANK or rank > EXPECTED_MAX_RANK
    ]
    structural_ok = not (
        malformed_rows or duplicate_ranks or missing_ranks or out_of_range_ranks
        or observed_ranks != expected_ranks
    )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    report_json.parent.mkdir(parents=True, exist_ok=True)
    if structural_ok:
        combined_text = ",".join(EXPECTED_HEADER) + "\n" + "\n".join(
            rows_by_rank[rank] for rank in expected_ranks
        ) + "\n"
        output_csv.write_text(combined_text, encoding="utf-8", newline="")
        combined_sha256: str | None = sha256_bytes(combined_text.encode("utf-8"))
    else:
        combined_sha256 = None

    report: dict[str, Any] = {
        "stage": "stage00_structural_raw_validation",
        "structural_ok": structural_ok,
        "semantic_cleaning_performed": False,
        "starter_adjudication_performed": False,
        "source_partition_count": len(parts),
        "physical_raw_row_count_excluding_headers": physical_raw_row_count,
        "expected_rank_min": EXPECTED_MIN_RANK,
        "expected_rank_max": EXPECTED_MAX_RANK,
        "expected_row_count": EXPECTED_MAX_RANK - EXPECTED_MIN_RANK + 1,
        "observed_unique_rank_count": len(observed_ranks),
        "missing_ranks": missing_ranks,
        "duplicate_ranks": sorted(set(duplicate_ranks)),
        "out_of_range_ranks": out_of_range_ranks,
        "malformed_rows": malformed_rows,
        "bye_shape_exception_count": len(bye_shape_rows),
        "bye_shape_rows": bye_shape_rows,
        "partitions": partition_summary,
        "combined_output_csv": str(output_csv) if structural_ok else None,
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
    report_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    args = parse_args()
    report = validate_and_concatenate(args.input_dir, args.output_csv, args.report_json)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["structural_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
