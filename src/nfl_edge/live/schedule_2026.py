"""Generic 2026 regular-season schedule contract and Tuesday active-week resolver."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SCHEDULE_SCHEMA_VERSION = "nfl-edge-live-schedule-v1"
DENVER = ZoneInfo("America/Denver")
ROLLOVER_LOCAL_TIME = time(6, 0)
EXPECTED_CONTEXT_FIELDS = (
    "away_rest", "home_rest", "roof", "surface", "stadium_id", "stadium",
)
EXPECTED_TEAMS = frozenset({
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
})
_WEEK_FILE_RE = re.compile(r"^week(?P<week>\d+)_schedule_v1\.json$")


class LiveScheduleError(RuntimeError):
    """Raised when a live regular-season schedule cannot be trusted."""


@dataclass(frozen=True)
class ActiveSchedule:
    path: Path
    payload: dict[str, Any]
    rollover_at_utc: str

    @property
    def season(self) -> int:
        return int(self.payload["season"])

    @property
    def week(self) -> int:
        return int(self.payload["week"])


def _utc(value: str, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise LiveScheduleError(f"{field} must be an RFC3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise LiveScheduleError(f"invalid {field}: {value!r}") from exc
    return parsed.astimezone(timezone.utc)


def _required_text(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise LiveScheduleError(f"{field} must be a non-empty string")
    return text


def _schema_matches(payload: dict[str, Any], *, season: int, week: int) -> bool:
    schema = str(payload.get("schema_version") or "")
    return schema in {
        SCHEDULE_SCHEMA_VERSION,
        f"nfl-edge-{season}-week{week}-schedule-v1",
    }


def validate_schedule(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LiveScheduleError("live schedule root must be an object")
    season = payload.get("season")
    week = payload.get("week")
    if isinstance(season, bool) or not isinstance(season, int) or season != 2026:
        raise LiveScheduleError("live 2026 schedule must use season=2026")
    if isinstance(week, bool) or not isinstance(week, int) or not 1 <= week <= 18:
        raise LiveScheduleError("regular-season week must be in 1..18")
    if not _schema_matches(payload, season=season, week=week):
        raise LiveScheduleError("live schedule schema drift")

    games = payload.get("games")
    if not isinstance(games, list) or not 1 <= len(games) <= 16:
        raise LiveScheduleError("regular-season schedule must contain 1..16 games")

    required = {
        "game_id", "away_team", "home_team", "scheduled_start_utc", "neutral_site",
        "venue", "venue_id", "away_rest", "home_rest", "surface", "roof_type",
        "roof_structure", "context_source_at_utc",
    }
    seen_games: set[str] = set()
    seen_teams: set[str] = set()
    prior_key: tuple[datetime, str] | None = None
    for index, game in enumerate(games):
        if not isinstance(game, dict) or set(game) != required:
            raise LiveScheduleError(f"game[{index}] schedule fields drift")
        away = str(game["away_team"])
        home = str(game["home_team"])
        if away not in EXPECTED_TEAMS or home not in EXPECTED_TEAMS or away == home:
            raise LiveScheduleError(f"game[{index}] has invalid canonical teams: {away}/{home}")
        gid = str(game["game_id"])
        expected_id = f"{season}_{week:02d}_{away}_{home}"
        if gid != expected_id:
            raise LiveScheduleError(f"game[{index}] id {gid!r} != {expected_id!r}")
        if gid in seen_games:
            raise LiveScheduleError(f"duplicate game_id: {gid}")
        if away in seen_teams or home in seen_teams:
            raise LiveScheduleError(f"team appears more than once in Week {week}: {away}/{home}")
        if not isinstance(game["neutral_site"], bool):
            raise LiveScheduleError(f"game[{index}].neutral_site must be boolean")

        kickoff = _utc(str(game["scheduled_start_utc"]), field=f"game[{index}].scheduled_start_utc")
        key = kickoff, gid
        if prior_key is not None and key < prior_key:
            raise LiveScheduleError("schedule must be chronological then game_id")
        prior_key = key

        _required_text(game["venue"], field=f"game[{index}].venue")
        _required_text(game["venue_id"], field=f"game[{index}].venue_id")
        _required_text(game["surface"], field=f"game[{index}].surface")
        for rest_field in ("away_rest", "home_rest"):
            value = game[rest_field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise LiveScheduleError(f"game[{index}].{rest_field} must be a non-negative integer")
        structure = str(game["roof_structure"]).upper()
        roof = game["roof_type"]
        if structure not in {"FIXED", "OUTDOOR", "RETRACTABLE"}:
            raise LiveScheduleError(f"game[{index}].roof_structure is unsupported")
        if structure == "RETRACTABLE":
            if roof is not None:
                raise LiveScheduleError(f"game[{index}] retractable roof must be resolved separately")
        elif structure == "FIXED":
            if roof != "dome":
                raise LiveScheduleError(f"game[{index}] fixed roof must use dome")
        elif roof != "outdoors":
            raise LiveScheduleError(f"game[{index}] outdoor venue must use outdoors")
        _utc(str(game["context_source_at_utc"]), field=f"game[{index}].context_source_at_utc")

        seen_games.add(gid)
        seen_teams.update((away, home))

    _utc(str(payload.get("verified_at_utc")), field="verified_at_utc")
    _utc(str(payload.get("context_verified_at_utc")), field="context_verified_at_utc")
    _required_text(payload.get("schedule_version"), field="schedule_version")
    _required_text(payload.get("source_url"), field="source_url")
    _required_text(payload.get("context_version"), field="context_version")
    _required_text(payload.get("context_source"), field="context_source")
    _required_text(payload.get("context_source_url"), field="context_source_url")
    if tuple(payload.get("context_fields") or ()) != EXPECTED_CONTEXT_FIELDS:
        raise LiveScheduleError("football-context field allowlist drift")
    if payload.get("market_fields_consumed") != []:
        raise LiveScheduleError("football schedule must not consume market fields")
    return payload


def load_schedule(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_schedule(payload)


def schedule_to_frame(payload: dict[str, Any], *, prediction_as_of_utc: str):
    import polars as pl

    validate_schedule(payload)
    _utc(prediction_as_of_utc, field="prediction_as_of_utc")
    season = int(payload["season"])
    week = int(payload["week"])
    rows = []
    for game in payload["games"]:
        rows.append({
            "game_id": game["game_id"],
            "season": season,
            "season_type": "REG",
            "week": week,
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
            "roof_structure": game["roof_structure"],
            "context_source_at_utc": game["context_source_at_utc"],
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


def rollover_at_utc(payload: dict[str, Any]) -> datetime:
    """Tuesday 06:00 America/Denver preceding the first kickoff in the slate."""
    validate_schedule(payload)
    first = min(_utc(str(game["scheduled_start_utc"]), field="scheduled_start_utc") for game in payload["games"])
    local = first.astimezone(DENVER)
    days_since_tuesday = (local.weekday() - 1) % 7
    rollover_date = (local - timedelta(days=days_since_tuesday)).date()
    return datetime.combine(rollover_date, ROLLOVER_LOCAL_TIME, tzinfo=DENVER).astimezone(timezone.utc)


def _schedule_files(
    repository_root: Path,
    *,
    season: int,
    schedule_root: Path | None = None,
) -> list[tuple[Path, dict[str, Any]]]:
    base = schedule_root if schedule_root is not None else repository_root / "data" / "live" / str(season)
    found: list[tuple[Path, dict[str, Any]]] = []
    if not base.is_dir():
        return found
    for path in sorted(base.glob("week*_schedule_v1.json")):
        match = _WEEK_FILE_RE.match(path.name)
        if match is None:
            continue
        payload = load_schedule(path)
        if int(payload["season"]) != season or int(payload["week"]) != int(match.group("week")):
            raise LiveScheduleError(f"schedule filename/content identity mismatch: {path}")
        found.append((path, payload))
    return found


def resolve_active_schedule(
    repository_root: str | Path,
    *,
    prediction_as_of_utc: str,
    season: int = 2026,
    schedule_root: str | Path | None = None,
) -> ActiveSchedule:
    """Resolve the active week and fail closed when a Tuesday rollover is missing."""
    now = _utc(prediction_as_of_utc, field="prediction_as_of_utc")
    root = Path(repository_root)
    external_root = None if schedule_root is None else Path(schedule_root)
    candidates = _schedule_files(root, season=season, schedule_root=external_root)
    eligible = [
        (path, payload, rollover_at_utc(payload))
        for path, payload in candidates
        if rollover_at_utc(payload) <= now
    ]
    if not eligible:
        raise LiveScheduleError(f"no active {season} regular-season schedule is available")

    path, payload, rollover = max(eligible, key=lambda item: (int(item[1]["week"]), item[2]))
    week = int(payload["week"])
    expiry = rollover + timedelta(days=7)
    if now >= expiry:
        if week < 18:
            base = external_root if external_root is not None else root / "data" / "live" / str(season)
            next_path = base / f"week{week + 1}_schedule_v1.json"
            raise LiveScheduleError(
                f"Week {week + 1} schedule is required after Tuesday rollover; missing or not eligible: {next_path}"
            )
        raise LiveScheduleError(
            f"Week 18 expired at {expiry.isoformat(timespec='seconds')}; regular-season production is closed"
        )
    return ActiveSchedule(
        path=path,
        payload=payload,
        rollover_at_utc=rollover.isoformat(timespec="seconds").replace("+00:00", "Z"),
    )
