"""Materialize the active 2026 NFL regular-season schedule from nflverse."""
from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

import requests

from .schedule_2026 import LiveScheduleError, rollover_at_utc, validate_schedule

NFLVERSE_GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
SOURCE_NAME = "nflverse/nfldata games.csv"
EASTERN = ZoneInfo("America/New_York")


class ScheduleMaterializationError(RuntimeError):
    """Raised when the upstream schedule cannot be materialized safely."""


def _utc(value: str) -> datetime:
    text = str(value)
    if not text.endswith("Z"):
        raise ScheduleMaterializationError("active-as-of must be RFC3339 UTC Z")
    try:
        return datetime.fromisoformat(text[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise ScheduleMaterializationError(f"invalid active-as-of timestamp: {value!r}") from exc


def _required(row: Mapping[str, Any], field: str) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        raise ScheduleMaterializationError(f"nflverse row is missing required {field}")
    return value


def _integer(row: Mapping[str, Any], field: str) -> int:
    value = _required(row, field)
    try:
        return int(float(value))
    except ValueError as exc:
        raise ScheduleMaterializationError(f"invalid integer {field}={value!r}") from exc


def _kickoff_utc(row: Mapping[str, Any]) -> str:
    gameday = _required(row, "gameday")
    gametime = _required(row, "gametime")
    try:
        local = datetime.fromisoformat(f"{gameday}T{gametime}").replace(tzinfo=EASTERN)
    except ValueError as exc:
        raise ScheduleMaterializationError(
            f"invalid nflverse gameday/gametime: {gameday} {gametime}"
        ) from exc
    return local.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _roof(row: Mapping[str, Any]) -> tuple[str | None, str]:
    value = _required(row, "roof").lower()
    if value == "outdoors":
        return "outdoors", "OUTDOOR"
    if value == "dome":
        return "dome", "FIXED"
    if value in {"open", "closed"}:
        # nflverse's open/closed values identify a retractable-roof venue. The
        # current position is deliberately not carried into the canonical
        # schedule; RoofResolver owns point-in-time roof evidence separately.
        return None, "RETRACTABLE"
    raise ScheduleMaterializationError(f"unsupported nflverse roof value {value!r}")


def _observed_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_week_schedule(
    rows: Iterable[Mapping[str, Any]],
    *,
    season: int,
    week: int,
    observed_at_utc: str,
) -> dict[str, Any]:
    _utc(observed_at_utc)
    selected = [
        row
        for row in rows
        if str(row.get("season") or "") == str(season)
        and str(row.get("game_type") or "").upper() == "REG"
        and str(row.get("week") or "") == str(week)
    ]
    if not selected:
        raise ScheduleMaterializationError(f"nflverse has no {season} REG Week {week} rows")

    games: list[dict[str, Any]] = []
    for row in selected:
        away = _required(row, "away_team")
        home = _required(row, "home_team")
        roof_type, roof_structure = _roof(row)
        location = str(row.get("location") or "").strip().lower()
        games.append(
            {
                "game_id": f"{season}_{week:02d}_{away}_{home}",
                "away_team": away,
                "home_team": home,
                "scheduled_start_utc": _kickoff_utc(row),
                "neutral_site": location == "neutral",
                "venue": _required(row, "stadium"),
                "venue_id": _required(row, "stadium_id"),
                "away_rest": _integer(row, "away_rest"),
                "home_rest": _integer(row, "home_rest"),
                "surface": _required(row, "surface").lower(),
                "roof_type": roof_type,
                "roof_structure": roof_structure,
                "context_source_at_utc": observed_at_utc,
            }
        )
    games.sort(key=lambda game: (game["scheduled_start_utc"], game["game_id"]))

    payload = {
        "schema_version": "nfl-edge-live-schedule-v1",
        "schedule_version": f"NFLVERSE_{season}_REG_WEEK{week}_{observed_at_utc}",
        "season": season,
        "week": week,
        "source": SOURCE_NAME,
        "source_url": NFLVERSE_GAMES_URL,
        "verified_at_utc": observed_at_utc,
        "context_version": f"NFLVERSE_{season}_REG_WEEK{week}_{observed_at_utc}",
        "context_source": SOURCE_NAME,
        "context_source_url": NFLVERSE_GAMES_URL,
        "context_verified_at_utc": observed_at_utc,
        "context_fields": [
            "away_rest", "home_rest", "roof", "surface", "stadium_id", "stadium"
        ],
        "market_fields_consumed": [],
        "games": games,
    }
    try:
        return validate_schedule(payload)
    except LiveScheduleError as exc:
        raise ScheduleMaterializationError(str(exc)) from exc


def choose_active_schedule(
    rows: list[Mapping[str, Any]],
    *,
    season: int,
    active_as_of_utc: str,
    observed_at_utc: str,
) -> dict[str, Any]:
    now = _utc(active_as_of_utc)
    candidates: list[dict[str, Any]] = []
    for week in range(1, 19):
        try:
            payload = build_week_schedule(
                rows, season=season, week=week, observed_at_utc=observed_at_utc
            )
        except ScheduleMaterializationError as exc:
            if "has no" in str(exc):
                continue
            raise
        if rollover_at_utc(payload) <= now:
            candidates.append(payload)
    if not candidates:
        raise ScheduleMaterializationError(
            f"no {season} regular-season week is active at {active_as_of_utc}"
        )
    return max(candidates, key=lambda payload: int(payload["week"]))


def fetch_nflverse_rows(*, session: requests.Session | None = None) -> list[dict[str, str]]:
    client = session or requests.Session()
    response = client.get(NFLVERSE_GAMES_URL, timeout=30)
    response.raise_for_status()
    reader = csv.DictReader(io.StringIO(response.text))
    rows = [dict(row) for row in reader]
    if not rows:
        raise ScheduleMaterializationError("nflverse games.csv returned no rows")
    return rows


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}-", delete=False) as handle:
            temp = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def materialize_active_schedule(
    *,
    output_dir: str | Path,
    season: int = 2026,
    active_as_of_utc: str | None = None,
    rows: list[Mapping[str, Any]] | None = None,
) -> tuple[Path, dict[str, Any]]:
    observed = _observed_now()
    active_as_of = active_as_of_utc or observed
    source_rows = list(rows) if rows is not None else fetch_nflverse_rows()
    payload = choose_active_schedule(
        source_rows,
        season=season,
        active_as_of_utc=active_as_of,
        observed_at_utc=observed,
    )
    path = Path(output_dir) / f"week{int(payload['week'])}_schedule_v1.json"
    _atomic_write(path, payload)
    return path, payload
