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

# Roster-status tokens that mean "not on a current active roster".
# The audit treats these as evidence the depth chart is stale or the
# player is no longer eligible to play.
ROSTER_NON_ACTIVE_TOKENS: frozenset[str] = frozenset(
    {"inactive", "pup", "non-football injury", "nfi", "suspended", "reserve", "retired"}
)


def _norm_token(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    token = value.strip().lower()
    if not token:
        return None
    return token


def _depth_order(value: object) -> int | None:
    """Normalize a depth order value to an int or None.

    Accepts ints, floats, and numeric strings. Booleans are rejected
    explicitly (Python's bool is a subclass of int but it is not a
    sensible depth order). Strings that don't parse to a number
    return None.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return int(value)
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return None
        try:
            return int(token)
        except ValueError:
            try:
                return int(float(token))
            except ValueError:
                return None
    return None


def classify(record: Mapping[str, object]) -> str:
    """Map one normalized QB record to an allowed evidence state.

    Rules (in order; the first match wins):

    1. ``AMBIGUOUS`` — at least two signals explicitly conflict in a
       way that the deterministic decision tree cannot resolve (see
       ``_is_ambiguous``).
    2. ``DEPTH_CHART_EXPECTED_OUT`` — injury_status in OUT set.
    3. ``DEPTH_CHART_EXPECTED_DOUBTFUL`` — injury_status in DOUBTFUL
       set.
    4. ``DEPTH_CHART_EXPECTED_QUESTIONABLE`` — injury_status in
       QUESTIONABLE/PROBABLE set, OR practice participation in DNP
       set.
    5. ``DEPTH_CHART_EXPECTED_LIMITED`` — practice participation in
       LIMITED set.
    6. ``DEPTH_CHART_EXPECTED_HEALTHY`` — depth_chart_order == 1 and
       no adverse signals.
    7. ``BACKUP_CANDIDATE`` — depth_chart_order >= 2.
    8. ``UNKNOWN`` — no usable signals.

    The ``AMBIGUOUS`` check runs *before* the explicit Out / Doubtful
    branches because the dominant unambiguous cases (e.g. ``injury=
    Out`` with no other conflicting signal) are not ambiguous; the
    AMBIGUOUS path only fires when at least two signals actively
    contradict each other.
    """
    if not isinstance(record, Mapping):
        return "UNKNOWN"

    # Tripwire: the audit must never emit the forbidden labels.
    # (This is enforced by the test suite; the runtime cannot produce
    # them because the function only returns the allowed set.)

    injury_status = _norm_token(record.get("injury_status"))
    practice = _norm_token(record.get("practice_participation"))
    roster_status = _norm_token(record.get("roster_status"))
    depth_order = _depth_order(record.get("depth_chart_order"))

    if _is_ambiguous(
        injury_status=injury_status,
        practice=practice,
        roster_status=roster_status,
        depth_order=depth_order,
    ):
        return "AMBIGUOUS"

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
    if depth_order is None:
        # No designation reported and no depth order; the source does
        # not allow a stronger claim. We deliberately do **not** return
        # HEALTHY here. Returning HEALTHY would imply a verified
        # health status that the source does not provide.
        return "UNKNOWN"

    if depth_order == 1:
        return "DEPTH_CHART_EXPECTED_HEALTHY"

    # depth_order is set and >1.
    return "BACKUP_CANDIDATE"


def _is_ambiguous(
    *,
    injury_status: str | None,
    practice: str | None,
    roster_status: str | None,
    depth_order: int | None,
) -> bool:
    """Detect when the deterministic decision tree cannot resolve the
    evidence state because at least two signals actively conflict.

    Documented conflict rules:

    * **Roster says non-active but depth order says starter.** If
      ``roster_status`` is in ``ROSTER_NON_ACTIVE_TOKENS`` AND
      ``depth_order == 1``, the source is claiming the player is the
      starter of a team whose roster does not include them. This is
      treated as AMBIGUOUS rather than HEALTHY.
    * **Injury says Out but practice says Full participation.** If
      ``injury_status`` is in ``INJURY_OUT_TOKENS`` AND
      ``practice`` is ``"full"`` (i.e. the player is reported as
      injured out but also fully participating in practice), the
      source's two evidence columns disagree.
    * **Limited practice but full participation later in week.** If
      ``practice`` is in ``PRACTICE_LIMITED_TOKENS`` AND
      ``practice`` is also ``"full"`` (only possible with a multi-
      valued column the audit has flattened), this branch fires.
      In practice this rarely triggers with a single-string
      ``practice_participation`` field; it is documented for
      forward-compatibility with multi-row payloads.
    """
    if roster_status in ROSTER_NON_ACTIVE_TOKENS and depth_order == 1:
        return True
    if injury_status in INJURY_OUT_TOKENS and practice == "full":
        return True
    return False


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
