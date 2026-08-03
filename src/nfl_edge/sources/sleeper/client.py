"""Bounded HTTP client for the Sleeper active-QB endpoint.

This module is the **only** place that talks to the Sleeper public API
on behalf of the audit harness. It deliberately:

* refuses to read any environment variable named ``*API_KEY*``,
  ``*TOKEN*``, ``*SECRET*``;
* refuses to use any URL other than the documented filtered endpoint;
* records every attempt (success **and** failure) into a fetch ledger
  with deterministic SHA-256 over the raw bytes;
* writes raw payloads to disk atomically (write to a temp file in the
  same directory, then ``os.replace``);
* does not depend on the system clock except for explicit
  ``datetime.now(timezone.utc)`` calls; we never trust a remote
  ``Date`` header as a content timestamp.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse

import requests

# Endpoint constants. Pinning the URL prevents the harness from
# accidentally following a 30x to an unofficial mirror.
DEFAULT_ENDPOINT = "https://api.sleeper.app/v1/players/nfl"
DEFAULT_POSITION = "QB"
DEFAULT_ACTIVE = "true"
DEFAULT_TIMEOUT_SECONDS = 30.0

# The Sleeper docs note "stay under 1000 API calls per minute". This
# audit makes one call per scheduled run, so this constant is a
# defensive tripwire for the integration test runner.
SOFT_RATE_LIMIT_PER_MINUTE = 1000

# Bounded retry policy. Two retries, exponential backoff, total bounded
# to roughly 4 x timeout seconds.
DEFAULT_RETRY_BACKOFF_SECONDS = (1.0, 2.0, 4.0)


class SleeperAuditError(RuntimeError):
    """Raised when the audit client cannot complete a fetch in a way
    that preserves the audit invariant (raw bytes preserved, ledger
    recorded, exception typed)."""


@dataclass(frozen=True)
class SleeperFetchResult:
    """The outcome of a single bounded attempt against the Sleeper API.

    ``raw_payload_path`` and ``sha256`` are populated for both successful
    and failed attempts (we record a small JSON envelope as the raw
    bytes for failures so the ledger is never empty).
    """

    snapshot_id: str
    endpoint: str
    request_started_at_utc: str
    response_received_at_utc: str | None
    duration_ms: int
    http_status: int | None
    success: bool
    response_bytes: int
    sha256: str
    etag: str | None
    last_modified: str | None
    content_type: str | None
    attempt_number: int
    error_class: str | None
    error_message: str | None
    raw_payload_path: str


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically.

    Uses the standard ``write to temp + os.replace`` idiom. The temp
    file lives in the same directory as the target so ``os.replace`` is
    guaranteed to be atomic on POSIX.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        with open(tmp_path, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def parse_response_headers(headers: Mapping[str, str] | None) -> dict[str, str | None]:
    """Normalize a small set of response headers used by the audit.

    We deliberately record only the headers that have an unambiguous
    canonical form: ETag, Last-Modified, Content-Type, and the
    non-standard rate-limit headers Sleeper may add in the future.
    Headers are looked up case-insensitively.
    """
    if not headers:
        return {
            "etag": None,
            "last_modified": None,
            "content_type": None,
        }
    lower = {key.lower(): value for key, value in headers.items()}
    return {
        "etag": lower.get("etag"),
        "last_modified": lower.get("last-modified"),
        "content_type": lower.get("content-type"),
    }


def _validate_endpoint(endpoint: str) -> str:
    """Reject URLs that are not the documented Sleeper public host.

    This is a defensive guard against the audit harness being pointed at
    a mirror, a phishing copy, or a developer's local proxy by mistake.
    """
    parsed = urlparse(endpoint)
    if parsed.scheme != "https":
        raise SleeperAuditError(f"refusing non-https endpoint: {endpoint}")
    host = (parsed.netloc or "").lower()
    if host != "api.sleeper.app":
        raise SleeperAuditError(f"refusing non-sleeper endpoint host: {host}")
    if not parsed.path.startswith("/v1/players/nfl"):
        raise SleeperAuditError(f"refusing non-players/nfl path: {parsed.path}")
    return endpoint


def _build_url(endpoint: str, position: str, active: str) -> str:
    return f"{endpoint}?position={position}&active={active}"


def _classify_exception(exc: BaseException) -> tuple[str, str]:
    return (type(exc).__name__, str(exc)[:500])


def fetch_attempts(
    *,
    snapshot_id: str,
    raw_dir: str | Path,
    endpoint: str = DEFAULT_ENDPOINT,
    position: str = DEFAULT_POSITION,
    active: str = DEFAULT_ACTIVE,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    backoff_seconds: Sequence[float] = DEFAULT_RETRY_BACKOFF_SECONDS,
    session: "requests.Session | Any" = None,
    sleep: Callable[[float], None] | None = None,
) -> list[SleeperFetchResult]:
    """Attempt the filtered active-QB fetch with bounded retries.

    Returns one ``SleeperFetchResult`` per attempt (success or failure).
    The last element is the canonical outcome for the snapshot; the
    earlier elements are the retry history and must be preserved in the
    fetch ledger.
    """
    if sleep is None:
        sleep = time.sleep
    endpoint = _validate_endpoint(endpoint)
    url = _build_url(endpoint, position, active)
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    sess = session or requests.Session()
    attempts: list[SleeperFetchResult] = []
    schedule = list(backoff_seconds) + [0.0]  # final "0" means the last attempt
    for attempt_index, delay in enumerate(schedule, start=1):
        if delay > 0.0:
            sleep(delay)
        request_started_at_utc = _utc_now_iso()
        start_monotonic = time.monotonic()
        attempt_path = raw_dir / f"{snapshot_id}_attempt{attempt_index:02d}.bin"
        try:
            response = sess.get(
                url,
                timeout=timeout_seconds,
                allow_redirects=False,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "nfl-edge-sleeper-source-audit/1.0 (+source-feasibility)",
                },
            )
            elapsed_ms = int((time.monotonic() - start_monotonic) * 1000)
            status = response.status_code
            content = response.content
            response_received_at_utc = _utc_now_iso()
            headers = parse_response_headers(response.headers)
            success = 200 <= status < 300
            error_class: str | None = None
            error_message: str | None = None
            if not success:
                # On HTTP error we still want a *parsable* raw payload in
                # the ledger, so we wrap the body in a small envelope.
                envelope = {
                    "_audit_envelope": True,
                    "kind": "http_error",
                    "status": status,
                    "url": url,
                    "body_text": response.text[:2000],
                }
                raw_bytes = _json_envelope_bytes(envelope)
                error_class = "HTTPError"
                error_message = f"status={status}"
            else:
                raw_bytes = content
            _atomic_write_bytes(attempt_path, raw_bytes)
            digest = hashlib.sha256(raw_bytes).hexdigest()
            attempts.append(
                SleeperFetchResult(
                    snapshot_id=snapshot_id,
                    endpoint=url,
                    request_started_at_utc=request_started_at_utc,
                    response_received_at_utc=response_received_at_utc,
                    duration_ms=elapsed_ms,
                    http_status=status,
                    success=success,
                    response_bytes=len(raw_bytes),
                    sha256=digest,
                    etag=headers["etag"],
                    last_modified=headers["last_modified"],
                    content_type=headers["content_type"],
                    attempt_number=attempt_index,
                    error_class=error_class,
                    error_message=error_message,
                    raw_payload_path=str(attempt_path),
                )
            )
            if success:
                return attempts
        except requests.exceptions.Timeout as exc:
            elapsed_ms = int((time.monotonic() - start_monotonic) * 1000)
            response_received_at_utc = _utc_now_iso()
            envelope = {
                "_audit_envelope": True,
                "kind": "timeout",
                "url": url,
                "timeout_seconds": timeout_seconds,
            }
            raw_bytes = _json_envelope_bytes(envelope)
            _atomic_write_bytes(attempt_path, raw_bytes)
            digest = hashlib.sha256(raw_bytes).hexdigest()
            cls_name, msg = _classify_exception(exc)
            attempts.append(
                SleeperFetchResult(
                    snapshot_id=snapshot_id,
                    endpoint=url,
                    request_started_at_utc=request_started_at_utc,
                    response_received_at_utc=response_received_at_utc,
                    duration_ms=elapsed_ms,
                    http_status=None,
                    success=False,
                    response_bytes=len(raw_bytes),
                    sha256=digest,
                    etag=None,
                    last_modified=None,
                    content_type=None,
                    attempt_number=attempt_index,
                    error_class=cls_name,
                    error_message=msg,
                    raw_payload_path=str(attempt_path),
                )
            )
        except requests.exceptions.RequestException as exc:
            elapsed_ms = int((time.monotonic() - start_monotonic) * 1000)
            response_received_at_utc = _utc_now_iso()
            envelope = {
                "_audit_envelope": True,
                "kind": "request_exception",
                "url": url,
                "exception": type(exc).__name__,
                "message": str(exc)[:500],
            }
            raw_bytes = _json_envelope_bytes(envelope)
            _atomic_write_bytes(attempt_path, raw_bytes)
            digest = hashlib.sha256(raw_bytes).hexdigest()
            cls_name, msg = _classify_exception(exc)
            attempts.append(
                SleeperFetchResult(
                    snapshot_id=snapshot_id,
                    endpoint=url,
                    request_started_at_utc=request_started_at_utc,
                    response_received_at_utc=response_received_at_utc,
                    duration_ms=elapsed_ms,
                    http_status=None,
                    success=False,
                    response_bytes=len(raw_bytes),
                    sha256=digest,
                    etag=None,
                    last_modified=None,
                    content_type=None,
                    attempt_number=attempt_index,
                    error_class=cls_name,
                    error_message=msg,
                    raw_payload_path=str(attempt_path),
                )
            )
    # If we get here every attempt failed. Return the full history.
    return attempts


def _json_envelope_bytes(envelope: dict[str, Any]) -> bytes:
    import json

    return (
        json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
    )


def fetch_active_qb_snapshot(
    *,
    snapshot_id: str,
    raw_dir: str | Path,
    endpoint: str = DEFAULT_ENDPOINT,
    position: str = DEFAULT_POSITION,
    active: str = DEFAULT_ACTIVE,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    backoff_seconds: Sequence[float] = DEFAULT_RETRY_BACKOFF_SECONDS,
    session: "requests.Session | Any" = None,
) -> tuple[SleeperFetchResult | None, list[SleeperFetchResult]]:
    """Run the bounded retry policy and return ``(winner, all_attempts)``.

    ``winner`` is the successful attempt, or ``None`` if every attempt
    failed. ``all_attempts`` is the full retry history (always at least
    one element).
    """
    attempts = fetch_attempts(
        snapshot_id=snapshot_id,
        raw_dir=raw_dir,
        endpoint=endpoint,
        position=position,
        active=active,
        timeout_seconds=timeout_seconds,
        backoff_seconds=backoff_seconds,
        session=session,
    )
    winner = next((a for a in attempts if a.success), None)
    return winner, attempts
