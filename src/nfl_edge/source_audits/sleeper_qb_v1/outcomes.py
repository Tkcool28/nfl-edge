"""Typed run-outcome contract for the Sleeper QB audit.

Every bounded audit run terminates in exactly one of the seven
outcomes below. The CLI maps outcomes to exit codes so that
``systemd`` and any operator-side tooling can distinguish a
transport failure from a parsing failure from a persistence failure
from a successful run.

Outcome -> exit code
--------------------

* ``SUCCESS`` -> 0
* ``TRANSPORT_FAILURE`` -> 10
* ``INCOMPLETE_RESPONSE`` -> 11
* ``NORMALIZATION_FAILURE`` -> 12
* ``PERSISTENCE_FAILURE`` -> 13
* ``LOCK_FAILURE`` -> 20
* ``REFERENCE_FAILURE`` -> 21

The seven categories are the audit's *only* allowed outcomes. New
failure modes must be folded into one of the existing categories or
the schema_version is bumped and downstream tooling is updated.

The "FETCH_FAILED_USING_NO_FALLBACK" and "INCOMPLETE_RESPONSE"
freshness tokens are intentionally *separate* from the run-outcome
enumeration. A run can complete with ``TRANSPORT_FAILURE`` while
still writing a meaningful freshness state for the live-audit report;
the freshness vocabulary is the audit's view of the *source*, and
the run-outcome enumeration is the audit's view of *itself*.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import polars as pl


class RunOutcome(str, Enum):
    """The seven allowed terminal outcomes of a single audit run."""

    SUCCESS = "SUCCESS"
    TRANSPORT_FAILURE = "TRANSPORT_FAILURE"
    INCOMPLETE_RESPONSE = "INCOMPLETE_RESPONSE"
    NORMALIZATION_FAILURE = "NORMALIZATION_FAILURE"
    PERSISTENCE_FAILURE = "PERSISTENCE_FAILURE"
    LOCK_FAILURE = "LOCK_FAILURE"
    REFERENCE_FAILURE = "REFERENCE_FAILURE"


# Rereview 4852338912: terminal run history is a durable parquet file
# (``run_history.parquet``) — not append-only JSONL. Each invocation
# writes exactly one row. ``success`` is derived from
# ``outcome == SUCCESS`` and is never derived from a single HTTP
# attempt.
#
# Rereview 4851615980 authoritativeness (Rereview 4851615980 / current
# pass): ``run_history.parquet`` is the ONLY authoritative terminal
# commit ledger. ``payload_sha256`` and ``raw_payload_path`` are
# carried so prior successful snapshots can be reconstructed from
# history alone — no derived cache file is read for correctness.
RUN_HISTORY_ROW_DTYPES: dict[str, pl.DataType] = {
    "snapshot_id": pl.Utf8,
    "observed_at_utc": pl.Utf8,
    "finished_at_utc": pl.Utf8,
    "outcome": pl.Utf8,
    "error_class": pl.Utf8,
    "error_message": pl.Utf8,
    "error_token": pl.Utf8,
    "exit_code": pl.Int32,
    "kind": pl.Utf8,
    "attempt_count": pl.Int32,
    "success": pl.Boolean,
    # Carried on every committed row; nullable for runs that did not
    # produce a successful payload (e.g. transport failures).
    "payload_sha256": pl.Utf8,
    "raw_payload_path": pl.Utf8,
}


# CLI exit codes per outcome. Every failure category exits nonzero.
EXIT_CODES: dict[RunOutcome, int] = {
    RunOutcome.SUCCESS: 0,
    RunOutcome.TRANSPORT_FAILURE: 10,
    RunOutcome.INCOMPLETE_RESPONSE: 11,
    RunOutcome.NORMALIZATION_FAILURE: 12,
    RunOutcome.PERSISTENCE_FAILURE: 13,
    RunOutcome.LOCK_FAILURE: 20,
    RunOutcome.REFERENCE_FAILURE: 21,
}


# Canonical error token strings surfaced to operators. These are the
# tokens that the live-audit markdown report quotes verbatim.
ERROR_TOKENS: dict[RunOutcome, str] = {
    RunOutcome.TRANSPORT_FAILURE: "FETCH_FAILED_USING_NO_FALLBACK",
    RunOutcome.INCOMPLETE_RESPONSE: "INCOMPLETE_RESPONSE",
    RunOutcome.NORMALIZATION_FAILURE: "NORMALIZATION_FAILURE",
    RunOutcome.PERSISTENCE_FAILURE: "PERSISTENCE_FAILURE",
    RunOutcome.LOCK_FAILURE: "LOCK_FAILURE",
    RunOutcome.REFERENCE_FAILURE: "REFERENCE_FAILURE",
}


@dataclass(frozen=True)
class RunOutcomeRecord:
    """The full record of one terminal outcome.

    The audit pipeline writes one of these to
    ``latest_run_status.json`` *every* run, success or failure, so a
    failed run always replaces a previous successful one.

    Rereview contract (Rereview 4851615980): the record also
    carries ``kind``, ``attempt_count``, and ``success`` so the
    terminal run history (one row per run in
    ``run_history.parquet``) is the single source of truth for the
    rolling metrics. ``success`` is derived from
    ``outcome == RunOutcome.SUCCESS`` and never from a single
    HTTP attempt.
    """

    outcome: RunOutcome
    snapshot_id: str | None
    observed_at_utc: str | None
    finished_at_utc: str
    error_class: str | None
    error_message: str | None
    error_token: str | None
    exit_code: int
    kind: str | None = None
    attempt_count: int = 0
    # Carried on every committed row so prior successful snapshots
    # can be reconstructed from history alone. Nullable for runs
    # without a successful payload.
    payload_sha256: str | None = None
    raw_payload_path: str | None = None

    @property
    def success(self) -> bool:
        """A run is successful iff its terminal outcome is SUCCESS.

        This property is the ONLY place in the audit that decides
        run success. Rolling metrics must derive
        ``successful_run_count`` from ``outcome == SUCCESS`` and
        count every other outcome as a failed run, regardless of
        whether any single HTTP attempt returned 2xx.
        """
        return self.outcome == RunOutcome.SUCCESS

    def to_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome.value,
            "snapshot_id": self.snapshot_id,
            "observed_at_utc": self.observed_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "error_class": self.error_class,
            "error_message": self.error_message,
            "error_token": self.error_token,
            "exit_code": self.exit_code,
            "kind": self.kind,
            "attempt_count": self.attempt_count,
            "success": self.success,
            "payload_sha256": self.payload_sha256,
            "raw_payload_path": self.raw_payload_path,
        }


def exit_code_for(outcome: RunOutcome) -> int:
    """Return the canonical exit code for ``outcome``."""
    return EXIT_CODES[outcome]


def error_token_for(outcome: RunOutcome) -> str:
    """Return the canonical error token for ``outcome`` (used in
    the live-audit report). ``SUCCESS`` returns an empty string."""
    return ERROR_TOKENS[outcome]
