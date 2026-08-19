"""Deterministic 575-row historical-market request-plan builder.

Consumes the frozen nflverse schedule (via :mod:`kickoffs`), builds the T-60
natural-kickoff clusters, and emits a deterministic, stable request plan with
one row per cluster. The plan reproduces the frozen acceptance counts (575
total; 107/111/116/120/121 by season) or raises :class:`ClusterError` with
evidence — it never silently mutates the algorithm to force a count.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import polars as pl

from .kickoffs import Cluster, ClusterError, build_clusters, load_kickoff_frame
from .manifest import (
    ALLOWED_BOOKS,
    EXPECTED_CLUSTERS_BY_SEASON,
    EXPECTED_TOTAL_CLUSTERS,
    EXPECTED_TOTAL_GAMES,
    MANIFEST_REQUEST_PLAN_PATH,
    MARKETS,
    SCHEDULE_SOURCE_PATH,
    write_manifest,
)

PLAN_SCHEMA: dict[str, pl.DataType] = {
    "request_plan_id": pl.Utf8,
    "cluster_id": pl.Utf8,
    "season": pl.Int32,
    "gameday": pl.Utf8,
    "earliest_kickoff_utc": pl.Utf8,
    "expected_earliest_kickoff_utc": pl.Utf8,
    "requested_target_timestamp_utc": pl.Utf8,
    "cluster_width_minutes": pl.Float64,
    "expected_lead_min": pl.Float64,
    "expected_lead_max": pl.Float64,
    "game_count": pl.Int32,
    "target_game_ids": pl.Utf8,
    "requested_bookmaker_keys": pl.Utf8,
    "requested_markets": pl.Utf8,
    "expected_credits": pl.Int32,
}


def _fmt_utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def plan_frame(clusters: list[Cluster]) -> pl.DataFrame:
    rows = []
    for c in clusters:
        rows.append(
            {
                "request_plan_id": c.request_plan_id,
                "cluster_id": c.cluster_id,
                "season": c.season,
                "gameday": c.gameday,
                "earliest_kickoff_utc": _fmt_utc(c.earliest_kickoff_utc),
                "expected_earliest_kickoff_utc": _fmt_utc(c.earliest_kickoff_utc),
                "requested_target_timestamp_utc": _fmt_utc(c.anchor_utc),
                "cluster_width_minutes": c.width_minutes,
                "expected_lead_min": min(c.lead_minutes),
                "expected_lead_max": max(c.lead_minutes),
                "game_count": c.game_count,
                "target_game_ids": ",".join(c.game_ids),
                "requested_bookmaker_keys": ",".join(ALLOWED_BOOKS),
                "requested_markets": ",".join(MARKETS),
                "expected_credits": 30,
            }
        )
    df = pl.DataFrame(rows, schema=PLAN_SCHEMA)
    # Deterministic stable ordering.
    df = df.sort(["season", "cluster_id"])
    return df


def _assert_acceptance_counts(clusters: list[Cluster], frame: pl.DataFrame) -> None:
    """Fail closed if the plan does not reproduce the frozen counts."""
    by_season: dict[int, int] = {}
    for c in clusters:
        by_season[c.season] = by_season.get(c.season, 0) + 1

    problems: list[str] = []
    if len(clusters) != EXPECTED_TOTAL_CLUSTERS:
        problems.append(f"total clusters {len(clusters)} != {EXPECTED_TOTAL_CLUSTERS}")
    for season, expected in EXPECTED_CLUSTERS_BY_SEASON.items():
        actual = by_season.get(season, 0)
        if actual != expected:
            problems.append(f"{season} clusters {actual} != {expected}")

    games = set()
    for c in clusters:
        games.update(c.game_ids)
    if len(games) != EXPECTED_TOTAL_GAMES:
        problems.append(
            f"assigned games {len(games)} != {EXPECTED_TOTAL_GAMES} "
            "(this implies games not assigned and/or duplicated)"
        )
    if frame.height != len(clusters):
        problems.append(f"plan rows {frame.height} != clusters {len(clusters)}")

    if problems:
        detail = "\n".join(
            f"  {s}: {by_season.get(s, 0)}" for s in sorted(by_season)
        )
        raise ClusterError(
            "Request plan does NOT reproduce the frozen acceptance counts. "
            "Refusing to emit a plan rather than mutating the clustering "
            "algorithm to force a count. Problems:\n  "
            + "\n  ".join(problems)
            + f"\nper-season observed:\n{detail}"
        )


def build_request_plan(
    schedule_path: str | Path = SCHEDULE_SOURCE_PATH,
) -> tuple[pl.DataFrame, list[Cluster]]:
    """Build (and validate) the full deterministic request plan."""
    frame = load_kickoff_frame(schedule_path)
    clusters = build_clusters(frame)
    plan = plan_frame(clusters)
    _assert_acceptance_counts(clusters, plan)
    return plan, clusters


def write_request_plan(
    plan: pl.DataFrame,
    *,
    plan_path: str | Path,
    json_path: str | Path,
    schedule_sha256: str,
    schedule_path: str | Path = SCHEDULE_SOURCE_PATH,
) -> str:
    """Atomically persist the plan parquet and its SHA-256 manifest."""
    plan_path = Path(plan_path)
    json_path = Path(json_path)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan.write_parquet(plan_path)

    digest = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    payload = {
        "version": "historical-market-request-plan-v1",
        "description": (
            "Deterministic T-60 natural-kickoff-cluster historical market "
            "acquisition request plan (575 rows). RAW acquisition only; no "
            "outcomes scored; 2025 not included."
        ),
        "plan_path": MANIFEST_REQUEST_PLAN_PATH,
        "row_count": plan.height,
        "sha256": digest,
        "schedule_source": {
            "path": SCHEDULE_SOURCE_PATH,
            "sha256": schedule_sha256,
        },
        "generated_at_utc": __import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "credits_expected": int(plan.height * 30),
        "request_plan_id_columns": ["request_plan_id"],
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return digest
