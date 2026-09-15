from __future__ import annotations

import pytest

from nfl_edge.live.schedule_2026 import LiveScheduleError, validate_schedule
from nfl_edge.live.schedule_materializer_2026 import (
    ScheduleMaterializationError,
    build_week_schedule,
)


def _row(*, away_team: str = "SF", home_team: str = "LA") -> dict[str, object]:
    return {
        "season": "2026",
        "game_type": "REG",
        "week": "2",
        "gameday": "2026-09-17",
        "gametime": "20:15",
        "away_team": away_team,
        "home_team": home_team,
        "stadium": "Test Stadium",
        "stadium_id": "TEST00",
        "away_rest": "7",
        "home_rest": "7",
        "surface": "grass",
        "roof": "outdoors",
        "location": "Home",
    }


def test_nflverse_la_alias_materializes_as_canonical_lar() -> None:
    payload = build_week_schedule(
        [_row()],
        season=2026,
        week=2,
        observed_at_utc="2026-09-15T21:00:00Z",
    )

    game = payload["games"][0]
    assert game["away_team"] == "SF"
    assert game["home_team"] == "LAR"
    assert game["game_id"] == "2026_02_SF_LAR"


def test_canonical_nflverse_team_codes_pass_through_unchanged() -> None:
    payload = build_week_schedule(
        [_row(away_team="BUF", home_team="MIA")],
        season=2026,
        week=2,
        observed_at_utc="2026-09-15T21:00:00Z",
    )

    game = payload["games"][0]
    assert game["away_team"] == "BUF"
    assert game["home_team"] == "MIA"
    assert game["game_id"] == "2026_02_BUF_MIA"


def test_unknown_nflverse_team_code_fails_closed_before_canonical_schedule() -> None:
    with pytest.raises(ScheduleMaterializationError, match="unsupported nflverse team code 'XYZ'"):
        build_week_schedule(
            [_row(home_team="XYZ")],
            season=2026,
            week=2,
            observed_at_utc="2026-09-15T21:00:00Z",
        )


def test_canonical_schedule_contract_still_rejects_raw_source_alias() -> None:
    payload = build_week_schedule(
        [_row()],
        season=2026,
        week=2,
        observed_at_utc="2026-09-15T21:00:00Z",
    )
    payload["games"][0]["home_team"] = "LA"
    payload["games"][0]["game_id"] = "2026_02_SF_LA"

    with pytest.raises(LiveScheduleError, match="invalid canonical teams"):
        validate_schedule(payload)
