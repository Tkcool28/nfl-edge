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


class RunOutcome(str, Enum):
    """The seven allowed terminal outcomes of a single audit run."""

    SUCCESS = "SUCCESS"
    TRANSPORT_FAILURE = "TRANSPORT_FAILURE"
    INCOMPLETE_RESPONSE = "INCOMPLETE_RESPONSE"
    NORMALIZATION_FAILURE = "NORMALIZATION_FAILURE"
    PERSISTENCE_FAILURE = "PERSISTENCE_FAILURE"
    LOCK_FAILURE = "LOCK_FAILURE"
    REFERENCE_FAILURE = "REFERENCE_FAILURE"


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
    """

    outcome: RunOutcome
    snapshot_id: str | None
    observed_at_utc: str | None
    finished_at_utc: str
    error_class: str | None
    error_message: str | None
    error_token: str | None
    exit_code: int

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
        }


def exit_code_for(outcome: RunOutcome) -> int:
    """Return the canonical exit code for ``outcome``."""
    return EXIT_CODES[outcome]


def error_token_for(outcome: RunOutcome) -> str:
    """Return the canonical error token for ``outcome`` (used in
    the live-audit report). ``SUCCESS`` returns an empty string."""
    return ERROR_TOKENS[outcome]
