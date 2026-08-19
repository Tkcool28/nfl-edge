"""DST-aware kickoff UTC derivation and deterministic T-60 kickoff clustering.

This module owns the two most safety-critical derivations in the historical
market acquisition manifest:

* ``gameday_gametime_to_utc`` — combines nflverse ``gameday`` (date) and
  ``gametime`` (time) into a UTC ``datetime``, interpreted in
  ``America/New_York`` in a DST-aware way. The frozen
  ``scheduled_start_utc`` column is all-NULL, so this is the authoritative
  kickoff clock for the plan.

* ``build_clusters`` — the deterministic *natural kickoff cluster* algorithm
  from the task contract:

    1. sort each gameday's kickoff timestamps;
    2. greedily group consecutive games whose kickoff is within
       ``CLUSTER_MAX_SPAN_MINUTES`` (30) of the cluster's earliest kickoff;
    3. anchor the request at ``earliest_kickoff - 60 min`` (T-60).

Every game belongs to exactly one cluster, so the observation lead is always
in ``[60, 90]`` minutes by construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from .manifest import (
    ACQUISITION_SEASONS,
    ANCHOR_LEAD_MINUTES,
    CLUSTER_MAX_SPAN_MINUTES,
    KICKOFF_TZ,
)

_EASTERN = ZoneInfo(KICKOFF_TZ)


class ClusterError(RuntimeError):
    """Raised when clustering violates the frozen acquisition contract."""


def gameday_gametime_to_utc(gameday: str, gametime: str) -> datetime:
    """Combine nflverse ``gameday``/``gametime`` into a UTC kickoff.

    ``gameday`` is ``YYYY-MM-DD`` and ``gametime`` is ``HH:MM``. The naive
    local time is interpreted in ``America/New_York`` and converted to UTC in
    a DST-aware way (``zoneinfo`` resolves the correct offset for the date).
    """
    if not isinstance(gameday, str) or not isinstance(gametime, str):
        raise TypeError("gameday and gametime must be strings")
    naive = datetime.strptime(f"{gameday} {gametime}", "%Y-%m-%d %H:%M")
    return naive.replace(tzinfo=_EASTERN).astimezone(timezone.utc)


def load_kickoff_frame(schedule_path: str | Path) -> pl.DataFrame:
    """Load the raw nflverse schedule and keep only acquisition seasons.

    Returns a frame with ``game_id``, ``season``, ``gameday``, ``gametime``.
    Only 2020--2024 rows are kept (2025 stays sealed).
    """
    frame = pl.read_parquet(schedule_path)
    missing = set(("game_id", "season", "gameday", "gametime")) - set(frame.columns)
    if missing:
        raise ClusterError(f"raw schedule missing columns: {sorted(missing)}")
    return frame.filter(pl.col("season").is_in(list(ACQUISITION_SEASONS))).select(
        ["game_id", "season", "gameday", "gametime"]
    )


@dataclass(frozen=True)
class Cluster:
    """One deterministic natural-kickoff acquisition cluster."""

    cluster_id: str
    request_plan_id: str
    season: int
    gameday: str
    earliest_kickoff_utc: datetime
    anchor_utc: datetime
    game_ids: tuple[str, ...]
    lead_minutes: tuple[float, ...]
    width_minutes: float
    game_count: int


def build_clusters(frame: pl.DataFrame) -> list[Cluster]:
    """Build deterministic T-60 natural kickoff clusters.

    Determinism: rows are sorted by ``(gameday, kickoff_utc, game_id)`` and
    processed in that fixed order; a game joins the open cluster for its
    gameday iff its kickoff is at most ``CLUSTER_MAX_SPAN_MINUTES`` after the
    cluster's earliest kickoff, otherwise it opens a new cluster. Clusters
    never span a gameday boundary.
    """
    rows: list[tuple[str, int, str, datetime]] = []
    for rec in frame.iter_rows(named=True):
        kick = gameday_gametime_to_utc(rec["gameday"], rec["gametime"])
        rows.append((rec["game_id"], int(rec["season"]), str(rec["gameday"]), kick))

    rows.sort(key=lambda r: (r[2], r[3], r[0]))  # gameday, kickoff, game_id

    # Group by gameday, then greedy-cluster within the day.
    per_day: dict[str, list[tuple[str, int, str, datetime]]] = {}
    for row in rows:
        per_day.setdefault(row[2], []).append(row)

    clusters: list[Cluster] = []
    for season in sorted(ACQUISITION_SEASONS):
        seq = 0
        for gameday in sorted(per_day):
            day_rows = per_day[gameday]
            if not day_rows or day_rows[0][1] != season:
                continue
            group: list[tuple[str, int, str, datetime]] = []
            for row in day_rows:
                if not group:
                    group = [row]
                    continue
                span = (row[3] - group[0][3]).total_seconds() / 60.0
                if span <= CLUSTER_MAX_SPAN_MINUTES:
                    group.append(row)
                else:
                    clusters.append(_make_cluster(season, seq, group))
                    seq += 1
                    group = [row]
            if group:
                clusters.append(_make_cluster(season, seq, group))
                seq += 1

    return clusters


def _make_cluster(
    season: int, seq: int, group: list[tuple[str, int, str, datetime]]
) -> Cluster:
    earliest = min(r[3] for r in group)
    anchor = earliest - timedelta(minutes=ANCHOR_LEAD_MINUTES)
    game_ids = tuple(sorted(r[0] for r in group))
    leads = tuple(round((r[3] - anchor).total_seconds() / 60.0, 4) for r in group)
    width = round((max(r[3] for r in group) - earliest).total_seconds() / 60.0, 4)
    idx = seq + 1
    gameday = group[0][2]
    return Cluster(
        cluster_id=f"{season}_{idx:03d}",
        request_plan_id=f"md_{season}_{idx:03d}",
        season=season,
        gameday=gameday,
        earliest_kickoff_utc=earliest,
        anchor_utc=anchor,
        game_ids=game_ids,
        lead_minutes=leads,
        width_minutes=width,
        game_count=len(game_ids),
    )
