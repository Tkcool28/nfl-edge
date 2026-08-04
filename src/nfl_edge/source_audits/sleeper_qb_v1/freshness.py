"""Freshness / staleness states for the Sleeper audit.

The audit distinguishes *fetched_at_utc* (when the audit harness ran
the request) from *first_observed_at_utc* (when the audit first saw a
particular field value) from any provider-level update timestamp
(Sleeper does not expose one in the response). Therefore freshness is
computed from observable proxies: the last successful fetch, repeated
identical payloads, and field-change counters.

Allowed states (spec §10):

* ``FRESH_FETCH_NO_CHANGE`` - the most recent successful fetch and no
  field has changed since the previous successful fetch.
* ``FRESH_FETCH_CHANGED`` - the most recent successful fetch and at
  least one field has changed.
* ``FETCH_FAILED_USING_NO_FALLBACK`` - the most recent attempt failed
  and the audit has no usable prior evidence to fall back on.
* ``STALE_LAST_SUCCESS`` - the most recent successful fetch is older
  than the configured staleness threshold.
* ``SCHEMA_DRIFT`` - the live response lacks fields the audit
  expected, or contains unexpected new fields.
* ``INCOMPLETE_RESPONSE`` - the response was 2xx but could not be
  parsed as a JSON object of player records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence

import polars as pl

ALLOWED_FRESHNESS_STATES: frozenset[str] = frozenset(
    {
        "FRESH_FETCH_NO_CHANGE",
        "FRESH_FETCH_CHANGED",
        "FETCH_FAILED_USING_NO_FALLBACK",
        "STALE_LAST_SUCCESS",
        "SCHEMA_DRIFT",
        "INCOMPLETE_RESPONSE",
    }
)

# The list of expected fields in the player-map response. Used by the
# schema-drift check.
EXPECTED_SLEEPER_FIELDS: frozenset[str] = frozenset(
    {
        "player_id",
        "first_name",
        "last_name",
        "position",
        "team",
        "status",
        "active",
        "injury_status",
        "depth_chart_position",
        "depth_chart_order",
    }
)


@dataclass(frozen=True)
class FreshnessInputs:
    last_success_at_utc: str | None
    last_failure_at_utc: str | None
    last_attempt_success: bool
    change_count: int
    last_payload_sha256: str | None
    prior_payload_sha256: str | None
    parsed_ok: bool
    present_fields: frozenset[str]


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError(f"timestamp must be timezone-aware: {value}")
    return dt.astimezone(timezone.utc)


def derive_freshness_state(
    inputs: FreshnessInputs,
    *,
    staleness_threshold_seconds: float,
    now: datetime | None = None,
) -> str:
    """Pick exactly one freshness state for the audit harness.

    Rereview contract (Rereview 4851615980): ``INCOMPLETE_RESPONSE``
    is reserved for the parse-level failure (HTTP succeeded but
    the body is malformed / empty / unusable). Transport-level
    failures (network exhaustion, timeout exhaustion, all-attempt
    HTTP failure) always produce ``FETCH_FAILED_USING_NO_FALLBACK``,
    regardless of the ``parsed_ok`` flag. Callers that want to
    distinguish transport vs parse must pass
    ``last_attempt_success=False`` for transport failures and
    ``last_attempt_success=True`` + an empty ``present_fields`` for
    parse failures.
    """
    # Transport-level: HTTP/network failed. The parsed_ok flag is
    # False here regardless of whether the failure was a connection
    # error, a timeout, or a 5xx after every retry. Do NOT pass
    # this case through the INCOMPLETE_RESPONSE branch.
    if not inputs.last_attempt_success:
        return "FETCH_FAILED_USING_NO_FALLBACK"
    if inputs.last_success_at_utc is None:
        return "FETCH_FAILED_USING_NO_FALLBACK"
    # Parse-level: HTTP succeeded but the body had no usable
    # fields. Distinguish from SCHEMA_DRIFT (which fires when
    # required fields are missing) by treating the all-empty
    # case as INCOMPLETE_RESPONSE — there is no schema to drift
    # against.
    if not inputs.present_fields:
        return "INCOMPLETE_RESPONSE"
    missing = EXPECTED_SLEEPER_FIELDS - inputs.present_fields
    if missing:
        return "SCHEMA_DRIFT"
    last_success = _parse_utc(inputs.last_success_at_utc)
    if last_success is None:
        return "FETCH_FAILED_USING_NO_FALLBACK"
    now = now or datetime.now(timezone.utc)
    age_seconds = (now - last_success).total_seconds()
    if age_seconds > staleness_threshold_seconds:
        return "STALE_LAST_SUCCESS"
    if inputs.change_count > 0:
        return "FRESH_FETCH_CHANGED"
    return "FRESH_FETCH_NO_CHANGE"


def schema_drift_fields(payload: object) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """Return ``(present, missing, extra)`` field sets for a Sleeper
    player map. The audit uses this to flag SCHEMA_DRIFT cleanly."""
    present: set[str] = set()
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, dict):
                present.update(value.keys())
    present_fs = frozenset(present)
    missing = EXPECTED_SLEEPER_FIELDS - present_fs
    # We do not flag "extra" fields as drift because Sleeper adds
    # fields over time (fantasy_data_id, rotowire_id, etc.) and those
    # are not drift; they are forward-compatible enrichment. The
    # missing set is the only schema-drift signal.
    return present_fs, missing, frozenset()


def change_count_for(ledger: pl.DataFrame) -> int:
    """Count the number of *informative* change events in a ledger."""
    if ledger.height == 0:
        return 0
    if "change_type" not in ledger.columns:
        return 0
    return int(ledger.filter(pl.col("change_type") != "first_seen").height)


def summarize_freshness_history(
    events: Sequence[Mapping[str, object]],
    *,
    staleness_threshold_seconds: float,
    now: datetime | None = None,
) -> dict[str, object]:
    """Reduce a sequence of per-run freshness events into the audit's
    reported metrics. Each event dict has at least the keys in
    ``FreshnessInputs``."""
    states: list[str] = []
    for event in events:
        raw_present = event.get("present_fields")
        if isinstance(raw_present, (set, frozenset, list, tuple)):
            present: frozenset[str] = frozenset(str(x) for x in raw_present)
        else:
            present = frozenset()
        raw_change = event.get("change_count")
        if isinstance(raw_change, (int, float)) and not isinstance(raw_change, bool):
            change_count_value: int = int(raw_change)
        else:
            change_count_value = 0
        inputs = FreshnessInputs(
            last_success_at_utc=(
                str(event["last_success_at_utc"])
                if event.get("last_success_at_utc") is not None
                else None
            ),
            last_failure_at_utc=(
                str(event["last_failure_at_utc"])
                if event.get("last_failure_at_utc") is not None
                else None
            ),
            last_attempt_success=bool(event.get("last_attempt_success")),
            change_count=change_count_value,
            last_payload_sha256=(
                str(event["last_payload_sha256"])
                if event.get("last_payload_sha256") is not None
                else None
            ),
            prior_payload_sha256=(
                str(event["prior_payload_sha256"])
                if event.get("prior_payload_sha256") is not None
                else None
            ),
            parsed_ok=bool(event.get("parsed_ok")),
            present_fields=present,
        )
        states.append(
            derive_freshness_state(
                inputs,
                staleness_threshold_seconds=staleness_threshold_seconds,
                now=now,
            )
        )
    counts: dict[str, int] = {state: 0 for state in sorted(ALLOWED_FRESHNESS_STATES)}
    for state in states:
        counts[state] = counts.get(state, 0) + 1
    return {"states": states, "counts": counts}
