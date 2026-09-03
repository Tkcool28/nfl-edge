from pathlib import Path

from nfl_edge.live.week1_2026 import EXPECTED_TEAMS, load_week1_schedule, schedule_to_frame

ROOT = Path(__file__).resolve().parents[2]


def test_official_week1_schedule_is_complete_and_unrevealed():
    payload = load_week1_schedule(ROOT / "data/live/2026/week1_schedule_v1.json")
    assert len(payload["games"]) == 16
    teams = {g[side] for g in payload["games"] for side in ("away_team", "home_team")}
    assert teams == EXPECTED_TEAMS
    assert sum(bool(g["neutral_site"]) for g in payload["games"]) == 1
    assert payload["games"][1]["game_id"] == "2026_01_SF_LAR"

    frame = schedule_to_frame(payload, prediction_as_of_utc="2026-09-02T18:00:00Z")
    assert frame.height == 16
    assert frame["target_available"].to_list() == [False] * 16
    assert frame["home_score"].null_count() == 16
    assert frame["away_score"].null_count() == 16
