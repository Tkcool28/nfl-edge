"""End-to-end bounded audit orchestrator.

The orchestrator is the single entry point the bounded shell scripts
call. It is intentionally synchronous, side-effect-only-on-its-own-
tree, and never imports from the modeling stack. The orchestrator:

1. fetches the Sleeper active-QB endpoint with bounded retries;
2. normalizes the response;
3. joins against a frozen nflverse QB reference (2025 stripped);
4. emits the change ledger against the immediately prior successful
   snapshot;
5. derives freshness state;
6. persists raw bytes, ledger, normalized frames, crosswalk, and
   reports.
"""

from __future__ import annotations

import json
import os
import time
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
from .changes import detect_changes
from .crosswalk import build_crosswalk
from .evidence_states import classify
from .freshness import (
    FreshnessInputs,
    change_count_for,
    derive_freshness_state,
    schema_drift_fields,
)
from .ho_game import build_observation_record
from .ids import snapshot_id_for, utc_now
from .metrics import compute_reliability_metrics
from .normalize import QB_SNAPSHOT_DTYPES, normalize_qb_payload
from .report import write_hof_observation_report, write_live_audit_report

AUDIT_VERSION = "sleeper-qb-audit-v1"


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

    The shipped reference is built from
    ``nflreadpy.load_ff_playerids()`` whose columns are
    ``sleeper_id`` (int) and ``name`` (str). The crosswalk expects
    ``player_id`` (str), ``full_name`` (str), and several stable-id
    columns. This helper performs that normalization in one place so
    the orchestrator and the offline audit CLI share the same
    semantics. The 2025 sealed holdout is excluded by the
    ``db_season != 2025`` filter applied when the file is built; this
    helper adds a defensive strip in case the reference is replaced.
    """
    path = Path(path)
    if not path.exists():
        return pl.DataFrame()
    frame = pl.read_parquet(path)
    if frame.height == 0:
        return frame
    # Coerce the Sleeper id column to a string so it can be compared
    # against Sleeper's string-keyed player map.
    if "sleeper_id" in frame.columns and "sleeper_id_str" not in frame.columns:
        frame = frame.with_columns(pl.col("sleeper_id").cast(pl.Utf8).alias("sleeper_id_str"))
    # Build a synthetic player_id (coalesce GSIS, fall back to sleeper).
    if "player_id" not in frame.columns:
        coalesce_inputs = []
        if "gsis_id" in frame.columns:
            coalesce_inputs.append(pl.col("gsis_id"))
        if "sleeper_id_str" in frame.columns:
            coalesce_inputs.append(pl.col("sleeper_id_str"))
        if coalesce_inputs:
            frame = frame.with_columns(pl.coalesce(coalesce_inputs).alias("player_id"))
    # Rename nflverse "name" -> "full_name" for the crosswalk's contract.
    if "name" in frame.columns and "full_name" not in frame.columns:
        frame = frame.rename({"name": "full_name"})
    # Add required schema columns if missing. We only add ``season``
    # when it is genuinely missing; we must never overwrite an
    # existing ``db_season`` because the 2025 tripwire below keys on
    # that column.
    for required, default_dtype in (
        ("position", pl.Utf8),
    ):
        if required not in frame.columns:
            frame = frame.with_columns(pl.lit(None, dtype=default_dtype).alias(required))
    if "position" in frame.columns:
        # Many reference rows are not QBs; restrict to QB before the
        # crosswalk indexes them.
        frame = frame.filter(pl.col("position") == "QB")
    # Defensive 2025 strip. The shipped reference excludes 2025 at
    # build time; this is a belt-and-braces tripwire. We only consult
    # ``db_season`` (the only season column the nflverse identity
    # table exposes); the in-frame ``season`` column is the model's
    # contract, not the identity table's, and must not be used to
    # filter the reference.
    if "db_season" in frame.columns:
        frame = frame.filter(pl.col("db_season") != 2025)
    # Project to the columns the crosswalk actually consults, plus
    # the synthesized Sleeper id so the crosswalk's exact-Sleeper
    # priority-0 path can fire.
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


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _evidence_frame(active_frame: pl.DataFrame) -> pl.DataFrame:
    if active_frame.height == 0:
        return pl.DataFrame(
            {
                "sleeper_player_id": pl.Series(
                    name="sleeper_player_id", values=[], dtype=pl.Utf8
                ),
                "evidence_state": pl.Series(
                    name="evidence_state", values=[], dtype=pl.Utf8
                ),
            }
        )
    states = [classify(row) for row in active_frame.to_dicts()]
    return active_frame.with_columns(pl.Series(name="evidence_state", values=states)).select(
        ["sleeper_player_id", "evidence_state"]
    )


class AuditOrchestrator:
    """Bounded single-run audit orchestrator.

    Parameters are paths and tuning knobs, not secrets. The class is
    safe to construct in a unit test and is fully deterministic when
    injected with a stub session.
    """

    def __init__(
        self,
        *,
        audit_root: str | Path,
        endpoint: str = DEFAULT_ENDPOINT,
        staleness_threshold_seconds: float = 6 * 3600.0,
        nflverse_qb_path: str | Path | None = None,
    ) -> None:
        self.audit_root = Path(audit_root)
        self.endpoint = endpoint
        self.staleness_threshold_seconds = staleness_threshold_seconds
        self.nflverse_qb_path = (
            Path(nflverse_qb_path) if nflverse_qb_path is not None else None
        )
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

    # ------------------------------------------------------------------
    # public entry points
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        session: Any | None = None,
        kind: str = "scheduled",
        hof_game: Mapping[str, Any] | None = None,
        hof_observation: Mapping[str, Any] | None = None,
        forced_snapshot_id: str | None = None,
        forced_observed_at_utc: str | None = None,
    ) -> dict[str, Any]:
        """Run the bounded audit once. Returns a JSON-ready dict."""
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
        # 3. Persist fetch ledger (always).
        self._append_fetch_ledger(attempts, observed_at_utc=observed_at_utc)
        # 4. Determine which prior snapshot to compare against.
        prior_active = self._read_prior_active()
        prior_evidence = self._read_prior_evidence()
        prior_snapshot_id = self._read_latest_snapshot_id()
        # 5. If the fetch failed, write a failure report and return.
        if winner is None:
            report_path = self.reports_root / f"failure_{snapshot_id}.json"
            report_payload = {
                "schema_version": "sleeper-qb-failure-v1",
                "snapshot_id": snapshot_id,
                "generated_at_utc": observed_at_utc,
                "attempts": [asdict(a) for a in attempts],
                "freshness_state": derive_freshness_state(
                    FreshnessInputs(
                        last_success_at_utc=None,
                        last_failure_at_utc=attempts[-1].response_received_at_utc
                        if attempts
                        else None,
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
            _atomic_write_text(report_path, json.dumps(report_payload, indent=2, default=str))
            return report_payload
        # 6. Parse the winning payload.
        try:
            raw_payload = json.loads(Path(winner.raw_payload_path).read_bytes())
        except json.JSONDecodeError as exc:
            report_payload = {
                "schema_version": "sleeper-qb-failure-v1",
                "snapshot_id": snapshot_id,
                "generated_at_utc": observed_at_utc,
                "error_class": "JSONDecodeError",
                "error_message": str(exc),
                "attempts": [asdict(a) for a in attempts],
            }
            _atomic_write_text(
                self.reports_root / f"failure_{snapshot_id}.json",
                json.dumps(report_payload, indent=2, default=str),
            )
            return report_payload
        present, missing, _ = schema_drift_fields(raw_payload)
        # 7. Normalize.
        active_frame, inactive_frame, warnings = normalize_qb_payload(
            snapshot_id=snapshot_id,
            fetched_at_utc=observed_at_utc,
            raw_payload=raw_payload,
        )
        # 8. Append normalized frames.
        self._append_active(active_frame)
        if inactive_frame.height > 0:
            self._append_inactive(inactive_frame)
        # 9. Build evidence-state frame.
        evidence_frame = _evidence_frame(active_frame)
        self._append_evidence(evidence_frame)
        # 10. Crosswalk.
        if self.nflverse_qb_path is not None:
            nflverse_qbs = _read_nflverse_qbs(self.nflverse_qb_path)
            crosswalk = build_crosswalk(
                snapshot_id=snapshot_id,
                active_qb_frame=active_frame,
                nflverse_qbs=nflverse_qbs,
            )
        else:
            crosswalk = build_crosswalk(
                snapshot_id=snapshot_id,
                active_qb_frame=active_frame,
                nflverse_qbs=pl.DataFrame(),
            )
        self._append_crosswalk(crosswalk)
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
        # 12. Update latest pointer.
        latest_pointer = {
            "snapshot_id": snapshot_id,
            "observed_at_utc": observed_at_utc,
            "payload_sha256": winner.sha256,
            "raw_payload_path": winner.raw_payload_path,
        }
        _atomic_write_text(
            self.latest_pointer_path,
            json.dumps(latest_pointer, indent=2, default=str) + "\n",
        )
        # 13. HOF observation (if requested).
        hof_payload: dict[str, Any] | None = None
        if hof_game is not None:
            hof_observation_id = (
                hof_observation.get("observation_id")
                if isinstance(hof_observation, Mapping)
                else f"hof-{snapshot_id}"
            )
            observation_record = build_observation_record(
                observation_id=str(hof_observation_id),
                game=hof_game,
                relevant_qb_rows=active_frame,
                pregame_snapshot_id=str(hof_observation.get("pregame_snapshot_id", snapshot_id)),
                postgame_snapshot_id=str(hof_observation.get("postgame_snapshot_id", snapshot_id)),
                pregame_evidence_frame=evidence_frame,
                postgame_evidence_frame=evidence_frame,
                all_snapshot_ids=[snapshot_id],
            )
            self._append_hof_observation(_hof_observation_frame(observation_record))
            evidence_state_counts = (
                observation_record["derived_evidence_state"]
                if observation_record["derived_evidence_state"]
                else []
            )
            counts: dict[str, int] = {}
            for state in evidence_state_counts:
                counts[state] = counts.get(state, 0) + 1
            hof_payload = write_hof_observation_report(
                observation=observation_record,
                evidence_state_counts=counts,
                output_markdown=self.reports_root / "sleeper_hof_game_observation.md",
                output_json=self.reports_root / "sleeper_hof_game_observation.json",
            )
        # 14. Live audit report.
        metrics = compute_reliability_metrics(
            fetch_attempts=[asdict(a) for a in attempts],
            active_qb_snapshots=[{
                "snapshot_id": snapshot_id,
                "rows": active_frame.to_dicts(),
            }],
            crosswalk_snapshots=[{
                "snapshot_id": snapshot_id,
                "rows": crosswalk.to_dicts(),
            }],
            change_ledger=change_ledger,
            freshness_history=[
                {
                    "last_success_at_utc": observed_at_utc,
                    "last_failure_at_utc": None,
                    "last_attempt_success": True,
                    "change_count": change_count_for(change_ledger),
                    "last_payload_sha256": winner.sha256,
                    "prior_payload_sha256": None,
                    "parsed_ok": True,
                    "present_fields": present,
                    "state": derive_freshness_state(
                        FreshnessInputs(
                            last_success_at_utc=observed_at_utc,
                            last_failure_at_utc=None,
                            last_attempt_success=True,
                            change_count=change_count_for(change_ledger),
                            last_payload_sha256=winner.sha256,
                            prior_payload_sha256=None,
                            parsed_ok=True,
                            present_fields=present,
                        ),
                        staleness_threshold_seconds=self.staleness_threshold_seconds,
                        now=observed,
                    ),
                }
            ],
        )
        freshness_state = metrics.get("freshness_state") if False else derive_freshness_state(
            FreshnessInputs(
                last_success_at_utc=observed_at_utc,
                last_failure_at_utc=None,
                last_attempt_success=True,
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
                    "kind": "success",
                    "at_utc": observed_at_utc,
                    "snapshot_id": snapshot_id,
                    "freshness_state": freshness_state,
                    "schema_drift_missing_fields": sorted(missing),
                    "warnings": warnings,
                }
            ],
            output_markdown=self.reports_root / "sleeper_qb_live_audit.md",
            output_json=self.reports_root / "sleeper_qb_live_audit.json",
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
        }

    # ------------------------------------------------------------------
    # persistence helpers
    # ------------------------------------------------------------------

    def _append_fetch_ledger(
        self,
        attempts: Sequence[SleeperFetchResult],
        *,
        observed_at_utc: str,
    ) -> None:
        self.raw_root.mkdir(parents=True, exist_ok=True)
        if not attempts:
            return
        new_frame = pl.DataFrame(
            [asdict(a) for a in attempts],
            infer_schema_length=len(attempts),
        )
        # Add observed_at_utc at ledger level for downstream joins.
        new_frame = new_frame.with_columns(pl.lit(observed_at_utc).alias("observed_at_utc"))
        if self.fetch_ledger_path.exists():
            existing = pl.read_parquet(self.fetch_ledger_path)
            combined = pl.concat([existing, new_frame], how="diagonal_relaxed")
        else:
            combined = new_frame
        combined.write_parquet(self.fetch_ledger_path)

    def _append_active(self, frame: pl.DataFrame) -> None:
        self.normalized_root.mkdir(parents=True, exist_ok=True)
        if self.active_qb_path.exists():
            existing = pl.read_parquet(self.active_qb_path)
            combined = pl.concat([existing, frame], how="diagonal_relaxed")
        else:
            combined = frame
        combined = combined.select(
            [pl.col(field).cast(dt, strict=False).alias(field) for field, dt in QB_SNAPSHOT_DTYPES.items()]
        )
        combined.write_parquet(self.active_qb_path)

    def _append_inactive(self, frame: pl.DataFrame) -> None:
        if self.inactive_qb_path.exists():
            existing = pl.read_parquet(self.inactive_qb_path)
            combined = pl.concat([existing, frame], how="diagonal_relaxed")
        else:
            combined = frame
        combined.write_parquet(self.inactive_qb_path)

    def _append_evidence(self, frame: pl.DataFrame) -> None:
        if frame.height == 0:
            return
        if self.evidence_path.exists():
            existing = pl.read_parquet(self.evidence_path)
            combined = pl.concat([existing, frame], how="diagonal_relaxed")
        else:
            combined = frame
        combined.write_parquet(self.evidence_path)

    def _append_crosswalk(self, frame: pl.DataFrame) -> None:
        if frame.height == 0:
            # Always write at least the schema so downstream readers
            # can rely on column presence.
            self.normalized_root.mkdir(parents=True, exist_ok=True)
            if not self.crosswalk_path.exists():
                from .crosswalk import CROSSWALK_DTYPES
                empty = pl.DataFrame(
                    {
                        field: pl.Series(name=field, values=[], dtype=dt)
                        for field, dt in CROSSWALK_DTYPES.items()
                    }
                )
                empty.write_parquet(self.crosswalk_path)
            return
        self.normalized_root.mkdir(parents=True, exist_ok=True)
        if self.crosswalk_path.exists():
            existing = pl.read_parquet(self.crosswalk_path)
            combined = pl.concat([existing, frame], how="diagonal_relaxed")
        else:
            combined = frame
        combined.write_parquet(self.crosswalk_path)

    def _append_changes(self, frame: pl.DataFrame) -> None:
        if frame.height == 0:
            return
        from .changes import CHANGE_LEDGER_DTYPES
        if self.change_ledger_path.exists():
            existing = pl.read_parquet(self.change_ledger_path)
            combined = pl.concat([existing, frame], how="diagonal_relaxed")
        else:
            combined = frame
        combined = combined.select(
            [pl.col(field).cast(dt, strict=False).alias(field) for field, dt in CHANGE_LEDGER_DTYPES.items()]
        )
        combined.write_parquet(self.change_ledger_path)

    def _append_hof_observation(self, frame: pl.DataFrame) -> None:
        from .ho_game import HOF_OBSERVATION_DTYPES
        if self.hof_obs_path.exists():
            existing = pl.read_parquet(self.hof_obs_path)
            combined = pl.concat([existing, frame], how="diagonal_relaxed")
        else:
            combined = frame
        combined = combined.select(
            [pl.col(field).cast(dt, strict=False).alias(field) for field, dt in HOF_OBSERVATION_DTYPES.items()]
        )
        combined.write_parquet(self.hof_obs_path)

    def _read_prior_active(self) -> pl.DataFrame | None:
        if not self.active_qb_path.exists():
            return None
        frame = pl.read_parquet(self.active_qb_path)
        if frame.height == 0:
            return None
        # Pick the last unique snapshot_id by sorted order.
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

    def _read_prior_evidence(self) -> pl.DataFrame | None:
        if not self.evidence_path.exists():
            return None
        return pl.read_parquet(self.evidence_path)

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
    from .ho_game import HOF_OBSERVATION_DTYPES
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
