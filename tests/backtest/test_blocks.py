"""Tests for the walk-forward block builder and 2025 tripwire."""

from __future__ import annotations

from datetime import datetime, timezone

import polars as pl
import pytest

from nfl_edge.backtest.blocks import (
    DEVELOPMENT_SEASON_MAX,
    FORWARD_USE_SEASON,
    SEALED_HOLDOUT_SEASON,
    PredictionBlock,
    assert_development_seasons_only,
    build_development_blocks,
)
from nfl_edge.common.errors import SealedHoldoutAccessError, WalkForwardError


def _dev_game(season: int, week: int, game_id: str = None, season_type: str = "REG") -> dict:
    return {
        "game_id": game_id or f"{season}_{week:02d}_A_B",
        "season": season,
        "season_type": season_type,
        "week": week,
        "prediction_as_of_utc": datetime(season, 9, 1, 12, 0, tzinfo=timezone.utc),
    }


def test_constants_documented():
    assert DEVELOPMENT_SEASON_MAX == 2024
    assert SEALED_HOLDOUT_SEASON == 2025
    assert FORWARD_USE_SEASON == 2026


def test_build_development_blocks_filters_2025():
    games = pl.DataFrame([
        _dev_game(2024, 1),
        _dev_game(2025, 1),  # sealed holdout
    ])
    blocks = build_development_blocks(games)
    # Only 2024 block should remain
    assert len(blocks) == 1
    assert blocks[0].season == 2024


def test_build_development_blocks_empty_input():
    games = pl.DataFrame([], schema={
        "game_id": pl.Utf8,
        "season": pl.Int64,
        "season_type": pl.Utf8,
        "week": pl.Int64,
        "prediction_as_of_utc": pl.Datetime(time_zone="UTC"),
    })
    assert build_development_blocks(games) == []


def test_build_development_blocks_orders_chronologically():
    games = pl.DataFrame([
        _dev_game(2024, 3),
        _dev_game(2020, 1),
        _dev_game(2022, 2),
    ])
    blocks = build_development_blocks(games)
    seasons = [b.season for b in blocks]
    assert seasons == [2020, 2022, 2024]


def test_prediction_block_rejects_2025():
    with pytest.raises(SealedHoldoutAccessError):
        PredictionBlock(
            block_id="2025_REG_W01",
            season=2025,
            season_type="REG",
            week=1,
            as_of_utc=datetime(2025, 9, 1, 12, 0, tzinfo=timezone.utc),
            game_ids=("2025_01_A_B",),
        )


def test_prediction_block_rejects_empty_game_ids():
    with pytest.raises(WalkForwardError):
        PredictionBlock(
            block_id="2024_REG_W01",
            season=2024,
            season_type="REG",
            week=1,
            as_of_utc=datetime(2024, 9, 1, 12, 0, tzinfo=timezone.utc),
            game_ids=(),
        )


def test_assert_development_seasons_only_passes_dev():
    games = pl.DataFrame([_dev_game(2024, 1)])
    assert_development_seasons_only(games)  # should not raise


def test_assert_development_seasons_only_fails_on_2025():
    games = pl.DataFrame([_dev_game(2025, 1)])
    with pytest.raises(SealedHoldoutAccessError):
        assert_development_seasons_only(games)


def test_assert_development_seasons_only_empty_input():
    games = pl.DataFrame([], schema={
        "game_id": pl.Utf8,
        "season": pl.Int64,
        "season_type": pl.Utf8,
        "week": pl.Int64,
        "prediction_as_of_utc": pl.Datetime(time_zone="UTC"),
    })
    assert_development_seasons_only(games)  # should not raise
