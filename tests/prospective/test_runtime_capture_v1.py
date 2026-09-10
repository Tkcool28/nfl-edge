from __future__ import annotations

import json
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
