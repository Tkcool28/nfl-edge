"""DST-aware kickoff conversion and clustering primitives (Task 05E-C3 §D/E)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from nfl_edge.market_data.kickoffs import (
    build_clusters,
    gameday_gametime_to_utc,
    load_kickoff_frame,
)
from nfl_edge.market_data.manifest import SCHEDULE_SOURCE_PATH


def _as(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


# --- DST-aware conversion ---------------------------------------------------

def test_dst_winter_is_utc_minus_5():
    # 2020-01-05 is winter (EST, UTC-5): 13:00 local -> 18:00 UTC.
    assert gameday_gametime_to_utc("2020-01-05", "13:00") == _as("2020-01-05T18:00:00Z")


def test_dst_summer_is_utc_minus_4():
    # 2020-09-13 (EDT, UTC-4): 13:00 local -> 17:00 UTC.
    assert gameday_gametime_to_utc("2020-09-13", "13:00") == _as("2020-09-13T17:00:00Z")


def test_dst_offset_changes_within_a_year():
    # DST-aware conversion: the same wall-clock time maps to a *different* UTC
    # hour depending on the season. Inspect the Eastern offset at the naive
    # local time (post-conversion datetimes are UTC, always offset 0).
    from datetime import datetime
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    winter = datetime(2020, 1, 5, 13, 0, tzinfo=ny)   # EST, UTC-5
    summer = datetime(2020, 9, 13, 13, 0, tzinfo=ny)  # EDT, UTC-4
    assert winter.utcoffset() == timedelta(hours=-5)
    assert summer.utcoffset() == timedelta(hours=-4)


def test_wrong_types_fail_closed():
    with pytest.raises(TypeError):
        gameday_gametime_to_utc(20200105, "13:00")  # type: ignore[arg-type]


# --- schedule scoping -------------------------------------------------------

def test_load_kickoff_frame_seasons_are_2020_2024_only():
    frame = load_kickoff_frame(SCHEDULE_SOURCE_PATH)
    assert set(frame.get_column("season").unique().to_list()) == {2020, 2021, 2022, 2023, 2024}


def test_cluster_seasons_block_outside_2020_2024():
    frame = load_kickoff_frame(SCHEDULE_SOURCE_PATH)
    clusters = build_clusters(frame)
    seasons = sorted({c.season for c in clusters})
    assert seasons == [2020, 2021, 2022, 2023, 2024]


# --- deterministic clustering ----------------------------------------------

def test_clustering_is_deterministic():
    frame = load_kickoff_frame(SCHEDULE_SOURCE_PATH)
    key = lambda cs: [(c.request_plan_id, c.game_ids, c.anchor_utc) for c in cs]  # noqa: E731
    assert key(build_clusters(frame)) == key(build_clusters(frame))


def test_cluster_width_never_exceeds_30_minutes():
    frame = load_kickoff_frame(SCHEDULE_SOURCE_PATH)
    for c in build_clusters(frame):
        assert c.width_minutes <= 30.0, c.cluster_id