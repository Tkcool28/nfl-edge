"""Ledger + immutable raw + resume verification (§H/I)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfl_edge.market_data.ledger import (
    LEDGER_SCHEMA,
    LedgerEntry,
    _utc_now_iso,
    append_ledger_entry,
    completed_request_ids,
    is_request_complete,
    sha256_of_file,
    write_raw_immutable,
)


def _entry(*, request_plan_id="md_2020_001", sha=None, raw="2020/md_2020_001.json", success=True):
    return LedgerEntry(
        request_plan_id=request_plan_id,
        season=2020,
        cluster_id="2020_001",
        requested_target_timestamp_utc="2020-01-01T17:00:00Z",
        expected_earliest_kickoff_utc="2020-01-01T18:00:00Z",
        target_game_ids="2020_01_A_B",
        actual_snapshot_timestamp_utc="2020-01-01T16:59:00Z",
        previous_snapshot_timestamp_utc=None,
        next_snapshot_timestamp_utc=None,
        http_status=200,
        x_requests_last=30,
        x_requests_used=30,
        x_requests_remaining=99730,
        response_content_sha256=sha,
        acquisition_timestamp_utc=_utc_now_iso(),
        requested_bookmaker_keys="draftkings,fanduel",
        requested_markets="h2h,spreads,totals",
        raw_payload_path=raw,
        request_url_redacted="https://example/?apiKey=REDACTED",
        success=success,
        error_class=None,
        error_message=None,
    )


def test_write_raw_immutable_writes_and_hashes(tmp_path):
    raw = tmp_path / "raw.json"
    digest = write_raw_immutable(raw, b'{"hello":1}')
    assert raw.exists()
    assert digest == sha256_of_file(raw)


def test_write_raw_immutable_refuses_overwrite(tmp_path):
    raw = tmp_path / "raw.json"
    write_raw_immutable(raw, b"a")
    with pytest.raises(FileExistsError):
        write_raw_immutable(raw, b"b")


def test_ledger_append_creates_parquet(tmp_path):
    ledger = tmp_path / "ledger.parquet"
    append_ledger_entry(_entry(sha="abc"), ledger)
    assert ledger.exists()
    import polars as pl

    frame = pl.read_parquet(ledger)
    assert frame.height == 1
    assert frame.get_column("request_plan_id").to_list() == ["md_2020_001"]


def test_is_request_complete_requires_raw_and_hash_match(tmp_path):
    raw_root = tmp_path / "raw"
    ledger = tmp_path / "ledger.parquet"
    raw_rel = "2020/md_2020_001.json"
    raw = raw_root / raw_rel
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b'{"snapshot": true}')
    digest = sha256_of_file(raw)

    # No ledger yet -> incomplete.
    assert not is_request_complete("md_2020_001", ledger_path=ledger, raw_root=raw_root)

    # Correct ledger -> complete.
    append_ledger_entry(_entry(sha=digest, raw=raw_rel), ledger)
    assert is_request_complete("md_2020_001", ledger_path=ledger, raw_root=raw_root)

    # Tampered raw (hash mismatch) -> incomplete / not trusted.
    raw.write_bytes(b'{"snapshot": false}')
    assert not is_request_complete("md_2020_001", ledger_path=ledger, raw_root=raw_root)


def test_completed_request_ids(tmp_path):
    raw_root = tmp_path / "raw"
    ledger = tmp_path / "ledger.parquet"
    raw = raw_root / "2020" / "md_2020_007.json"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"x")
    digest = sha256_of_file(raw)
    append_ledger_entry(_entry(request_plan_id="md_2020_007", sha=digest, raw="2020/md_2020_007.json"), ledger)
    assert completed_request_ids(ledger_path=ledger, raw_root=raw_root) == {"md_2020_007"}


def test_ledger_schema_is_stable():
    # The ledger schema must not drift silently.
    assert "request_plan_id" in LEDGER_SCHEMA
    assert "response_content_sha256" in LEDGER_SCHEMA
    assert "request_url_redacted" in LEDGER_SCHEMA
    assert "x_requests_last" in LEDGER_SCHEMA
