from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from nfl_edge.prospective.runtime_v1 import (
    capture_published_product,
    runtime_publications_dir,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/contracts/nfl_edge_product_api_v1_week1_mock.json"


def _product() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_runtime_capture_writes_expected_week_layout_and_is_idempotent(tmp_path: Path) -> None:
    product = _product()
    first = capture_published_product(
        product,
        runtime_root=tmp_path,
        published_at_utc="2026-09-02T14:00:05Z",
    )
    second = capture_published_product(
        product,
        runtime_root=tmp_path,
        published_at_utc="2026-09-02T14:05:00Z",
    )

    expected_dir = runtime_publications_dir(tmp_path, season=2026, week=1)
    files = sorted(expected_dir.glob("*.json"))
    assert first["status"] == "CAPTURED"
    assert second["status"] == "DEDUPLICATED"
    assert first["publication_id"] == second["publication_id"]
    assert first["source_product_sha256"] == second["source_product_sha256"]
    assert len(files) == 1
    stored = json.loads(files[0].read_text(encoding="utf-8"))
    assert stored["capture_mode"] == "NATIVE_PROSPECTIVE"
    assert stored["published_at_utc"] == "2026-09-02T14:00:05Z"
    assert stored["creation_provenance"]["provider_calls"] == 0
    assert stored["creation_provenance"]["user_specific_data_included"] is False


def test_runtime_capture_never_writes_user_specific_dollar_fields(tmp_path: Path) -> None:
    capture_published_product(
        _product(),
        runtime_root=tmp_path,
        published_at_utc="2026-09-02T14:00:05Z",
    )
    payload = next(tmp_path.rglob("*.json")).read_text(encoding="utf-8").lower()
    for forbidden in (
        "username",
        "session_id",
        "password_hash",
        "bankroll",
        "dollar_stake",
        "wager_history",
    ):
        assert forbidden not in payload


def test_runtime_capture_preserves_null_week_boundary_for_empty_slate(tmp_path: Path) -> None:
    product = _product()
    no_play = deepcopy(product["headlines"]["hit_rate"])
    no_play["game_id"] = None
    no_play["matchup"] = None
    no_play["market"] = None
    no_play["selection"] = None
    no_play["book"] = None
    no_play["line"] = None
    no_play["american_odds"] = None
    no_play["model_probability"] = None
    no_play["trust_probability"] = None
    no_play["market_probability"] = None
    no_play["ev"] = None
    no_play["recommended_units"] = 0.0
    no_play["play_through"] = None
    no_play["value_at"] = None
    for lane_key, lane_name in (
        ("hit_rate", "HIT_RATE"),
        ("balanced", "BALANCED"),
        ("value", "VALUE"),
    ):
        lane = deepcopy(no_play)
        lane["lane"] = lane_name
        product["headlines"][lane_key] = lane
    product["games"] = []

    capture_published_product(
        product,
        runtime_root=tmp_path,
        published_at_utc="2026-09-02T14:00:05Z",
    )
    stored = json.loads(next(tmp_path.rglob("*.json")).read_text(encoding="utf-8"))
    assert stored["source_week_last_kickoff_at_utc"] is None
