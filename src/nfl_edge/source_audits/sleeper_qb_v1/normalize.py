"""QB-only normalization for the Sleeper source audit.

The Sleeper ``/v1/players/nfl?position=QB&active=true`` endpoint is
expected to return only active QBs. As a defensive tripwire the
normalizer also accepts the full player map and filters to QB records
locally, so a future undocumented endpoint change cannot silently
import non-QB rows.

The output schema is the stable list defined in the task spec §6. Field
preservation rules:

* Sleeper returns JSON numbers for IDs (``espn_id``, ``yahoo_id`` ...);
  we coerce them to strings.
* Empty strings, ``None``, and missing keys are all preserved as
  explicit ``None`` cells in the parquet output, so downstream code can
  distinguish "absent" from "explicitly empty".
* The normalized frame is sorted by ``(team, depth_chart_order,
  sleeper_player_id)`` so two runs over the same raw bytes are
  bit-identical.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

import polars as pl

# Schema version is part of every audit artifact so a future change is
# detectable as SCHEMA_DRIFT in the harness.
QB_SNAPSHOT_SCHEMA_VERSION = "qb-snapshot-v1"

# Stable field list. Order matters for parquet round-trips.
QB_SNAPSHOT_FIELDS: tuple[str, ...] = (
    "snapshot_id",
    "fetched_at_utc",
    "sleeper_player_id",
    "gsis_id",
    "espn_id",
    "sportradar_id",
    "yahoo_id",
    "fantasy_data_id",
    "rotowire_id",
    "first_name",
    "last_name",
    "full_name",
    "team",
    "position",
    "active",
    "age",
    "years_exp",
    "roster_status",
    "injury_status",
    "injury_body_part",
    "injury_notes",
    "injury_start_date",
    "practice_participation",
    "practice_description",
    "depth_chart_position",
    "depth_chart_order",
    "search_rank",
    "raw_record_sha256",
)

QB_SNAPSHOT_DTYPES: dict[str, pl.DataType] = {
    "snapshot_id": pl.Utf8,
    "fetched_at_utc": pl.Utf8,
    "sleeper_player_id": pl.Utf8,
    "gsis_id": pl.Utf8,
    "espn_id": pl.Utf8,
    "sportradar_id": pl.Utf8,
    "yahoo_id": pl.Utf8,
    "fantasy_data_id": pl.Utf8,
    "rotowire_id": pl.Utf8,
    "first_name": pl.Utf8,
    "last_name": pl.Utf8,
    "full_name": pl.Utf8,
    "team": pl.Utf8,
    "position": pl.Utf8,
    "active": pl.Boolean,
    "age": pl.Int32,
    "years_exp": pl.Int32,
    "roster_status": pl.Utf8,
    "injury_status": pl.Utf8,
    "injury_body_part": pl.Utf8,
    "injury_notes": pl.Utf8,
    "injury_start_date": pl.Utf8,
    "practice_participation": pl.Utf8,
    "practice_description": pl.Utf8,
    "depth_chart_position": pl.Utf8,
    "depth_chart_order": pl.Int32,
    "search_rank": pl.Int32,
    "raw_record_sha256": pl.Utf8,
}


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    return str(value)


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        # bool is a subclass of int; reject it explicitly.
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


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no", ""}:
            return False
    return None


def normalize_qb_record(
    *,
    snapshot_id: str,
    fetched_at_utc: str,
    sleeper_player_id: str,
    raw_record: Mapping[str, Any],
) -> dict[str, Any]:
    """Project a single Sleeper player map value into the stable
    schema. Accepts any mapping (the docstring example, the live
    response, or a test fixture)."""
    record_hash_source = json.dumps(
        dict(raw_record), sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    import hashlib

    raw_record_sha = hashlib.sha256(record_hash_source).hexdigest()
    return {
        "snapshot_id": snapshot_id,
        "fetched_at_utc": fetched_at_utc,
        "sleeper_player_id": sleeper_player_id,
        "gsis_id": _coerce_str(raw_record.get("gsis_id")),
        "espn_id": _coerce_str(raw_record.get("espn_id")),
        "sportradar_id": _coerce_str(raw_record.get("sportradar_id")),
        "yahoo_id": _coerce_str(raw_record.get("yahoo_id")),
        "fantasy_data_id": _coerce_str(raw_record.get("fantasy_data_id")),
        "rotowire_id": _coerce_str(raw_record.get("rotowire_id")),
        "first_name": _coerce_str(raw_record.get("first_name")),
        "last_name": _coerce_str(raw_record.get("last_name")),
        "full_name": _coerce_str(raw_record.get("full_name")),
        "team": _coerce_str(raw_record.get("team")),
        "position": _coerce_str(raw_record.get("position")),
        "active": _coerce_bool(raw_record.get("active")),
        "age": _coerce_int(raw_record.get("age")),
        "years_exp": _coerce_int(raw_record.get("years_exp")),
        "roster_status": _coerce_str(raw_record.get("status")),
        "injury_status": _coerce_str(raw_record.get("injury_status")),
        "injury_body_part": _coerce_str(raw_record.get("injury_body_part")),
        "injury_notes": _coerce_str(raw_record.get("injury_notes")),
        "injury_start_date": _coerce_str(raw_record.get("injury_start_date")),
        "practice_participation": _coerce_str(raw_record.get("practice_participation")),
        "practice_description": _coerce_str(raw_record.get("practice_description")),
        "depth_chart_position": _coerce_int(raw_record.get("depth_chart_position")),
        "depth_chart_order": _coerce_int(raw_record.get("depth_chart_order")),
        "search_rank": _coerce_int(raw_record.get("search_rank")),
        "raw_record_sha256": raw_record_sha,
    }


def normalize_qb_payload(
    *,
    snapshot_id: str,
    fetched_at_utc: str,
    raw_payload: Mapping[str, Any],
) -> tuple[pl.DataFrame, pl.DataFrame, list[str]]:
    """Normalize a Sleeper player map into the active-QB frame.

    Returns ``(active_frame, inactive_frame, warnings)``. ``raw_payload``
    is the full player map (keyed by Sleeper id). The function filters
    to ``position == "QB"`` and further splits into active vs inactive
    so the audit can flag source drift if the filtered endpoint stops
    being active-only.
    """
    active_rows: list[dict[str, Any]] = []
    inactive_rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for player_id, raw_record in raw_payload.items():
        if not isinstance(raw_record, Mapping):
            warnings.append(f"non-mapping record at {player_id}; skipped")
            continue
        position = _coerce_str(raw_record.get("position"))
        if position != "QB":
            continue
        normalized = normalize_qb_record(
            snapshot_id=snapshot_id,
            fetched_at_utc=fetched_at_utc,
            sleeper_player_id=str(player_id),
            raw_record=raw_record,
        )
        if normalized["active"] is True:
            active_rows.append(normalized)
        else:
            inactive_rows.append(normalized)
    active_frame = _frame_from_rows(active_rows)
    inactive_frame = _frame_from_rows(inactive_rows)
    return active_frame, inactive_frame, warnings


def _frame_from_rows(rows: list[dict[str, Any]]) -> pl.DataFrame:
    if not rows:
        # Build an empty frame with the canonical schema so consumers
        # can always rely on column presence and dtypes.
        return pl.DataFrame(
            {field: pl.Series(name=field, values=[], dtype=dt) for field, dt in QB_SNAPSHOT_DTYPES.items()}
        )
    frame = pl.DataFrame(rows, infer_schema_length=len(rows))
    # Reorder and cast to the canonical schema so dtype drift is impossible.
    frame = frame.select(
        [
            pl.col(field).cast(dt, strict=False).alias(field)
            for field, dt in QB_SNAPSHOT_DTYPES.items()
        ]
    )
    sort_cols = ["team", "depth_chart_order", "sleeper_player_id"]
    return frame.sort(sort_cols, nulls_last=True)
