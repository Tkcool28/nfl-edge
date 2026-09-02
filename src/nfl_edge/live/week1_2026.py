"""Deterministic NFL 2026 Week 1 schedule input for the live scorer."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEDULE_SCHEMA_VERSION = "nfl-edge-2026-week1-schedule-v1"
EXPECTED_GAMES = 16
EXPECTED_TEAMS = frozenset({
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
})
EXPECTED_CONTEXT_FIELDS = (
    "away_rest", "home_rest", "roof", "surface", "stadium_id", "stadium",
)
EXPECTED_MISSING_ROOF_GAME_IDS = frozenset({"2026_01_BAL_IND", "2026_01_BUF_HOU"})


class LiveScheduleError(RuntimeError):
    pass


def _utc(value: str, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise LiveScheduleError(f"{field} must be an RFC3339 UTC timestamp")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise LiveScheduleError(f"invalid {field}: {value!r}") from exc


def _required_text(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise LiveScheduleError(f"{field} must be a non-empty string")
    return text


def validate_week1_schedule(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEDULE_SCHEMA_VERSION:
        raise LiveScheduleError("2026 Week 1 schedule schema drift")
    if payload.get("season") != 2026 or payload.get("week") != 1:
        raise LiveScheduleError("live Week 1 schedule must be season=2026 week=1")
    games = payload.get("games")
    if not isinstance(games, list) or len(games) != EXPECTED_GAMES:
        raise LiveScheduleError(f"expected exactly {EXPECTED_GAMES} Week 1 games")
    required = {
        "game_id", "away_team", "home_team", "scheduled_start_utc", "neutral_site",
        "venue", "venue_id", "away_rest", "home_rest", "surface", "roof_type",
    }
    seen_games: set[str] = set()
    seen_teams: set[str] = set()
    missing_roof_games: set[str] = set()
    prior_key: tuple[datetime, str] | None = None
    for index, game in enumerate(games):
        if not isinstance(game, dict) or set(game) != required:
            raise LiveScheduleError(f"game[{index}] schedule fields drift")
        gid = str(game["game_id"])
        away = str(game["away_team"])
        home = str(game["home_team"])
        expected_id = f"2026_01_{away}_{home}"
        if gid != expected_id:
            raise LiveScheduleError(f"game[{index}] id {gid!r} != {expected_id!r}")
        if gid in seen_games:
            raise LiveScheduleError(f"duplicate game_id: {gid}")
        if away == home or away in seen_teams or home in seen_teams:
            raise LiveScheduleError(f"Week 1 team appears more than once: {away}/{home}")
        if away not in EXPECTED_TEAMS or home not in EXPECTED_TEAMS:
            raise LiveScheduleError(f"unknown canonical team: {away}/{home}")
        if not isinstance(game["neutral_site"], bool):
            raise LiveScheduleError(f"game[{index}].neutral_site must be boolean")
        kickoff = _utc(str(game["scheduled_start_utc"]), field=f"game[{index}].scheduled_start_utc")
        key = kickoff, gid
        if prior_key is not None and key < prior_key:
            raise LiveScheduleError("Week 1 schedule must be chronological then game_id")
        prior_key = key

        _required_text(game["venue"], field=f"game[{index}].venue")
        _required_text(game["venue_id"], field=f"game[{index}].venue_id")
        _required_text(game["surface"], field=f"game[{index}].surface")
        for rest_field in ("away_rest", "home_rest"):
            value = game[rest_field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise LiveScheduleError(f"game[{index}].{rest_field} must be a non-negative integer")
        roof = game["roof_type"]
        if roof is None:
            missing_roof_games.add(gid)
        else:
            _required_text(roof, field=f"game[{index}].roof_type")

        seen_games.add(gid)
        seen_teams.update((away, home))
    if seen_teams != EXPECTED_TEAMS:
        raise LiveScheduleError(f"Week 1 team coverage drift: missing={sorted(EXPECTED_TEAMS - seen_teams)}")
    if missing_roof_games != EXPECTED_MISSING_ROOF_GAME_IDS:
        raise LiveScheduleError(
            "Week 1 roof-context missingness drift: "
            f"observed={sorted(missing_roof_games)} expected={sorted(EXPECTED_MISSING_ROOF_GAME_IDS)}"
        )

    _utc(str(payload.get("verified_at_utc")), field="verified_at_utc")
    _utc(str(payload.get("context_verified_at_utc")), field="context_verified_at_utc")
    if not payload.get("schedule_version") or not payload.get("source_url"):
        raise LiveScheduleError("schedule provenance is incomplete")
    _required_text(payload.get("context_version"), field="context_version")
    if not payload.get("context_source") or not payload.get("context_source_url"):
        raise LiveScheduleError("football-context provenance is incomplete")
    if tuple(payload.get("context_fields") or ()) != EXPECTED_CONTEXT_FIELDS:
        raise LiveScheduleError("football-context field allowlist drift")
    if payload.get("market_fields_consumed") != []:
        raise LiveScheduleError("Week 1 football fixture must not consume market fields")
    return payload


def load_week1_schedule(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_week1_schedule(payload)


def schedule_to_frame(payload: dict[str, Any], *, prediction_as_of_utc: str):
    """Return an unrevealed Polars game frame for accepted feature builders."""
    import polars as pl

    validate_week1_schedule(payload)
    _utc(prediction_as_of_utc, field="prediction_as_of_utc")
    rows = []
    for game in payload["games"]:
        rows.append({
            "game_id": game["game_id"],
            "season": 2026,
            "season_type": "REG",
            "week": 1,
            "home_team": game["home_team"],
            "away_team": game["away_team"],
            "gameday": game["scheduled_start_utc"][:10],
            "home_score": None,
            "away_score": None,
            "target_available": False,
            "neutral_site": bool(game["neutral_site"]),
            "neutral_site_source": "neutral" if game["neutral_site"] else "home",
            "venue_id": game["venue_id"],
            "roof_type": game["roof_type"],
            "surface": game["surface"],
            "away_rest": game["away_rest"],
            "home_rest": game["home_rest"],
            "scheduled_start_utc": game["scheduled_start_utc"],
            "prediction_as_of_utc": prediction_as_of_utc,
        })
    return pl.DataFrame(rows).with_columns(
        pl.col("scheduled_start_utc").str.to_datetime(time_zone="UTC"),
        pl.col("prediction_as_of_utc").str.to_datetime(time_zone="UTC"),
        pl.col("home_score").cast(pl.Int32),
        pl.col("away_score").cast(pl.Int32),
    )
