"""NFL-season development boundary for the Totals V1 feature pipeline.

The development universe is exactly ``season >= 2018 AND season <= 2024``.
The sealed holdout is ``season == 2025``.

This is an NFL-season rule, never a calendar-year rule. Season-2024 postseason
games played in January/February 2025 (e.g. ``2024_22_KC_PHI`` on 2025-02-09)
are required development data and must remain valid. Do not use ``year !=
2025``, ``gameday < 2025-01-01``, or any date-based exclusion here.
"""

from __future__ import annotations

from typing import Iterable

import polars as pl

from ...common.errors import SealedHoldoutAccessError, WalkForwardError

DEVELOPMENT_SEASON_MIN = 2018
DEVELOPMENT_SEASON_MAX = 2024
SEALED_HOLDOUT_SEASON = 2025

# Canonical block type ordering, matching src/nfl_edge/backtest/blocks.py.
SEASON_TYPE_PRIORITY: dict[str, int] = {"REG": 0, "WC": 1, "DIV": 2, "CON": 3, "SB": 4}


def assert_development_season(season: int, *, where: str) -> None:
    """Hard-fail a single NFL season if it is below or above the development window."""
    season = int(season)
    if season > DEVELOPMENT_SEASON_MAX:
        raise SealedHoldoutAccessError(season, where, "season exceeds totals development max")
    if season < DEVELOPMENT_SEASON_MIN:
        raise WalkForwardError(where, f"season {season} below totals development min {DEVELOPMENT_SEASON_MIN}")


def assert_seasons_in_development(seasons: Iterable[int], *, where: str) -> None:
    """Hard-fail if any NFL season in ``seasons`` falls outside 2018..2024."""
    for season in seasons:
        assert_development_season(season, where=where)


def assert_frame_development_only(
    frame: pl.DataFrame,
    *,
    season_col: str = "season",
    where: str = "totals_v1",
) -> None:
    """Hard-fail a development-path frame if it contains any out-of-window NFL season.

    This is the primary tripwire for the 2025 sealed holdout. It inspects the
    NFL ``season`` column only; it never consults calendar dates. Raises
    :class:`SealedHoldoutAccessError` on season > 2024 and
    :class:`WalkForwardError` on season < 2018.
    """
    if season_col not in frame.columns:
        raise WalkForwardError(where, f"missing season column {season_col!r}")
    if frame.height == 0:
        return
    seasons = frame[season_col].unique().to_list()
    assert_seasons_in_development(seasons, where=where)
