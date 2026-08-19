"""Persistent acquisition ledger and immutable raw-payload store.

Design guarantees (Task 05E-C3 §H, §I, §J):

* **RAW immutability** — ``write_raw_immutable`` writes to a temp file in the
  same directory, ``fsync``es it, computes the SHA-256, then ``os.replace``s
  into the final path. It refuses to overwrite an existing final path, so a
  completed raw snapshot can never be silently rewritten by a later run.

* **Idempotent resume** — ``is_request_complete`` returns True only when an
  accepted ledger row exists *and* the raw file exists *and* its on-disk
  SHA-256 matches the ledger's recorded hash. The runner skips any
  ``request_plan_id`` that is complete, so a crash mid-run never causes a
  re-spend on already-verified snapshots.

* **Secret safety** — the ledger records request URLs only after secret
  redaction (the ``apiKey`` value is replaced), and never stores keys.
"""

from __future__ import annotations

import hashlib
import io
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import polars as pl

from .manifest import LEDGER_PATH, RESPONSE_COST_HEADER

LEDGER_SCHEMA: dict[str, pl.DataType] = {
    "request_plan_id": pl.Utf8,
    "season": pl.Int32,
    "cluster_id": pl.Utf8,
    "requested_target_timestamp_utc": pl.Utf8,
    "expected_earliest_kickoff_utc": pl.Utf8,
    "target_game_ids": pl.Utf8,
    "actual_snapshot_timestamp_utc": pl.Utf8,
    "previous_snapshot_timestamp_utc": pl.Utf8,
    "next_snapshot_timestamp_utc": pl.Utf8,
    "http_status": pl.Int32,
    "x_requests_last": pl.Int32,
    "x_requests_used": pl.Int32,
    "x_requests_remaining": pl.Int32,
    "response_content_sha256": pl.Utf8,
    "acquisition_timestamp_utc": pl.Utf8,
    "requested_bookmaker_keys": pl.Utf8,
    "requested_markets": pl.Utf8,
    "raw_payload_path": pl.Utf8,
    "request_url_redacted": pl.Utf8,
    "success": pl.Boolean,
    "error_class": pl.Utf8,
    "error_message": pl.Utf8,
}

# Column names that must never carry the API key.
_FORBIDDEN_CONTENT = ("ODDS_API_KEY", "authorization", "x-api-key")


@dataclass(frozen=True)
class LedgerEntry:
    """One completed-or-failed acquisition attempt (see §H metadata)."""

    request_plan_id: str
    season: int
    cluster_id: str
    requested_target_timestamp_utc: str
    expected_earliest_kickoff_utc: str
    target_game_ids: str
    actual_snapshot_timestamp_utc: str | None
    previous_snapshot_timestamp_utc: str | None
    next_snapshot_timestamp_utc: str | None
    http_status: int | None
    x_requests_last: int | None
    x_requests_used: int | None
    x_requests_remaining: int | None
    response_content_sha256: str | None
    acquisition_timestamp_utc: str
    requested_bookmaker_keys: str
    requested_markets: str
    raw_payload_path: str | None
    request_url_redacted: str
    success: bool
    error_class: str | None
    error_message: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_plan_id": self.request_plan_id,
            "season": self.season,
            "cluster_id": self.cluster_id,
            "requested_target_timestamp_utc": self.requested_target_timestamp_utc,
            "expected_earliest_kickoff_utc": self.expected_earliest_kickoff_utc,
            "target_game_ids": self.target_game_ids,
            "actual_snapshot_timestamp_utc": self.actual_snapshot_timestamp_utc,
            "previous_snapshot_timestamp_utc": self.previous_snapshot_timestamp_utc,
            "next_snapshot_timestamp_utc": self.next_snapshot_timestamp_utc,
            "http_status": self.http_status,
            "x_requests_last": self.x_requests_last,
            "x_requests_used": self.x_requests_used,
            "x_requests_remaining": self.x_requests_remaining,
            "response_content_sha256": self.response_content_sha256,
            "acquisition_timestamp_utc": self.acquisition_timestamp_utc,
            "requested_bookmaker_keys": self.requested_bookmaker_keys,
            "requested_markets": self.requested_markets,
            "raw_payload_path": self.raw_payload_path,
            "request_url_redacted": self.request_url_redacted,
            "success": self.success,
            "error_class": self.error_class,
            "error_message": self.error_message,
        }


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    """Write ``data`` atomically (temp + fsync + ``os.replace``)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def sha256_of_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_raw_immutable(raw_path: str | Path, data: bytes) -> str:
    """Persist raw bytes immutably; returns their SHA-256.

    Raises :class:`FileExistsError` if ``raw_path`` already exists so a raw
    snapshot is never rewritten.
    """
    raw_path = Path(raw_path)
    if raw_path.exists():
        raise FileExistsError(f"refusing to overwrite immutable raw: {raw_path}")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = raw_path.with_name(f".{raw_path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # Hash the exact bytes that will be persisted.
        digest = hashlib.sha256(data).hexdigest()
        os.replace(tmp, raw_path)
        dir_fd = os.open(str(raw_path.parent), os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        return digest
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def append_ledger_entry(entry: LedgerEntry, ledger_path: str | Path = LEDGER_PATH) -> None:
    """Atomically append one ledger row (never a partial write)."""
    ledger_path = Path(ledger_path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pl.DataFrame([entry.as_dict()], infer_schema_length=1).with_columns(
        [
            pl.col("http_status").cast(pl.Int32, strict=False),
            pl.col("season").cast(pl.Int32, strict=False),
            pl.col("x_requests_last").cast(pl.Int32, strict=False),
            pl.col("x_requests_used").cast(pl.Int32, strict=False),
            pl.col("x_requests_remaining").cast(pl.Int32, strict=False),
        ]
    )
    if ledger_path.exists() and ledger_path.stat().st_size > 0:
        existing = pl.read_parquet(ledger_path)
        combined = pl.concat([existing, frame], how="diagonal_relaxed")
    else:
        combined = frame
    buf = io.BytesIO()
    combined.write_parquet(buf)
    atomic_write_bytes(ledger_path, buf.getvalue())


def load_ledger(ledger_path: str | Path = LEDGER_PATH) -> pl.DataFrame:
    path = Path(ledger_path)
    if not path.exists() or path.stat().st_size == 0:
        return pl.DataFrame(schema=LEDGER_SCHEMA)
    return pl.read_parquet(path)


def is_request_complete(
    request_plan_id: str,
    *,
    ledger_path: str | Path = LEDGER_PATH,
    raw_root: str | Path,
) -> bool:
    """True iff a *verified* successful raw snapshot exists for the request.

    Requires all of: a ledger row with ``success``; a ``raw_payload_path``;
    the raw file exists on disk; and the on-disk SHA-256 equals the ledger's
    recorded ``response_content_sha256``.
    """
    ledger_path = Path(ledger_path)
    if not ledger_path.exists() or ledger_path.stat().st_size == 0:
        return False
    matching = load_ledger(ledger_path).filter(
        (pl.col("request_plan_id") == request_plan_id) & (pl.col("success") == True)  # noqa: E712
    )
    if matching.height == 0:
        return False
    row = matching.row(0, named=True)
    raw_path = row.get("raw_payload_path")
    recorded_hash = row.get("response_content_sha256")
    if not raw_path or not recorded_hash:
        return False
    raw_file = Path(raw_root) / raw_path if not Path(raw_path).is_absolute() else Path(raw_path)
    if not raw_file.exists():
        return False
    return sha256_of_file(raw_file) == recorded_hash


def completed_request_ids(
    *,
    ledger_path: str | Path = LEDGER_PATH,
    raw_root: str | Path,
) -> set[str]:
    """Set of request_plan_ids with verified completed raw snapshots."""
    ids: set[str] = set()
    for rid in load_ledger(ledger_path).get_column("request_plan_id").unique().to_list():
        if is_request_complete(rid, ledger_path=ledger_path, raw_root=raw_root):
            ids.add(rid)
    return ids


def ensure_secret_safe_text(text: str, *, secrets: Sequence[str] = ()) -> None:
    """Hard-fail if secret-like material appears in persisted text.

    Checks both generic secret tokens and any concrete secret values supplied
    (e.g. the live ``ODDS_API_KEY``), so a leak of the actual key is rejected
    even though a fully-redacted URL legitimately contains ``apiKey=REDACTED``.
    """
    low = text.lower()
    for token in _FORBIDDEN_CONTENT:
        if token.lower() in low:
            raise ValueError(
                f"refusing to persist secret-like content: contains {token!r}"
            )
    for secret in secrets:
        if secret and secret in text:
            raise ValueError("refusing to persist secret-like content: contains the raw key value")
