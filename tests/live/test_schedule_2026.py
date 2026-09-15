from __future__ import annotations

import json
from pathlib import Path

import pytest

from nfl_edge.live.schedule_2026 import LiveScheduleError, load_schedule, resolve_active_schedule, rollover_at_utc


def make_schedule(week: int, kickoff: str, away: str, home: str) -> dict:
    return {
        "schema_version": "nfl-edge-live-schedule-v1",
        "schedule_version": f"TEST_WEEK_{week}",
        "season": 2026,
        "week": week,
        "source": "test",
        "source_url": "https://www.nfl.com/schedules/2026/",
        "verified_at_utc": "2026-09-01T00:00:00Z",
        "context_version": f"TEST_CONTEXT_{week}",
        "context_source": "test",
        "context_source_url": "https://github.com/nflverse/nfldata",
        "context_verified_at_utc": "2026-09-01T00:00:00Z",
        "context_fields": ["away_rest", "home_rest", "roof", "surface", "stadium_id", "stadium"],
        "market_fields_consumed": [],
        "games": [{
            "game_id": f"2026_{week:02d}_{away}_{home}",
            "away_team": away,
            "home_team": home,
            "scheduled_start_utc": kickoff,
            "neutral_site": False,
            "venue": "Test Stadium",
            "venue_id": "TEST00",
            "away_rest": 7,
            "home_rest": 7,
            "surface": "grass",
            "roof_type": "outdoors",
            "roof_structure": "OUTDOOR",
            "context_source_at_utc": "2026-09-01T00:00:00Z",
        }],
    }


def write_schedule(root: Path, payload: dict) -> Path:
    week = int(payload["week"])
    path = root / "data" / "live" / "2026" / f"week{week}_schedule_v1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_generic_schedule_allows_less_than_16_games(tmp_path: Path) -> None:
    path = write_schedule(tmp_path, make_schedule(2, "2026-09-17T00:15:00Z", "DET", "BUF"))
    loaded = load_schedule(path)
    assert loaded["week"] == 2
    assert len(loaded["games"]) == 1


def test_week2_rollover_is_tuesday_0600_denver() -> None:
    payload = make_schedule(2, "2026-09-17T00:15:00Z", "DET", "BUF")
    assert rollover_at_utc(payload).isoformat() == "2026-09-15T12:00:00+00:00"


def test_active_week_changes_at_tuesday_boundary(tmp_path: Path) -> None:
    write_schedule(tmp_path, make_schedule(1, "2026-09-10T00:20:00Z", "NE", "SEA"))
    write_schedule(tmp_path, make_schedule(2, "2026-09-17T00:15:00Z", "DET", "BUF"))
    before = resolve_active_schedule(tmp_path, prediction_as_of_utc="2026-09-15T11:59:59Z")
    after = resolve_active_schedule(tmp_path, prediction_as_of_utc="2026-09-15T12:00:00Z")
    assert before.week == 1
    assert after.week == 2


def test_missing_next_week_fails_closed_after_rollover(tmp_path: Path) -> None:
    write_schedule(tmp_path, make_schedule(1, "2026-09-10T00:20:00Z", "NE", "SEA"))
    with pytest.raises(LiveScheduleError):
        resolve_active_schedule(tmp_path, prediction_as_of_utc="2026-09-15T12:00:00Z")
