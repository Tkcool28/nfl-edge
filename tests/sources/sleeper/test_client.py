"""Tests for the Sleeper audit client.

All tests use local fixtures and do not hit the network.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nfl_edge.sources.sleeper import (
    DEFAULT_ENDPOINT,
    SleeperAuditError,
    fetch_active_qb_snapshot,
    parse_response_headers,
)

# --- 1. Successful QB response normalization (covered in normalize tests)
# --- 2. Failed HTTP response recording
# --- 3. Timeout handling
# --- 4. Retry behavior
# --- 5. Atomic raw write
# --- 6. Exact payload hashing
# --- 7. Duplicate payload identification


class _StubResponse:
    def __init__(self, status_code: int, payload: dict | None, headers: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = json.dumps(self._payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.text = self.content.decode("utf-8")
        self.headers = headers or {"Content-Type": "application/json"}


class _StubSession:
    def __init__(self, responses: list[_StubResponse], raise_timeout_after: int | None = None) -> None:
        self.responses = list(responses)
        self.raise_timeout_after = raise_timeout_after
        self.calls: list[dict] = []
        self.idx = 0

    def get(self, url, timeout, allow_redirects, headers):
        self.calls.append({"url": url, "timeout": timeout, "headers": headers})
        if self.raise_timeout_after is not None and self.idx >= self.raise_timeout_after:
            import requests
            self.idx += 1
            raise requests.exceptions.Timeout("stub timeout")
        response = self.responses[self.idx]
        self.idx += 1
        return response


def _sample_qb_map() -> dict:
    return {
        "1042": {
            "player_id": "1042",
            "first_name": "Patrick",
            "last_name": "Mahomes",
            "position": "QB",
            "team": "KC",
            "status": "Active",
            "active": True,
            "gsis_id": "00-0033873",
            "depth_chart_order": 1,
            "injury_status": None,
        }
    }


def test_atomic_raw_write_creates_file_and_temp_is_removed(tmp_path: Path) -> None:
    # 5. Atomic raw write
    raw_dir = tmp_path / "raw"
    response = _StubResponse(200, _sample_qb_map(), headers={"ETag": '"abc"', "Last-Modified": "X"})
    session = _StubSession([response])
    winner, attempts = fetch_active_qb_snapshot(
        snapshot_id="sleeper-test-1",
        raw_dir=raw_dir,
        session=session,
        backoff_seconds=[0.0],
    )
    assert winner is not None
    assert winner.success
    attempt_path = Path(winner.raw_payload_path)
    assert attempt_path.exists()
    # No leftover temp files.
    leftover = list(raw_dir.glob(".tmp*")) + list(raw_dir.glob(".*.tmp*"))
    assert not leftover


def test_successful_response_is_hashed_and_recorded(tmp_path: Path) -> None:
    # 6. Exact payload hashing
    raw_dir = tmp_path / "raw"
    payload = _sample_qb_map()
    response = _StubResponse(200, payload)
    session = _StubSession([response])
    winner, _ = fetch_active_qb_snapshot(
        snapshot_id="sleeper-test-hash",
        raw_dir=raw_dir,
        session=session,
        backoff_seconds=[0.0],
    )
    assert winner is not None
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert winner.sha256 == expected
    assert winner.response_bytes == len(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def test_failed_http_response_is_recorded_with_error_envelope(tmp_path: Path) -> None:
    # 2. Failed HTTP response recording
    raw_dir = tmp_path / "raw"
    # Provide one stub response for every retry attempt.
    response = _StubResponse(500, {"error": "boom"})
    session = _StubSession([response, response, response, response, response])
    winner, attempts = fetch_active_qb_snapshot(
        snapshot_id="sleeper-test-fail",
        raw_dir=raw_dir,
        session=session,
        backoff_seconds=[0.0, 0.0, 0.0, 0.0],
    )
    assert winner is None
    assert len(attempts) >= 1
    last = attempts[-1]
    assert last.success is False
    assert last.http_status == 500
    assert last.error_class == "HTTPError"
    body = Path(last.raw_payload_path).read_bytes()
    assert b"_audit_envelope" in body
    # Failed attempts still produce a SHA-256.
    assert len(last.sha256) == 64


def test_timeout_is_recorded(tmp_path: Path) -> None:
    # 3. Timeout handling
    raw_dir = tmp_path / "raw"
    session = _StubSession([_StubResponse(200, _sample_qb_map())], raise_timeout_after=0)
    winner, attempts = fetch_active_qb_snapshot(
        snapshot_id="sleeper-test-timeout",
        raw_dir=raw_dir,
        session=session,
        backoff_seconds=[0.0, 0.0, 0.0, 0.0],
    )
    assert winner is None
    assert attempts[0].success is False
    assert attempts[0].error_class == "Timeout"


def test_retry_recovers_on_second_attempt(tmp_path: Path) -> None:
    # 4. Retry behavior
    raw_dir = tmp_path / "raw"
    session = _StubSession(
        [
            _StubResponse(503, {"error": "busy"}),
            _StubResponse(200, _sample_qb_map()),
        ]
    )
    winner, attempts = fetch_active_qb_snapshot(
        snapshot_id="sleeper-test-retry",
        raw_dir=raw_dir,
        session=session,
        backoff_seconds=[0.0, 0.0, 0.0],
    )
    assert winner is not None
    assert len(attempts) == 2
    assert attempts[0].success is False
    assert attempts[1].success is True


def test_duplicate_payload_identified_by_hash(tmp_path: Path) -> None:
    # 7. Duplicate payload identification
    raw_dir = tmp_path / "raw"
    payload = _sample_qb_map()
    session1 = _StubSession([_StubResponse(200, payload)])
    winner1, _ = fetch_active_qb_snapshot(
        snapshot_id="snap-A", raw_dir=raw_dir, session=session1, backoff_seconds=[0.0]
    )
    session2 = _StubSession([_StubResponse(200, payload)])
    winner2, _ = fetch_active_qb_snapshot(
        snapshot_id="snap-B", raw_dir=raw_dir, session=session2, backoff_seconds=[0.0]
    )
    assert winner1 is not None
    assert winner2 is not None
    assert winner1.sha256 == winner2.sha256


def test_endpoint_validation_rejects_non_sleeper() -> None:
    with pytest.raises(SleeperAuditError):
        fetch_active_qb_snapshot(
            snapshot_id="x",
            raw_dir=Path("/tmp/never-written"),
            endpoint="https://example.com/v1/players/nfl",
            session=_StubSession([]),
            backoff_seconds=[0.0],
        )


def test_endpoint_validation_rejects_non_https() -> None:
    with pytest.raises(SleeperAuditError):
        fetch_active_qb_snapshot(
            snapshot_id="x",
            raw_dir=Path("/tmp/never-written"),
            endpoint="http://api.sleeper.app/v1/players/nfl",
            session=_StubSession([]),
            backoff_seconds=[0.0],
        )


def test_default_endpoint_is_documented() -> None:
    # 1. Successful QB response normalization - the endpoint is the
    # documented one.
    assert DEFAULT_ENDPOINT == "https://api.sleeper.app/v1/players/nfl"


def test_parse_response_headers_normalizes_known_keys() -> None:
    headers = {"eTag": "abc", "LAST-MODIFIED": "today", "content-TYPE": "json"}
    parsed = parse_response_headers(headers)
    assert parsed["etag"] == "abc"
    assert parsed["last_modified"] == "today"
    assert parsed["content_type"] == "json"
