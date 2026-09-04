from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient

os.environ.setdefault("NFL_EDGE_DB_PATH", "/tmp/nfl-edge-backend-duplicate-import.sqlite3")
os.environ.setdefault("NFL_EDGE_PRODUCT_DIR", "/tmp/nfl-edge-backend-duplicate-import-product")
os.environ.setdefault("NFL_EDGE_COOKIE_SECURE", "false")

from nfl_edge.backend.app import create_app  # noqa: E402
from nfl_edge.backend.publication import ProductStore  # noqa: E402
from nfl_edge.backend.settings import BackendSettings  # noqa: E402
from nfl_edge.contracts.live_product_v1 import validate_product_snapshot  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/contracts/nfl_edge_product_api_v1_week1_mock.json"
STATE = ROOT / "data/live/2026/entering_product_state_v1.json"


def test_same_exact_offer_in_two_lanes_consumes_one_stake_and_one_wager(tmp_path: Path) -> None:
    product = json.loads(FIXTURE.read_text(encoding="utf-8"))
    product["product_version"] = "duplicate-headline-test-v1"
    duplicate = deepcopy(product["headlines"]["balanced"])
    duplicate["lane"] = "HIT_RATE"
    product["headlines"]["hit_rate"] = duplicate
    validate_product_snapshot(product)

    settings = BackendSettings(
        db_path=tmp_path / "users.sqlite3",
        product_dir=tmp_path / "publication",
        decision_state_path=STATE,
        cookie_secure=False,
        allowed_origin="http://testserver",
        allowed_hosts=("testserver",),
        auth_rate_limit_per_minute=100,
    )
    ProductStore(settings.product_dir).publish(product)
    client = TestClient(create_app(settings))
    assert client.post(
        "/api/v1/auth/register",
        json={"username": "duplicate_user", "password": "correct horse battery staple"},
    ).status_code == 201
    assert client.put(
        "/api/v1/profile",
        json={"bankroll": "1000.00", "risk_profile": "Normal"},
    ).status_code == 200

    view = client.get("/api/v1/product/latest").json()
    assert view["product"]["headlines"]["hit_rate"]["recommended_units"] == 0.75
    assert view["product"]["headlines"]["balanced"]["recommended_units"] == 0.75
    assert view["headline_overlays"]["hit_rate"]["recommended_dollars"] == "7.50"
    assert view["headline_overlays"]["balanced"]["recommended_dollars"] == "0.00"
    assert view["headline_overlays"]["balanced"]["duplicate_of_lane"] == "HIT_RATE"
    assert view["headline_overlays"]["balanced"]["stake_suppressed_reason"] == "DUPLICATE_EXACT_OFFER"

    duplicate_log = client.post(
        "/api/v1/wagers",
        json={
            "source_type": "HEADLINE",
            "product_version": product["product_version"],
            "lane": "BALANCED",
            "idempotency_key": "duplicate-secondary-click",
        },
    )
    assert duplicate_log.status_code == 409
    assert "duplicate headline recommendation" in duplicate_log.json()["detail"]

    primary_log = client.post(
        "/api/v1/wagers",
        json={
            "source_type": "HEADLINE",
            "product_version": product["product_version"],
            "lane": "HIT_RATE",
            "actual_dollars": "8.00",
            "idempotency_key": "duplicate-primary-click",
        },
    )
    assert primary_log.status_code == 201, primary_log.text
    wager = primary_log.json()["wager"]
    assert wager["recommended_dollars"] == "7.50"

    refreshed = client.get("/api/v1/product/latest").json()
    primary_overlay = refreshed["headline_overlays"]["hit_rate"]
    duplicate_overlay = refreshed["headline_overlays"]["balanced"]
    assert primary_overlay["wager_logged"] is True
    assert duplicate_overlay["wager_logged"] is True
    assert duplicate_overlay["logged_wager_id"] == primary_overlay["logged_wager_id"] == wager["wager_id"]
    assert duplicate_overlay["actual_dollars"] == primary_overlay["actual_dollars"] == "8.00"
