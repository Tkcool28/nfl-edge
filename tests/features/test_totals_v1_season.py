"""Tests for the NFL-season development boundary (2018..2024) and 2025 tripwire."""

from __future__ import annotations

import polars as pl
import pytest

from nfl_edge.common.errors import SealedHoldoutAccessError, WalkForwardError
from nfl_edge.features.totals_v1.season import (
    DEVELOPMENT_SEASON_MAX,
    DEVELOPMENT_SEASON_MIN,
    SEALED_HOLDOUT_SEASON,
    assert_development_season,
    assert_frame_development_only,
    assert_seasons_in_development,
)


def _frame(seasons) -> pl.DataFrame:
    return pl.DataFrame({"season": seasons, "game_id": [f"g{i}" for i in range(len(seasons))]})


def test_constants():
    assert DEVELOPMENT_SEASON_MIN == 2018
    assert DEVELOPMENT_SEASON_MAX == 2024
    assert SEALED_HOLDOUT_SEASON == 2025


@pytest.mark.parametrize("season", [2018, 2019, 2020, 2021, 2022, 2023, 2024])
def test_development_season_passes(season):
    assert_development_season(season, where="t")  # should not raise


def test_2025_hard_fails():
    with pytest.raises(SealedHoldoutAccessError):
        assert_development_season(2025, where="t")


def test_below_2018_hard_fails():
    with pytest.raises(WalkForwardError):
        assert_development_season(2017, where="t")


def test_frame_with_2025_hard_fails():
    with pytest.raises(SealedHoldoutAccessError):
        assert_frame_development_only(_frame([2024, 2025]), where="t")


def test_frame_all_dev_passes():
    assert_frame_development_only(_frame([2018, 2024]), where="t")  # no raise


def test_frame_below_min_fails():
    with pytest.raises(WalkForwardError):
        assert_frame_development_only(_frame([2017]), where="t")


def test_seasons_in_development():
    assert_seasons_in_development([2018, 2024], where="t")  # no raise


def test_nfl_season_2024_calendar_2025_date_remains_valid():
    """Season-2024 postseason played in calendar 2025 must remain valid.

    The boundary is keyed only on the NFL season column, not the calendar date.
    """
    frame = pl.DataFrame(
        {
            "season": [2024, 2024],
            "game_id": ["2024_22_KC_PHI", "2024_19_WAS_TB"],
            "gameday": ["2025-02-09", "2025-01-12"],  # calendar dates in 2025
        }
    )
    # Season column is 2024 -> valid; a calendar-based exclusion would wrongly reject.
    assert_frame_development_only(frame, season_col="season", where="t")


def test_missing_season_col_fails():
    frame = pl.DataFrame({"game_id": ["a"]})
    with pytest.raises(WalkForwardError):
        assert_frame_development_only(frame, season_col="season", where="t")
