"""Bounded live 2026 NFL market acquisition, matching, normalization and replay.

This module is production wiring only.  It does not contain evaluator, selector,
staking, or football-model methodology.

The Odds API request is deliberately one bounded current-odds call:
- sport: americanfootball_nfl
- bookmakers: draftkings,fanduel,pinnacle
- markets: h2h,spreads,totals

The provider documents current-odds quota cost as markets x effective regions,
with an explicit list of up to ten bookmakers counting as one region.  The
request shape below therefore has an expected cost of three credits.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

from nfl_edge.contracts.market_qb_v1 import validate_market_board

PROVIDER = "THE_ODDS_API"
API_BASE = "https://api.the-odds-api.com/v4"
SPORT_KEY = "americanfootball_nfl"
BOOKMAKER_KEYS = ("draftkings", "fanduel", "pinnacle")
MARKET_KEYS = ("h2h", "spreads", "totals")
BOOK_MAP = {
    "draftkings": "DRAFTKINGS",
    "fanduel": "FANDUEL",
    "pinnacle": "PINNACLE",
}
MARKET_MAP = {
    "h2h": ("moneyline", "MONEYLINE"),
    "spreads": ("spread", "SPREAD"),
    "totals": ("total", "TOTAL"),
}
MARKET_FRESHNESS_THRESHOLD_SECONDS = 900.0
MATCH_KICKOFF_TOLERANCE_SECONDS = 15 * 60
REQUEST_TIMEOUT_SECONDS = 20.0

TEAM_NAME_TO_ABBR = {
    "Arizona Cardinals": "ARI",
    "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR",
    "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN",
    "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN",
    "Detroit Lions": "DET",
    "Green Bay Packers": "GB",
    "Houston Texans": "HOU",
    "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV",
    "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR",
    "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN",
    "New England Patriots": "NE",
    "New Orleans Saints": "NO",
    "New York Giants": "NYG",
    "New York Jets": "NYJ",
    "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA",
    "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN",
    "Washington Commanders": "WAS",
}


class LiveMarketError(RuntimeError):
    """Raised when live market acquisition or normalization fails closed."""


@dataclass(frozen=True)
class LiveMarketCapture:
    response_path: Path
    metadata_path: Path
    response_sha256: str
    acquired_at_utc: str
    credits_consumed: int | None
    credits_remaining: int | None


def _parse_utc(value: str) -> datetime:
    text = str(value)
    if not text.endswith("Z"):
        raise LiveMarketError(f"timestamp must be RFC3339 UTC with Z suffix: {text!r}")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise LiveMarketError(f"invalid UTC timestamp: {text!r}") from exc
    return parsed.astimezone(timezone.utc)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _safe_header_int(headers: Mapping[str, Any], key: str) -> int | None:
    value = headers.get(key)
    if value is None:
        value = headers.get(key.lower())
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def expected_credit_cost(
    *,
    bookmakers: Sequence[str] = BOOKMAKER_KEYS,
    markets: Sequence[str] = MARKET_KEYS,
) -> int:
    """Return documented expected current-odds quota cost for this request shape."""
    if not bookmakers or not markets:
        raise LiveMarketError("bookmakers and markets must both be non-empty")
    effective_regions = math.ceil(len(tuple(bookmakers)) / 10)
    return len(tuple(markets)) * effective_regions


def build_request_plan(schedule: Mapping[str, Any]) -> dict[str, Any]:
    """Build the one bounded request without including the API key."""
    games = list(schedule.get("games") or [])
    if int(schedule.get("season", -1)) != 2026 or int(schedule.get("week", -1)) != 1:
        raise LiveMarketError("live market request requires the canonical 2026 Week 1 schedule")
    if len(games) != 16:
        raise LiveMarketError(f"canonical Week 1 schedule must contain 16 games, got {len(games)}")
    kickoffs = sorted(_parse_utc(str(game["scheduled_start_utc"])) for game in games)
    pad = MATCH_KICKOFF_TOLERANCE_SECONDS
    start = datetime.fromtimestamp(kickoffs[0].timestamp() - pad, tz=timezone.utc)
    end = datetime.fromtimestamp(kickoffs[-1].timestamp() + pad, tz=timezone.utc)
    return {
        "endpoint": f"{API_BASE}/sports/{SPORT_KEY}/odds/",
        "params": {
            "bookmakers": ",".join(BOOKMAKER_KEYS),
            "markets": ",".join(MARKET_KEYS),
            "oddsFormat": "american",
            "dateFormat": "iso",
            "commenceTimeFrom": start.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "commenceTimeTo": end.isoformat(timespec="seconds").replace("+00:00", "Z"),
        },
        "expected_credit_cost": expected_credit_cost(),
        "sport": SPORT_KEY,
        "bookmakers": list(BOOKMAKER_KEYS),
        "markets": list(MARKET_KEYS),
    }


def acquire_live_response(
    *,
    schedule: Mapping[str, Any],
    output_dir: str | Path,
    live: bool,
    api_key: str | None = None,
    session: requests.Session | None = None,
    acquired_at_utc: str | None = None,
) -> LiveMarketCapture:
    """Perform exactly one billable request and persist success before parsing.

    There are intentionally no automatic retries.  A transport/HTTP failure
    returns control to the operator instead of risking repeated billable calls.
    """
    if not live:
        raise LiveMarketError("live Odds API acquisition requires the explicit live=True gate")
    key = api_key or os.environ.get("ODDS_API_KEY")
    if not key:
        raise LiveMarketError("ODDS_API_KEY is required for explicit live acquisition")

    plan = build_request_plan(schedule)
    params = dict(plan["params"])
    params["apiKey"] = key
    client = session or requests.Session()
    response = client.get(
        str(plan["endpoint"]),
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise LiveMarketError(
            f"Odds API request failed with HTTP {response.status_code}; no automatic retry performed"
        )

    acquired = acquired_at_utc or _utc_now()
    _parse_utc(acquired)
    raw = bytes(response.content)
    digest = _sha256_bytes(raw)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    compact = acquired.replace("-", "").replace(":", "")
    response_path = out / f"odds-api-nfl-week1-{compact}-{digest[:12]}.json"
    metadata_path = response_path.with_suffix(".meta.json")

    # Persist the exact successful body before parsing/normalization.  A parser
    # defect can therefore be repaired and replayed for zero extra credits.
    response_path.write_bytes(raw)

    try:
        parsed = json.loads(response_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveMarketError(
            f"successful Odds API response was persisted at {response_path} but is not valid JSON"
        ) from exc
    if not isinstance(parsed, list):
        raise LiveMarketError(
            f"successful Odds API response was persisted at {response_path} but root is not an array"
        )

    consumed = _safe_header_int(response.headers, "x-requests-last")
    remaining = _safe_header_int(response.headers, "x-requests-remaining")
    used = _safe_header_int(response.headers, "x-requests-used")
    metadata = {
        "provider": PROVIDER,
        "acquired_at_utc": acquired,
        "endpoint": str(plan["endpoint"]),
        "sport": plan["sport"],
        "bookmakers": plan["bookmakers"],
        "markets": plan["markets"],
        "request_params_without_secret": plan["params"],
        "expected_credit_cost": int(plan["expected_credit_cost"]),
        "response_status": int(response.status_code),
        "response_sha256": digest,
        "response_bytes": len(raw),
        "credits_consumed": consumed,
        "credits_remaining": remaining,
        "credits_used_total": used,
        "automatic_retries": 0,
    }
    metadata_path.write_bytes(_canonical_json_bytes(metadata))
    return LiveMarketCapture(
        response_path=response_path,
        metadata_path=metadata_path,
        response_sha256=digest,
        acquired_at_utc=acquired,
        credits_consumed=consumed,
        credits_remaining=remaining,
    )


def load_capture(
    response_path: str | Path,
    *,
    metadata_path: str | Path | None = None,
    acquired_at_utc: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load a saved provider response for zero-credit deterministic replay."""
    response_file = Path(response_path)
    raw = response_file.read_bytes()
    try:
        events = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LiveMarketError(f"saved market response is not valid JSON: {response_file}") from exc
    if not isinstance(events, list):
        raise LiveMarketError("saved market response root must be an array")

    meta_file = Path(metadata_path) if metadata_path is not None else response_file.with_suffix(".meta.json")
    metadata: dict[str, Any] = {}
    if meta_file.is_file():
        loaded = json.loads(meta_file.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise LiveMarketError("market response metadata root must be an object")
        metadata = dict(loaded)
    acquired = acquired_at_utc or metadata.get("acquired_at_utc")
    if acquired is None:
        raise LiveMarketError(
            "replay requires capture metadata or an explicit acquired_at_utc timestamp"
        )
    _parse_utc(str(acquired))
    metadata.setdefault("provider", PROVIDER)
    metadata["acquired_at_utc"] = str(acquired)
    metadata["response_sha256"] = _sha256_bytes(raw)
    metadata.setdefault("credits_consumed", None)
    metadata.setdefault("credits_remaining", None)
    return [dict(event) for event in events], metadata


def _normalized_team(value: Any) -> str | None:
    text = str(value or "").strip()
    if text in TEAM_NAME_TO_ABBR:
        return TEAM_NAME_TO_ABBR[text]
    if text in TEAM_NAME_TO_ABBR.values():
        return text
    return None


def _event_candidates(
    event: Mapping[str, Any],
    schedule_games: Sequence[Mapping[str, Any]],
) -> list[str]:
    home = _normalized_team(event.get("home_team"))
    away = _normalized_team(event.get("away_team"))
    commence_raw = event.get("commence_time")
    if home is None or away is None or commence_raw is None:
        return []
    commence = _parse_utc(str(commence_raw))
    candidates: list[str] = []
    for game in schedule_games:
        if str(game.get("home_team")) != home or str(game.get("away_team")) != away:
            continue
        kickoff = _parse_utc(str(game["scheduled_start_utc"]))
        if abs((commence - kickoff).total_seconds()) <= MATCH_KICKOFF_TOLERANCE_SECONDS:
            candidates.append(str(game["game_id"]))
    return candidates


def match_provider_events(
    schedule: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, str], dict[str, Any]]:
    """Fail closed on ambiguous events or duplicate provider->canonical mappings."""
    games = list(schedule.get("games") or [])
    canonical_ids = {str(game["game_id"]) for game in games}
    mapping: dict[str, str] = {}
    unmatched_events: list[str] = []
    ambiguous_events: list[dict[str, Any]] = []
    duplicate_mappings: list[dict[str, str]] = []
    owner_by_game: dict[str, str] = {}

    for index, event in enumerate(events):
        event_id = str(event.get("id") or f"event-index-{index}")
        candidates = _event_candidates(event, games)
        if len(candidates) == 0:
            unmatched_events.append(event_id)
            continue
        if len(candidates) > 1:
            ambiguous_events.append({"provider_event_id": event_id, "candidates": candidates})
            continue
        game_id = candidates[0]
        prior = owner_by_game.get(game_id)
        if prior is not None:
            duplicate_mappings.append(
                {
                    "game_id": game_id,
                    "first_provider_event_id": prior,
                    "duplicate_provider_event_id": event_id,
                }
            )
            continue
        owner_by_game[game_id] = event_id
        mapping[event_id] = game_id

    matched_games = set(mapping.values())
    audit = {
        "provider_events_returned": len(events),
        "canonical_games_expected": len(games),
        "matched_provider_events": len(mapping),
        "matched_canonical_games": len(matched_games),
        "unmatched_provider_event_ids": sorted(unmatched_events),
        "unmatched_canonical_game_ids": sorted(canonical_ids - matched_games),
        "ambiguous_provider_events": ambiguous_events,
        "duplicate_mappings": duplicate_mappings,
    }
    if ambiguous_events or duplicate_mappings:
        raise LiveMarketError(
            "provider event mapping failed closed: "
            f"ambiguous={len(ambiguous_events)} duplicates={len(duplicate_mappings)}"
        )
    return mapping, audit


def _freshness(observed_at_utc: str, acquired_at_utc: str) -> dict[str, Any]:
    observed = _parse_utc(observed_at_utc)
    acquired = _parse_utc(acquired_at_utc)
    age = max(0.0, (acquired - observed).total_seconds())
    threshold = MARKET_FRESHNESS_THRESHOLD_SECONDS
    if age < threshold * 0.5:
        state = "FRESH"
    elif age <= threshold:
        state = "AGING"
    else:
        state = "STALE"
    return {
        "state": state,
        "observed_at_utc": observed_at_utc,
        "age_seconds": age,
        "threshold_seconds": threshold,
    }


def _offer_id(material: Mapping[str, Any]) -> str:
    raw = json.dumps(material, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return f"toa-{hashlib.sha256(raw).hexdigest()[:24]}"


def _empty_board() -> dict[str, dict[str, list[dict[str, Any]]]]:
    return {"moneyline": {}, "spread": {}, "total": {}}


def _normalized_selection(
    *,
    market_key: str,
    outcome_name: Any,
    game: Mapping[str, Any],
) -> str | None:
    name = str(outcome_name or "").strip()
    if market_key == "totals":
        upper = name.upper()
        return upper if upper in {"OVER", "UNDER"} else None
    abbr = _normalized_team(name)
    if abbr in {str(game["home_team"]), str(game["away_team"])}:
        return abbr
    return None


def normalize_market_snapshot(
    *,
    schedule: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    acquired_at_utc: str,
    response_sha256: str,
    credits_consumed: int | None = None,
    credits_remaining: int | None = None,
) -> dict[str, Any]:
    """Normalize one captured response into the frozen live market offer contract."""
    _parse_utc(acquired_at_utc)
    mapping, audit = match_provider_events(schedule, events)
    games_by_id = {str(game["game_id"]): dict(game) for game in schedule["games"]}
    boards = {game_id: _empty_board() for game_id in games_by_id}
    exact_seen: dict[tuple[str, str, str], set[tuple[Any, ...]]] = {}
    offer_count = 0
    stale_offer_count = 0
    omitted_unknown_outcomes = 0
    matched_event_with_no_required_offers: list[str] = []

    event_by_id = {
        str(event.get("id") or f"event-index-{index}"): event
        for index, event in enumerate(events)
    }
    for provider_event_id, game_id in sorted(mapping.items()):
        event = event_by_id[provider_event_id]
        game = games_by_id[game_id]
        before = offer_count
        for bookmaker in event.get("bookmakers") or []:
            key = str(bookmaker.get("key") or "")
            if key not in BOOK_MAP:
                continue
            book = BOOK_MAP[key]
            book_update = bookmaker.get("last_update")
            for market in bookmaker.get("markets") or []:
                market_key = str(market.get("key") or "")
                if market_key not in MARKET_MAP:
                    continue
                board_key, market_type = MARKET_MAP[market_key]
                observed = str(market.get("last_update") or book_update or acquired_at_utc)
                freshness = _freshness(observed, acquired_at_utc)
                for outcome in market.get("outcomes") or []:
                    normalized = _normalized_selection(
                        market_key=market_key,
                        outcome_name=outcome.get("name"),
                        game=game,
                    )
                    if normalized is None:
                        omitted_unknown_outcomes += 1
                        continue
                    try:
                        price = int(outcome["price"])
                    except (KeyError, TypeError, ValueError) as exc:
                        raise LiveMarketError(
                            f"invalid American price: event={provider_event_id} book={key} market={market_key}"
                        ) from exc
                    if -99 <= price <= 99:
                        raise LiveMarketError(f"invalid American odds {price}")
                    line: float | None
                    if market_key == "h2h":
                        line = None
                    else:
                        point = outcome.get("point")
                        if point is None:
                            raise LiveMarketError(
                                f"missing point: event={provider_event_id} book={key} market={market_key}"
                            )
                        line = float(point)
                        if not math.isfinite(line):
                            raise LiveMarketError("market line must be finite")

                    signature = (normalized, line, price, observed)
                    bucket_key = (game_id, board_key, book)
                    bucket_seen = exact_seen.setdefault(bucket_key, set())
                    if signature in bucket_seen:
                        raise LiveMarketError(
                            "exact duplicate market observation: "
                            f"game={game_id} market={market_type} book={book} signature={signature}"
                        )
                    bucket_seen.add(signature)
                    id_material = {
                        "provider_event_id": provider_event_id,
                        "game_id": game_id,
                        "book": book,
                        "market": market_type,
                        "selection": normalized,
                        "line": line,
                        "price": price,
                        "snapshot_at_utc": observed,
                    }
                    offer = {
                        "offer_id": _offer_id(id_material),
                        "provider": PROVIDER,
                        "game_id": game_id,
                        "sportsbook": book,
                        "market_type": market_type,
                        "selection": str(outcome.get("name") or normalized),
                        "line": line,
                        "price": price,
                        "snapshot_at_utc": observed,
                        "normalized_selection": normalized,
                        "freshness": freshness,
                    }
                    boards[game_id][board_key].setdefault(book, []).append(offer)
                    offer_count += 1
                    stale_offer_count += int(freshness["state"] == "STALE")
        if offer_count == before:
            matched_event_with_no_required_offers.append(game_id)

    for game_id, board in boards.items():
        for board_key in ("moneyline", "spread", "total"):
            for book in list(board[board_key]):
                board[board_key][book] = sorted(
                    board[board_key][book],
                    key=lambda offer: (
                        str(offer["normalized_selection"]),
                        -9999.0 if offer["line"] is None else float(offer["line"]),
                        int(offer["price"]),
                        str(offer["snapshot_at_utc"]),
                        str(offer["offer_id"]),
                    ),
                )
        validate_market_board(board, game_id, f"market_snapshot.games.{game_id}.market_board")

    coverage_by_book = {}
    for book in BOOK_MAP.values():
        coverage_by_book[book] = {
            market_type: sum(
                bool(boards[gid][board_key].get(book))
                for gid in sorted(boards)
            )
            for market_type, board_key in (
                ("MONEYLINE", "moneyline"),
                ("SPREAD", "spread"),
                ("TOTAL", "total"),
            )
        }
    coverage_by_market = {
        market_type: sum(
            any(boards[gid][board_key].get(book) for book in BOOK_MAP.values())
            for gid in sorted(boards)
        )
        for market_type, board_key in (
            ("MONEYLINE", "moneyline"),
            ("SPREAD", "spread"),
            ("TOTAL", "total"),
        )
    }
    audit = dict(audit)
    audit.update(
        {
            "matched_event_with_no_required_market_game_ids": sorted(
                matched_event_with_no_required_offers
            ),
            "offers_normalized": offer_count,
            "stale_offers": stale_offer_count,
            "unknown_outcomes_omitted": omitted_unknown_outcomes,
            "exact_duplicates": 0,
        }
    )
    identity_material = {
        "provider": PROVIDER,
        "acquired_at_utc": acquired_at_utc,
        "response_sha256": response_sha256,
        "boards": boards,
    }
    snapshot_hash = hashlib.sha256(_canonical_json_bytes(identity_material)).hexdigest()
    return {
        "schema_version": "NFL_EDGE_LIVE_MARKET_V1",
        "provider": PROVIDER,
        "market_snapshot_version": f"live-market:{snapshot_hash[:24]}",
        "snapshot_sha256": snapshot_hash,
        "acquired_at_utc": acquired_at_utc,
        "response_sha256": response_sha256,
        "sport": SPORT_KEY,
        "season": 2026,
        "week": 1,
        "books": list(BOOK_MAP.values()),
        "market_types": ["MONEYLINE", "SPREAD", "TOTAL"],
        "credits_consumed": credits_consumed,
        "credits_remaining": credits_remaining,
        "audit": audit,
        "coverage_by_book": coverage_by_book,
        "coverage_by_market": coverage_by_market,
        "games": [
            {"game_id": game_id, "market_board": boards[game_id]}
            for game_id in sorted(boards)
        ],
    }


def market_snapshot_bytes(snapshot: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(snapshot, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
