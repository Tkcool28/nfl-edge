"""Freshness, Sleeper/QB and live market contract validation V1."""
from __future__ import annotations

from typing import Any

from nfl_edge.contracts.common_v1 import (
    BOOKS,
    FRESHNESS_STATES,
    MARKET_TYPES,
    QB_RESOLUTION_STATUSES,
    ContractValidationError,
    require_enum,
    require_keys,
    require_map,
    require_number,
    require_string,
    validate_american_odds,
    validate_utc_timestamp,
)


def validate_freshness(value: Any, path: str = "freshness") -> None:
    obj = require_map(value, path)
    require_keys(obj, {"state", "observed_at_utc", "age_seconds", "threshold_seconds"}, path)
    state = require_enum(obj["state"], FRESHNESS_STATES, f"{path}.state")
    if state == "UNAVAILABLE":
        validate_utc_timestamp(obj["observed_at_utc"], f"{path}.observed_at_utc", nullable=True)
        if obj["age_seconds"] is not None:
            require_number(obj["age_seconds"], f"{path}.age_seconds", 0.0)
    else:
        validate_utc_timestamp(obj["observed_at_utc"], f"{path}.observed_at_utc")
        require_number(obj["age_seconds"], f"{path}.age_seconds", 0.0)
    require_number(obj["threshold_seconds"], f"{path}.threshold_seconds", 0.0)


def validate_qb_context(value: Any, path: str) -> None:
    obj = require_map(value, path)
    required = {
        "team", "game_id", "expected_starter", "sleeper_player_id", "canonical_qb_id", "gsis_id",
        "depth_designation", "injury_status", "source", "source_snapshot_at_utc", "provenance_id",
        "resolution_status", "freshness", "warning_state", "last_changed_at_utc",
    }
    require_keys(obj, required, path)
    require_string(obj["team"], f"{path}.team")
    require_string(obj["game_id"], f"{path}.game_id")
    resolution = require_enum(obj["resolution_status"], QB_RESOLUTION_STATUSES, f"{path}.resolution_status")
    require_string(obj["source"], f"{path}.source")
    require_string(obj["provenance_id"], f"{path}.provenance_id")
    validate_freshness(obj["freshness"], f"{path}.freshness")
    validate_utc_timestamp(obj["source_snapshot_at_utc"], f"{path}.source_snapshot_at_utc", nullable=True)
    validate_utc_timestamp(obj["last_changed_at_utc"], f"{path}.last_changed_at_utc", nullable=True)
    for field in (
        "expected_starter", "sleeper_player_id", "canonical_qb_id", "gsis_id",
        "depth_designation", "injury_status", "warning_state",
    ):
        if obj[field] is not None:
            require_string(obj[field], f"{path}.{field}")
    if resolution in {"RESOLVED", "OVERRIDDEN"} and (
        obj["expected_starter"] is None or obj["canonical_qb_id"] is None
    ):
        raise ContractValidationError(f"{path} resolved QB requires expected_starter and canonical_qb_id")


def validate_market_offer(value: Any, path: str = "offer") -> None:
    obj = require_map(value, path)
    required = {
        "offer_id", "provider", "game_id", "sportsbook", "market_type", "selection", "line", "price",
        "snapshot_at_utc", "normalized_selection", "freshness",
    }
    require_keys(obj, required, path)
    for field in ("offer_id", "provider", "game_id", "selection", "normalized_selection"):
        require_string(obj[field], f"{path}.{field}")
    require_enum(obj["sportsbook"], BOOKS, f"{path}.sportsbook")
    market = require_enum(obj["market_type"], MARKET_TYPES, f"{path}.market_type")
    if market == "MONEYLINE":
        if obj["line"] is not None:
            raise ContractValidationError(f"{path}.line must be null for MONEYLINE")
    else:
        require_number(obj["line"], f"{path}.line")
    validate_american_odds(obj["price"], f"{path}.price")
    validate_utc_timestamp(obj["snapshot_at_utc"], f"{path}.snapshot_at_utc")
    validate_freshness(obj["freshness"], f"{path}.freshness")


def validate_market_board(value: Any, game_id: str, path: str) -> None:
    board = require_map(value, path)
    require_keys(board, {"moneyline", "spread", "total"}, path)
    for market_key, market_type in (("moneyline", "MONEYLINE"), ("spread", "SPREAD"), ("total", "TOTAL")):
        books = require_map(board[market_key], f"{path}.{market_key}")
        unknown = set(books) - BOOKS
        if unknown:
            raise ContractValidationError(f"{path}.{market_key} has unknown book(s): {sorted(unknown)}")
        for book, offers in books.items():
            if not isinstance(offers, list):
                raise ContractValidationError(f"{path}.{market_key}.{book} must be an array")
            seen: set[str] = set()
            for index, offer in enumerate(offers):
                offer_path = f"{path}.{market_key}.{book}[{index}]"
                validate_market_offer(offer, offer_path)
                if offer["game_id"] != game_id or offer["market_type"] != market_type or offer["sportsbook"] != book:
                    raise ContractValidationError(f"{offer_path} identity does not match its game/market/book bucket")
                if offer["offer_id"] in seen:
                    raise ContractValidationError(f"{offer_path}.offer_id duplicates an exact offer")
                seen.add(str(offer["offer_id"]))
