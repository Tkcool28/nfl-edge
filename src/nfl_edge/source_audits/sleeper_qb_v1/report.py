"""Report writers for the Sleeper QB source audit.

The audit emits one human-readable markdown report and one machine-
readable JSON report per major event type:

* the rolling live audit (``sleeper_qb_live_audit.md/.json``);
* the HOF Game observation (``sleeper_hof_game_observation.md/.json``).

The reports explicitly separate:

* fields directly returned by Sleeper;
* fields derived by the audit pipeline;
* first-observed timestamps;
* unsupported claims;
* open questions;
* operational failures.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .atomic_io import atomic_write_text
from .evidence_states import EVIDENCE_STATE_DESCRIPTIONS, validate_no_forbidden_labels


def write_live_audit_report(
    *,
    metrics: Mapping[str, Any],
    freshness_state: str,
    last_payload_sha256: str | None,
    endpoint: str,
    source_contract_version: str,
    observations: list[Mapping[str, Any]],
    output_markdown: str | Path,
    output_json: str | Path,
    source_history: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Render the live audit report and write it to disk.

    Returns the JSON-ready dict so the caller can post-process it.

    ``source_history`` carries committed-history provenance
    (``source_history_row_count``,
    ``source_history_last_finished_at_utc``,
    ``source_history_last_snapshot_id``) so consumers can detect
    a stale cached report by comparing the cached provenance with
    the live ledger.
    """
    metrics_view = dict(metrics)
    report_payload: dict[str, Any] = {
        "schema_version": "sleeper-qb-live-audit-v1",
        "generated_at_utc": _utc_now_iso(),
        "source_contract_version": source_contract_version,
        "endpoint": endpoint,
        "freshness_state": freshness_state,
        "last_payload_sha256": last_payload_sha256,
        "metrics": metrics_view,
        "observations": list(observations),
        "source_history": dict(source_history or {}),
    }
    Path(output_json).parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        output_json,
        json.dumps(report_payload, indent=2, default=str) + "\n",
    )
    markdown = render_live_audit_markdown(report_payload)
    atomic_write_text(output_markdown, markdown)
    return report_payload


def render_live_audit_markdown(payload: Mapping[str, Any]) -> str:
    metrics = payload.get("metrics", {})
    lines: list[str] = []
    lines.append("# Sleeper QB Source Live Audit")
    lines.append("")
    lines.append(f"- Generated at (UTC): `{payload.get('generated_at_utc')}`")
    lines.append(f"- Source contract version: `{payload.get('source_contract_version')}`")
    lines.append(f"- Endpoint: `{payload.get('endpoint')}`")
    lines.append(f"- Current freshness state: **{payload.get('freshness_state')}**")
    lines.append(f"- Last successful payload SHA-256: `{payload.get('last_payload_sha256')}`")
    lines.append("")
    lines.append("## Reliability metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    # Render the per-snapshot reconciliation table separately so the
    # numbers reconcile exactly: matched + unmatched + excluded ==
    # total_current_team_candidates.
    by_snapshot = metrics.get("current_team_crosswalk_by_snapshot", {})
    for key, value in metrics.items():
        if key == "current_team_crosswalk_by_snapshot":
            continue
        lines.append(f"| `{key}` | `{_render_value(value)}` |")
    lines.append("")

    if by_snapshot:
        lines.append("## Current-team crosswalk reconciliation (per snapshot)")
        lines.append("")
        lines.append(
            "The current-team QB candidate set is the active QB snapshot's\n"
            "`team` non-null rows. Each crosswalk row is classified into\n"
            "exactly one match method. The sum of buckets must equal\n"
            "`total_current_team_candidates`."
        )
        lines.append("")
        for sid, counts in by_snapshot.items():
            matched_total = (
                counts.get("exact_sleeper_id", 0)
                + counts.get("exact_gsis", 0)
                + counts.get("exact_espn", 0)
                + counts.get("exact_other_stable", 0)
                + counts.get("name_team_fallback", 0)
            )
            sum_check = (
                matched_total
                + counts.get("unmatched", 0)
                + counts.get("excluded_dup_ambig", 0)
            )
            reconciles = sum_check == counts.get("total_current_team_candidates", 0)
            lines.append(f"### Snapshot: `{sid}`")
            lines.append("")
            lines.append("| Bucket | Count |")
            lines.append("| --- | --- |")
            lines.append(f"| `exact_sleeper_id` | {counts.get('exact_sleeper_id', 0)} |")
            lines.append(f"| `exact_gsis` | {counts.get('exact_gsis', 0)} |")
            lines.append(f"| `exact_espn` | {counts.get('exact_espn', 0)} |")
            lines.append(f"| `exact_other_stable` | {counts.get('exact_other_stable', 0)} |")
            lines.append(f"| `name_team_fallback` | {counts.get('name_team_fallback', 0)} |")
            lines.append(f"| `unmatched` | {counts.get('unmatched', 0)} |")
            lines.append(f"| `excluded_dup_ambig` | {counts.get('excluded_dup_ambig', 0)} |")
            lines.append(
                f"| `total_current_team_candidates` | "
                f"{counts.get('total_current_team_candidates', 0)} |"
            )
            lines.append(
                f"| **sum(buckets + unmatched + excluded)** | **{sum_check}** |"
            )
            lines.append(
                f"| **reconciles** | **{'YES' if reconciles else 'NO'}** |"
            )
            lines.append("")
    lines.append("## Source fields directly returned by Sleeper")
    lines.append("")
    lines.append(
        "- Sleeper player-map values: `first_name`, `last_name`, `position`, `team`, `status`,"
        " `active`, `injury_status`, `injury_body_part`, `injury_notes`, `injury_start_date`,"
        " `practice_participation`, `practice_description`, `depth_chart_position`,"
        " `depth_chart_order`, `search_rank`, `age`, `years_exp`."
    )
    lines.append(
        "- Sleeper ID cross-references: `gsis_id`, `espn_id`, `sportradar_id`, `yahoo_id`,"
        " `fantasy_data_id`, `rotowire_id`."
    )
    lines.append(
        "- Sleeper response headers recorded per attempt: `ETag`, `Last-Modified`,"
        " `Content-Type` (when present)."
    )
    lines.append("")
    lines.append("## Fields derived by this audit pipeline")
    lines.append("")
    lines.append("- `player_identity_key`, `raw_record_sha256`, `evidence_state`.")
    lines.append("- The change-ledger rows (`first_seen`, `populated`, `cleared`, `changed`, `dropped`).")
    lines.append("- Freshness state machine outputs.")
    lines.append("- nflverse crosswalk `match_method` and `match_confidence`.")
    lines.append("")
    lines.append("## First-observed timestamps")
    lines.append("")
    lines.append(
        "- `first_observed_at_utc` and `first_observed_changed_at_utc` are recorded per change."
    )
    lines.append(
        "- `fetched_at_utc` is **not** treated as evidence that Sleeper changed the underlying"
        " record at that moment."
    )
    lines.append("")
    lines.append("## Unsupported claims (recorded explicitly)")
    lines.append("")
    lines.append(
        "- Historical Sleeper injury/practice snapshots. The public endpoint is current-state"
        " only; the audit does not synthesize history."
    )
    lines.append(
        "- Verification that a reported `ACTIVE` QB is medically healthy. Absence of an"
        " injury designation is not a positive health claim."
    )
    lines.append("")
    lines.append("## Open questions")
    lines.append("")
    lines.append(
        "- Will Sleeper expose a stable historical archive of player states? Until that is"
        " proven, the deferred historical QB-retraining milestone in"
        " `docs/modeling_gap_report.md` remains blocked."
    )
    lines.append(
        "- Will the depth-chart ordering be authoritative for the first preseason games? The"
        " August 6, 2026 HOF Game observation will provide a first data point."
    )
    lines.append("")
    lines.append("## Operational failures")
    lines.append("")
    failures = [obs for obs in payload.get("observations", []) if obs.get("kind") == "failure"]
    if not failures:
        lines.append("- No failed fetches recorded in this run.")
    else:
        for failure in failures:
            lines.append(
                f"- {failure.get('at_utc')}: {failure.get('error_class')} - {failure.get('error_message')}"
            )
    lines.append("")
    return "\n".join(lines)


def build_hof_payload(
    *,
    observation: Mapping[str, Any],
    evidence_state_counts: Mapping[str, int],
) -> dict[str, Any]:
    """Compute the HOF observation report payload WITHOUT writing
    any files.

    Used by ``AuditOrchestrator._run_hof_workflow`` so the report
    content can be staged before the authoritative commit, then
    written to disk by ``_refresh_derived_views`` only after the
    commit succeeds (Rereview 4859475614 defect 3.2).
    """
    states = list(evidence_state_counts.keys())
    validate_no_forbidden_labels(states)
    return {
        "schema_version": "sleeper-hof-game-observation-v1",
        "generated_at_utc": _utc_now_iso(),
        "observation": dict(observation),
        "evidence_state_counts": dict(evidence_state_counts),
        "evidence_state_descriptions": {
            k: EVIDENCE_STATE_DESCRIPTIONS.get(k, "")
            for k in evidence_state_counts
        },
    }


def persist_hof_payload(
    payload: Mapping[str, Any],
    *,
    output_markdown: str | Path,
    output_json: str | Path,
) -> dict[str, Any]:
    """Write a pre-built HOF payload (from
    :func:`build_hof_payload`) to disk as JSON + markdown.

    Returns the payload (so callers can chain). Called by
    ``_refresh_derived_views`` AFTER the authoritative commit.
    """
    Path(output_json).parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        output_json,
        json.dumps(dict(payload), indent=2, default=str) + "\n",
    )
    markdown = render_hof_markdown(payload)
    atomic_write_text(output_markdown, markdown)
    return dict(payload)


def write_hof_observation_report(
    *,
    observation: Mapping[str, Any],
    evidence_state_counts: Mapping[str, int],
    output_markdown: str | Path,
    output_json: str | Path,
) -> dict[str, Any]:
    """Render the Hall of Fame Game observation report.

    Computes the payload via :func:`build_hof_payload` and writes
    the JSON + markdown via :func:`persist_hof_payload`.
    """
    payload = build_hof_payload(
        observation=observation,
        evidence_state_counts=evidence_state_counts,
    )
    return persist_hof_payload(
        payload,
        output_markdown=output_markdown,
        output_json=output_json,
    )


def render_hof_markdown(payload: Mapping[str, Any]) -> str:
    obs = payload.get("observation", {})
    counts = payload.get("evidence_state_counts", {})
    lines: list[str] = []
    lines.append("# Sleeper Hall of Fame Game Observation")
    lines.append("")
    lines.append(f"- Generated at (UTC): `{payload.get('generated_at_utc')}`")
    lines.append(f"- Observation id: `{obs.get('observation_id')}`")
    lines.append(f"- Game id: `{obs.get('game_id')}`")
    lines.append(f"- Home team: `{obs.get('home_team')}`")
    lines.append(f"- Away team: `{obs.get('away_team')}`")
    lines.append(f"- Scheduled start (UTC): `{obs.get('scheduled_start_utc')}`")
    lines.append(f"- Scheduled start (local label): `{obs.get('scheduled_start_local')}`")
    lines.append(
        f"- Latest snapshot before kickoff: `{obs.get('latest_snapshot_before_kickoff')}`"
    )
    lines.append(f"- Postgame snapshot id: `{obs.get('postgame_snapshot_id')}`")
    lines.append("")
    lines.append("## Evidence state counts (postgame snapshot)")
    lines.append("")
    if not counts:
        lines.append("- No postgame evidence recorded yet.")
    else:
        lines.append("| State | Count | Description |")
        lines.append("| --- | --- | --- |")
        for state, count in counts.items():
            description = EVIDENCE_STATE_DESCRIPTIONS.get(state, "")
            lines.append(f"| `{state}` | {count} | {description} |")
    lines.append("")
    lines.append("## Per-QB observation")
    lines.append("")
    relevant = obs.get("relevant_sleeper_qbs") or []
    depth_orders = obs.get("observed_depth_order") or []
    injury_statuses = obs.get("observed_injury_status") or []
    practice = obs.get("observed_practice_participation") or []
    evidence = obs.get("derived_evidence_state") or []
    if not relevant:
        lines.append("- No relevant QBs were recorded for this game.")
    else:
        lines.append("| Sleeper id | Depth order | Injury status | Practice | Evidence state |")
        lines.append("| --- | --- | --- | --- | --- |")
        for idx, sleeper_id in enumerate(relevant):
            lines.append(
                "| `{0}` | {1} | {2} | {3} | {4} |".format(
                    sleeper_id,
                    depth_orders[idx] if idx < len(depth_orders) else "-",
                    injury_statuses[idx] if idx < len(injury_statuses) else "-",
                    practice[idx] if idx < len(practice) else "-",
                    evidence[idx] if idx < len(evidence) else "-",
                )
            )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- The pregame snapshot id is preserved verbatim and is not overwritten by the"
        " postgame collection."
    )
    lines.append(
        "- The audit's verdict on Sleeper is not based on which preseason QB takes the"
        " first snap; the HOF Game is primarily a reliability probe of the source."
    )
    lines.append("")
    return "\n".join(lines)


def _render_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
