"""One strict nflverse-2026 identity seam before canonical live contracts."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

import polars as pl

CANONICAL_TEAMS = frozenset(
    {
        "ARI",
        "ATL",
        "BAL",
        "BUF",
        "CAR",
        "CHI",
        "CIN",
        "CLE",
        "DAL",
        "DEN",
        "DET",
        "GB",
        "HOU",
        "IND",
        "JAX",
        "KC",
        "LAC",
        "LAR",
        "LV",
        "MIA",
        "MIN",
        "NE",
        "NO",
        "NYG",
        "NYJ",
        "PHI",
        "PIT",
        "SEA",
        "SF",
        "TB",
        "TEN",
        "WAS",
    }
)

# Audited against the currently published 2026 nflverse schedule, team, player,
# and PBP files. This is intentionally narrower than historical-source aliases.
NFLVERSE_2026_TEAM_ALIASES = {"LA": "LAR"}


class NFLVerse2026IdentityError(ValueError):
    """Raised when a raw nflverse identity cannot enter the canonical contract."""


def canonical_team(value: Any, *, field: str = "team") -> str:
    source = str(value or "").strip().upper()
    if not source:
        raise NFLVerse2026IdentityError(f"nflverse {field} is blank")
    canonical = NFLVERSE_2026_TEAM_ALIASES.get(source, source)
    if canonical not in CANONICAL_TEAMS:
        raise NFLVerse2026IdentityError(f"unsupported nflverse team code {source!r} in {field}")
    return canonical


def canonical_game_id(value: Any, *, season: int = 2026, field: str = "game_id") -> str:
    token = str(value or "").strip().upper()
    parts = token.split("_")
    if len(parts) != 4 or parts[0] != str(season) or not parts[1].isdigit():
        raise NFLVerse2026IdentityError(f"invalid nflverse {field}: {value!r}")
    week = int(parts[1])
    if not 1 <= week <= 18:
        raise NFLVerse2026IdentityError(f"invalid nflverse {field} week: {value!r}")
    return f"{season}_{week:02d}_{canonical_team(parts[2], field=field)}_{canonical_team(parts[3], field=field)}"


def canonical_schedule_game_id(row: Mapping[str, Any], *, season: int, week: int) -> str:
    away = canonical_team(row.get("away_team"), field="away_team")
    home = canonical_team(row.get("home_team"), field="home_team")
    return f"{season}_{week:02d}_{away}_{home}"


def normalize_frame(frame: pl.DataFrame, *, team_columns: Iterable[str]) -> pl.DataFrame:
    """Normalize raw-team and game-ID columns, rejecting unknown identities."""
    result = frame
    for column in team_columns:
        if column not in result.columns:
            continue
        values = result.get_column(column).to_list()
        try:
            normalized = [canonical_team(value, field=column) if value is not None else None for value in values]
        except NFLVerse2026IdentityError as exc:
            raise NFLVerse2026IdentityError(str(exc)) from exc
        result = result.with_columns(pl.Series(column, normalized))
    if "game_id" in result.columns:
        try:
            game_ids = [
                canonical_game_id(value) if value is not None else None for value in result["game_id"].to_list()
            ]
        except NFLVerse2026IdentityError as exc:
            raise NFLVerse2026IdentityError(str(exc)) from exc
        result = result.with_columns(pl.Series("game_id", game_ids))
    return result
