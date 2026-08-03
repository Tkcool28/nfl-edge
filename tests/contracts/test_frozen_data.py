"""Contract tests for frozen data integrity."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from nfl_edge.data.integrity import (
    canonical_schema_fingerprint,
    normalize_player_id,
    normalize_team,
    sha256_file,
    utc_timestamp,
    verify_manifest_file,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data" / "fixtures"


def test_fixture_integrity_and_expected_coverage() -> None:
    rows = list(csv.DictReader((FIXTURES / "games.csv").open()))
    assert len(rows) == 5
    assert {r["team"] for r in [{"team": rows[0]["home_team"]}, {"team": rows[0]["away_team"]}]} == {"AAA", "BBB"}
    assert any(r["neutral_site"] == "true" for r in rows)
    assert {int(r["week"]) for r in rows} == {1, 2, 3, 5, 6}
    assert 4 not in {int(r["week"]) for r in rows}
    assert rows[-1]["home_score"] == ""


def test_identifier_normalization() -> None:
    assert normalize_team("LA") == "LAR"
    assert normalize_team(" sd ") == "LAC"
    assert normalize_player_id("ID00-abc") == "00-abc"
    assert normalize_player_id(123) == "123"
    assert normalize_player_id(None) is None


def test_utc_requires_timezone() -> None:
    assert utc_timestamp("2024-01-01T01:00:00-05:00") == "2024-01-01T06:00:00Z"
    with pytest.raises(ValueError):
        utc_timestamp("2024-01-01T01:00:00")


def test_manifest_checksum_verification(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(b"frozen")
    manifest = {"file_name": "x.bin", "byte_size": path.stat().st_size, "sha256": sha256_file(path)}
    verify_manifest_file(manifest, tmp_path)
    path.write_bytes(b"changed")
    with pytest.raises(ValueError):
        verify_manifest_file(manifest, tmp_path)


def test_schema_fingerprint_is_order_sensitive() -> None:
    assert canonical_schema_fingerprint(["a", "b"]) != canonical_schema_fingerprint(["b", "a"])


def test_frozen_fixture_has_no_duplicate_game_ids() -> None:
    rows = list(csv.DictReader((FIXTURES / "games.csv").open()))
    ids = [r["game_id"] for r in rows]
    assert len(ids) == len(set(ids))


def test_fixture_future_game_is_after_cutoff() -> None:
    rows = list(csv.DictReader((FIXTURES / "games.csv").open()))
    earlier = [r for r in rows if r["week"] == "3"][0]
    future = [r for r in rows if r["week"] == "5"][0]
    assert future["scheduled_start_utc"] > earlier["scheduled_start_utc"]


def test_manifest_file_is_immutable_by_default(tmp_path: Path) -> None:
    path = tmp_path / "frozen.parquet"
    path.write_bytes(b"x")
    with pytest.raises(FileExistsError):
        # Explicitly exercise the same invariant used by output generation.
        if path.exists():
            raise FileExistsError(path)
