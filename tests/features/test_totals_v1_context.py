"""Tests for the narrow Totals V1 schedule-context projection."""

from __future__ import annotations

import polars as pl
import pytest

from nfl_edge.common.errors import SealedHoldoutAccessError, WalkForwardError
from nfl_edge.features.totals_v1.context import (
    APPROVED_CONTEXT_FIELDS,
    PROHIBITED_CONTEXT_FIELDS,
    ContextProjectionError,
    assert_no_prohibited_context_columns,
    find_prohibited_columns,
    project_totals_context,
)


def _schedule(extra: dict | None = None, season=2024):
    row = {
        "game_id": ["2024_01_KC_BAL"],
        "season": [season],
        "game_type": ["REG"],
        "week": [1],
        "away_rest": [7],
        "home_rest": [7],
        "roof": ["outdoors"],
        "surface": ["grass"],
        "away_score": [24],
        "home_score": [17],
        "result": [7],
        "total": [41],
        "away_moneyline": [100],
        "home_moneyline": [-120],
        "spread_line": [-2.5],
        "away_spread_odds": [-110],
        "home_spread_odds": [-110],
        "total_line": [44.5],
        "under_odds": [-110],
        "over_odds": [-110],
        "away_qb_id": ["Q1"],
        "home_qb_id": ["Q2"],
        "away_qb_name": ["QB-A"],
        "home_qb_name": ["QB-B"],
        "temp": [72],
        "wind": [8],
    }
    if extra:
        row.update(extra)
    return pl.DataFrame(row)


def test_approved_fields_survive_projection():
    sched = _schedule()
    proj = project_totals_context(sched)
    assert set(proj.columns) == set(APPROVED_CONTEXT_FIELDS)
    assert proj["game_id"].to_list() == ["2024_01_KC_BAL"]
    assert proj["away_rest"].to_list() == [7]
    assert proj["home_rest"].to_list() == [7]
    assert proj["roof"].to_list() == ["outdoors"]
    assert proj["surface"].to_list() == ["grass"]
    # game_type renamed to season_type
    assert proj["season_type"].to_list() == ["REG"]


def test_prohibited_fields_absent_after_projection():
    sched = _schedule()
    proj = project_totals_context(sched)
    found = find_prohibited_columns(proj.columns)
    assert found == []
    assert_no_prohibited_context_columns(proj)
    # none of the explicit prohibited fields present
    assert not (set(proj.columns) & PROHIBITED_CONTEXT_FIELDS)


def test_2025_season_input_hard_fails():
    sched = _schedule(season=2025)
    with pytest.raises(SealedHoldoutAccessError):
        project_totals_context(sched)


def test_below_2018_input_hard_fails():
    sched = _schedule(season=2017)
    with pytest.raises(WalkForwardError):
        project_totals_context(sched)


def test_season_2024_calendar_2025_remains_valid():
    """Season-2024 game with a 2025 calendar date stays in development context.

    The boundary is keyed on NFL season (2024), not calendar date.
    """
    sched = _schedule(extra={"game_id": ["2024_22_KC_PHI"], "game_type": ["SB"], "week": [22]}, season=2024)
    proj = project_totals_context(sched)
    assert proj["season"].to_list() == [2024]
    assert proj["game_id"].to_list() == ["2024_22_KC_PHI"]


def test_missing_approved_column_fails():
    sched = _schedule()
    sched = sched.drop("surface")
    with pytest.raises(ContextProjectionError, match="missing approved context columns"):
        project_totals_context(sched)


def test_find_prohibited_columns_detects_all_prohibited():
    cols = list(_schedule().columns)
    found = find_prohibited_columns(cols)
    for p in PROHIBITED_CONTEXT_FIELDS:
        assert p in found, f"{p} not detected as prohibited"


def test_assert_no_prohibited_fails_when_present():
    bad = pl.DataFrame({"game_id": ["a"], "result": [7], "total_line": [44.5]})
    with pytest.raises(ContextProjectionError, match="prohibited context columns"):
        assert_no_prohibited_context_columns(bad)
