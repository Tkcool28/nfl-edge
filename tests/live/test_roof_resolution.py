from pathlib import Path

import pytest

from nfl_edge.live.roof import LiveRoofError, RoofResolver
from nfl_edge.live.week1_2026 import load_week1_schedule

ROOT = Path(__file__).resolve().parents[2]


def _games():
    payload = load_week1_schedule(ROOT / "data/live/2026/week1_schedule_v1.json")
    return {game["game_id"]: game for game in payload["games"]}


def test_fixed_dome_behavior_is_unchanged():
    roof = RoofResolver({}).resolve(_games()["2026_01_NO_DET"])
    assert roof.structure == "FIXED"
    assert roof.status == "CLOSED"
    assert roof.model_category == "dome"


def test_fixed_outdoors_behavior_is_unchanged():
    roof = RoofResolver({}).resolve(_games()["2026_01_ATL_PIT"])
    assert roof.structure == "OUTDOOR"
    assert roof.status == "OPEN"
    assert roof.model_category == "outdoors"


@pytest.mark.parametrize("value", ("UNKNOWN", "AJAR", ""))
def test_unsupported_retractable_roof_value_fails_closed(value):
    game = _games()["2026_01_BAL_IND"]
    resolver = RoofResolver({
        game["game_id"]: {
            "status": value,
            "source": "test",
            "source_at_utc": "2026-09-02T20:00:00Z",
        }
    })
    with pytest.raises(LiveRoofError, match="unsupported roof status"):
        resolver.resolve(game)


def test_manual_override_is_explicit_and_preserves_provenance():
    game = _games()["2026_01_BUF_HOU"]
    resolver = RoofResolver(
        {
            game["game_id"]: {
                "status": "PENDING",
                "source": "pending source",
                "source_at_utc": "2026-09-02T20:00:00Z",
            }
        },
        overrides={
            game["game_id"]: {
                "status": "OPEN",
                "source": "Houston Texans official roof announcement",
                "source_at_utc": "2026-09-13T15:30:00Z",
            }
        },
    )
    roof = resolver.resolve(game)
    assert roof.status == "OPEN"
    assert roof.model_category == "open"
    assert roof.override_applied is True
    assert roof.source == "Houston Texans official roof announcement"
    assert roof.source_at_utc == "2026-09-13T15:30:00Z"
