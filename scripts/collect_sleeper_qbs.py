"""Bounded CLI to run one Sleeper QB source-audit pass.

This is the entry point invoked by the bounded systemd timer and by
tests. The CLI:

* reads ``config/sleeper_qb_audit_v1.yaml``;
* acquires the audit lock with a configurable timeout;
* constructs an ``AuditOrchestrator`` rooted at the configured audit
  directory;
* runs the bounded fetch + normalization + crosswalk + change ledger
  + HOF workflow as requested by ``--kind``;
* prints the result JSON to stdout;
* exits with the canonical exit code for the run's ``RunOutcome``.

Real network I/O is opt-in via ``--use-fake-session``; without it,
the CLI uses an injected deterministic stub session in tests.

Exit codes (see ``outcomes.py``):

* ``0`` — SUCCESS
* ``10`` — TRANSPORT_FAILURE
* ``11`` — INCOMPLETE_RESPONSE
* ``12`` — NORMALIZATION_FAILURE
* ``13`` — PERSISTENCE_FAILURE
* ``20`` — LOCK_FAILURE
* ``21`` — REFERENCE_FAILURE
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nfl_edge.source_audits.sleeper_qb_v1.atomic_io import (  # noqa: E402
    ReferenceArtifact,
    atomic_append_run_history,
    atomic_write_text,
)
from nfl_edge.source_audits.sleeper_qb_v1.locking import (  # noqa: E402
    LockFailure,
    advisory_lock,
)
from nfl_edge.source_audits.sleeper_qb_v1.outcomes import (  # noqa: E402
    ERROR_TOKENS,
    EXIT_CODES,
    RUN_HISTORY_ROW_DTYPES,
    RunOutcome,
    RunOutcomeRecord,
)
from nfl_edge.source_audits.sleeper_qb_v1.pipeline import (  # noqa: E402
    AuditOrchestrator,
)


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"audit config not found: {path}")
    loaded = yaml.safe_load(path.read_text())
    return loaded if isinstance(loaded, dict) else {}


def _build_orchestrator(
    config: dict[str, Any],
    audit_root: Path,
    *,
    reference_manifest: Sequence[ReferenceArtifact] | None = None,
) -> AuditOrchestrator:
    return AuditOrchestrator(
        audit_root=audit_root,
        endpoint=config.get(
            "endpoint", "https://api.sleeper.app/v1/players/nfl"
        ),
        staleness_threshold_seconds=float(
            config.get("staleness_threshold_seconds", 6 * 3600)
        ),
        nflverse_qb_path=config.get("nflverse_qb_path"),
        hof_fixture_path=config.get("hof_fixture_path"),
        reference_manifest=reference_manifest,
    )


def _resolve_reference_manifest(
    *,
    cli_value: Path | None,
    config: dict[str, Any],
    audit_root: Path | None = None,
) -> tuple[list[ReferenceArtifact], str | None]:
    """Resolve the configured reference manifest.

    The rereview contract makes ``reference_manifest`` mandatory.
    If the config key is missing, the configured path is missing,
    the JSON is malformed, the schema is malformed, or the
    artifacts list is empty, this function returns ``([], error)``
    where ``error`` is a descriptive message. The caller is
    expected to surface that error as ``REFERENCE_FAILURE`` (exit
    21). The CLI flag does not bypass the configured manifest: if
    a configured manifest is present, the CLI flag must agree
    (same file). This avoids silently skipping verification in a
    way that defeats the clean-clone contract.

    Rereview 4852338912: ``OSError`` from reading the manifest
    file is caught and returned as an error string, so the CLI
    can persist it to ``latest_run_status.json`` and the terminal
    run history rather than crashing with a bare traceback.
    """
    config_value = config.get("reference_manifest")
    if config_value is None:
        return ([], "missing reference_manifest in config (mandatory)")
    configured_path = Path(str(config_value))
    if not configured_path.exists():
        return ([], f"missing reference manifest file: {configured_path}")
    try:
        raw = json.loads(configured_path.read_text())
    except OSError as exc:
        return ([], f"cannot read reference manifest file: {exc}")
    except json.JSONDecodeError as exc:
        return ([], f"malformed reference manifest JSON: {exc}")
    if not isinstance(raw, dict):
        return ([], "reference manifest must be a JSON object with an 'artifacts' array")
    artifacts_raw = raw.get("artifacts")
    if not isinstance(artifacts_raw, list) or not artifacts_raw:
        return ([], "reference manifest has empty or missing 'artifacts' array")
    parsed: list[ReferenceArtifact] = []
    for entry in artifacts_raw:
        if not isinstance(entry, dict):
            return ([], f"reference manifest entry is not a JSON object: {entry!r}")
        try:
            parsed.append(
                ReferenceArtifact(
                    path=str(entry["path"]),
                    sha256=str(entry["sha256"]),
                    row_count=int(entry["row_count"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            return (
                [],
                f"reference manifest schema violation on entry {entry!r}: {exc}",
            )
    # CLI flag, if supplied, must match the configured path. We do
    # not silently allow the flag to bypass the configured manifest.
    if cli_value is not None and cli_value != configured_path:
        return (
            [],
            f"--reference-manifest {cli_value} does not match configured "
            f"{configured_path}; refusing to skip verification",
        )
    return (parsed, None)


def _emit_terminal(
    *,
    outcome: RunOutcome,
    error_class: str | None = None,
    error_message: str | None = None,
    extra: dict[str, Any] | None = None,
    audit_root: Path | None = None,
    snapshot_id: str | None = None,
    observed_at_utc: str | None = None,
    attempt_count: int = 0,
    kind: str | None = None,
) -> tuple[RunOutcome, int] | None:
    """Print a structured terminal outcome JSON to stderr.

    Used when the CLI must abort with a typed outcome before the
    orchestrator's normal pipeline can return a result (e.g. a
    malformed config or a missing reference manifest).

    Rereview 4852338912: when ``audit_root`` is known, the terminal
    outcome is also durably persisted to ``latest_run_status.json``
    and ``run_history.parquet`` so the rolling metrics and the
    audit root's single-source-of-truth pointer both reflect the
    failure. For failures before ``audit_root`` is known, stderr
    + nonzero exit is the acceptable fallback.

    Rereview 4852878097: persistence is history-first, then status.
    The actual ``kind`` is taken from the caller's CLI argument
    (not hardcoded to ``"scheduled"``). Persistence failures are
    surfaced: if either the history append or the latest-status
    write fails, the function returns a tuple of
    ``(PERSISTENCE_FAILURE, exit_code=13)`` so the caller can
    return that exit code rather than pretending the failure was
    durably recorded. ``OSError`` is never silently swallowed.
    """
    payload: dict[str, Any] = {
        "run_outcome": outcome.value,
        "exit_code": EXIT_CODES[outcome],
        "error_token": ERROR_TOKENS.get(outcome, ""),
    }
    if error_class is not None:
        payload["error_class"] = error_class
    if error_message is not None:
        payload["error_message"] = error_message
    if extra:
        payload.update(extra)
    print(json.dumps(payload, indent=2, default=str), file=sys.stderr)

    # When audit_root is known, durably persist the terminal outcome.
    if audit_root is None:
        return None
    from datetime import datetime, timezone
    finished_at = datetime.now(timezone.utc).isoformat()
    record = RunOutcomeRecord(
        outcome=outcome,
        snapshot_id=snapshot_id,
        observed_at_utc=observed_at_utc,
        finished_at_utc=finished_at,
        error_class=error_class,
        error_message=error_message,
        error_token=ERROR_TOKENS.get(outcome, ""),
        exit_code=EXIT_CODES[outcome],
        kind=kind,
        attempt_count=attempt_count,
    )
    history_path = audit_root / "run_history.parquet"
    latest_status_path = audit_root / "latest_run_status.json"
    try:
        atomic_append_run_history(
            history_path,
            record.to_dict(),
            row_schema=RUN_HISTORY_ROW_DTYPES,
        )
    except OSError as exc:
        # History persistence failed. We cannot truthfully record
        # this terminal outcome; surface PERSISTENCE_FAILURE (13).
        # Do NOT silently pretend the history was appended.
        print(
            f"persistence failure: run_history write failed: {exc}",
            file=sys.stderr,
        )
        return (RunOutcome.PERSISTENCE_FAILURE, EXIT_CODES[RunOutcome.PERSISTENCE_FAILURE])
    try:
        atomic_write_text(
            latest_status_path,
            json.dumps(record.to_dict(), indent=2, default=str) + "\n",
        )
    except OSError as exc:
        # History was written; status write failed. Surface
        # PERSISTENCE_FAILURE (13). We do NOT retry the history
        # append — that would produce two rows for one invocation.
        print(
            f"persistence failure: latest_run_status write failed: {exc}",
            file=sys.stderr,
        )
        return (RunOutcome.PERSISTENCE_FAILURE, EXIT_CODES[RunOutcome.PERSISTENCE_FAILURE])
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one Sleeper QB source-audit pass."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "config" / "sleeper_qb_audit_v1.yaml",
        help="Path to the audit YAML config.",
    )
    parser.add_argument(
        "--kind",
        default="scheduled",
        choices=["scheduled", "pregame", "postgame"],
        help="Audit run kind.",
    )
    parser.add_argument(
        "--lock-timeout-seconds",
        type=float,
        default=0.0,
        help="Maximum wall-clock seconds to wait for the audit lock; 0 means fail fast.",
    )
    parser.add_argument(
        "--use-fake-session",
        action="store_true",
        help="Use the deterministic stub session (tests only).",
    )
    parser.add_argument(
        "--reference-manifest",
        type=Path,
        default=None,
        help="Optional path to a JSON file listing {path, sha256, row_count} entries to verify before the run.",
    )
    parser.add_argument(
        "--observed-at-utc",
        default=None,
        help="Override the audit's notion of now (ISO 8601). Tests only.",
    )
    parser.add_argument(
        "--snapshot-id",
        default=None,
        help="Override the deterministic snapshot id. Tests only.",
    )
    args = parser.parse_args(argv)

    # Rereview 4852878097: the actual requested kind must flow into
    # every persisted terminal record (never hardcoded "scheduled").
    requested_kind = args.kind

    def _terminate(
        *,
        outcome: RunOutcome,
        error_class: str | None = None,
        error_message: str | None = None,
        audit_root: Path | None = None,
        extra: dict[str, Any] | None = None,
    ) -> int:
        """Invoke ``_emit_terminal`` with the requested kind and
        surface persistence failures as exit code 13.

        For failures before ``audit_root`` is known, this is a
        thin wrapper that returns the canonical exit code. For
        failures after ``audit_root`` is known, persistence
        failures inside ``_emit_terminal`` are surfaced as exit
        code 13 (``PERSISTENCE_FAILURE``).
        """
        kwargs: dict[str, Any] = {
            "outcome": outcome,
            "error_class": error_class,
            "error_message": error_message,
            "kind": requested_kind,
        }
        if audit_root is not None:
            kwargs["audit_root"] = audit_root
        if extra:
            kwargs["extra"] = extra
        result = _emit_terminal(**kwargs)
        if result is None:
            return EXIT_CODES[outcome]
        # ``_emit_terminal`` returned a (PERSISTENCE_FAILURE, 13)
        # tuple because one of the durable writes failed.
        return result[1]

    # 1. Config loading. A missing / malformed config is a
    #    NORMALIZATION_FAILURE (the input is unusable).
    try:
        config = _load_config(args.config)
    except FileNotFoundError as exc:
        return _terminate(
            outcome=RunOutcome.NORMALIZATION_FAILURE,
            error_class="FileNotFoundError",
            error_message=str(exc),
        )
    except yaml.YAMLError as exc:
        return _terminate(
            outcome=RunOutcome.NORMALIZATION_FAILURE,
            error_class="YAMLError",
            error_message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        return _terminate(
            outcome=RunOutcome.NORMALIZATION_FAILURE,
            error_class=type(exc).__name__,
            error_message=str(exc),
        )

    # 2. Audit-root resolution.
    try:
        audit_root = Path(str(config.get("audit_root", "data/source_audits/sleeper_qb_v1")))
    except Exception as exc:  # noqa: BLE001
        return _terminate(
            outcome=RunOutcome.NORMALIZATION_FAILURE,
            error_class=type(exc).__name__,
            error_message=f"bad audit_root in config: {exc}",
        )
    try:
        audit_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _terminate(
            outcome=RunOutcome.PERSISTENCE_FAILURE,
            error_class=type(exc).__name__,
            error_message=f"cannot create audit_root {audit_root}: {exc}",
            audit_root=audit_root,
        )
    # 3. Reference-manifest resolution. Mandatory per the
    #    rereview contract; any failure is a REFERENCE_FAILURE.
    reference_manifest, manifest_error = _resolve_reference_manifest(
        cli_value=args.reference_manifest,
        config=config,
        audit_root=audit_root,
    )
    if manifest_error is not None:
        return _terminate(
            outcome=RunOutcome.REFERENCE_FAILURE,
            error_class="ReferenceManifestResolutionError",
            error_message=manifest_error,
            audit_root=audit_root,
        )

    session = None
    if args.use_fake_session:
        try:
            from scripts._sleeper_fake_session import FakeSleeperSession

            session = FakeSleeperSession()
        except Exception as exc:  # noqa: BLE001
            return _terminate(
                outcome=RunOutcome.NORMALIZATION_FAILURE,
                error_class=type(exc).__name__,
                error_message=f"cannot load fake session: {exc}",
                audit_root=audit_root,
            )

    # 4. Lock acquire. LockFailure -> LOCK_FAILURE.
    try:
        with advisory_lock(
            audit_root,
            kind=args.kind,
            lock_timeout_seconds=args.lock_timeout_seconds,
        ):
            # 5. Orchestrator construction.
            try:
                orchestrator = _build_orchestrator(
                    config, audit_root, reference_manifest=reference_manifest
                )
            except Exception as exc:  # noqa: BLE001
                return _terminate(
                    outcome=RunOutcome.NORMALIZATION_FAILURE,
                    error_class=type(exc).__name__,
                    error_message=f"cannot construct orchestrator: {exc}",
                    audit_root=audit_root,
                )
            # 6. Run.
            try:
                result = orchestrator.run(
                    session=session,
                    kind=args.kind,
                    forced_observed_at_utc=args.observed_at_utc,
                    forced_snapshot_id=args.snapshot_id,
                )
            except OSError as exc:
                # Rereview 4858328151 §4: an OSError that escapes
                # the orchestrator must NOT cause the CLI to write
                # a second terminal-history row. The orchestrator
                # owns the terminal outcome. If something genuinely
                # raises after the orchestrator's run() began, the
                # CLI surfaces it as PERSISTENCE_FAILURE without
                # calling ``_terminate`` (which would attempt a
                # second history append). The ``orchestrator``
                # local is referenced so the loop variable is not
                # lost.
                print(
                    f"persistence failure (orchestrator escaped): "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                return EXIT_CODES[RunOutcome.PERSISTENCE_FAILURE]
            except Exception as exc:  # noqa: BLE001
                # Non-OSError exceptions from inside the
                # orchestrator are likewise CLI-surfaced without
                # a second terminal-history row.
                print(
                    f"unexpected exception in orchestrator: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                return EXIT_CODES[RunOutcome.NORMALIZATION_FAILURE]
            # Rereview 4852878097: when the orchestrator reports
            # PERSISTENCE_FAILURE (e.g. history-write or status-
            # write failure inside the pipeline), surface the
            # underlying error to stderr so operators see the
            # cause, then return the typed exit code.
            if (
                result.get("run_outcome") == RunOutcome.PERSISTENCE_FAILURE.value
                and result.get("error_class")
            ):
                print(
                    f"persistence failure: {result['error_class']}: "
                    f"{result.get('error_message', '')}",
                    file=sys.stderr,
                )
    except LockFailure as exc:
        return _terminate(
            outcome=RunOutcome.LOCK_FAILURE,
            error_class="LockFailure",
            error_message=str(exc),
            audit_root=audit_root,
        )

    print(json.dumps(result, indent=2, default=str))
    return int(result.get("exit_code", EXIT_CODES[RunOutcome.SUCCESS]))


if __name__ == "__main__":
    raise SystemExit(main())
