"""Audit-only QB evidence-state classification.

Allowed states (spec §8):

* ``DEPTH_CHART_EXPECTED_HEALTHY``
* ``DEPTH_CHART_EXPECTED_LIMITED``
* ``DEPTH_CHART_EXPECTED_QUESTIONABLE``
* ``DEPTH_CHART_EXPECTED_DOUBTFUL``
* ``DEPTH_CHART_EXPECTED_OUT``
* ``BACKUP_CANDIDATE``
* ``AMBIGUOUS``
* ``UNKNOWN``

Forbidden labels (must never be emitted by this module):

* ``CONFIRMED_STARTER``
* ``CONFIRMED_ACTIVE``

The classifier is a pure function of a single normalized QB record. It
must be deterministic and side-effect free so the test suite can
exhaustively cover the decision tree.
"""

from __future__ import annotations

from typing import Mapping

ALLOWED_EVIDENCE_STATES: frozenset[str] = frozenset(
    {
        "DEPTH_CHART_EXPECTED_HEALTHY",
        "DEPTH_CHART_EXPECTED_LIMITED",
        "DEPTH_CHART_EXPECTED_QUESTIONABLE",
        "DEPTH_CHART_EXPECTED_DOUBTFUL",
        "DEPTH_CHART_EXPECTED_OUT",
        "BACKUP_CANDIDATE",
        "AMBIGUOUS",
        "UNKNOWN",
    }
)

FORBIDDEN_LABELS: frozenset[str] = frozenset({"CONFIRMED_STARTER", "CONFIRMED_ACTIVE"})

# Injury status token set, normalized for comparison. Sleeper's docs
# use capitalized strings ("Out", "Questionable", "Probable", "Doubtful",
# "IR"); we also accept lower-case for forward compatibility.
INJURY_OUT_TOKENS: frozenset[str] = frozenset({"out", "ir", "injured reserve", "pup"})
INJURY_DOUBTFUL_TOKENS: frozenset[str] = frozenset({"doubtful"})
INJURY_QUESTIONABLE_TOKENS: frozenset[str] = frozenset({"questionable", "probable"})

# Practice participation tokens. Sleeper's documented vocabulary
# includes "Full", "Limited", "DNP" (did not participate).
PRACTICE_LIMITED_TOKENS: frozenset[str] = frozenset({"limited", "lp"})
PRACTICE_DNP_TOKENS: frozenset[str] = frozenset({"dnp", "did not participate"})


def _norm_token(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    token = value.strip().lower()
    if not token:
        return None
    return token


def classify(record: Mapping[str, object]) -> str:
    """Map one normalized QB record to an allowed evidence state.

    Rules (in order):

    1. If injury_status is in OUT set -> DEPTH_CHART_EXPECTED_OUT.
    2. If injury_status is in DOUBTFUL set -> DEPTH_CHART_EXPECTED_DOUBTFUL.
    3. If injury_status is in QUESTIONABLE/PROBABLE set OR practice in
       LIMITED set -> DEPTH_CHART_EXPECTED_LIMITED if practice is the
       only signal, else DEPTH_CHART_EXPECTED_QUESTIONABLE.
    4. If depth_chart_order is missing or null and there is no usable
       evidence -> UNKNOWN.
    5. If depth_chart_order is not 1 (including ``None``) -> BACKUP_CANDIDATE.
    6. If depth_chart_order is 1 and no adverse status reported ->
       DEPTH_CHART_EXPECTED_HEALTHY.
    7. If we cannot decide -> AMBIGUOUS.
    """
    if not isinstance(record, Mapping):
        return "UNKNOWN"

    # Tripwire: the audit must never emit the forbidden labels.
    # (This is enforced by the test suite; the runtime cannot produce
    # them because the function only returns the allowed set.)

    injury_status = _norm_token(record.get("injury_status"))
    practice = _norm_token(record.get("practice_participation"))
    depth_order = record.get("depth_chart_order")

    if injury_status in INJURY_OUT_TOKENS:
        return "DEPTH_CHART_EXPECTED_OUT"
    if injury_status in INJURY_DOUBTFUL_TOKENS:
        return "DEPTH_CHART_EXPECTED_DOUBTFUL"
    if injury_status in INJURY_QUESTIONABLE_TOKENS:
        return "DEPTH_CHART_EXPECTED_QUESTIONABLE"
    if practice in PRACTICE_LIMITED_TOKENS:
        return "DEPTH_CHART_EXPECTED_LIMITED"
    if practice in PRACTICE_DNP_TOKENS:
        return "DEPTH_CHART_EXPECTED_QUESTIONABLE"

    # No injury or practice signal. Decide by depth chart order.
    if depth_order is None or depth_order == "":
        # No designation reported and no depth order; the source does
        # not allow a stronger claim. We deliberately do **not** return
        # HEALTHY here. Returning HEALTHY would imply a verified
        # health status that the source does not provide.
        return "UNKNOWN"

    if depth_order == 1:
        return "DEPTH_CHART_EXPECTED_HEALTHY"

    # depth_order is set and >1.
    return "BACKUP_CANDIDATE"


def validate_no_forbidden_labels(states: list[str]) -> None:
    """Defensive: raise if any forbidden label slipped in. Used by tests
    and the report writer to keep the audit honest."""
    bad = [s for s in states if s in FORBIDDEN_LABELS]
    if bad:
        raise ValueError(f"forbidden evidence-state label(s): {bad!r}")


EVIDENCE_STATE_DESCRIPTIONS: dict[str, str] = {
    "DEPTH_CHART_EXPECTED_HEALTHY": (
        "Depth order 1 and no adverse status reported. NOT a verified"
        " health claim; just absence of reported injury or limited practice."
    ),
    "DEPTH_CHART_EXPECTED_LIMITED": (
        "Depth order 1 and Limited practice participation; not a"
        " starter-out classification."
    ),
    "DEPTH_CHART_EXPECTED_QUESTIONABLE": (
        "Questionable or Probable injury status, or Did Not Participate"
        " in practice."
    ),
    "DEPTH_CHART_EXPECTED_DOUBTFUL": "Doubtful injury status.",
    "DEPTH_CHART_EXPECTED_OUT": "Out, IR, or PUP; effectively not playing.",
    "BACKUP_CANDIDATE": "Depth order >= 2 or otherwise not the chart leader.",
    "AMBIGUOUS": "Conflicting or partial evidence; no defensible deterministic label.",
    "UNKNOWN": "No usable evidence; no designation reported, no depth order, or required fields are null.",
}
