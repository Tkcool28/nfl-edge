"""Snapshot-to-snapshot change detection for the Sleeper QB audit.

Given two normalized QB frames (current and prior), this module emits
a row per changed field per player. A *return* to a previous value is
a new change event because the audit records the *fact* of the field
having changed at this wall-clock moment, not the value trajectory.

The change ledger is the audit's primary tool for answering "did the
source tell us anything new since the last collection?" It must
therefore be append-only and must be derivable from the raw snapshot
bytes alone (so a future re-run of the audit over the same bytes
produces the same ledger).
"""

from __future__ import annotations

from typing import Mapping

import polars as pl

from .ids import change_id_for, player_identity_key

CHANGE_LEDGER_SCHEMA_VERSION = "qb-change-ledger-v1"

CHANGE_LEDGER_FIELDS: tuple[str, ...] = (
    "change_id",
    "player_identity_key",
    "sleeper_player_id",
    "team",
    "field_name",
    "old_value",
    "new_value",
    "prior_snapshot_id",
    "current_snapshot_id",
    "prior_observed_at_utc",
    "first_observed_changed_at_utc",
    "change_type",
)

CHANGE_LEDGER_DTYPES: dict[str, pl.DataType] = {
    "change_id": pl.Utf8,
    "player_identity_key": pl.Utf8,
    "sleeper_player_id": pl.Utf8,
    "team": pl.Utf8,
    "field_name": pl.Utf8,
    "old_value": pl.Utf8,
    "new_value": pl.Utf8,
    "prior_snapshot_id": pl.Utf8,
    "current_snapshot_id": pl.Utf8,
    "prior_observed_at_utc": pl.Utf8,
    "first_observed_changed_at_utc": pl.Utf8,
    "change_type": pl.Utf8,
}

# Per spec §9, the audit tracks changes in at least these fields.
TRACKED_FIELDS: tuple[str, ...] = (
    "team",
    "active",
    "roster_status",
    "injury_status",
    "injury_body_part",
    "injury_start_date",
    "practice_participation",
    "depth_chart_position",
    "depth_chart_order",
    "evidence_state",
)


def _stringify(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def detect_changes(
    *,
    current_frame: pl.DataFrame,
    current_evidence_frame: pl.DataFrame,
    prior_frame: pl.DataFrame | None,
    prior_evidence_frame: pl.DataFrame | None,
    current_snapshot_id: str,
    current_observed_at_utc: str,
    prior_snapshot_id: str | None = None,
    prior_observed_at_utc: str | None = None,
) -> pl.DataFrame:
    """Compute the change ledger between two snapshots.

    ``prior_frame`` may be ``None`` for the very first snapshot of a
    fresh audit run. In that case every tracked field for every QB is
    recorded as a "first_seen" change so the first ledger is
    informative rather than empty.
    """
    if "snapshot_id" not in current_frame.columns:
        raise ValueError("current_frame must contain snapshot_id")
    # Attach evidence state to current frame for change tracking.
    current_with_evidence = current_frame.join(
        current_evidence_frame.select(
            ["sleeper_player_id", "evidence_state"]
        ),
        on="sleeper_player_id",
        how="left",
    )

    def _key_for_row(row: Mapping[str, object]) -> str:
        return player_identity_key(
            sleeper_player_id=str(row.get("sleeper_player_id", "")),
            gsis_id=row.get("gsis_id") if isinstance(row.get("gsis_id"), str) else None,
        )

    current_records: dict[str, dict[str, object]] = {}
    for row in current_with_evidence.to_dicts():
        pid = str(row.get("sleeper_player_id", ""))
        row["player_identity_key"] = _key_for_row(row)
        current_records[pid] = row

    prior_records: dict[str, dict[str, object]] = {}
    if prior_frame is not None and prior_frame.height > 0:
        prior_with_evidence = prior_frame
        if prior_evidence_frame is not None and prior_evidence_frame.height > 0:
            prior_with_evidence = prior_frame.join(
                prior_evidence_frame.select(["sleeper_player_id", "evidence_state"]),
                on="sleeper_player_id",
                how="left",
            )
        for row in prior_with_evidence.to_dicts():
            pid = str(row.get("sleeper_player_id", ""))
            row["player_identity_key"] = _key_for_row(row)
            prior_records[pid] = row

    rows: list[dict[str, object]] = []
    all_pids = set(current_records) | set(prior_records)
    for pid in sorted(all_pids):
        current = current_records.get(pid)
        prior = prior_records.get(pid)
        if prior is None and current is not None:
            # First time we see this QB.
            for field in TRACKED_FIELDS:
                if field == "evidence_state":
                    new_val = current.get("evidence_state")
                else:
                    new_val = current.get(field)
                if new_val is None or _stringify(new_val) == "":
                    # Don't emit first-seen events for absent fields.
                    continue
                rows.append(
                    {
                        "change_id": change_id_for(current_snapshot_id, str(current["player_identity_key"]), field),
                        "player_identity_key": str(current["player_identity_key"]),
                        "sleeper_player_id": pid,
                        "team": current.get("team"),
                        "field_name": field,
                        "old_value": None,
                        "new_value": _stringify(new_val),
                        "prior_snapshot_id": prior_snapshot_id,
                        "current_snapshot_id": current_snapshot_id,
                        "prior_observed_at_utc": prior_observed_at_utc,
                        "first_observed_changed_at_utc": current_observed_at_utc,
                        "change_type": "first_seen",
                    }
                )
            continue
        if current is None and prior is not None:
            # QB dropped off the active list. Emit a single tombstone
            # change for tracking purposes.
            rows.append(
                {
                    "change_id": change_id_for(
                        current_snapshot_id,
                        str(prior.get("player_identity_key", pid)),
                        "active_presence",
                    ),
                    "player_identity_key": str(prior.get("player_identity_key", pid)),
                    "sleeper_player_id": pid,
                    "team": prior.get("team"),
                    "field_name": "active_presence",
                    "old_value": "present",
                    "new_value": "absent",
                    "prior_snapshot_id": prior_snapshot_id,
                    "current_snapshot_id": current_snapshot_id,
                    "prior_observed_at_utc": prior_observed_at_utc,
                    "first_observed_changed_at_utc": current_observed_at_utc,
                    "change_type": "dropped",
                }
            )
            continue
        if current is None or prior is None:
            continue
        # Both snapshots have the row; compare tracked fields.
        for field in TRACKED_FIELDS:
            old_value = prior.get(field) if field != "evidence_state" else prior.get("evidence_state")
            new_value = current.get(field) if field != "evidence_state" else current.get("evidence_state")
            old_str = _stringify(old_value)
            new_str = _stringify(new_value)
            if old_str == new_str:
                continue
            change_type = "changed"
            if old_str == "" and new_str != "":
                change_type = "populated"
            elif new_str == "" and old_str != "":
                change_type = "cleared"
            rows.append(
                {
                    "change_id": change_id_for(
                        current_snapshot_id, str(current["player_identity_key"]), field
                    ),
                    "player_identity_key": str(current["player_identity_key"]),
                    "sleeper_player_id": pid,
                    "team": current.get("team"),
                    "field_name": field,
                    "old_value": old_str if old_str else None,
                    "new_value": new_str if new_str else None,
                    "prior_snapshot_id": prior_snapshot_id,
                    "current_snapshot_id": current_snapshot_id,
                    "prior_observed_at_utc": prior_observed_at_utc,
                    "first_observed_changed_at_utc": current_observed_at_utc,
                    "change_type": change_type,
                }
            )
    if not rows:
        return pl.DataFrame(
            {
                field: pl.Series(name=field, values=[], dtype=dt)
                for field, dt in CHANGE_LEDGER_DTYPES.items()
            }
        )
    frame = pl.DataFrame(rows, infer_schema_length=len(rows))
    frame = frame.select(
        [
            pl.col(field).cast(dt, strict=False).alias(field)
            for field, dt in CHANGE_LEDGER_DTYPES.items()
        ]
    )
    return frame.sort(
        ["team", "sleeper_player_id", "field_name"], nulls_last=True
    )
