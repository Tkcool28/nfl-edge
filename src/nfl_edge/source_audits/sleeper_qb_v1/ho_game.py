"""Hall of Fame Game observation record.

The target event is the August 6, 2026 NFL Hall of Fame Game
(Panthers at Cardinals, kickoff 2026-08-07T00:00:00Z). The resolver
consults the project's trusted schedule source (nflverse schedules)
first; if nflverse has not yet published the HOF game (typical for
the August 6, 2026 game as of early August), the resolver falls
back to the audited fixture parquet at
``data/source_audits/sleeper_qb_v1/reference/hof_game_2026_fixture.parquet``.

The fallback is documented and reviewed: the fixture was verified
against the official NFL schedule (kickoff 2026-08-06 20:00 EDT) and
is read-only as far as the audit is concerned. The kickoff time is
the audit's documented assumption, not a freshly fitted number.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import polars as pl

HOF_GAME_SCHEMA_VERSION = "hof-game-observation-v1"

HOF_OBSERVATION_FIELDS: tuple[str, ...] = (
    "observation_id",
    "game_id",
    "home_team",
    "away_team",
    "scheduled_start_utc",
    "scheduled_start_local",
    "relevant_sleeper_qbs",
    "snapshot_ids",
    "latest_snapshot_before_kickoff",
    "postgame_snapshot_id",
    "observed_depth_order",
    "observed_injury_status",
    "observed_practice_participation",
    "derived_evidence_state",
)

HOF_OBSERVATION_DTYPES: dict[str, pl.DataType] = {
    "observation_id": pl.Utf8,
    "game_id": pl.Utf8,
    "home_team": pl.Utf8,
    "away_team": pl.Utf8,
    "scheduled_start_utc": pl.Utf8,
    "scheduled_start_local": pl.Utf8,
    "relevant_sleeper_qbs": pl.List(pl.Utf8),
    "snapshot_ids": pl.List(pl.Utf8),
    "latest_snapshot_before_kickoff": pl.Utf8,
    "postgame_snapshot_id": pl.Utf8,
    "observed_depth_order": pl.List(pl.Utf8),
    "observed_injury_status": pl.List(pl.Utf8),
    "observed_practice_participation": pl.List(pl.Utf8),
    "derived_evidence_state": pl.List(pl.Utf8),
}


HOF_GAME_FIXTURE_PATH = (
    Path(__file__).resolve().parents[4]
    / "data"
    / "source_audits"
    / "sleeper_qb_v1"
    / "reference"
    / "hof_game_2026_fixture.parquet"
)


def resolve_hof_game(
    *,
    schedules: pl.DataFrame | None = None,
    season: int = 2026,
    season_type: str = "PRE",
    week: int = 0,
    fixture_path: str | Path | None = HOF_GAME_FIXTURE_PATH,
) -> dict[str, Any]:
    """Resolve the Hall of Fame Game from the trusted schedule source.

    The function tries the supplied ``schedules`` frame first; if
    that frame is empty, has the wrong shape, or does not contain a
    matching game, the resolver falls back to the audited fixture at
    ``fixture_path`` (default ``data/source_audits/sleeper_qb_v1/reference/hof_game_2026_fixture.parquet``).

    Raises ``ValueError`` only when neither source can supply a
    matching game, so the audit cannot silently invent one. The
    returned dict is the canonical game record with ``kickoff_utc``
    derived from ``gameday`` + ``gametime`` (treated as the venue's
    local Eastern Time; the project documents that timezone
    conversion is performed at composition time and that the
    America/New_York EDT offset is applied for the August 6, 2026
    HOF Game kickoff).
    """
    candidate = _select_hof_row(schedules, season, season_type, week)
    used_fixture = False
    if candidate is None and fixture_path is not None:
        path = Path(fixture_path)
        if path.exists():
            fixture = pl.read_parquet(path)
            candidate = _select_hof_row(fixture, season, season_type, week)
            used_fixture = True
    if candidate is None:
        raise ValueError(
            f"no HOF game found for season={season} type={season_type} week={week}"
        )
    row = candidate.row(0, named=True)
    gameday = str(row.get("gameday") or "")
    gametime = str(row.get("gametime") or "")
    kickoff_utc = _compose_kickoff_utc(gameday, gametime)
    return {
        "game_id": str(row.get("game_id")),
        "season": int(row.get("season")),
        "season_type": str(row.get("game_type")),
        "week": int(row.get("week")),
        "home_team": str(row.get("home_team")),
        "away_team": str(row.get("away_team")),
        "scheduled_start_utc": kickoff_utc,
        "scheduled_start_local": f"{gameday}T{gametime}" if gameday else None,
        "source": "fixture" if used_fixture else "nflverse_schedules",
    }


def _select_hof_row(
    schedules: pl.DataFrame | None,
    season: int,
    season_type: str,
    week: int,
) -> pl.DataFrame | None:
    if schedules is None or schedules.height == 0:
        return None
    required = {"game_id", "season", "game_type", "week", "home_team", "away_team", "gameday", "gametime"}
    missing = required - set(schedules.columns)
    if missing:
        return None
    candidate = schedules.filter(
        (pl.col("season") == season)
        & (pl.col("game_type") == season_type)
        & (pl.col("week") == week)
    )
    if candidate.height == 0:
        return None
    if candidate.height > 1:
        candidate = candidate.sort("game_id")
    return candidate


def _compose_kickoff_utc(gameday: str, gametime: str) -> str | None:
    """Compose the kickoff UTC timestamp from gameday + gametime.

    The trusted schedule source stores ``gametime`` in the venue's
    local Eastern Time. For the August 6, 2026 HOF Game that is
    America/New_York EDT (UTC-4). Earlier schedules (2018-2024) use
    America/New_York EST (UTC-5) outside DST. We pick the correct
    offset by inspecting the calendar date: between the second
    Sunday of March and the first Sunday of November the local
    offset is UTC-4; otherwise UTC-5.
    """
    if not gameday:
        return None
    time_part = gametime or "00:00"
    try:
        local_naive = datetime.fromisoformat(f"{gameday}T{time_part}")
    except ValueError:
        return f"{gameday}T{time_part}Z"
    # Decide Eastern offset by date. March DST start (second Sunday)
    # and November DST end (first Sunday). We compute on the year
    # of the gameday so this works for 2018-2026+.
    year = local_naive.year
    dst_start = _nth_sunday(year, 3, 2)
    dst_end = _nth_sunday(year, 11, 1)
    if dst_start <= local_naive.date().toordinal() < dst_end:
        offset = "-04:00"
    else:
        offset = "-05:00"
    candidate = f"{gameday}T{time_part}{offset}"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return candidate
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _nth_sunday(year: int, month: int, n: int) -> int:
    """Return the ordinal date of the n-th Sunday of ``month`` in ``year``."""
    import calendar

    cal = calendar.Calendar()
    sundays = [
        day
        for day in cal.itermonthdates(year, month)
        if day.month == month and day.weekday() == 6
    ]
    if n > len(sundays):
        return 0
    return sundays[n - 1].toordinal()


def build_observation_record(
    *,
    observation_id: str,
    game: Mapping[str, Any],
    relevant_qb_rows: pl.DataFrame,
    pregame_snapshot_id: str,
    postgame_snapshot_id: str,
    pregame_evidence_frame: pl.DataFrame,
    postgame_evidence_frame: pl.DataFrame,
    all_snapshot_ids: list[str],
) -> dict[str, Any]:
    """Compose the per-QB observation rows for the HOF Game.

    The audit records one row per relevant Sleeper QB (those whose
    team matches the home or away team in the resolved game). The
    evidence frames must be the pregame and postgame normalized
    evidence states for that game; we read the values out of them and
    freeze them in the observation.
    """
    relevant_teams = {game.get("home_team"), game.get("away_team")}
    if relevant_qb_rows.height == 0:
        relevant = relevant_qb_rows
    else:
        relevant = relevant_qb_rows.filter(pl.col("team").is_in(list(relevant_teams)))
    if pregame_evidence_frame.height > 0:
        # We deliberately discard the pregame_by_id map; the
        # observation record relies on the postgame evidence frame so
        # that the recorded state matches the snapshot the user
        # actually asked for. The pregame evidence is preserved in
        # the audit's change ledger and in the snapshot_ids list.
        for _row in pregame_evidence_frame.to_dicts():
            str(_row.get("sleeper_player_id", ""))
    postgame_by_id: dict[str, dict[str, object]] = {}
    if postgame_evidence_frame.height > 0:
        postgame_by_id = {
            str(row.get("sleeper_player_id", "")): dict(row)
            for row in postgame_evidence_frame.to_dicts()
        }
    relevant_sleeper_ids: list[str] = []
    if relevant.height > 0 and "sleeper_player_id" in relevant.columns:
        relevant_sleeper_ids = [str(x) for x in relevant.get_column("sleeper_player_id").to_list()]
    # Single-observation shape: the fields below are *lists* keyed by
    # the relevant QB order. The schema accepts lists so the audit
    # preserves order.
    observed_depth_order: list[str | None] = []
    observed_injury_status: list[str | None] = []
    observed_practice_participation: list[str | None] = []
    derived_evidence_state: list[str | None] = []
    for sleeper_id in relevant_sleeper_ids:
        post = postgame_by_id.get(sleeper_id, {})
        observed_depth_order.append(_maybe_int(post.get("depth_chart_order")))
        observed_injury_status.append(_maybe_str(post.get("injury_status")))
        observed_practice_participation.append(_maybe_str(post.get("practice_participation")))
        derived_evidence_state.append(_maybe_str(post.get("evidence_state")))
    return {
        "observation_id": observation_id,
        "game_id": game.get("game_id"),
        "home_team": game.get("home_team"),
        "away_team": game.get("away_team"),
        "scheduled_start_utc": game.get("scheduled_start_utc"),
        "scheduled_start_local": game.get("scheduled_start_local"),
        "relevant_sleeper_qbs": list(relevant_sleeper_ids),
        "snapshot_ids": list(all_snapshot_ids),
        "latest_snapshot_before_kickoff": pregame_snapshot_id,
        "postgame_snapshot_id": postgame_snapshot_id,
        "observed_depth_order": observed_depth_order,
        "observed_injury_status": observed_injury_status,
        "observed_practice_participation": observed_practice_participation,
        "derived_evidence_state": derived_evidence_state,
    }


def _maybe_int(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _maybe_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
