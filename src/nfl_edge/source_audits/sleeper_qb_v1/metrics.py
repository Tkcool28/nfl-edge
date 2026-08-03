"""Reliability metrics for the Sleeper QB source audit.

This module reduces the fetch ledger, the normalized snapshots, the
crosswalk, and the change ledger into the reliability metrics the spec
requires (spec §13). It is a pure aggregator: no I/O, no clock, no
network.
"""

from __future__ import annotations

from typing import Any, Mapping

import polars as pl


def compute_reliability_metrics(
    *,
    fetch_attempts: list[Mapping[str, Any]],
    active_qb_snapshots: list[Mapping[str, Any]],
    crosswalk_snapshots: list[Mapping[str, Any]],
    change_ledger: pl.DataFrame,
    freshness_history: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compute the spec §13 metrics from the audit's own artifacts."""
    scheduled = len(fetch_attempts)
    attempted = sum(1 for attempt in fetch_attempts)
    successful = sum(1 for attempt in fetch_attempts if attempt.get("success"))
    failed = attempted - successful
    success_pct = (successful / attempted) if attempted else 0.0
    latencies = sorted(int(a.get("duration_ms", 0)) for a in fetch_attempts)
    median_latency = _percentile(latencies, 0.5) if latencies else None
    max_latency = max(latencies) if latencies else None
    http_status_counts: dict[str, int] = {}
    raw_sizes: list[int] = []
    for attempt in fetch_attempts:
        status = attempt.get("http_status")
        if status is None:
            http_status_counts["network_error"] = http_status_counts.get("network_error", 0) + 1
        else:
            key = str(int(status))
            http_status_counts[key] = http_status_counts.get(key, 0) + 1
        raw_sizes.append(int(attempt.get("response_bytes", 0)))
    total_active_rows = 0
    unique_sleeper_ids: set[str] = set()
    snapshots_with_null_injury = 0
    snapshots_with_populated_injury = 0
    snapshots_with_practice = 0
    snapshots_with_depth_order = 0
    for snapshot in active_qb_snapshots:
        rows = snapshot.get("rows", [])
        total_active_rows += len(rows)
        for row in rows:
            sleeper_id = str(row.get("sleeper_player_id", ""))
            if sleeper_id:
                unique_sleeper_ids.add(sleeper_id)
            injury = row.get("injury_status")
            if injury in (None, ""):
                snapshots_with_null_injury += 1
            else:
                snapshots_with_populated_injury += 1
            practice = row.get("practice_participation")
            if practice not in (None, ""):
                snapshots_with_practice += 1
            depth = row.get("depth_chart_order")
            if depth not in (None, ""):
                snapshots_with_depth_order += 1
    # Per-row counts for the global metrics.
    exact_id_matches = 0
    fallback_matches = 0
    unmatched = 0
    duplicates: dict[str, int] = {}
    # Per-snapshot per-method counts for the reconciliation table.
    # The audit must satisfy:
    #   sum(match categories + unmatched + excluded) ==
    #   total_current_team_candidates
    # where the current-team denominator is the count of crosswalk
    # rows in the snapshot whose sleeper_player_id corresponds to a
    # current-team QB (i.e. the row's team is non-null in the active
    # QB snapshot). The metrics derive that denominator from the
    # active QB snapshot's ``team`` field, indexed by
    # ``sleeper_player_id``, and join it onto the crosswalk row.
    crosswalk_method_counts: dict[str, dict[str, int]] = {}
    current_team_ids_by_snapshot: dict[str, set[str]] = {}
    for snapshot in active_qb_snapshots:
        sid = str(snapshot.get("snapshot_id", ""))
        if not sid:
            continue
        ids = current_team_ids_by_snapshot.setdefault(sid, set())
        for row in snapshot.get("rows", []):
            pid = str(row.get("sleeper_player_id", ""))
            team = row.get("team")
            if pid and team not in (None, ""):
                ids.add(pid)
    for snapshot in crosswalk_snapshots:
        rows = snapshot.get("rows", [])
        sid = str(snapshot.get("snapshot_id", ""))
        # The orchestrator does not tag crosswalk snapshots with
        # ``snapshot_id`` in the same shape; fall back to the
        # crosswalk row's own snapshot_id when missing.
        if not sid:
            for row in rows:
                sid = str(row.get("snapshot_id", ""))
                break
        current_team_ids = current_team_ids_by_snapshot.get(sid, set())
        for row in rows:
            method = row.get("match_method")
            is_matched = bool(row.get("is_matched"))
            if method in {"exact_sleeper_id", "exact_gsis", "exact_espn", "exact_other_stable"} and is_matched:
                exact_id_matches += 1
            elif method == "name_team_fallback":
                fallback_matches += 1
            else:
                unmatched += 1
            nflv = row.get("nflverse_player_id")
            if nflv:
                duplicates[nflv] = duplicates.get(nflv, 0) + 1
            # Per-snapshot per-method tally restricted to current-team QBs.
            if sid and current_team_ids and str(row.get("sleeper_player_id", "")) in current_team_ids:
                bucket = crosswalk_method_counts.setdefault(sid, {
                    "exact_sleeper_id": 0,
                    "exact_gsis": 0,
                    "exact_espn": 0,
                    "exact_other_stable": 0,
                    "name_team_fallback": 0,
                    "unmatched": 0,
                    "excluded_dup_ambig": 0,
                    "total_current_team_candidates": 0,
                })
                if method in bucket:
                    bucket[method] += 1
                elif method in (None, "none") or not is_matched:
                    bucket["unmatched"] += 1
                else:
                    bucket["excluded_dup_ambig"] += 1
                bucket["total_current_team_candidates"] += 1
    duplicate_id_violations = sum(1 for count in duplicates.values() if count > 1)
    field_change_events = int(change_ledger.height) if change_ledger is not None else 0
    schema_drift_events = sum(
        1 for event in freshness_history if event.get("state") == "SCHEMA_DRIFT"
    )
    incomplete_events = sum(
        1 for event in freshness_history if event.get("state") == "INCOMPLETE_RESPONSE"
    )
    stale_intervals = sum(
        1 for event in freshness_history if event.get("state") == "STALE_LAST_SUCCESS"
    )
    intervals = [int(e.get("interval_seconds", 0)) for e in freshness_history if "interval_seconds" in e]
    longest_interval = max(intervals) if intervals else None
    return {
        "scheduled_fetches": scheduled,
        "attempted_fetches": attempted,
        "successful_fetches": successful,
        "failed_fetches": failed,
        "success_pct": round(success_pct, 4),
        "median_latency_ms": median_latency,
        "max_latency_ms": max_latency,
        "http_status_counts": dict(sorted(http_status_counts.items())),
        "raw_response_size_bytes": {
            "min": min(raw_sizes) if raw_sizes else 0,
            "max": max(raw_sizes) if raw_sizes else 0,
            "total": sum(raw_sizes),
        },
        "active_qb_row_count": total_active_rows,
        "unique_sleeper_qb_ids": len(unique_sleeper_ids),
        "exact_id_crosswalk_count": exact_id_matches,
        "fallback_name_crosswalk_count": fallback_matches,
        "unmatched_qb_count": unmatched,
        "duplicate_id_violations": duplicate_id_violations,
        "current_team_crosswalk_by_snapshot": {
            sid: counts for sid, counts in sorted(crosswalk_method_counts.items())
        },
        "schema_drift_events": schema_drift_events,
        "snapshots_with_null_injury_status": snapshots_with_null_injury,
        "snapshots_with_populated_injury_status": snapshots_with_populated_injury,
        "snapshots_with_practice_participation": snapshots_with_practice,
        "snapshots_with_depth_chart_order": snapshots_with_depth_order,
        "field_change_events": field_change_events,
        "stale_intervals": stale_intervals,
        "longest_interval_without_successful_fetch_seconds": longest_interval,
        "incomplete_response_events": incomplete_events,
    }


def _percentile(sorted_values: list[int], percentile: float) -> int:
    if not sorted_values:
        return 0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return int(round(sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight))
