"""Deterministic identifier helpers for the Sleeper audit.

The audit's snapshot, change, and crosswalk identifiers are derived
purely from the audit-time UTC timestamp so that two attempts that run
within the same second on the same calendar day (in UTC) produce
identical ids and the idempotency tests can rely on that property.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone

_SNAPSHOT_SUFFIX_LEN = 8


def utc_now() -> datetime:
    """Single source of truth for the audit wall clock.

    Centralized so tests can monkeypatch the audit's notion of "now"
    without faking ``datetime.now`` globally.
    """
    return datetime.now(timezone.utc)


def snapshot_id_for(timestamp: datetime, *, kind: str = "scheduled") -> str:
    """Return the canonical snapshot id for ``timestamp``.

    Format: ``sleeper-<kind>-YYYYMMDDTHHMMSSZ-<suffix>`` where the
    suffix is the first 8 hex digits of a UUID5 over the audit scope.
    Two callers computing the id for the same UTC second receive the
    same id only if they pass the same kind; ``kind`` therefore makes
    pregame and postgame ids distinguishable from the twice-daily ones.
    """
    if timestamp.tzinfo is None:
        raise ValueError("snapshot timestamp must be timezone-aware")
    stamp = timestamp.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"nfl-edge/sleeper-qb-audit-v1/{kind}/{stamp}",
    ).hex[:_SNAPSHOT_SUFFIX_LEN]
    return f"sleeper-{kind}-{stamp}-{suffix}"


def change_id_for(snapshot_id: str, player_key: str, field: str) -> str:
    """Deterministic change id so the same logical change is stable
    across replays of the same snapshot pair."""
    payload = f"{snapshot_id}|{player_key}|{field}".encode("utf-8")
    return f"chg-{hashlib.sha1(payload).hexdigest()[:16]}"


def player_identity_key(*, sleeper_player_id: str, gsis_id: str | None) -> str:
    """Stable cross-snapshot identity key.

    Prefer ``gsis_id`` when present (NFL's canonical id), otherwise fall
    back to the Sleeper id. The key must be stable across snapshots
    even when the displayed Sleeper id or name changes.
    """
    if gsis_id:
        return f"gsis:{gsis_id}"
    return f"sleeper:{sleeper_player_id}"


_SLUG_RE = re.compile(r"[^A-Za-z0-9]+")


def safe_slug(value: str) -> str:
    """Restrict a string to a path-safe slug."""
    cleaned = _SLUG_RE.sub("-", value).strip("-")
    return cleaned or "unknown"
