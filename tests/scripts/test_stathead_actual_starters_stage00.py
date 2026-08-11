"""Structural tests for the Stathead Stage 00 raw validator."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "stathead_actual_starters" / "validate_concat_raw.py"

_spec = importlib.util.spec_from_file_location("stathead_stage00_validator", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
validator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validator)

HEADER = validator.EXPECTED_HEADER


def test_ordinary_13_field_row_is_preserved() -> None:
    row = [
        "1", "Quarterback One", "Sun", "1", "1", "2024-09-08", "25-001", "AAA", "@",
        "BBB", "W 20-10", "QB", "OneQu00",
    ]

    logical, is_bye_shape = validator.normalize_raw_row(row)

    assert logical == row
    assert is_bye_shape is False


def test_valid_12_field_bye_row_is_expanded_at_location_slot() -> None:
    raw_bye = [
        "732", "Sam Howell", "Sun", "13", "14", "2023-12-10", "23-085", "WAS", "BYE",
        "", "QB", "HoweSa00",
    ]

    logical, is_bye_shape = validator.normalize_raw_row(raw_bye)

    assert is_bye_shape is True
    assert logical == [
        "732", "Sam Howell", "Sun", "13", "14", "2023-12-10", "23-085", "WAS", "",
        "BYE", "", "QB", "HoweSa00",
    ]


def test_generic_12_field_row_is_rejected() -> None:
    generic_short_row = [
        "5", "Quarterback Five", "Sun", "1", "1", "2024-09-08", "25-001", "AAA", "@",
        "BBB", "QB", "FiveQu00",
    ]

    with pytest.raises(ValueError, match="expected 13 fields"):
        validator.normalize_raw_row(generic_short_row)


def _write_partition(path: Path, rows: list[list[str]]) -> None:
    path.write_text(
        ",".join(HEADER) + "\n" + "\n".join(",".join(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_rank_continuity_is_reported(tmp_path: Path) -> None:
    input_dir = tmp_path / "raw"
    input_dir.mkdir()
    _write_partition(
        input_dir / "ranks_0001_0002.csv",
        [
            ["1", "Q One", "Sun", "1", "1", "2024-09-08", "25-001", "AAA", "", "BBB", "", "QB", "OneQe00"],
            ["3", "Q Three", "Sun", "1", "1", "2024-09-08", "25-001", "CCC", "", "DDD", "", "QB", "ThrQe00"],
        ],
    )

    report = validator.validate_and_concatenate(
        input_dir, tmp_path / "combined.csv", tmp_path / "report.json"
    )

    assert report["structural_ok"] is False
    assert report["missing_ranks"][0] == 2


def test_duplicate_rank_is_reported(tmp_path: Path) -> None:
    input_dir = tmp_path / "raw"
    input_dir.mkdir()
    row = ["1", "Q One", "Sun", "1", "1", "2024-09-08", "25-001", "AAA", "", "BBB", "", "QB", "OneQe00"]
    _write_partition(input_dir / "ranks_0001_0001.csv", [row])
    _write_partition(input_dir / "ranks_0002_0002.csv", [row])

    report = validator.validate_and_concatenate(
        input_dir, tmp_path / "combined.csv", tmp_path / "report.json"
    )

    assert report["structural_ok"] is False
    assert report["duplicate_ranks"] == [1]
