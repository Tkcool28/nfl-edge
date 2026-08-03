"""Tests for deterministic retrieval without live network access."""

from pathlib import Path

import polars as pl
import pytest

from nfl_edge.data.audit import retrieve_sources


def test_retrieval_requires_explicit_seasons_and_refuses_overwrite(tmp_path: Path) -> None:
    def loader(name: str, seasons: list[int]) -> pl.DataFrame:
        return pl.DataFrame({"season": seasons, "source": [name] * len(seasons)})

    raw = tmp_path / "raw"
    manifests = retrieve_sources(
        [2024], raw, tmp_path / "manifests",
        retrieved_at_utc="2026-01-01T00:00:00Z", loader=loader,
    )
    assert len(manifests) == 7
    assert all(item["row_count"] == 1 for item in manifests)
    with pytest.raises(FileExistsError):
        retrieve_sources([2024], raw, tmp_path / "manifests2", retrieved_at_utc="2026-01-01T00:00:00Z", loader=loader)


def test_retrieval_empty_season_list_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        retrieve_sources([], tmp_path / "raw", tmp_path / "manifests", loader=lambda *_: pl.DataFrame())
