"""Shared primitives for NFL EDGE live backend contracts V1."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping

from nfl_edge.staking_policy_v1 import UNIT_LADDER

PRODUCT_SCHEMA_VERSION = "NFL_EDGE_PRODUCT_API_V1"
USER_STATE_SCHEMA_VERSION = "NFL_EDGE_USER_STATE_V1"
EXACT_OFFER_SCHEMA_VERSION = "NFL_EDGE_EXACT_OFFER_V1"
LIVE_SCORER_SCHEMA_VERSION = "NFL_EDGE_LIVE_SCORER_V1"
QB_RESOLVER_SCHEMA_VERSION = "NFL_EDGE_EXPECTED_QB_RESOLVER_V1"
MARKET_SCHEMA_VERSION = "NFL_EDGE_LIVE_MARKET_V1"

LANES = frozenset({"HIT_RATE", "BALANCED", "VALUE"})
HEADLINE_STATES = frozenset({"BET", "NO_PLAY", "TARGET_ONLY", "SUPPRESSED", "UNSUPPORTED"})
MARKET_TYPES = frozenset({"MONEYLINE", "SPREAD", "TOTAL"})
BOOKS = frozenset({"DRAFTKINGS", "FANDUEL", "PINNACLE"})
RETAIL_BOOKS = frozenset({"DRAFTKINGS", "FANDUEL"})
FRESHNESS_STATES = frozenset({"FRESH", "AGING", "STALE", "UNAVAILABLE"})
GAME_STATUSES = frozenset({"SCHEDULED", "PREGAME", "IN_PROGRESS", "FINAL", "POSTPONED", "CANCELLED"})
SLATE_STATUSES = frozenset({"UPCOMING", "ACTIVE", "COMPLETE", "OFFSEASON"})
QB_RESOLUTION_STATUSES = frozenset(
    {"RESOLVED", "NEW_PLAYER", "UNRESOLVED", "AMBIGUOUS", "MISSING_EVIDENCE", "OVERRIDDEN"}
)
MODEL_OUTPUT_STATUSES = frozenset({
    "AVAILABLE",
    "AVAILABLE_WITH_ROOF_SCENARIOS",
    "UNAVAILABLE",
    "UNSUPPORTED",
    "FAILED",
    "STALE_INPUT",
})
SUPPORT_STATES = frozenset({"SUPPORTED", "PARTIAL", "UNSUPPORTED"})
VERDICTS = frozenset({"BET", "NO", "TARGET_ONLY", "SUPPRESSED", "UNSUPPORTED"})


class ContractValidationError(ValueError):
    """Raised when a payload violates a frozen V1 contract."""


def require_map(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{path} must be an object")
    return value


def require_keys(obj: Mapping[str, Any], keys: set[str] | frozenset[str], path: str) -> None:
    missing = sorted(set(keys) - set(obj))
    if missing:
        raise ContractValidationError(f"{path} missing required field(s): {missing}")


def require_exact_keys(obj: Mapping[str, Any], keys: set[str] | frozenset[str], path: str) -> None:
    """Require exactly the declared keys for a fixed ``additionalProperties: false`` object."""
    expected = set(keys)
    require_keys(obj, expected, path)
    unknown = sorted(set(obj) - expected)
    if unknown:
        raise ContractValidationError(
            f"{path} has unknown field(s): {unknown}; payload is not JSON compliant with the frozen V1 schema"
        )


def require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{path} must be a non-empty string")
    return value


def require_enum(value: Any, allowed: frozenset[str], path: str) -> str:
    text = require_string(value, path)
    if text not in allowed:
        raise ContractValidationError(f"{path} must be one of {sorted(allowed)}")
    return text


def require_number(value: Any, path: str, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{path} must be numeric")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{path} must be finite") from exc
    if not math.isfinite(number):
        raise ContractValidationError(f"{path} must be finite")
    if minimum is not None and number < minimum:
        raise ContractValidationError(f"{path} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise ContractValidationError(f"{path} must be <= {maximum}")
    return number


def validate_probability(value: Any, path: str) -> None:
    if value is not None:
        require_number(value, path, 0.0, 1.0)


def validate_utc_timestamp(value: Any, path: str, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    text = require_string(value, path)
    if not text.endswith("Z"):
        raise ContractValidationError(f"{path} must be RFC3339 UTC and end in Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractValidationError(f"{path} must be a valid RFC3339 timestamp") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ContractValidationError(f"{path} must be UTC")


def validate_warnings(value: Any, path: str) -> None:
    if not isinstance(value, list):
        raise ContractValidationError(f"{path} must be an array")
    for index, warning in enumerate(value):
        require_string(warning, f"{path}[{index}]")


def validate_american_odds(value: Any, path: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{path} must be an integer American price")
    if -99 <= value <= 99:
        raise ContractValidationError(f"{path} must be <= -100 or >= +100")


def validate_units(value: Any, path: str) -> float:
    units = require_number(value, path, 0.0)
    if units not in UNIT_LADDER:
        raise ContractValidationError(f"{path} must be on frozen ladder {UNIT_LADDER}")
    return units
