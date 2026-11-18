"""The NFL's November 9, 2026 Week 11 flex decision and its replay boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

CORRECTION_ID = "NFL_2026_REG_WEEK11_FLEX_20261109_V1"
ANNOUNCEMENT = "https://www.nfl.com/news/week-11-schedule-change"
ORIGINAL_ESPN_RESPONSE_SHA256 = "9104027621c0b36d9496a41c3f4e8dcd18b7893e7412abb40f0d77bbf5e1478b"


@dataclass(frozen=True)
class FlexGame:
    away: str
    home: str
    old_local: str
    new_local: str
    old_utc: str
    new_utc: str
    espn_id: str

    @property
    def game_id(self) -> str:
        return f"2026_11_{self.away}_{self.home}"

    def check_source_identity(self, row: Mapping[str, Any]) -> bool:
        return (
            str(row.get("season")) == "2026"
            and str(row.get("week")) == "11"
            and row.get("game_type") == "REG"
            and row.get("game_id") == self.game_id
            and row.get("away_team") == self.away
            and row.get("home_team") == self.home
            and row.get("gameday") == "2026-11-22"
        )


FLEX_GAMES = {
    game.game_id: game
    for game in (
        FlexGame("JAX", "NYG", "13:00", "16:25", "2026-11-22T18:00:00Z", "2026-11-22T21:25:00Z", "401873069"),
        FlexGame("PIT", "PHI", "16:25", "13:00", "2026-11-22T21:25:00Z", "2026-11-22T18:00:00Z", "401873076"),
    )
}


class Week11FlexError(ValueError):
    """The source or canonical schedule fell outside the reviewed decision."""


def reconcile_week11_flex(
    rows: list[Mapping[str, Any]], games: list[dict[str, Any]],
) -> dict[str, Any]:
    source = {str(row.get("game_id")): row for row in rows}
    canonical = {game["game_id"]: game for game in games}
    decisions = []
    for gid, flex in FLEX_GAMES.items():
        row = source.get(gid, {})
        game = canonical.get(gid, {})
        if (
            sum(row.get("game_id") == gid for row in rows) != 1
            or not flex.check_source_identity(row)
            or (game.get("away_team"), game.get("home_team")) != (flex.away, flex.home)
        ):
            raise Week11FlexError(f"{CORRECTION_ID}: source or canonical identity mismatch for {gid}")
        expected = {flex.old_local: flex.old_utc, flex.new_local: flex.new_utc}.get(row.get("gametime"))
        if expected is None or game["scheduled_start_utc"] != expected:
            raise Week11FlexError(f"{CORRECTION_ID}: unsupported nflverse kickoff for {gid}")
        game["scheduled_start_utc"] = flex.new_utc
        decisions.append({
            "game_id": gid,
            "away_team": flex.away,
            "home_team": flex.home,
            "original_nflverse_kickoff_utc": flex.old_utc,
            "observed_nflverse_kickoff_utc": expected,
            "official_kickoff_utc": flex.new_utc,
            "espn_event_id": flex.espn_id,
        })
    return {
        "correction_id": CORRECTION_ID,
        "season": 2026,
        "season_type": "REG",
        "week": 11,
        "official_source_url": ANNOUNCEMENT,
        "official_announcement_date": "2026-11-09",
        "reference_espn_response_sha256": ORIGINAL_ESPN_RESPONSE_SHA256,
        "games": decisions,
    }
