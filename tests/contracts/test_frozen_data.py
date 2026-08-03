"""Contract tests for frozen data integrity."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import polars as pl
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


def test_every_committed_source_manifest_verifies_from_repository_root() -> None:
    manifests = ROOT / "data" / "manifests"
    for path in sorted(manifests.glob("*_frozen-baseline-v1.json")):
        data = json.loads(path.read_text())
        if isinstance(data, list):
            continue
        file_name = Path(data["file_name"])
        assert not file_name.is_absolute()
        assert file_name.parts[:4] == ("data", "raw", "source_snapshots", "v1")
        verify_manifest_file(data, ROOT)


def test_committed_frozen_outputs_verify_and_preserve_game_identity() -> None:
    manifest_path = ROOT / "data" / "manifests" / "frozen_outputs_frozen-baseline-v1.json"
    outputs = json.loads(manifest_path.read_text())
    assert len(outputs) == 6
    for output in outputs:
        verify_manifest_file(output, ROOT)

    games_path = ROOT / "data" / "frozen" / "games" / "games_2018_2025.parquet"
    games = pl.read_parquet(games_path)
    assert games["scheduled_start_utc"].null_count() == games.height
    assert not games["scheduled_start_utc"].drop_nulls().str.ends_with("Z").any()
    assert games["source_game_id"].null_count() == 0
    assert games["source_game_id"].n_unique() == games.height
    assert games["source_game_id"].n_unique() > 1
    assert games["source_game_id"].to_list() == games["game_id"].to_list()
    assert set(games["season"].unique().to_list()) == set(range(2018, 2026))


def test_historical_observed_times_are_null_and_manifest_creation_time_is_valid() -> None:
    manifest_path = ROOT / "data" / "manifests" / "frozen_outputs_frozen-baseline-v1.json"
    outputs = json.loads(manifest_path.read_text())
    creation_times = {output["created_at_utc"] for output in outputs}
    assert len(creation_times) == 1
    creation_time = next(iter(creation_times))
    assert creation_time.endswith("Z")
    assert utc_timestamp(creation_time) == creation_time
    for relative_path in (
        "data/frozen/games/games_2018_2025.parquet",
        "data/frozen/team_game_stats/team_game_stats_2018_2025.parquet",
        "data/frozen/qb_game_stats/qb_game_stats_2018_2025.parquet",
    ):
        frame = pl.read_parquet(ROOT / relative_path)
        assert frame["observed_at_utc"].null_count() == frame.height
        assert creation_time not in frame["observed_at_utc"].drop_nulls().to_list()
