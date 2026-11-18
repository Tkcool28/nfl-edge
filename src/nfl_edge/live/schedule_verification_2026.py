"""Resolve kickoff disagreements using the saved Odds pull and ESPN."""

from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .nflverse_2026_identity import CANONICAL_TEAMS
from .markets_2026 import _normalized_team, _parse_utc
from .schedule_2026 import rollover_at_utc, validate_schedule

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ESPN_ALIASES = {"JAC": "JAX", "WSH": "WAS", "WFT": "WAS", "LA": "LAR"}
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REQUEST_SECONDS = 18


class ScheduleVerificationError(ValueError):
    """Kickoff evidence cannot safely resolve a disagreement."""


def espn_week_url(season: int, week: int) -> str:
    return f"{ESPN_SCOREBOARD}?dates={season}&seasontype=2&week={week}"


def _kickoff(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        raise ValueError("ESPN kickoff has no timezone")
    return timestamp.astimezone(timezone.utc)


def _utc_text(timestamp: datetime) -> str:
    return timestamp.isoformat().replace("+00:00", "Z")


def _espn_team(competitor: Any) -> str | None:
    team = competitor.get("team") if isinstance(competitor, dict) else None
    abbreviation = team.get("abbreviation") if isinstance(team, dict) else None
    if not isinstance(abbreviation, str):
        return None
    code = abbreviation.strip().upper()
    canonical = ESPN_ALIASES.get(code, code)
    return canonical if canonical in CANONICAL_TEAMS else None


def _event_rows(
    raw: bytes, *, matchups: dict[tuple[str, str], str],
) -> dict[str, dict[str, Any]]:
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError("ESPN response has no events list")
    rows: dict[str, dict[str, Any]] = {}
    ids: set[str] = set()
    for event in payload["events"]:
        competitions = event.get("competitions") if isinstance(event, dict) else None
        if not isinstance(competitions, list):
            continue
        for competition in competitions:
            competitors = competition.get("competitors") if isinstance(competition, dict) else None
            if not isinstance(competitors, list):
                continue
            identities = [
                (entry.get("homeAway") if isinstance(entry, dict) else None, _espn_team(entry))
                for entry in competitors
            ]
            teams = {team for _, team in identities}
            # Identify the matchup before checking orientation so a reversed
            # or extra competitor cannot hide ambiguous affected evidence.
            matched = next(
                ((away, home, gid) for (away, home), gid in matchups.items() if {away, home} <= teams),
                None,
            )
            if matched is None:
                continue
            away, home, gid = matched
            if len(competitions) != 1 or len(identities) != 2:
                raise ValueError(f"ambiguous ESPN competition for {gid}")
            if ("away", away) not in identities or ("home", home) not in identities:
                raise ValueError(f"incorrect ESPN home/away orientation for {gid}")
            if gid in rows:
                raise ValueError(f"duplicate ESPN game {gid}")
            event_id = event["id"]
            if not isinstance(event_id, str) or not event_id.isascii() or not event_id.isdigit() or event_id in ids:
                raise ValueError(f"invalid or duplicate ESPN event ID for {gid}")
            if competition["id"] != event_id:
                raise ValueError(f"ESPN competition identity disagrees with event {event_id}")
            kickoff = _kickoff(event["date"])
            if kickoff != _kickoff(competition["date"]):
                raise ValueError(f"ESPN event and competition kickoffs disagree for {event_id}")
            rows[gid] = {"event_id": event_id, "kickoff_utc": _utc_text(kickoff)}
            ids.add(event_id)
    return rows


def _espn_scoreboard(url: str) -> bytes:
    started = time.monotonic()
    with requests.get(url, timeout=(6, 6), stream=True, allow_redirects=False) as response:
        if response.status_code != 200:
            raise ScheduleVerificationError(f"ESPN HTTP {response.status_code}")
        raw = bytearray()
        for chunk in response.iter_content(chunk_size=16384):
            raw.extend(chunk)
            if len(raw) > MAX_RESPONSE_BYTES or time.monotonic() - started >= REQUEST_SECONDS:
                raise ScheduleVerificationError("ESPN response exceeded the acquisition limit")
    return bytes(raw)


def _kickoff_disagreements(schedule: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not events:
        return []
    games = {(game["away_team"], game["home_team"]): game for game in schedule["games"]}
    seen: set[str] = set()
    disagreements = []
    for event in events:
        pair = _normalized_team(event.get("away_team")), _normalized_team(event.get("home_team"))
        game = games.get(pair)
        if game is None or not event.get("commence_time"):
            continue
        gid = game["game_id"]
        if gid in seen:
            raise ScheduleVerificationError(f"multiple Odds events for {gid}")
        seen.add(gid)
        odds_kickoff = _parse_utc(str(event["commence_time"]))
        if odds_kickoff != _parse_utc(game["scheduled_start_utc"]):
            if not event.get("id"):
                raise ScheduleVerificationError(f"Odds event for {gid} has no ID")
            disagreements.append({
                "game_id": gid,
                "odds_event_id": str(event["id"]),
                "nflverse_kickoff_utc": game["scheduled_start_utc"],
                "odds_kickoff_utc": _utc_text(odds_kickoff),
            })
    return sorted(disagreements, key=lambda row: row["game_id"])


def reconcile_market_kickoffs(
    schedule: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    live: bool,
    espn_response: Path | None = None,
    capture_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Check ESPN only for specific nflverse/Odds kickoff disagreements."""
    discrepancies = _kickoff_disagreements(schedule, events)
    if not discrepancies:
        return schedule, None

    season, week = schedule["season"], schedule["week"]
    url = espn_week_url(season, week)
    report = {
        "schema_version": "NFL_EDGE_KICKOFF_RECONCILIATION_V1",
        "season": season,
        "week": week,
        "original_schedule_version": schedule["schedule_version"],
        "espn": {"url": url},
        "discrepancies": discrepancies,
    }
    if not live and espn_response is None:
        return schedule, {**report, "status": "ESPN_CAPTURE_REQUIRED"}
    try:
        if live:
            raw = _espn_scoreboard(url)
            report["espn"]["retrieved_at_utc"] = _utc_text(datetime.now(timezone.utc))
            if capture_path is not None:
                capture_path.parent.mkdir(parents=True, exist_ok=True)
                capture_path.write_bytes(raw)
        else:
            assert espn_response is not None
            with espn_response.open("rb") as handle:
                raw = handle.read(MAX_RESPONSE_BYTES + 1)
            report["espn"]["saved_response"] = str(espn_response)
    except (OSError, requests.RequestException, ScheduleVerificationError) as exc:
        return schedule, {**report, "status": "ESPN_UNAVAILABLE", "detail": str(exc)}
    report["espn"]["response_sha256"] = hashlib.sha256(raw).hexdigest()
    try:
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("ESPN response exceeds the byte limit")
        disputed_ids = {row["game_id"] for row in discrepancies}
        matchups = {
            (game["away_team"], game["home_team"]): game["game_id"]
            for game in schedule["games"] if game["game_id"] in disputed_ids
        }
        secondary = _event_rows(raw, matchups=matchups)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return schedule, {**report, "status": "ESPN_INVALID_RESPONSE", "detail": str(exc)}

    for row in discrepancies:
        espn = secondary.get(row["game_id"], {})
        row["espn_event_id"] = espn.get("event_id")
        row["espn_kickoff_utc"] = espn.get("kickoff_utc")
    if any(row["espn_kickoff_utc"] != row["odds_kickoff_utc"] for row in discrepancies):
        return schedule, {**report, "status": "KICKOFF_UNCONFIRMED"}

    revised = deepcopy(schedule)
    kickoffs = {row["game_id"]: row["odds_kickoff_utc"] for row in discrepancies}
    for game in revised["games"]:
        if game["game_id"] in kickoffs:
            game["scheduled_start_utc"] = kickoffs[game["game_id"]]
    revised["games"].sort(key=lambda game: (_parse_utc(game["scheduled_start_utc"]), game["game_id"]))
    if rollover_at_utc(revised) != rollover_at_utc(schedule):
        return schedule, {**report, "status": "ACTIVE_WEEK_BOUNDARY_CHANGED"}
    slate = [(game["game_id"], game["scheduled_start_utc"]) for game in revised["games"]]
    digest = hashlib.sha256(json.dumps(slate, separators=(",", ":")).encode()).hexdigest()
    revised["schedule_version"] = f"ODDS_ESPN_{season}_REG_WEEK{week}_{digest}"
    return validate_schedule(revised), {**report, "status": "KICKOFF_CONFIRMED"}
