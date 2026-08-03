"""Feature schema, key, market, UTC, and fingerprint validation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import polars as pl

MARKET_COLUMNS = frozenset(
    {
        "away_moneyline",
        "home_moneyline",
        "spread_line",
        "total_line",
        "away_spread_odds",
        "home_spread_odds",
        "under_odds",
        "over_odds",
        "closing_odds",
        "closing_probability",
        "current_market_probability",
        "pinnacle_probability",
        "pinnacle_price",
        "draftkings_price",
        "fanduel_price",
        "clv",
    }
)
MARKET_TOKENS = ("moneyline", "spread_odds", "total_line", "closing_", "pinnacle", "draftkings", "fanduel", "_odds")


def find_market_columns(columns: Iterable[str]) -> list[str]:
    found = []
    for column in columns:
        lower = column.lower()
        if lower in MARKET_COLUMNS or any(token in lower for token in MARKET_TOKENS):
            found.append(column)
    return sorted(found)


def assert_no_market_columns(frame_or_columns: pl.DataFrame | Iterable[str]) -> None:
    if isinstance(frame_or_columns, pl.DataFrame):
        columns = list(frame_or_columns.columns)
    else:
        columns = list(frame_or_columns)
    found = find_market_columns(columns)
    if found:
        raise ValueError(f"market columns are prohibited from the model feature matrix: {found}")


def assert_unique_keys(frame: pl.DataFrame, keys: list[str], label: str) -> None:
    missing = [key for key in keys if key not in frame.columns]
    if missing:
        raise ValueError(f"{label} missing key columns: {missing}")
    if any(frame[key].null_count() for key in keys):
        raise ValueError(f"{label} keys contain nulls: {keys}")
    duplicates = frame.group_by(keys).len().filter(pl.col("len") > 1)
    if duplicates.height:
        raise ValueError(f"duplicate {label} rows for keys {keys}: {duplicates.head(5).to_dicts()}")


def assert_utc_columns(frame: pl.DataFrame, columns: list[str], allow_all_null: bool = False) -> None:
    for column in columns:
        if column not in frame.columns:
            raise ValueError(f"missing UTC timestamp column: {column}")
        dtype = frame.schema[column]
        if dtype == pl.Null and allow_all_null:
            continue
        if not isinstance(dtype, pl.datatypes.Datetime) or dtype.time_zone != "UTC":
            raise ValueError(f"{column} must be timezone-aware UTC, got {dtype}")


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()


def schema_fingerprint(frame: pl.DataFrame) -> str:
    return canonical_json_sha256([(name, str(dtype)) for name, dtype in frame.schema.items()])


def logical_frame_fingerprint(frame: pl.DataFrame) -> str:
    ordered = frame.select(frame.columns)
    payload = {
        "schema": [(name, str(dtype)) for name, dtype in ordered.schema.items()],
        "rows": [
            [
                _canonical_value(value)
                for value in row
            ]
            for row in ordered.iter_rows()
        ],
    }
    return canonical_json_sha256(payload)


def _canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("logical fingerprint rejects naive datetime")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Path):
        return value.as_posix()
    return value
