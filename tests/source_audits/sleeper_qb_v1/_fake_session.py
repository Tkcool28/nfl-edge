"""Test-only stub HTTP session for the Sleeper audit.

The orchestrator accepts a ``requests.Session``-compatible object. In
tests we inject this stub so the audit can run without making real
network calls. The module is also used by ``scripts/_sleeper_fake_session.py``
when the CLI is run with ``--use-fake-session``; keeping the
implementation in one place prevents drift between the two copies.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _fake_player_map() -> dict[str, dict[str, Any]]:
    return {
        "1042": {
            "player_id": "1042",
            "first_name": "Patrick",
            "last_name": "Mahomes",
            "full_name": "Patrick Mahomes",
            "position": "QB",
            "team": "KC",
            "status": "Active",
            "active": True,
            "gsis_id": "00-0033873",
            "espn_id": "3139477",
            "yahoo_id": "30123",
            "fantasy_data_id": "18030",
            "sportradar_id": "c4a5d6e0-9d4f-4b3a-8f0a-1234567890ab",
            "rotowire_id": "8449",
            "depth_chart_position": 1,
            "depth_chart_order": 1,
            "injury_status": None,
            "injury_body_part": None,
            "injury_notes": None,
            "injury_start_date": None,
            "practice_participation": None,
            "practice_description": None,
            "search_rank": 1,
            "age": 30,
            "years_exp": 9,
        },
        "7523": {
            "player_id": "7523",
            "first_name": "Anthony",
            "last_name": "Richardson",
            "full_name": "Anthony Richardson",
            "position": "QB",
            "team": "IND",
            "status": "Active",
            "active": True,
            "gsis_id": "00-0036980",
            "espn_id": "4422809",
            "depth_chart_position": 1,
            "depth_chart_order": 1,
            "injury_status": "Questionable",
            "injury_body_part": "Shoulder",
            "injury_notes": "Limited in practice",
            "injury_start_date": "2026-08-02",
            "practice_participation": "Limited",
            "age": 23,
            "years_exp": 2,
        },
        "4866": {
            "player_id": "4866",
            "first_name": "Joe",
            "last_name": "Flacco",
            "full_name": "Joe Flacco",
            "position": "QB",
            "team": "IND",
            "status": "Active",
            "active": True,
            "gsis_id": "00-0024231",
            "depth_chart_position": 2,
            "depth_chart_order": 2,
            "injury_status": None,
            "age": 41,
            "years_exp": 17,
        },
    }


class FakeSleeperResponse:
    def __init__(self, status: int, payload: dict[str, Any] | list[Any] | None) -> None:
        self.status_code = status
        payload = payload if payload is not None else {}
        self.content = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.text = self.content.decode("utf-8")
        self.headers = {"Content-Type": "application/json; charset=utf-8"}
        digest = hashlib.sha256(self.content).hexdigest()
        self.headers["ETag"] = f'"{digest}"'
        self.headers["Last-Modified"] = "Tue, 05 Aug 2026 12:00:00 GMT"

    def raise_for_status(self) -> None:
        if not (200 <= self.status_code < 300):
            raise RuntimeError(f"fake session status {self.status_code}")


class FakeSleeperSession:
    """A minimal stub for the audit client.

    Returns one canonical active-QB player map on the first call. A
    second call (within the same orchestrator lifetime) flips one
    QB's injury status so the change-ledger tests can observe a
    deterministic delta.

    Failure-injection knobs (used by CLI tests):

    * ``raise_timeout`` — every ``.get`` raises
      ``requests.exceptions.Timeout``.
    * ``raise_status`` — every ``.get`` returns the given HTTP
      status code (e.g. ``503``) with an empty player map.
    * ``invalid_json`` — every ``.get`` returns HTTP 200 with a
      body that is not a JSON object of player records (the body
      is a JSON array, which the orchestrator must reject as
      ``INCOMPLETE_RESPONSE``).
    """

    def __init__(self) -> None:
        self.call_count = 0
        self.raise_timeout = False
        self.raise_status: int | None = None
        self.invalid_json = False

    def get(self, url: str, timeout: float, allow_redirects: bool, headers: dict[str, str]) -> FakeSleeperResponse:
        self.call_count += 1
        if self.raise_timeout:
            import requests
            raise requests.exceptions.Timeout("fake timeout")
        if self.raise_status is not None:
            return FakeSleeperResponse(self.raise_status, {})
        if self.invalid_json:
            # A JSON array is parseable JSON but is not a
            # player-map dict, so the orchestrator's parse guard
            # must reject it as INCOMPLETE_RESPONSE.
            return FakeSleeperResponse(200, ["a", "b", "c"])
        if self.call_count == 1:
            return FakeSleeperResponse(200, _fake_player_map())
        data = _fake_player_map()
        data["7523"]["injury_status"] = "Out"
        return FakeSleeperResponse(200, data)
