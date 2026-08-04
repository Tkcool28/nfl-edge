"""Reliability metrics for the Sleeper QB source audit.

This module reduces the audit's run history into the reliability
metrics the spec requires. It is a pure aggregator: no I/O, no clock,
no network.

Count separation
----------------

The spec separates four counts:

* ``scheduled_run_count`` — distinct scheduled (or pregame /
  postgame) runs that attempted at least one HTTP fetch.
* ``attempted_fetch_count`` — total HTTP fetch attempts across all
  runs.
* ``successful_run_count`` / ``failed_run_count`` — per-run outcomes.
  A run with three retries where the last attempt succeeds counts as
  one *successful run*, not three.
* ``successful_attempt_count`` / ``failed_attempt_count`` — per-
  attempt outcomes. The same successful run contributes one
  successful attempt and two failed attempts.

Reconciling the two views:

    scheduled_run_count
        == successful_run_count + failed_run_count
    attempted_fetch_count
        == successful_attempt_count + failed_attempt_count
    attempted_fetch_count
        >= scheduled_run_count
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

import polars as pl


@dataclass(frozen=True)
class RunMetric:
    """The audit's view of a single run.

    The orchestrator constructs one of these per run and passes a
    list to ``compute_reliability_metrics``.

    Rereview contract (Rereview 4851615980): ``success`` is derived
    from the terminal ``run_outcome == SUCCESS``, never from a
    single HTTP attempt. Runs that succeeded at HTTP but failed
    in normalization / persistence / reference / HOF are
    counted as failed runs.
    """

    snapshot_id: str
    observed_at_utc: str
    success: bool
    run_outcome: str | None = None
    attempt_count: int = 0
    kind: str | None = None
    fetch_attempts: list[Mapping[str, Any]] = field(default_factory=list)
    active_rows: list[Mapping[str, Any]] = field(default_factory=list)
    crosswalk_rows: list[Mapping[str, Any]] = field(default_factory=list)


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


def compute_reliability_metrics(
    *,
    runs: Iterable[RunMetric],
    change_ledger: pl.DataFrame,
    freshness_history: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute the spec §13 metrics from the audit's own artifacts.

    Parameters
    ----------
    runs
        One ``RunMetric`` per audit run (success and failure).
    change_ledger
        The full persisted change ledger.
    freshness_history
        Optional per-run freshness summary; if provided, the metric
        block exposes the freshness-event counts.
    """
    runs_list = list(runs)
    freshness_history = freshness_history or []

    scheduled_run_count = len(runs_list)
    successful_run_count = sum(1 for r in runs_list if r.success)
    failed_run_count = scheduled_run_count - successful_run_count

    attempted_fetch_count = 0
    successful_attempt_count = 0
    failed_attempt_count = 0
    latencies: list[int] = []
    http_status_counts: dict[str, int] = {}
    raw_sizes: list[int] = []
    for run in runs_list:
        for attempt in run.fetch_attempts:
            attempted_fetch_count += 1
            success = bool(attempt.get("success"))
            if success:
                successful_attempt_count += 1
            else:
                failed_attempt_count += 1
            latencies.append(int(attempt.get("duration_ms", 0)))
            status = attempt.get("http_status")
            if status is None:
                http_status_counts["network_error"] = http_status_counts.get("network_error", 0) + 1
            else:
                key = str(int(status))
                http_status_counts[key] = http_status_counts.get(key, 0) + 1
            raw_sizes.append(int(attempt.get("response_bytes", 0)))

    median_latency = _percentile(sorted(latencies), 0.5) if latencies else None
    max_latency = max(latencies) if latencies else None

    total_active_rows = 0
    unique_sleeper_ids: set[str] = set()
    snapshots_with_null_injury = 0
    snapshots_with_populated_injury = 0
    snapshots_with_practice = 0
    snapshots_with_depth_order = 0
    for run in runs_list:
        for row in run.active_rows:
            total_active_rows += 1
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

    exact_id_matches = 0
    fallback_matches = 0
    unmatched = 0
    duplicates: dict[str, int] = {}
    crosswalk_method_counts: dict[str, dict[str, int]] = {}
    current_team_ids_by_snapshot: dict[str, set[str]] = {}
    for run in runs_list:
        ids = current_team_ids_by_snapshot.setdefault(run.snapshot_id, set())
        for row in run.active_rows:
            pid = str(row.get("sleeper_player_id", ""))
            team = row.get("team")
            if pid and team not in (None, ""):
                ids.add(pid)
    for run in runs_list:
        sid = run.snapshot_id
        current_team_ids = current_team_ids_by_snapshot.get(sid, set())
        for row in run.crosswalk_rows:
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
    success_pct = (
        successful_attempt_count / attempted_fetch_count
        if attempted_fetch_count
        else 0.0
    )
    return {
        "scheduled_run_count": scheduled_run_count,
        "attempted_fetch_count": attempted_fetch_count,
        "successful_run_count": successful_run_count,
        "failed_run_count": failed_run_count,
        "successful_attempt_count": successful_attempt_count,
        "failed_attempt_count": failed_attempt_count,
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


def _safe_read_parquet(path: Path) -> pl.DataFrame:
    """Read a parquet file; return an empty frame if it is missing.

    The rolling metrics build reads every audit artifact; an audit
    that has never written ``normalized/qb_snapshots.parquet`` (for
    example) must not crash the report writer.
    """
    if not path.exists():
        return pl.DataFrame()
    return pl.read_parquet(path)


def build_runs_from_disk(
    audit_root: str | Path,
) -> tuple[list[RunMetric], pl.DataFrame]:
    """Rebuild a list of ``RunMetric`` from the persisted audit history.

    The function reads ``run_history.parquet`` (the terminal run
    history) as its primary source of truth. Every row in
    ``run_history.parquet`` becomes one ``RunMetric`` with a
    terminal ``run_outcome`` and the corresponding ``success``
    boolean. The ``fetch_ledger.parquet`` is read second to
    attach per-run attempt detail (latency, http_status, response
    bytes) but it does NOT determine success — the terminal
    outcome does.

    Per the rereview contract: a run is successful iff
    ``run_outcome == SUCCESS``. INCOMPLETE_RESPONSE,
    NORMALIZATION_FAILURE, PERSISTENCE_FAILURE,
    REFERENCE_FAILURE, HOF workflow failures, and TRANSPORT_FAILURE
    all count as failed runs even when the underlying HTTP attempt
    succeeded.

    The second return value is the full change ledger, also
    read from disk.
    """
    audit_root = Path(audit_root)
    fetch_ledger_path = audit_root / "fetch_ledger.parquet"
    active_path = audit_root / "normalized" / "qb_snapshots.parquet"
    crosswalk_path = audit_root / "normalized" / "qb_identity_crosswalk.parquet"
    change_ledger_path = audit_root / "normalized" / "qb_change_ledger.parquet"
    run_history_path = audit_root / "run_history.parquet"

    fetch_ledger = _safe_read_parquet(fetch_ledger_path)
    active = _safe_read_parquet(active_path)
    crosswalk = _safe_read_parquet(crosswalk_path)
    change_ledger = _safe_read_parquet(change_ledger_path)

    # Read run history (terminal outcomes). One parquet row per run.
    # Rereview 4852338912: run_history.parquet replaces run_history.jsonl.
    # The parquet file is the single source of truth for terminal
    # outcomes. Malformed rows (e.g. from an interrupted write) are
    # surfaced, not silently skipped — the file is written atomically
    # so partial writes cannot occur.
    history: list[dict[str, Any]] = []
    if run_history_path.exists() and run_history_path.stat().st_size > 0:
        run_history_frame = pl.read_parquet(run_history_path)
        history = run_history_frame.to_dicts()

    runs: list[RunMetric] = []
    for record in history:
        run_outcome = str(record.get("outcome", ""))
        # The terminal run-outcome is the ONLY source of truth for
        # success. A run with HTTP success + a downstream failure
        # is a failed run.
        success = run_outcome == "SUCCESS"
        observed_at_utc = str(record.get("observed_at_utc") or "")
        snapshot_id = str(record.get("snapshot_id") or "")
        kind = record.get("kind")
        attempt_count = int(record.get("attempt_count") or 0)
        # Attach the per-run attempts from the fetch ledger.
        attempts: list[dict[str, Any]] = []
        if (
            fetch_ledger.height > 0
            and observed_at_utc
            and "observed_at_utc" in fetch_ledger.columns
        ):
            attempts = (
                fetch_ledger.filter(pl.col("observed_at_utc") == observed_at_utc)
                .sort("attempt_number")
                .to_dicts()
            )
        active_rows: list[dict[str, Any]] = []
        if (
            active.height > 0
            and observed_at_utc
            and "fetched_at_utc" in active.columns
        ):
            active_rows = active.filter(
                pl.col("fetched_at_utc") == observed_at_utc
            ).to_dicts()
        crosswalk_rows: list[dict[str, Any]] = []
        if (
            crosswalk.height > 0
            and snapshot_id
            and "snapshot_id" in crosswalk.columns
        ):
            crosswalk_rows = crosswalk.filter(
                pl.col("snapshot_id") == snapshot_id
            ).to_dicts()
        runs.append(
            RunMetric(
                snapshot_id=snapshot_id,
                observed_at_utc=observed_at_utc,
                success=success,
                run_outcome=run_outcome,
                attempt_count=attempt_count,
                kind=str(kind) if kind else None,
                fetch_attempts=attempts,
                active_rows=active_rows,
                crosswalk_rows=crosswalk_rows,
            )
        )

    return runs, change_ledger


def compute_rolling_metrics_from_disk(
    audit_root: str | Path,
    *,
    freshness_history: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute the rolling metrics from persisted audit artifacts.

    This is the entry point the live-audit report writer uses. It
    reads the full history (every successful and failed run) so
    the rolling metrics include the entire observation window, not
    just the current run.
    """
    runs, change_ledger = build_runs_from_disk(audit_root)
    return compute_reliability_metrics(
        runs=runs,
        change_ledger=change_ledger,
        freshness_history=freshness_history,
    )
