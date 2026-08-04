"""Reconciliation tests for the Sleeper QB source audit.

These tests assert that the headline metrics reconcile exactly: the
sum of per-method match buckets, unmatched rows, and excluded rows
must equal the ``total_current_team_candidates`` count for each
snapshot reported in the metrics. The tests also assert that the
serialized unmatched count equals the number of serialized unmatched
records in the crosswalk parquet.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from nfl_edge.source_audits.sleeper_qb_v1 import metrics, normalize
from nfl_edge.source_audits.sleeper_qb_v1.crosswalk import (
    build_crosswalk,
)


def _sample_payload() -> dict[str, dict[str, Any]]:
    """Build a small deterministic Sleeper-like payload.

    3 current-team QBs (matched), 1 free agent (unmatched), 1
    duplicate Sleeper id (rejection path), 1 record with
    `gsis_id` only.
    """
    return {
        "1": {
            "player_id": "1", "position": "QB", "team": "KC",
            "active": True, "sleeper_id": 1, "gsis_id": "GSIS-1",
            "full_name": "Pat Mahomes", "first_name": "Pat", "last_name": "Mahomes",
        },
        "2": {
            "player_id": "2", "position": "QB", "team": "BUF",
            "active": True, "sleeper_id": 2, "gsis_id": "GSIS-2",
            "full_name": "Josh Allen", "first_name": "Josh", "last_name": "Allen",
        },
        "3": {
            "player_id": "3", "position": "QB", "team": "CIN",
            "active": True, "sleeper_id": 3, "espn_id": "3040",
            "full_name": "Joe Burrow", "first_name": "Joe", "last_name": "Burrow",
        },
        "4": {
            "player_id": "4", "position": "QB", "team": None,
            "active": True, "sleeper_id": 4,
            "full_name": "Free Agent QB", "first_name": "Free", "last_name": "Agent",
        },
        "5": {
            "player_id": "5", "position": "QB", "team": "DAL",
            "active": True, "sleeper_id": 5,
            "full_name": "Camp Arm", "first_name": "Camp", "last_name": "Arm",
        },
    }


def _sample_reference() -> pl.DataFrame:
    """Build a deterministic nflverse reference with 4 QBs and 1 FA."""
    return pl.DataFrame([
        {
            "player_id": "GSIS-1", "sleeper_id": 1, "gsis_id": "GSIS-1",
            "espn_id": 1234, "full_name": "Pat Mahomes", "position": "QB",
            "db_season": 2026, "team": "KC",
        },
        {
            "player_id": "GSIS-2", "sleeper_id": 2, "gsis_id": "GSIS-2",
            "full_name": "Josh Allen", "position": "QB",
            "db_season": 2026, "team": "BUF",
        },
        {
            "player_id": "ESPN-3040", "sleeper_id": 3, "espn_id": 3040,
            "full_name": "Joe Burrow", "position": "QB",
            "db_season": 2026, "team": "CIN",
        },
        {
            "player_id": "GSIS-FA", "sleeper_id": 4, "gsis_id": "GSIS-FA",
            "full_name": "Free Agent QB", "position": "QB",
            "db_season": 2026, "team": None,
        },
    ])


def _normalize(payload: dict[str, dict[str, Any]], snap_id: str) -> pl.DataFrame:
    """Wrap normalize_qb_payload (which returns a tuple) and return
    the active frame only."""
    active, _inactive, _warnings = normalize.normalize_qb_payload(
        snapshot_id=snap_id,
        fetched_at_utc="2026-08-03T00:00:00Z",
        raw_payload=payload,
    )
    return active


def test_reconciliation_table_sums_to_total_candidates() -> None:
    """For each snapshot, the metrics must report buckets that sum
    exactly to the snapshot's current-team candidate count."""
    snap_id = "snap-test-1"
    active = _normalize(_sample_payload(), snap_id)
    ref = _sample_reference()
    crosswalk_frame = build_crosswalk(
        snapshot_id=snap_id, active_qb_frame=active, nflverse_qbs=ref,
    )
    rows = active.to_dicts()
    m = metrics.compute_reliability_metrics(
        runs=[
            metrics.RunMetric(
                snapshot_id=snap_id,
                observed_at_utc="2026-08-03T00:00:00Z",
                success=True,
                fetch_attempts=[{"success": True, "duration_ms": 50, "http_status": 200,
                                  "response_bytes": 1024}],
                active_rows=rows,
                crosswalk_rows=crosswalk_frame.to_dicts(),
            )
        ],
        change_ledger=pl.DataFrame(),
        freshness_history=[],
    )
    by_snapshot = m["current_team_crosswalk_by_snapshot"]
    assert snap_id in by_snapshot, "snapshot missing from reconciliation"
    counts = by_snapshot[snap_id]
    matched = (
        counts["exact_sleeper_id"]
        + counts["exact_gsis"]
        + counts["exact_espn"]
        + counts["exact_other_stable"]
        + counts["name_team_fallback"]
    )
    sum_check = matched + counts["unmatched"] + counts["excluded_dup_ambig"]
    assert sum_check == counts["total_current_team_candidates"], (
        f"sum({matched} matched + {counts['unmatched']} unmatched + "
        f"{counts['excluded_dup_ambig']} excluded) = {sum_check} "
        f"but total_current_team_candidates = "
        f"{counts['total_current_team_candidates']}"
    )


def test_unmatched_serialized_count_equals_records() -> None:
    """The serialized unmatched count must equal the number of
    serialized unmatched records in the crosswalk parquet."""
    snap_id = "snap-test-2"
    active = _normalize(_sample_payload(), snap_id)
    ref = _sample_reference()
    crosswalk_frame = build_crosswalk(
        snapshot_id=snap_id, active_qb_frame=active, nflverse_qbs=ref,
    )
    import pathlib
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "crosswalk.parquet"
        crosswalk_frame.write_parquet(path)
        reloaded = pl.read_parquet(path)
    active_rows = active.to_dicts()
    m = metrics.compute_reliability_metrics(
        runs=[
            metrics.RunMetric(
                snapshot_id=snap_id,
                observed_at_utc="2026-08-03T00:00:00Z",
                success=True,
                fetch_attempts=[{"success": True, "duration_ms": 50, "http_status": 200,
                                  "response_bytes": 1024}],
                active_rows=active_rows,
                crosswalk_rows=reloaded.to_dicts(),
            )
        ],
        change_ledger=pl.DataFrame(),
        freshness_history=[],
    )
    by_snapshot = m["current_team_crosswalk_by_snapshot"]
    counts = by_snapshot[snap_id]
    serialized_unmatched = counts["unmatched"]
    active_ct_ids = {
        str(r["sleeper_player_id"])
        for r in active_rows
        if r.get("team") not in (None, "")
    }
    serialized_unmatched_records = [
        r for r in reloaded.to_dicts()
        if str(r.get("sleeper_player_id", "")) in active_ct_ids
        and not r.get("is_matched")
    ]
    assert serialized_unmatched == len(serialized_unmatched_records), (
        f"unmatched count = {serialized_unmatched} but record list "
        f"length = {len(serialized_unmatched_records)}"
    )


def test_fantasy_position_only_records_excluded() -> None:
    """A record with `position != 'QB'` and `fantasy_positions=['QB']`
    must NOT be in the current-team candidate denominator (because the
    normalize step drops it before the crosswalk runs)."""
    snap_id = "snap-test-3"
    payload = _sample_payload()
    payload["99"] = {
        "player_id": "99", "position": "TE", "team": "NYG",
        "active": True, "sleeper_id": 99,
        "fantasy_positions": ["QB"],
        "full_name": "Tommy Stevens", "first_name": "Tommy", "last_name": "Stevens",
    }
    active = _normalize(payload, snap_id)
    assert "99" not in active.get_column("sleeper_player_id").to_list(), (
        "fantasy-position-only record leaked into normalized snapshot"
    )
    # 3 current-team QBs + 1 free agent + 1 camp arm = 5
    assert active.height == 5
