"""Shared prospective-card tracking contracts and deterministic helpers."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping

PUBLICATION_SCHEMA_VERSION = "NFL_EDGE_PROSPECTIVE_CARD_PUBLICATION_V1"
EPISODES_SCHEMA_VERSION = "NFL_EDGE_PROSPECTIVE_CARD_EPISODES_V1"
OFFICIAL_SCHEMA_VERSION = "NFL_EDGE_PROSPECTIVE_CARD_OFFICIAL_V1"
RESULT_SCHEMA_VERSION = "NFL_EDGE_PROSPECTIVE_CARD_RESULT_V1"
SUMMARY_SCHEMA_VERSION = "NFL_EDGE_PROSPECTIVE_CARD_SUMMARY_V1"
BUILDER_VERSION = "prospective-card-tracking-v1"
LANE_ORDER = ("hit_rate", "balanced", "value")
LANE_RANK = {lane: index for index, lane in enumerate(LANE_ORDER)}


class ProspectiveCardError(ValueError):
    """Prospective evidence cannot be derived safely."""


class AppendOnlyViolation(ProspectiveCardError):
    """An immutable prospective path conflicts with prior evidence."""


def parse_utc(value: str) -> datetime:
    text = str(value)
    if not text.endswith("Z"):
        raise ProspectiveCardError(f"timestamp must use canonical UTC Z form: {text!r}")
    try:
        return datetime.fromisoformat(text[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise ProspectiveCardError(f"invalid UTC timestamp: {text!r}") from exc


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:24]}"


def source_product_sha256(product: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(product)).hexdigest()


def exact_offer_tuple(row: Mapping[str, Any]) -> tuple[Any, ...] | None:
    if any(row.get(field) is None for field in ("game_id", "market", "selection", "book", "american_odds")):
        return None
    return (
        row["game_id"],
        row["market"],
        row["selection"],
        row["book"],
        row.get("line"),
        row["american_odds"],
    )


def exact_offer_identity(row: Mapping[str, Any]) -> str | None:
    identity = exact_offer_tuple(row)
    return None if identity is None else stable_id("offer", *identity)


def logical_identity(lane_key: str, row: Mapping[str, Any]) -> str | None:
    if any(row.get(field) is None for field in ("game_id", "market", "normalized_selection")):
        return None
    # Line and price intentionally remain outside episode identity so their movement
    # can be measured while the same logical recommendation remains selected.
    return stable_id(
        "logical",
        lane_key,
        row["game_id"],
        row["market"],
        row["normalized_selection"],
    )


def wager_identity(lane_key: str, row: Mapping[str, Any]) -> str | None:
    if any(row.get(field) is None for field in ("game_id", "market", "normalized_selection")):
        return None
    line = None if str(row["market"]).upper() == "MONEYLINE" else row.get("line")
    return stable_id(
        "wager",
        lane_key,
        row["game_id"],
        row["market"],
        row["normalized_selection"],
        line,
    )


def assert_same_week(publications: list[Mapping[str, Any]]) -> tuple[int, int]:
    if not publications:
        raise ProspectiveCardError("at least one publication is required")
    keys = {(int(item["season"]), int(item["week"])) for item in publications}
    if len(keys) != 1:
        raise ProspectiveCardError(f"mixed season/week publications are not allowed: {sorted(keys)}")
    return next(iter(keys))
