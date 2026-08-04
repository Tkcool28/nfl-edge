"""End-to-end bounded audit orchestrator.

The orchestrator is the single entry point the bounded shell scripts
call. It is intentionally synchronous, side-effect-only-on-its-own-
tree, and never imports from the modeling stack. The orchestrator:

1. fetches the Sleeper active-QB endpoint with bounded retries;
2. normalizes the response;
3. joins against a frozen nflverse QB reference (2025 stripped);
4. emits the change ledger against the immediately prior successful
   snapshot's evidence;
5. derives freshness state;
6. persists raw bytes, ledger, normalized frames, crosswalk, and
   reports — all atomically;
7. records a single ``RunOutcome`` per run in
   ``latest_run_status.json``.

Run kinds
---------

* ``scheduled`` — twice-daily recurring collection.
* ``pregame`` — Hall of Fame Game pre-kickoff collection. Freezes
  an immutable pregame pointer for the postgame run to consult.
* ``postgame`` — Hall of Fame Game post-kickoff collection. Loads
  the frozen pregame pointer, rejects missing/malformed/post-
  kickoff data, builds the per-QB observation with both pregame
  and postgame values preserved.

Atomicity
---------

Every mutable artifact under ``audit_root`` is written via the
temp-file + fsync + ``os.replace`` idiom in ``atomic_io``. The
prior valid artifact remains byte-identical until the new one is
fully durable.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import polars as pl

from ...sources.sleeper import (
    DEFAULT_ENDPOINT,
    SleeperFetchResult,
    fetch_active_qb_snapshot,
)
from .atomic_io import (
    ReferenceArtifact,
    atomic_append_parquet,
    atomic_append_run_history,
    atomic_write_parquet,
    atomic_write_text,
    verify_reference_manifest,
)
from .changes import CHANGE_LEDGER_DTYPES, detect_changes
from .crosswalk import CROSSWALK_DTYPES, build_crosswalk
from .evidence_states import classify
from .freshness import (
    FreshnessInputs,
    change_count_for,
    derive_freshness_state,
    schema_drift_fields,
)
from .ho_game import (
    HOF_OBSERVATION_DTYPES,
    build_observation_record,
    resolve_hof_game,
)
from .ids import snapshot_id_for, utc_now
from .metrics import compute_rolling_metrics_from_disk
from .normalize import QB_SNAPSHOT_DTYPES, normalize_qb_payload
from .outcomes import (
    ERROR_TOKENS,
    EXIT_CODES,
    RUN_HISTORY_ROW_DTYPES,
    RunOutcome,
    RunOutcomeRecord,
)
from .report import write_hof_observation_report, write_live_audit_report

AUDIT_VERSION = "sleeper-qb-audit-v1"

EVIDENCE_STATE_DTYPES = {
    "snapshot_id": pl.Utf8,
    "observed_at_utc": pl.Utf8,
    "sleeper_player_id": pl.Utf8,
    "evidence_state": pl.Utf8,
}


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _read_nflverse_qbs(
    path: str | Path,
) -> pl.DataFrame:
    """Read the nflverse-derived player identity reference and normalize
    its column names to the schema the crosswalk expects.
    """
    path = Path(path)
    if not path.exists():
        return pl.DataFrame()
    frame = pl.read_parquet(path)
    if frame.height == 0:
        return frame
    if "sleeper_id" in frame.columns and "sleeper_id_str" not in frame.columns:
        frame = frame.with_columns(pl.col("sleeper_id").cast(pl.Utf8).alias("sleeper_id_str"))
    if "player_id" not in frame.columns:
        coalesce_inputs = []
        if "gsis_id" in frame.columns:
            coalesce_inputs.append(pl.col("gsis_id"))
        if "sleeper_id_str" in frame.columns:
            coalesce_inputs.append(pl.col("sleeper_id_str"))
        if coalesce_inputs:
            frame = frame.with_columns(pl.coalesce(coalesce_inputs).alias("player_id"))
    if "name" in frame.columns and "full_name" not in frame.columns:
        frame = frame.rename({"name": "full_name"})
    for required, default_dtype in (
        ("position", pl.Utf8),
    ):
        if required not in frame.columns:
            frame = frame.with_columns(pl.lit(None, dtype=default_dtype).alias(required))
    if "position" in frame.columns:
        frame = frame.filter(pl.col("position") == "QB")
    if "db_season" in frame.columns:
        frame = frame.filter(pl.col("db_season") != 2025)
    keep = [
        c for c in (
            "player_id", "gsis_id", "espn_id", "sportradar_id", "yahoo_id",
            "fantasy_data_id", "rotowire_id", "full_name", "team", "position",
            "season", "first_name", "last_name",
            "sleeper_id_str", "sleeper_id", "sleeper_player_id", "db_season",
        )
        if c in frame.columns
    ]
    return frame.select(keep)


def _evidence_frame(
    active_frame: pl.DataFrame,
    *,
    snapshot_id: str,
    observed_at_utc: str,
) -> pl.DataFrame:
    """Build the per-QB evidence-state frame with snapshot metadata.

    The frame's columns are ``snapshot_id``, ``observed_at_utc``,
    ``sleeper_player_id``, ``evidence_state``. The first two columns
    are required so the rolling-history code can select the prior
    snapshot's evidence rows precisely (rather than joining the
    complete historical evidence file on ``sleeper_player_id``).
    """
    if active_frame.height == 0:
        return pl.DataFrame(
            {field: pl.Series(name=field, values=[], dtype=dt)
             for field, dt in EVIDENCE_STATE_DTYPES.items()}
        )
    states = [classify(row) for row in active_frame.to_dicts()]
    return active_frame.with_columns(
        pl.Series(name="evidence_state", values=states),
        pl.lit(snapshot_id).alias("snapshot_id"),
        pl.lit(observed_at_utc).alias("observed_at_utc"),
    ).select(list(EVIDENCE_STATE_DTYPES.keys()))


# Allowed kinds for a bounded audit run. ``scheduled`` is the
# twice-daily collection; ``pregame`` and ``postgame`` are the
# Hall-of-Fame-Game observations.
ALLOWED_KINDS: frozenset[str] = frozenset({"scheduled", "pregame", "postgame"})


class AuditOrchestrator:
    """Bounded single-run audit orchestrator."""

    def __init__(
        self,
        *,
        audit_root: str | Path,
        endpoint: str = DEFAULT_ENDPOINT,
        staleness_threshold_seconds: float = 6 * 3600.0,
        nflverse_qb_path: str | Path | None = None,
        hof_fixture_path: str | Path | None = None,
        reference_manifest: Sequence[ReferenceArtifact] | None = None,
    ) -> None:
        self.audit_root = Path(audit_root)
        self.endpoint = endpoint
        self.staleness_threshold_seconds = staleness_threshold_seconds
        self.nflverse_qb_path = (
            Path(nflverse_qb_path) if nflverse_qb_path is not None else None
        )
        self.hof_fixture_path = (
            Path(hof_fixture_path) if hof_fixture_path is not None else None
        )
        self.reference_manifest = list(reference_manifest or [])
        self.raw_root = self.audit_root / "raw"
        self.normalized_root = self.audit_root / "normalized"
        self.reports_root = self.audit_root / "reports"
        self.fetch_ledger_path = self.audit_root / "fetch_ledger.parquet"
        self.active_qb_path = self.normalized_root / "qb_snapshots.parquet"
        self.inactive_qb_path = self.normalized_root / "qb_inactive_snapshots.parquet"
        self.evidence_path = self.normalized_root / "qb_evidence_states.parquet"
        self.crosswalk_path = self.normalized_root / "qb_identity_crosswalk.parquet"
        self.change_ledger_path = self.normalized_root / "qb_change_ledger.parquet"
        self.hof_obs_path = self.normalized_root / "hof_game_observation.parquet"
        self.latest_pointer_path = self.audit_root / "latest_snapshot.json"
        self.latest_run_status_path = self.audit_root / "latest_run_status.json"
        self.run_history_path = self.audit_root / "run_history.parquet"
        self.pregame_pointer_path = self.audit_root / "hof_pregame_pointer.json"

    # ------------------------------------------------------------------
    # public entry points
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        session: Any | None = None,
        kind: str = "scheduled",
        forced_snapshot_id: str | None = None,
        forced_observed_at_utc: str | None = None,
    ) -> dict[str, Any]:
        """Run the bounded audit once. Returns a JSON-ready dict
        suitable for the CLI to convert into a process exit code.

        The returned dict always contains the key ``run_outcome``
        (a ``RunOutcome`` value) and ``exit_code`` (its mapped
        integer).
        """
        if kind not in ALLOWED_KINDS:
            self._commit_terminal_record(
                RunOutcomeRecord(
                    outcome=RunOutcome.NORMALIZATION_FAILURE,
                    snapshot_id=None,
                    observed_at_utc=None,
                    finished_at_utc=_utc_now_iso(),
                    error_class="ValueError",
                    error_message=f"unknown run kind: {kind!r}; allowed={sorted(ALLOWED_KINDS)}",
                    error_token=ERROR_TOKENS[RunOutcome.NORMALIZATION_FAILURE],
                    exit_code=EXIT_CODES[RunOutcome.NORMALIZATION_FAILURE],
                    kind=kind,
                    attempt_count=0,
                )
            )
            return {
                "run_outcome": RunOutcome.NORMALIZATION_FAILURE.value,
                "exit_code": EXIT_CODES[RunOutcome.NORMALIZATION_FAILURE],
                "error_class": "ValueError",
                "error_message": f"unknown run kind: {kind!r}",
            }

        # Reference-manifest verification runs *before* the network.
        # A missing or checksum-mismatched reference cannot be fixed
        # by retrying the API.
        if self.reference_manifest:
            reference_dir = self.audit_root / "reference"
            ok, errors = verify_reference_manifest(
                reference_dir, self.reference_manifest
            )
            if not ok:
                outcome = RunOutcome.REFERENCE_FAILURE
                record = RunOutcomeRecord(
                    outcome=outcome,
                    snapshot_id=None,
                    observed_at_utc=None,
                    finished_at_utc=_utc_now_iso(),
                    error_class="ReferenceVerificationError",
                    error_message="; ".join(errors),
                    error_token=ERROR_TOKENS[outcome],
                    exit_code=EXIT_CODES[outcome],
                    kind=kind,
                    attempt_count=0,
                )
                self._commit_terminal_record(record)
                return {
                    "run_outcome": outcome.value,
                    "exit_code": EXIT_CODES[outcome],
                    "error_class": "ReferenceVerificationError",
                    "error_message": "; ".join(errors),
                    "errors": errors,
                }

        # 1. Resolve snapshot_id and observed_at_utc deterministically.
        observed = utc_now()
        snapshot_id = forced_snapshot_id or snapshot_id_for(observed, kind=kind)
        observed_at_utc = forced_observed_at_utc or _utc_now_iso()
        raw_run_dir = self.raw_root / _date_partition(observed)

        # 2. Fetch with bounded retries.
        winner, attempts = fetch_active_qb_snapshot(
            snapshot_id=snapshot_id,
            raw_dir=raw_run_dir,
            endpoint=self.endpoint,
            session=session,
        )

        # 3. Persist fetch ledger (always, success or failure).
        self._append_fetch_ledger(attempts, observed_at_utc=observed_at_utc)

        # 4. Branch on outcome.
        if winner is None:
            return self._finalize_transport_failure(
                kind=kind,
                snapshot_id=snapshot_id,
                observed_at_utc=observed_at_utc,
                attempts=attempts,
                observed=observed,
            )

        # 5. Parse the winning payload.
        try:
            raw_payload = json.loads(Path(winner.raw_payload_path).read_bytes())
        except json.JSONDecodeError as exc:
            return self._finalize_incomplete_response(
                kind=kind,
                snapshot_id=snapshot_id,
                observed_at_utc=observed_at_utc,
                attempts=attempts,
                error_class="JSONDecodeError",
                error_message=str(exc),
            )

        # If the JSON parses but is not a usable object of player
        # records, that's also INCOMPLETE_RESPONSE.
        present, missing, _ = schema_drift_fields(raw_payload)
        if not isinstance(raw_payload, dict) or not raw_payload:
            return self._finalize_incomplete_response(
                kind=kind,
                snapshot_id=snapshot_id,
                observed_at_utc=observed_at_utc,
                attempts=attempts,
                error_class="EmptyOrInvalidPlayerMap",
                error_message="payload parsed as JSON but is not a non-empty player map",
            )

        # 6. Normalize.
        try:
            active_frame, inactive_frame, warnings = normalize_qb_payload(
                snapshot_id=snapshot_id,
                fetched_at_utc=observed_at_utc,
                raw_payload=raw_payload,
            )
        except Exception as exc:  # noqa: BLE001 - normalize must not crash the audit silently
            return self._finalize_normalization_failure(
                kind=kind,
                snapshot_id=snapshot_id,
                observed_at_utc=observed_at_utc,
                attempts=attempts,
                error_class=type(exc).__name__,
                error_message=str(exc),
            )

        # 7. Append normalized frames (atomic).
        # Capture the *prior* snapshot id before we overwrite the
        # ``latest_snapshot.json`` pointer and before the new active
        # rows are appended to the rolling parquet. This is the only
        # point at which the prior id is well-defined: after the
        # append, ``_read_prior_active`` would see the current
        # snapshot as the last one and return it as the prior.
        prior_snapshot_id = self._read_latest_snapshot_id()
        self._append_active(active_frame)
        if inactive_frame.height > 0:
            self._append_inactive(inactive_frame)

        # 8. Build evidence-state frame (with snapshot metadata).
        evidence_frame = _evidence_frame(
            active_frame,
            snapshot_id=snapshot_id,
            observed_at_utc=observed_at_utc,
        )
        self._append_evidence(evidence_frame)

        # 9. Crosswalk (with reference).
        if self.nflverse_qb_path is not None:
            nflverse_qbs = _read_nflverse_qbs(self.nflverse_qb_path)
        else:
            nflverse_qbs = pl.DataFrame()
        crosswalk = build_crosswalk(
            snapshot_id=snapshot_id,
            active_qb_frame=active_frame,
            nflverse_qbs=nflverse_qbs,
        )
        self._append_crosswalk(crosswalk)

        # 10. Determine which prior snapshot to compare against and
        # read its evidence *only* (snapshot-scoped, not the entire
        # historical evidence file). Use the prior snapshot id we
        # captured before the append; this is the exact prior
        # successful snapshot, never the current one.
        prior_active = self._read_active_for_snapshot(prior_snapshot_id or "")
        prior_evidence = self._read_evidence_for_snapshot(prior_snapshot_id or "")

        # 11. Change ledger.
        change_ledger = detect_changes(
            current_frame=active_frame,
            current_evidence_frame=evidence_frame,
            prior_frame=prior_active,
            prior_evidence_frame=prior_evidence,
            current_snapshot_id=snapshot_id,
            current_observed_at_utc=observed_at_utc,
            prior_snapshot_id=prior_snapshot_id,
            prior_observed_at_utc=self._read_latest_observed_at_utc(),
        )
        self._append_changes(change_ledger)

        # 12. HOF workflow — completes before any terminal-state
        # persistence so a failed HOF run does not advance the
        # latest-success pointer or write a misleading live report.
        hof_payload: dict[str, Any] | None = None
        hof_run_outcome: RunOutcome | None = None
        if kind in {"pregame", "postgame"}:
            hof_result = self._run_hof_workflow(
                kind=kind,
                snapshot_id=snapshot_id,
                observed_at_utc=observed_at_utc,
                active_frame=active_frame,
                evidence_frame=evidence_frame,
            )
            hof_payload = hof_result.get("payload")
            hof_run_outcome = hof_result.get("outcome")

        # 13. Determine the provisional final terminal outcome.
        # The HTTP fetch succeeded, but a downstream HOF failure
        # downgrades the run: a successful collection with a
        # failed HOF is NOT a success. The provisional outcome is
        # what gets reported in the live report's current-run
        # observation; a later report-write or pointer-write
        # failure may downgrade it to PERSISTENCE_FAILURE.
        provisional_outcome = hof_run_outcome or RunOutcome.SUCCESS
        report_write_failed = False
        report_error_class: str | None = None
        report_error_message: str | None = None
        report_payload: dict[str, Any] | None = None
        pointer_write_failed = False
        pointer_error_class: str | None = None
        pointer_error_message: str | None = None

        # Build the in-memory provisional record used for the
        # current-run-inclusive metrics (Rereview 4858328151 §2)
        # BEFORE the live report is computed. The report writer
        # then sees the current invocation.
        provisional_record = {
            "outcome": provisional_outcome.value,
            "snapshot_id": snapshot_id,
            "observed_at_utc": observed_at_utc,
            "kind": kind,
            "attempt_count": len(attempts),
            "success": provisional_outcome == RunOutcome.SUCCESS,
        }
        # Per-attempt detail for the current invocation (used by
        # attempt reconciliation in the metrics).
        current_fetch_attempts = [
            {
                "success": a.error_class is None,
                "duration_ms": int(a.duration_ms or 0),
                "http_status": a.http_status,
                "response_bytes": int(a.response_bytes or 0),
            }
            for a in attempts
        ]
        current_active_rows = active_frame.to_dicts()
        current_crosswalk_rows = crosswalk.to_dicts()

        # 14. Write live report + rolling metrics BEFORE persisting
        # the terminal outcome. The metrics computation includes
        # the current invocation's provisional record so the live
        # report reflects the run that is about to be committed.
        # If this fails, the terminal outcome becomes
        # PERSISTENCE_FAILURE — the run cannot produce a live
        # report — and exactly one terminal-history row reflects
        # that outcome.
        try:
            metrics = compute_rolling_metrics_from_disk(
                self.audit_root,
                freshness_history=[
                    {
                        "last_success_at_utc": observed_at_utc,
                        "last_failure_at_utc": None,
                        "last_attempt_success": (
                            provisional_outcome == RunOutcome.SUCCESS
                        ),
                        "change_count": change_count_for(change_ledger),
                        "last_payload_sha256": winner.sha256,
                        "prior_payload_sha256": None,
                        "parsed_ok": True,
                        "present_fields": present,
                    }
                ],
                current_run_record=provisional_record,
                current_active_rows=current_active_rows,
                current_crosswalk_rows=current_crosswalk_rows,
                current_fetch_attempts=current_fetch_attempts,
            )
            freshness_state = derive_freshness_state(
                FreshnessInputs(
                    last_success_at_utc=observed_at_utc,
                    last_failure_at_utc=None,
                    last_attempt_success=(
                        provisional_outcome == RunOutcome.SUCCESS
                    ),
                    change_count=change_count_for(change_ledger),
                    last_payload_sha256=winner.sha256,
                    prior_payload_sha256=None,
                    parsed_ok=True,
                    present_fields=present,
                ),
                staleness_threshold_seconds=self.staleness_threshold_seconds,
                now=observed,
            )
            report_payload = write_live_audit_report(
                metrics=metrics,
                freshness_state=freshness_state,
                last_payload_sha256=winner.sha256,
                endpoint=self.endpoint,
                source_contract_version=AUDIT_VERSION,
                observations=[
                    {
                        "kind": (
                            "success"
                            if provisional_outcome == RunOutcome.SUCCESS
                            else "failure"
                        ),
                        "at_utc": observed_at_utc,
                        "snapshot_id": snapshot_id,
                        "run_outcome": provisional_outcome.value,
                        "freshness_state": freshness_state,
                        "schema_drift_missing_fields": sorted(missing),
                        "warnings": warnings,
                    }
                ],
                output_markdown=self.reports_root / "sleeper_qb_live_audit.md",
                output_json=self.reports_root / "sleeper_qb_live_audit.json",
            )
        except OSError as exc:
            report_write_failed = True
            report_error_class = type(exc).__name__
            report_error_message = str(exc)
            metrics = None
            freshness_state = None

        # 15. Resolve the TRUE final outcome after the live report
        # write. A failed report write downgrades the outcome to
        # PERSISTENCE_FAILURE. The latest-success pointer is
        # advanced only if the provisional outcome is still
        # SUCCESS after this step.
        final_outcome = provisional_outcome
        if report_write_failed:
            final_outcome = RunOutcome.PERSISTENCE_FAILURE

        # 16. Atomically advance latest_snapshot.json ONLY when the
        # true final outcome is SUCCESS (Rereview 4858328151 §3:
        # pointer must be written BEFORE terminal history/status
        # are committed, but only after all other success-path
        # work has completed). A pointer-write failure downgrades
        # the outcome to PERSISTENCE_FAILURE; the prior pointer
        # file remains byte-identical because ``os.replace`` only
        # succeeds on a complete atomic write. The CLI must NOT
        # attempt a second terminal-history row — that would
        # record SUCCESS for an invocation whose pointer write
        # failed. The orchestrator owns the terminal outcome.
        if final_outcome == RunOutcome.SUCCESS:
            latest_pointer = {
                "snapshot_id": snapshot_id,
                "observed_at_utc": observed_at_utc,
                "payload_sha256": winner.sha256,
                "raw_payload_path": winner.raw_payload_path,
                "kind": kind,
            }
            try:
                atomic_write_text(
                    self.latest_pointer_path,
                    json.dumps(latest_pointer, indent=2, default=str) + "\n",
                )
            except OSError as exc:
                pointer_write_failed = True
                pointer_error_class = type(exc).__name__
                pointer_error_message = str(exc)
                final_outcome = RunOutcome.PERSISTENCE_FAILURE

        # 17. Persist exactly ONE terminal-history row reflecting
        # the actual final outcome (Rereview 4858328151 §3).
        # History-first ordering: history is written before status.
        # A history failure surfaces PERSISTENCE_FAILURE and does
        # NOT write status or advance the latest-success pointer.
        error_class_for_record: str | None = None
        error_message_for_record: str | None = None
        if final_outcome != RunOutcome.SUCCESS:
            if pointer_write_failed:
                error_class_for_record = pointer_error_class
                error_message_for_record = (
                    f"latest_snapshot write failed: {pointer_error_message}"
                )
            elif report_write_failed:
                error_class_for_record = report_error_class
                error_message_for_record = (
                    f"live report write failed: {report_error_message}"
                )
        record = RunOutcomeRecord(
            outcome=final_outcome,
            snapshot_id=snapshot_id,
            observed_at_utc=observed_at_utc,
            finished_at_utc=_utc_now_iso(),
            error_class=error_class_for_record,
            error_message=error_message_for_record,
            error_token=(
                ERROR_TOKENS[final_outcome]
                if final_outcome != RunOutcome.SUCCESS
                else None
            ),
            exit_code=EXIT_CODES[final_outcome],
            kind=kind,
            attempt_count=len(attempts),
        )
        history_written = False
        try:
            self._append_run_history(record)
            history_written = True  # noqa: F841 — recorded for symmetry with status path
        except OSError as exc:
            return self._failure_after_history_failure(
                kind=kind,
                snapshot_id=snapshot_id,
                observed_at_utc=observed_at_utc,
                attempts=attempts,
                history_error=exc,
            )

        # 18. Write latest_run_status.json. History-first ordering:
        # history was already durably written, so a status failure
        # cannot drop the terminal record. A status failure
        # surfaces PERSISTENCE_FAILURE but does NOT advance the
        # latest-success pointer and does NOT append a second
        # history row.
        try:
            self._write_latest_run_status(record)
        except OSError as exc:
            return self._failure_after_status_failure(
                kind=kind,
                snapshot_id=snapshot_id,
                observed_at_utc=observed_at_utc,
                attempts=attempts,
                status_error=exc,
            )

        return {
            "snapshot_id": snapshot_id,
            "observed_at_utc": observed_at_utc,
            "payload_sha256": winner.sha256,
            "freshness_state": freshness_state,
            "metrics": metrics,
            "active_row_count": active_frame.height,
            "inactive_row_count": inactive_frame.height,
            "matched_count": int(crosswalk.filter(pl.col("is_matched")).height),
            "unmatched_count": int(crosswalk.filter(~pl.col("is_matched")).height),
            "change_event_count": int(change_ledger.height),
            "report": report_payload,
            "hof": hof_payload,
            "run_outcome": final_outcome.value,
            "exit_code": EXIT_CODES[final_outcome],
        }

    # ------------------------------------------------------------------
    # HOF pregame / postgame workflow
    # ------------------------------------------------------------------

    def _run_hof_workflow(
        self,
        *,
        kind: str,
        snapshot_id: str,
        observed_at_utc: str,
        active_frame: pl.DataFrame,
        evidence_frame: pl.DataFrame,
    ) -> dict[str, Any]:
        """Implement the pregame freeze-pointer + postgame comparison.

        Pregame behavior:

        * resolve the committed HOF fixture via ``resolve_hof_game``
          (or accept an injected ``game`` mapping);
        * collect one snapshot (already done by the caller);
        * persist an immutable pregame pointer containing
          ``game_id``, ``kickoff_utc``, ``selected_snapshot_id``,
          ``observed_at_utc``, ``normalized_snapshot_reference``,
          ``evidence_snapshot_reference``;
        * prove the selected snapshot occurred *before* kickoff.

        Postgame behavior:

        * resolve the same fixture;
        * load the exact frozen pregame pointer;
        * reject missing, malformed, mismatched, or post-kickoff
          pregame data;
        * collect the postgame snapshot (already done by the caller);
        * build the HOF observation from the full normalized
          pregame rows, the full normalized postgame rows, and the
          snapshot-scoped evidence rows;
        * preserve both pregame and postgame values per QB.
        """
        try:
            game = resolve_hof_game(fixture_path=self.hof_fixture_path)
        except Exception as exc:  # noqa: BLE001
            return {
                "outcome": RunOutcome.REFERENCE_FAILURE,
                "payload": {
                    "error_class": type(exc).__name__,
                    "error_message": str(exc),
                },
            }
        kickoff_utc = game.get("scheduled_start_utc")
        if not kickoff_utc:
            return {
                "outcome": RunOutcome.REFERENCE_FAILURE,
                "payload": {
                    "error_class": "MissingKickoff",
                    "error_message": "resolved HOF game has no scheduled_start_utc",
                },
            }

        if kind == "pregame":
            pre_kickoff = _utc_iso_is_before(observed_at_utc, kickoff_utc)
            if not pre_kickoff:
                return {
                    "outcome": RunOutcome.NORMALIZATION_FAILURE,
                    "payload": {
                        "error_class": "PostKickoffPregame",
                        "error_message": (
                            f"pregame collection at {observed_at_utc} is at or after "
                            f"kickoff {kickoff_utc}"
                        ),
                    },
                }
            pointer = {
                "schema_version": "hof-pregame-pointer-v1",
                "game_id": game.get("game_id"),
                "kickoff_utc": kickoff_utc,
                "selected_snapshot_id": snapshot_id,
                "observed_at_utc": observed_at_utc,
                "normalized_snapshot_reference": str(self.active_qb_path),
                "evidence_snapshot_reference": str(self.evidence_path),
            }
            atomic_write_text(
                self.pregame_pointer_path,
                json.dumps(pointer, indent=2, default=str) + "\n",
            )
            return {
                "outcome": None,
                "payload": {
                    "kind": "pregame",
                    "pointer_path": str(self.pregame_pointer_path),
                    "pointer": pointer,
                },
            }

        # kind == "postgame"
        if not self.pregame_pointer_path.exists():
            return {
                "outcome": RunOutcome.NORMALIZATION_FAILURE,
                "payload": {
                    "error_class": "MissingPregamePointer",
                    "error_message": (
                        "postgame run without a frozen pregame pointer; cannot compare"
                    ),
                },
            }
        try:
            pointer = json.loads(self.pregame_pointer_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "outcome": RunOutcome.NORMALIZATION_FAILURE,
                "payload": {
                    "error_class": "MalformedPregamePointer",
                    "error_message": str(exc),
                },
            }
        required_pointer_fields = {
            "game_id", "kickoff_utc", "selected_snapshot_id",
            "observed_at_utc", "normalized_snapshot_reference",
            "evidence_snapshot_reference",
        }
        missing_pointer_fields = required_pointer_fields - set(pointer)
        if missing_pointer_fields:
            return {
                "outcome": RunOutcome.NORMALIZATION_FAILURE,
                "payload": {
                    "error_class": "MalformedPregamePointer",
                    "error_message": (
                        f"pregame pointer missing required fields: "
                        f"{sorted(missing_pointer_fields)}"
                    ),
                },
            }
        if pointer.get("game_id") != game.get("game_id"):
            return {
                "outcome": RunOutcome.NORMALIZATION_FAILURE,
                "payload": {
                    "error_class": "PregamePointerGameMismatch",
                    "error_message": (
                        f"pregame game_id={pointer.get('game_id')} does not match "
                        f"resolved postgame game_id={game.get('game_id')}"
                    ),
                },
            }
        if not _utc_iso_is_before(str(pointer.get("observed_at_utc")), kickoff_utc):
            return {
                "outcome": RunOutcome.NORMALIZATION_FAILURE,
                "payload": {
                    "error_class": "PregamePointerPostKickoff",
                    "error_message": (
                        f"frozen pregame observed_at_utc={pointer.get('observed_at_utc')} "
                        f"is not before kickoff {kickoff_utc}"
                    ),
                },
            }
        if _utc_iso_is_before(kickoff_utc, observed_at_utc) is False:
            return {
                "outcome": RunOutcome.NORMALIZATION_FAILURE,
                "payload": {
                    "error_class": "PostgamePreKickoff",
                    "error_message": (
                        f"postgame observed_at_utc={observed_at_utc} is before kickoff "
                        f"{kickoff_utc}; refusing to build a postgame observation before "
                        f"kickoff has elapsed"
                    ),
                },
            }

        # Build the per-QB observation from BOTH pregame and postgame
        # normalized rows + snapshot-scoped evidence. We read the
        # pregame active rows by ``selected_snapshot_id`` so we never
        # join the entire historical active file on sleeper_player_id.
        pregame_active = self._read_active_for_snapshot(
            str(pointer.get("selected_snapshot_id"))
        )
        pregame_evidence = self._read_evidence_for_snapshot(
            str(pointer.get("selected_snapshot_id"))
        )
        observation_id = f"hof-{game.get('game_id')}-{snapshot_id}"
        observation_record = build_observation_record(
            observation_id=observation_id,
            game=game,
            relevant_qb_rows=active_frame,
            pregame_snapshot_id=str(pointer.get("selected_snapshot_id")),
            postgame_snapshot_id=snapshot_id,
            pregame_evidence_frame=pregame_evidence,
            postgame_evidence_frame=evidence_frame,
            pregame_normalized_frame=pregame_active,
            postgame_normalized_frame=active_frame,
            all_snapshot_ids=[
                str(pointer.get("selected_snapshot_id")),
                snapshot_id,
            ],
        )
        try:
            self._append_hof_observation(_hof_observation_frame(observation_record))
        except OSError as exc:
            return {
                "outcome": RunOutcome.PERSISTENCE_FAILURE,
                "payload": {
                    "error_class": type(exc).__name__,
                    "error_message": str(exc),
                },
            }
        # Per-state counts over the postgame evidence so the markdown
        # report stays consistent with the observation record.
        evidence_state_counts: dict[str, int] = {}
        for state in observation_record.get("derived_evidence_state") or []:
            if state is None:
                continue
            evidence_state_counts[state] = evidence_state_counts.get(state, 0) + 1
        try:
            hof_payload = write_hof_observation_report(
                observation=observation_record,
                evidence_state_counts=evidence_state_counts,
                output_markdown=self.reports_root / "sleeper_hof_game_observation.md",
                output_json=self.reports_root / "sleeper_hof_game_observation.json",
            )
        except OSError as exc:
            return {
                "outcome": RunOutcome.PERSISTENCE_FAILURE,
                "payload": {
                    "error_class": type(exc).__name__,
                    "error_message": str(exc),
                },
            }
        return {"outcome": None, "payload": hof_payload}

    # ------------------------------------------------------------------
    # outcome-finalization helpers
    # ------------------------------------------------------------------

    def _finalize_transport_failure(
        self,
        *,
        kind: str,
        snapshot_id: str,
        observed_at_utc: str,
        attempts: Sequence[SleeperFetchResult],
        observed: datetime,
    ) -> dict[str, Any]:
        outcome = RunOutcome.TRANSPORT_FAILURE
        report_payload = {
            "schema_version": "sleeper-qb-failure-v1",
            "snapshot_id": snapshot_id,
            "generated_at_utc": observed_at_utc,
            "attempts": [asdict(a) for a in attempts],
            "freshness_state": derive_freshness_state(
                FreshnessInputs(
                    last_success_at_utc=None,
                    last_failure_at_utc=(
                        attempts[-1].response_received_at_utc
                        if attempts
                        else None
                    ),
                    last_attempt_success=False,
                    change_count=0,
                    last_payload_sha256=None,
                    prior_payload_sha256=None,
                    parsed_ok=False,
                    present_fields=frozenset(),
                ),
                staleness_threshold_seconds=self.staleness_threshold_seconds,
                now=observed,
            ),
        }
        self._write_failure_report(snapshot_id, report_payload)
        last_error = attempts[-1] if attempts else None
        record = RunOutcomeRecord(
            outcome=outcome,
            snapshot_id=snapshot_id,
            observed_at_utc=observed_at_utc,
            finished_at_utc=_utc_now_iso(),
            error_class=last_error.error_class if last_error else None,
            error_message=last_error.error_message if last_error else None,
            error_token=ERROR_TOKENS[outcome],
            exit_code=EXIT_CODES[outcome],
            kind=kind,
            attempt_count=len(attempts),
        )
        self._commit_terminal_record(record)
        return {
            "snapshot_id": snapshot_id,
            "observed_at_utc": observed_at_utc,
            "freshness_state": report_payload["freshness_state"],
            "run_outcome": outcome.value,
            "exit_code": EXIT_CODES[outcome],
            "attempts": [asdict(a) for a in attempts],
        }

    def _finalize_incomplete_response(
        self,
        *,
        kind: str,
        snapshot_id: str,
        observed_at_utc: str,
        attempts: Sequence[SleeperFetchResult],
        error_class: str,
        error_message: str,
    ) -> dict[str, Any]:
        outcome = RunOutcome.INCOMPLETE_RESPONSE
        # Per the rereview contract, the freshness state for a
        # parse-level failure (HTTP succeeded but the body was
        # malformed / empty / unusable) is INCOMPLETE_RESPONSE.
        # The transport-level path produces FETCH_FAILED_USING_NO_FALLBACK;
        # that path does not flow through this function.
        freshness_state = "INCOMPLETE_RESPONSE"
        report_payload = {
            "schema_version": "sleeper-qb-failure-v1",
            "snapshot_id": snapshot_id,
            "generated_at_utc": observed_at_utc,
            "error_class": error_class,
            "error_message": error_message,
            "attempts": [asdict(a) for a in attempts],
            "freshness_state": freshness_state,
        }
        self._write_failure_report(snapshot_id, report_payload)
        record = RunOutcomeRecord(
            outcome=outcome,
            snapshot_id=snapshot_id,
            observed_at_utc=observed_at_utc,
            finished_at_utc=_utc_now_iso(),
            error_class=error_class,
            error_message=error_message,
            error_token=ERROR_TOKENS[outcome],
            exit_code=EXIT_CODES[outcome],
            kind=kind,
            attempt_count=len(attempts),
        )
        self._commit_terminal_record(record)
        return {
            "snapshot_id": snapshot_id,
            "observed_at_utc": observed_at_utc,
            "freshness_state": freshness_state,
            "run_outcome": outcome.value,
            "exit_code": EXIT_CODES[outcome],
            "error_class": error_class,
            "error_message": error_message,
        }

    def _finalize_normalization_failure(
        self,
        *,
        kind: str,
        snapshot_id: str,
        observed_at_utc: str,
        attempts: Sequence[SleeperFetchResult],
        error_class: str,
        error_message: str,
    ) -> dict[str, Any]:
        outcome = RunOutcome.NORMALIZATION_FAILURE
        record = RunOutcomeRecord(
            outcome=outcome,
            snapshot_id=snapshot_id,
            observed_at_utc=observed_at_utc,
            finished_at_utc=_utc_now_iso(),
            error_class=error_class,
            error_message=error_message,
            error_token=ERROR_TOKENS[outcome],
            exit_code=EXIT_CODES[outcome],
            kind=kind,
            attempt_count=len(attempts),
        )
        self._commit_terminal_record(record)
        return {
            "snapshot_id": snapshot_id,
            "observed_at_utc": observed_at_utc,
            "run_outcome": outcome.value,
            "exit_code": EXIT_CODES[outcome],
            "error_class": error_class,
            "error_message": error_message,
        }

    def _failure_after_history_failure(
        self,
        *,
        kind: str,
        snapshot_id: str,
        observed_at_utc: str,
        attempts: Sequence[SleeperFetchResult],
        history_error: BaseException,
    ) -> dict[str, Any]:
        """Handle a history-write failure.

        History-first ordering (Rereview 4852878097 §5): if the
        durable history append failed, status MUST NOT be written
        (because then ``latest_run_status.json`` would claim an
        outcome absent from ``run_history.parquet``). The terminal
        outcome is PERSISTENCE_FAILURE (exit 13). No second history
        row is attempted — one row per invocation.

        The latest-success pointer is not advanced.
        """
        return {
            "snapshot_id": snapshot_id,
            "observed_at_utc": observed_at_utc,
            "run_outcome": RunOutcome.PERSISTENCE_FAILURE.value,
            "exit_code": EXIT_CODES[RunOutcome.PERSISTENCE_FAILURE],
            "error_class": type(history_error).__name__,
            "error_message": f"run_history write failed: {history_error}",
        }

    def _failure_after_status_failure(
        self,
        *,
        kind: str,
        snapshot_id: str,
        observed_at_utc: str,
        attempts: Sequence[SleeperFetchResult],
        status_error: BaseException,
    ) -> dict[str, Any]:
        """Handle a status-write failure.

        History-first ordering (Rereview 4852878097 §5): history was
        already durably written, so the terminal record is preserved
        in ``run_history.parquet``. A status-write failure surfaces
        PERSISTENCE_FAILURE (exit 13) without re-appending a second
        history row and without advancing the latest-success pointer.
        """
        return {
            "snapshot_id": snapshot_id,
            "observed_at_utc": observed_at_utc,
            "run_outcome": RunOutcome.PERSISTENCE_FAILURE.value,
            "exit_code": EXIT_CODES[RunOutcome.PERSISTENCE_FAILURE],
            "error_class": type(status_error).__name__,
            "error_message": f"latest_run_status write failed: {status_error}",
        }

    def _write_failure_report(self, snapshot_id: str, payload: dict[str, Any]) -> None:
        try:
            atomic_write_text(
                self.reports_root / f"failure_{snapshot_id}.json",
                json.dumps(payload, indent=2, default=str),
            )
        except OSError:
            # Failure reports are best-effort; never raise from here.
            pass

    def _write_latest_run_status(self, record: RunOutcomeRecord) -> None:
        atomic_write_text(
            self.latest_run_status_path,
            json.dumps(record.to_dict(), indent=2, default=str) + "\n",
        )

    def _commit_terminal_record(
        self,
        record: RunOutcomeRecord,
    ) -> None:
        """Persist a terminal outcome to ``run_history.parquet`` and
        ``latest_run_status.json`` in history-first order.

        Rereview 4852878097 §3 + §5:

        * Exactly one terminal-history row is appended per invocation.
        * History is appended BEFORE status is written, so a status
          failure cannot leave ``latest_run_status.json`` claiming an
          outcome absent from ``run_history.parquet``.
        * If the history write raises ``OSError``, it propagates and
          status is NOT written.
        * If the history write succeeds and the status write raises
          ``OSError``, the status failure propagates and the caller is
          responsible for surfacing ``PERSISTENCE_FAILURE`` (exit 13)
          without re-appending a second history row.
        """
        self._append_run_history(record)
        self._write_latest_run_status(record)

    def _append_run_history(self, record: RunOutcomeRecord) -> None:
        """Append one row to ``run_history.parquet``.

        Rereview 4852338912: the terminal run history is a durable
        parquet file (``run_history.parquet``). Any ``OSError``
        propagates to the caller — it is never swallowed, because a
        missing terminal-history row means the rolling metrics would
        silently drop a terminal record.
        """
        atomic_append_run_history(
            self.run_history_path,
            record.to_dict(),
            row_schema=RUN_HISTORY_ROW_DTYPES,
        )

    # ------------------------------------------------------------------
    # persistence helpers (atomic)
    # ------------------------------------------------------------------

    def _append_fetch_ledger(
        self,
        attempts: Sequence[SleeperFetchResult],
        *,
        observed_at_utc: str,
    ) -> None:
        if not attempts:
            return
        new_frame = pl.DataFrame(
            [asdict(a) for a in attempts],
            infer_schema_length=len(attempts),
        )
        new_frame = new_frame.with_columns(pl.lit(observed_at_utc).alias("observed_at_utc"))
        atomic_append_parquet(self.fetch_ledger_path, new_frame)

    def _append_active(self, frame: pl.DataFrame) -> None:
        atomic_append_parquet(
            self.active_qb_path, frame, schema_dtypes=QB_SNAPSHOT_DTYPES
        )

    def _append_inactive(self, frame: pl.DataFrame) -> None:
        atomic_append_parquet(self.inactive_qb_path, frame)

    def _append_evidence(self, frame: pl.DataFrame) -> None:
        if frame.height == 0:
            return
        atomic_append_parquet(
            self.evidence_path, frame, schema_dtypes=EVIDENCE_STATE_DTYPES
        )

    def _append_crosswalk(self, frame: pl.DataFrame) -> None:
        if frame.height == 0:
            # Always write at least the schema so downstream readers
            # can rely on column presence.
            if not self.crosswalk_path.exists():
                empty = pl.DataFrame(
                    {
                        field: pl.Series(name=field, values=[], dtype=dt)
                        for field, dt in CROSSWALK_DTYPES.items()
                    }
                )
                atomic_write_parquet(self.crosswalk_path, empty)
            return
        atomic_append_parquet(self.crosswalk_path, frame)

    def _append_changes(self, frame: pl.DataFrame) -> None:
        if frame.height == 0:
            return
        atomic_append_parquet(
            self.change_ledger_path, frame, schema_dtypes=CHANGE_LEDGER_DTYPES
        )

    def _append_hof_observation(self, frame: pl.DataFrame) -> None:
        atomic_append_parquet(
            self.hof_obs_path, frame, schema_dtypes=HOF_OBSERVATION_DTYPES
        )

    # ------------------------------------------------------------------
    # snapshot-scoped reads
    # ------------------------------------------------------------------

    def _read_prior_active(self) -> pl.DataFrame | None:
        if not self.active_qb_path.exists():
            return None
        frame = pl.read_parquet(self.active_qb_path)
        if frame.height == 0:
            return None
        unique_snapshots = (
            frame.select("snapshot_id", "fetched_at_utc")
            .unique(subset=["snapshot_id"], keep="last")
            .sort("fetched_at_utc")
        )
        if unique_snapshots.height == 0:
            return None
        last = unique_snapshots.row(unique_snapshots.height - 1, named=True)
        prior = frame.filter(pl.col("snapshot_id") == last["snapshot_id"])
        return prior

    def _read_active_for_snapshot(self, snapshot_id: str) -> pl.DataFrame:
        if not self.active_qb_path.exists() or not snapshot_id:
            return pl.DataFrame(
                {field: pl.Series(name=field, values=[], dtype=dt)
                 for field, dt in QB_SNAPSHOT_DTYPES.items()}
            )
        frame = pl.read_parquet(self.active_qb_path)
        if frame.height == 0:
            return frame
        return frame.filter(pl.col("snapshot_id") == snapshot_id)

    def _read_evidence_for_snapshot(self, snapshot_id: str) -> pl.DataFrame:
        """Snapshot-scoped evidence read. The rolling-history code
        joins the prior evidence frame to the current frame on
        ``sleeper_player_id``; that join must be filtered to the
        *exact* prior successful snapshot, never the entire
        historical evidence file. This helper enforces that.
        """
        if not self.evidence_path.exists() or not snapshot_id:
            return pl.DataFrame(
                {field: pl.Series(name=field, values=[], dtype=dt)
                 for field, dt in EVIDENCE_STATE_DTYPES.items()}
            )
        frame = pl.read_parquet(self.evidence_path)
        if frame.height == 0:
            return frame
        return frame.filter(pl.col("snapshot_id") == snapshot_id)

    def _read_prior_evidence(self) -> pl.DataFrame | None:
        """Backward-compatible alias. Returns the prior snapshot's
        evidence-scoped frame so change detection is exact.
        """
        prior_snapshot_id = self._read_latest_snapshot_id()
        return self._read_evidence_for_snapshot(prior_snapshot_id or "")

    def _read_prior_evidence_for(self, snapshot_id: str | None) -> pl.DataFrame | None:
        return self._read_evidence_for_snapshot(snapshot_id or "")

    def _read_latest_snapshot_id(self) -> str | None:
        if not self.latest_pointer_path.exists():
            return None
        try:
            data = json.loads(self.latest_pointer_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        return data.get("snapshot_id")

    def _read_latest_observed_at_utc(self) -> str | None:
        if not self.latest_pointer_path.exists():
            return None
        try:
            data = json.loads(self.latest_pointer_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        return data.get("observed_at_utc")


def _date_partition(timestamp: datetime) -> str:
    ts = timestamp.astimezone(timezone.utc)
    return f"{ts.year:04d}/{ts.month:02d}/{ts.day:02d}"


def _hof_observation_frame(record: Mapping[str, Any]) -> pl.DataFrame:
    row: dict[str, Any] = {}
    for field in HOF_OBSERVATION_DTYPES:
        value = record.get(field)
        if field in {"relevant_sleeper_qbs", "snapshot_ids"} and value is None:
            value = []
        row[field] = value
    frame = pl.DataFrame([row], infer_schema_length=1)
    frame = frame.select(
        [pl.col(field).cast(dt, strict=False).alias(field) for field, dt in HOF_OBSERVATION_DTYPES.items()]
    )
    return frame


def _utc_iso_is_before(left: str, right: str) -> bool:
    """Return True iff ``left`` strictly precedes ``right`` in UTC.

    Both inputs are ISO-8601 strings; ``Z`` is treated as ``+00:00``.
    A malformed input raises ``ValueError`` so callers can treat
    that as a structural error.
    """
    def _parse(value: str) -> datetime:
        text = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            raise ValueError(f"timestamp must be timezone-aware: {value}")
        return dt.astimezone(timezone.utc)
    return _parse(left) < _parse(right)
