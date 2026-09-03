from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nfl_edge.live.markets_2026 import (
    LiveMarketError,
    acquire_live_response,
    build_request_plan,
    expected_credit_cost,
    match_provider_events,
    normalize_market_snapshot,
)
from nfl_edge.live.week1_2026 import load_week1_schedule
from tests.live.odds_api_week1_fixture import build_synthetic_week1_response

ROOT = Path(__file__).resolve().parents[2]
SCHEDULE = ROOT / "data/live/2026/week1_schedule_v1.json"
ACQUIRED = "2026-09-03T18:00:00Z"


class _Response:
    def __init__(self, content: bytes) -> None:
        self.status_code = 200
        self.content = content
        self.headers = {
            "x-requests-last": "3",
            "x-requests-remaining": "497",
            "x-requests-used": "3",
        }


class _Session:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, params: dict[str, object], timeout: float):
        self.calls.append({"url": url, "params": dict(params), "timeout": timeout})
        return _Response(self.content)


def _schedule():
    return load_week1_schedule(SCHEDULE)


def _events():
    return build_synthetic_week1_response(_schedule(), observed_at_utc=ACQUIRED)


def _raw() -> bytes:
    return (json.dumps(_events(), sort_keys=True, separators=(",", ":")) + "\n").encode()


def test_credit_plan_is_one_region_times_three_markets():
    assert expected_credit_cost() == 3
    plan = build_request_plan(_schedule())
    assert plan["expected_credit_cost"] == 3
    assert plan["bookmakers"] == ["draftkings", "fanduel", "pinnacle"]
    assert plan["markets"] == ["h2h", "spreads", "totals"]
    assert "apiKey" not in plan["params"]


def test_synthetic_fixture_matches_all_16_and_normalizes_required_board():
    events = _events()
    mapping, audit = match_provider_events(_schedule(), events)
    assert len(mapping) == 16
    assert audit["provider_events_returned"] == 16
    assert audit["matched_canonical_games"] == 16
    assert audit["unmatched_provider_event_ids"] == []
    assert audit["unmatched_canonical_game_ids"] == []
    assert audit["ambiguous_provider_events"] == []
    assert audit["duplicate_mappings"] == []

    raw = _raw()
    snapshot = normalize_market_snapshot(
        schedule=_schedule(),
        events=events,
        acquired_at_utc=ACQUIRED,
        response_sha256=hashlib.sha256(raw).hexdigest(),
        credits_consumed=0,
        credits_remaining=None,
    )
    assert snapshot["schema_version"] == "NFL_EDGE_LIVE_MARKET_V1"
    assert snapshot["audit"]["offers_normalized"] == 16 * 3 * 3 * 2
    assert snapshot["audit"]["stale_offers"] == 0
    assert snapshot["audit"]["exact_duplicates"] == 0
    assert snapshot["coverage_by_market"] == {
        "MONEYLINE": 16,
        "SPREAD": 16,
        "TOTAL": 16,
    }
    for book in ("DRAFTKINGS", "FANDUEL", "PINNACLE"):
        assert snapshot["coverage_by_book"][book] == {
            "MONEYLINE": 16,
            "SPREAD": 16,
            "TOTAL": 16,
        }
    assert len(snapshot["games"]) == 16


def test_matching_fails_closed_on_duplicate_provider_mapping():
    events = _events()
    duplicate = dict(events[0])
    duplicate["id"] = "synthetic-duplicate-event"
    with pytest.raises(LiveMarketError, match="failed closed"):
        match_provider_events(_schedule(), [*events, duplicate])


def test_live_acquisition_requires_explicit_gate(tmp_path):
    with pytest.raises(LiveMarketError, match="explicit live=True"):
        acquire_live_response(
            schedule=_schedule(),
            output_dir=tmp_path,
            live=False,
            api_key="not-used",
        )


def test_live_acquisition_is_one_call_persists_raw_and_records_quota_without_secret(tmp_path):
    raw = _raw()
    client = _Session(raw)
    capture = acquire_live_response(
        schedule=_schedule(),
        output_dir=tmp_path,
        live=True,
        api_key="super-secret-test-key",
        session=client,
        acquired_at_utc=ACQUIRED,
    )
    assert len(client.calls) == 1
    assert capture.response_path.read_bytes() == raw
    assert capture.credits_consumed == 3
    assert capture.credits_remaining == 497
    meta = json.loads(capture.metadata_path.read_text())
    assert meta["automatic_retries"] == 0
    assert meta["credits_consumed"] == 3
    assert meta["credits_remaining"] == 497
    assert "apiKey" not in meta["request_params_without_secret"]
    assert "super-secret-test-key" not in capture.metadata_path.read_text()
    assert "super-secret-test-key" not in capture.response_path.read_text()


def test_replay_normalization_is_byte_stable():
    raw = _raw()
    kwargs = dict(
        schedule=_schedule(),
        events=_events(),
        acquired_at_utc=ACQUIRED,
        response_sha256=hashlib.sha256(raw).hexdigest(),
        credits_consumed=0,
        credits_remaining=None,
    )
    first = normalize_market_snapshot(**kwargs)
    second = normalize_market_snapshot(**kwargs)
    first_bytes = json.dumps(first, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    second_bytes = json.dumps(second, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    assert first_bytes == second_bytes
