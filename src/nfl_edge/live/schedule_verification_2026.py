"""Independent, fail-closed verification of the active nflverse schedule."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

from .nflverse_2026_identity import CANONICAL_TEAMS
from .week11_flex_2026 import CORRECTION_ID, FLEX_GAMES

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ESPN_ALIASES = {"JAC": "JAX", "WSH": "WAS", "WFT": "WAS", "LA": "LAR"}
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REQUEST_SECONDS = 18
EASTERN = ZoneInfo("America/New_York")


class ScheduleVerificationError(ValueError):
    """The independent schedule source did not substantiate the active slate."""


def espn_week_url(season: int, week: int) -> str:
    return f"{ESPN_SCOREBOARD}?dates={season}&seasontype=2&week={week}"


def _kickoff(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        raise ValueError("ESPN kickoff has no timezone")
    return timestamp.astimezone(timezone.utc)


def _utc_text(timestamp: datetime) -> str:
    return timestamp.isoformat().replace("+00:00", "Z")


def _event_rows(raw: bytes, *, season: int, week: int) -> dict[str, dict[str, Any]]:
    payload = json.loads(raw)
    if (
        (payload["season"]["year"], payload["season"]["type"], payload["week"]["number"]) != (season, 2, week)
        or not isinstance(payload["events"], list)
    ):
        raise ValueError("ESPN response season, season type or week drift")
    rows: dict[str, dict[str, Any]] = {}
    ids: set[str] = set()
    for event in payload["events"]:
        if (event["season"]["year"], event["season"]["type"], event["week"]["number"]) != (season, 2, week):
            raise ValueError("ESPN event season, season type or week drift")
        event_id = event["id"]
        if not isinstance(event_id, str) or not event_id.isascii() or not event_id.isdigit() or event_id in ids:
            raise ValueError("invalid or duplicate ESPN event ID")
        ids.add(event_id)
        competition, = event["competitions"]
        if competition["id"] != event_id:
            raise ValueError(f"ESPN competition identity disagrees with event {event_id}")
        kickoff = _kickoff(event["date"])
        if kickoff != _kickoff(competition["date"]):
            raise ValueError(f"ESPN event and competition kickoffs disagree for {event_id}")
        teams = {}
        for competitor in competition["competitors"]:
            side, alias = competitor["homeAway"], competitor["team"]["abbreviation"]
            team = ESPN_ALIASES.get(alias, alias)
            if side not in {"home", "away"} or side in teams or team not in CANONICAL_TEAMS:
                raise ValueError(f"invalid ESPN team or orientation for event {event_id}")
            teams[side] = team
        if set(teams) != {"home", "away"} or teams["away"] == teams["home"]:
            raise ValueError(f"incomplete ESPN team identity for event {event_id}")
        gid = f"{season}_{week:02d}_{teams['away']}_{teams['home']}"
        if gid in rows:
            raise ValueError(f"duplicate ESPN game {gid}")
        rows[gid] = {
            "event_id": event_id,
            "away_team": teams["away"],
            "home_team": teams["home"],
            "kickoff_utc": _utc_text(kickoff),
            "game_date_eastern": kickoff.astimezone(EASTERN).date().isoformat(),
        }
    return rows


def verify_espn_response(
    schedule: dict[str, Any], raw: bytes, *, primary: dict[str, Any], retrieved_at_utc: str, url: str,
) -> dict[str, Any]:
    """Compare the exact slate with captured bytes, including for offline replay."""
    season, week = schedule["season"], schedule["week"]
    expected = {game["game_id"]: game for game in schedule["games"]}
    correction = schedule.get("kickoff_reconciliation")
    reconciliations = {row["game_id"]: row for row in correction["games"]} if correction else {}
    primary_games = {}
    for gid, game in expected.items():
        canonical = game["scheduled_start_utc"]
        original = reconciliations[gid]["observed_nflverse_kickoff_utc"] if gid in reconciliations else canonical
        primary_games[gid] = {
            "away_team": game["away_team"],
            "home_team": game["home_team"],
            "nflverse_kickoff_utc": original,
            "canonical_kickoff_utc": canonical,
            "game_date_eastern": _kickoff(original).astimezone(EASTERN).date().isoformat(),
        }
    report = {
        "schema_version": "NFL_EDGE_INDEPENDENT_SCHEDULE_VERIFICATION_V1",
        "season": season,
        "season_type": "REG",
        "week": week,
        "primary": primary,
        "secondary": {"url": url, "retrieved_at_utc": retrieved_at_utc,
                      "response_sha256": hashlib.sha256(raw).hexdigest()},
        "expected_game_count": len(expected),
        "canonical_slate_sha256": hashlib.sha256(json.dumps(
            {gid: game["scheduled_start_utc"] for gid, game in expected.items()}, sort_keys=True,
        ).encode()).hexdigest(),
        "primary_games": primary_games,
        "correction_id": correction["correction_id"] if correction else None,
        "discrepancies": [],
    }
    try:
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("saved ESPN response exceeds the byte limit")
        if not retrieved_at_utc.endswith("Z"):
            raise ValueError("ESPN retrieval timestamp must be UTC")
        _kickoff(retrieved_at_utc)
        events = _event_rows(raw, season=season, week=week)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return {**report, "status": "ESPN_INVALID_RESPONSE", "detail": str(exc)}

    missing, unexpected = sorted(expected.keys() - events.keys()), sorted(events.keys() - expected.keys())
    report.update(secondary_games=events, espn_game_count=len(events), missing_games=missing, unexpected_games=unexpected)
    if missing or unexpected:
        report["status"] = "ESPN_SLATE_MISMATCH"
        return report

    for gid, source in primary_games.items():
        event = events[gid]
        flex = FLEX_GAMES.get(gid) if report["correction_id"] == CORRECTION_ID else None
        if (
            event["kickoff_utc"] == source["nflverse_kickoff_utc"] == source["canonical_kickoff_utc"]
            and (flex is None or event["event_id"] == flex.espn_id)
        ):
            continue
        approved = bool(
            flex and event["event_id"] == flex.espn_id
            and event["kickoff_utc"] == source["canonical_kickoff_utc"] == flex.new_utc
            and source["nflverse_kickoff_utc"] == flex.old_utc
        )
        report["discrepancies"].append({
            "game_id": gid,
            **source,
            "espn_event_id": event["event_id"],
            "espn_kickoff_utc": event["kickoff_utc"],
            "espn_game_date_eastern": event["game_date_eastern"],
            "approved_correction": approved,
        })
    report["status"] = (
        "VERIFIED" if all(row["approved_correction"] for row in report["discrepancies"]) else "KICKOFF_DISCREPANCY"
    )
    return report


def verify_independent_schedule(schedule: dict[str, Any], *, primary: dict[str, Any]) -> dict[str, Any]:
    # The REST query requests one exact regular-season week. The parser verifies
    # that ESPN actually honored that window and returned the full slate.
    season, week = schedule["season"], schedule["week"]
    url = espn_week_url(season, week)
    started = time.monotonic()
    secondary = {"url": url, "requested_at_utc": _utc_text(datetime.now(timezone.utc))}
    try:
        with requests.get(url, timeout=(6, 6), stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                raise ScheduleVerificationError(f"ESPN HTTP {response.status_code}")
            chunks = bytearray()
            for chunk in response.iter_content(chunk_size=16384):
                chunks.extend(chunk)
                if len(chunks) > MAX_RESPONSE_BYTES:
                    raise ScheduleVerificationError("ESPN response exceeds the byte limit")
                if time.monotonic() - started >= REQUEST_SECONDS:
                    raise ScheduleVerificationError("ESPN response exceeded the acquisition deadline")
    except (requests.RequestException, ScheduleVerificationError) as exc:
        timed_out = isinstance(exc, requests.Timeout) or "timeout" in str(exc).lower() or "deadline" in str(exc)
        return {
            "schema_version": "NFL_EDGE_INDEPENDENT_SCHEDULE_VERIFICATION_V1",
            "status": "ESPN_TIMEOUT" if timed_out else "ESPN_UNAVAILABLE",
            "season": season, "season_type": "REG", "week": week, "primary": primary, "secondary": secondary,
            "detail": str(exc),
        }
    report = verify_espn_response(
        schedule, bytes(chunks), primary=primary, retrieved_at_utc=_utc_text(datetime.now(timezone.utc)), url=url,
    )
    report["secondary"].update(secondary)
    return report
