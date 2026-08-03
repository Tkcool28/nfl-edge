"""Conservative pre-cutoff starting-quarterback evidence classification."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import polars as pl

from .validation import assert_unique_keys

CERTAINTY_STATES = (
    "CONFIRMED_PRE_CUTOFF",
    "DEPTH_CHART_SUPPORTED",
    "ROSTER_SUPPORTED",
    "AMBIGUOUS",
    "UNKNOWN",
    "POSTGAME_ONLY_EVIDENCE",
)


def _utc(value: Any) -> datetime | None:
    if value is None or str(value).strip() in {"", "None", "null"}:
        return None
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("starter evidence timestamp must be timezone-aware")
    return result.astimezone(timezone.utc)


def _depth_rows(depth: pl.DataFrame | None) -> list[dict[str, Any]]:
    if depth is None or depth.is_empty():
        return []
    rows = []
    for item in depth.to_dicts():
        position = str(item.get("position") or item.get("pos_name") or item.get("depth_position") or "").upper()
        if position not in {"QB", "QUARTERBACK"}:
            continue
        team = item.get("team") or item.get("club_code")
        rank = item.get("depth_rank")
        if rank is None:
            rank = item.get("pos_rank")
        if rank is None:
            rank = item.get("depth_team")
        rows.append(
            {
                **item,
                "team": team,
                "depth_rank": int(rank) if rank not in {None, ""} else None,
                "source_dt_parsed": _utc(item.get("source_dt")),
            }
        )
    return rows


def _roster_rows(rosters: pl.DataFrame | None) -> list[dict[str, Any]]:
    if rosters is None or rosters.is_empty():
        return []
    rows = []
    for row in rosters.to_dicts():
        if str(row.get("position") or "").upper() != "QB":
            continue
        quality = str(row.get("timestamp_quality") or "")
        if quality and quality != "PRE_CUTOFF_FIXTURE_EVIDENCE":
            continue
        rows.append(row)
    return rows


def _override_index(overrides: pl.DataFrame | None) -> dict[tuple[str, str], dict[str, Any]]:
    if overrides is None or overrides.is_empty():
        return {}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(overrides.to_dicts()):
        key = (row["game_id"], row["team"])
        if "observed_at_utc" not in row:
            raise ValueError(f"starter override missing observed_at_utc column at row {index} for {key}")
        observed = row.get("observed_at_utc")
        if observed is None or str(observed).strip() == "":
            raise ValueError(f"starter override requires timezone-aware observed_at_utc for {key}")
        parsed = _utc(observed)
        if parsed is None:
            raise ValueError(f"starter override requires timezone-aware observed_at_utc for {key}")
        grouped[key].append(row)
    result = {}
    for key, rows in grouped.items():
        ids = {str(row.get("expected_starter_id")) for row in rows if row.get("expected_starter_id") is not None}
        if len(ids) > 1:
            raise ValueError(f"conflicting starter override records for {key}: {sorted(ids)}")
        result[key] = max(
            rows,
            key=lambda row: _utc(row.get("observed_at_utc")) or datetime.min.replace(tzinfo=timezone.utc),
        )
    return result


def _postgame_index(postgame: pl.DataFrame | None) -> dict[tuple[str, str], list[str]]:
    result: dict[tuple[str, str], list[str]] = defaultdict(list)
    if postgame is None or postgame.is_empty():
        return result
    for row in postgame.to_dicts():
        player_id = row.get("player_id")
        if player_id and player_id not in result[(row["game_id"], row["team"])]:
            result[(row["game_id"], row["team"])].append(player_id)
    return result


def _roster_candidates(rows: list[dict[str, Any]], game: dict[str, Any], team: str) -> list[str]:
    exact = [
        row
        for row in rows
        if row.get("season") == game["season"]
        and row.get("team") == team
        and row.get("week") == game["week"]
        and row.get("player_id")
    ]
    if not exact:
        exact = [
            row
            for row in rows
            if row.get("season") == game["season"] and row.get("team") == team and row.get("player_id")
        ]
    return sorted({str(row["player_id"]) for row in exact})[:2]


def _resolve_side(
    game: dict[str, Any],
    team: str,
    cutoff: datetime,
    depth: list[dict[str, Any]],
    rosters: list[dict[str, Any]],
    overrides: dict[tuple[str, str], dict[str, Any]],
    postgame: dict[tuple[str, str], list[str]],
) -> dict[str, Any]:
    override = overrides.get((game["game_id"], team))
    if override is not None:
        override_time = _utc(override.get("observed_at_utc"))
        if override_time is not None and override_time <= cutoff:
            return {
                "certainty": "CONFIRMED_PRE_CUTOFF",
                "candidate_1": override.get("expected_starter_id"),
                "candidate_2": None,
                "reason_codes": "TIMESTAMPED_OFFICIAL_OVERRIDE_PRE_CUTOFF",
                "postgame_id": (postgame.get((game["game_id"], team)) or [None])[0],
            }

    evidence = [
        row
        for row in depth
        if row.get("season") == game["season"]
        and row.get("week") == game["week"]
        and row.get("team") == team
        and row.get("player_id")
        and row.get("source_dt_parsed") is not None
        and row["source_dt_parsed"] <= cutoff
    ]
    if evidence:
        latest_by_player: dict[str, dict[str, Any]] = {}
        for row in evidence:
            player = str(row["player_id"])
            if player not in latest_by_player or row["source_dt_parsed"] > latest_by_player[player]["source_dt_parsed"]:
                latest_by_player[player] = row
        latest = list(latest_by_player.values())
        min_rank = min((row["depth_rank"] for row in latest if row["depth_rank"] is not None), default=None)
        leaders = sorted(
            {
                str(row["player_id"])
                for row in latest
                if min_rank is None or row.get("depth_rank") == min_rank
            }
        )
        if len(leaders) == 1:
            return {
                "certainty": "DEPTH_CHART_SUPPORTED",
                "candidate_1": leaders[0],
                "candidate_2": None,
                "reason_codes": "TIMESTAMPED_DEPTH_ROW_AT_OR_BEFORE_CUTOFF",
                "postgame_id": (postgame.get((game["game_id"], team)) or [None])[0],
            }
        if leaders:
            return {
                "certainty": "AMBIGUOUS",
                "candidate_1": leaders[0],
                "candidate_2": leaders[1] if len(leaders) > 1 else None,
                "reason_codes": "CONFLICTING_TOP_DEPTH_ROWS_PRE_CUTOFF",
                "postgame_id": (postgame.get((game["game_id"], team)) or [None])[0],
            }

    candidates = _roster_candidates(rosters, game, team)
    if candidates:
        certainty = "ROSTER_SUPPORTED" if len(candidates) == 1 else "AMBIGUOUS"
        return {
            "certainty": certainty,
            "candidate_1": candidates[0],
            "candidate_2": candidates[1] if len(candidates) > 1 else None,
            "reason_codes": "ROSTER_MEMBERSHIP_ONLY" if len(candidates) == 1 else "MULTIPLE_ROSTER_QBS_NO_RANK",
            "postgame_id": (postgame.get((game["game_id"], team)) or [None])[0],
        }

    postgame_ids = postgame.get((game["game_id"], team), [])
    if postgame_ids:
        return {
            "certainty": "POSTGAME_ONLY_EVIDENCE",
            "candidate_1": None,
            "candidate_2": None,
            "reason_codes": "POSTGAME_EVIDENCE_RETAINED_FOR_AUDIT_NOT_STARTER_SELECTION",
            "postgame_id": postgame_ids[0],
        }
    return {
        "certainty": "UNKNOWN",
        "candidate_1": None,
        "candidate_2": None,
        "reason_codes": "NO_DEFENSIBLE_PRE_CUTOFF_EVIDENCE",
        "postgame_id": None,
    }


def resolve_starter_certainty(
    games: pl.DataFrame,
    availability: pl.DataFrame,
    depth_evidence: pl.DataFrame | None = None,
    rosters: pl.DataFrame | None = None,
    postgame_evidence: pl.DataFrame | None = None,
    overrides: pl.DataFrame | None = None,
) -> pl.DataFrame:
    assert_unique_keys(games, ["game_id"], "game")
    avail = {
        (row["season"], row["season_type"], row["week"]): row["prediction_as_of_utc"]
        for row in availability.to_dicts()
    }
    depth = _depth_rows(depth_evidence)
    roster = _roster_rows(rosters)
    override_index = _override_index(overrides)
    postgame = _postgame_index(postgame_evidence)
    rows = []
    for game in games.sort(["season", "week", "game_id"]).to_dicts():
        cutoff = avail[(game["season"], game["season_type"], game["week"])]
        home = _resolve_side(game, game["home_team"], cutoff, depth, roster, override_index, postgame)
        away = _resolve_side(game, game["away_team"], cutoff, depth, roster, override_index, postgame)
        combined = home["certainty"] if home["certainty"] == away["certainty"] else (
            "POSTGAME_ONLY_EVIDENCE"
            if "POSTGAME_ONLY_EVIDENCE" in {home["certainty"], away["certainty"]}
            and {home["certainty"], away["certainty"]}.issubset({"POSTGAME_ONLY_EVIDENCE", "UNKNOWN"})
            else (
                "AMBIGUOUS" if "AMBIGUOUS" in {home["certainty"], away["certainty"]} else "UNKNOWN"
            )
        )
        rows.append(
            {
                "game_id": game["game_id"],
                "season": int(game["season"]),
                "season_type": game["season_type"],
                "week": int(game["week"]),
                "home_team": game["home_team"],
                "away_team": game["away_team"],
                "feature_as_of_utc": cutoff,
                "home_qb_candidate_1": home["candidate_1"],
                "home_qb_candidate_2": home["candidate_2"],
                "away_qb_candidate_1": away["candidate_1"],
                "away_qb_candidate_2": away["candidate_2"],
                "home_starter_certainty": home["certainty"],
                "away_starter_certainty": away["certainty"],
                "starter_certainty": combined,
                "starter_reason_codes": f"HOME:{home['reason_codes']}|AWAY:{away['reason_codes']}",
                "home_postgame_qb_evidence_id": home["postgame_id"],
                "away_postgame_qb_evidence_id": away["postgame_id"],
            }
        )
    result = pl.DataFrame(rows).with_columns(pl.col("feature_as_of_utc").cast(pl.Datetime("us", "UTC")))
    assert_unique_keys(result, ["game_id"], "starter game")
    return result


def starter_scenarios(starters: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for row in starters.to_dicts():
        for side in ("home", "away"):
            candidates = [row.get(f"{side}_qb_candidate_1"), row.get(f"{side}_qb_candidate_2")]
            if not any(candidates):
                candidates = [None]
            for rank, player_id in enumerate(candidates, start=1):
                if rank == 2 and player_id is None:
                    continue
                rows.append(
                    {
                        "game_id": row["game_id"],
                        "season": row["season"],
                        "season_type": row["season_type"],
                        "week": row["week"],
                        "team": row[f"{side}_team"] if f"{side}_team" in row else (
                            row["home_team"] if side == "home" else row["away_team"]
                        ),
                        "side": side,
                        "candidate_rank": rank,
                        "player_id": player_id,
                        "starter_certainty": row[f"{side}_starter_certainty"],
                        "feature_as_of_utc": row["feature_as_of_utc"],
                    }
                )
    return pl.DataFrame(rows).sort(["season", "week", "game_id", "side", "candidate_rank"])
