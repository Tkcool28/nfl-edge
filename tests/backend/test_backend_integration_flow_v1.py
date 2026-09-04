from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("NFL_EDGE_DB_PATH", "/tmp/nfl-edge-backend-integration-import.sqlite3")
os.environ.setdefault("NFL_EDGE_PRODUCT_DIR", "/tmp/nfl-edge-backend-integration-import-product")
os.environ.setdefault("NFL_EDGE_COOKIE_SECURE", "false")

from nfl_edge.backend.app import create_app  # noqa: E402
from nfl_edge.backend.publication import ProductStore  # noqa: E402
from nfl_edge.backend.settings import BackendSettings  # noqa: E402
from nfl_edge.contracts.live_product_v1 import validate_product_snapshot  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/contracts/nfl_edge_product_api_v1_week1_mock.json"
STATE = ROOT / "data/live/2026/entering_product_state_v1.json"


def _opposing(template: dict, *, offer_id: str, selection: str, line, price: int) -> dict:
    row = deepcopy(template)
    row.update(offer_id=offer_id, selection=selection, normalized_selection=selection, line=line, price=price)
    return row


def _integration_product() -> dict:
    product = json.loads(FIXTURE.read_text(encoding="utf-8"))
    product["product_version"] = "backend-integration-flow-v1"
    board = product["games"][0]["market_board"]
    board["moneyline"]["PINNACLE"].append(
        _opposing(
            board["moneyline"]["PINNACLE"][0],
            offer_id="integration-pin-ml-aaa",
            selection="AAA",
            line=None,
            price=102,
        )
    )
    board["spread"]["PINNACLE"].append(
        _opposing(
            board["spread"]["PINNACLE"][0],
            offer_id="integration-pin-spread-bbb",
            selection="BBB",
            line=-2.5,
            price=-106,
        )
    )
    board["total"]["PINNACLE"].append(
        _opposing(
            board["total"]["PINNACLE"][0],
            offer_id="integration-pin-total-under",
            selection="UNDER",
            line=44.5,
            price=-107,
        )
    )
    validate_product_snapshot(product)
    return product


def test_full_backend_flow_two_users_wager_restart_and_exact_offers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = BackendSettings(
        db_path=tmp_path / "users.sqlite3",
        product_dir=tmp_path / "publication",
        decision_state_path=STATE,
        cookie_secure=False,
        allowed_origin="http://testserver",
        allowed_hosts=("testserver",),
        auth_rate_limit_per_minute=100,
    )
    product = _integration_product()
    ProductStore(settings.product_dir).publish(product)
    app = create_app(settings)

    user_a = TestClient(app)
    user_b = TestClient(app)
    password_a = "user a durable password"
    password_b = "user b durable password"
    assert user_a.post("/api/v1/auth/register", json={"username": "IntegrationA", "password": password_a}).status_code == 201
    assert user_a.put("/api/v1/profile", json={"bankroll": "500.00", "risk_profile": "Normal"}).status_code == 200
    assert user_b.post("/api/v1/auth/register", json={"username": "IntegrationB", "password": password_b}).status_code == 201
    assert user_b.put("/api/v1/profile", json={"bankroll": "2000.00", "risk_profile": "Aggressive"}).status_code == 200

    # Prove a fresh browser session can log User A back in and resolve the same identity.
    relog_a = TestClient(app)
    login = relog_a.post("/api/v1/auth/login", json={"username": "integrationa", "password": password_a})
    assert login.status_code == 200
    a_id = login.json()["user"]["user_id"]
    assert relog_a.get("/api/v1/auth/me").json()["user"]["user_id"] == a_id

    view_a = relog_a.get("/api/v1/product/latest").json()
    view_b = user_b.get("/api/v1/product/latest").json()
    assert view_a["product"] == view_b["product"]
    assert view_a["product"]["headlines"]["balanced"]["recommended_units"] == view_b["product"]["headlines"]["balanced"]["recommended_units"]
    assert view_a["product"]["headlines"]["balanced"]["model_probability"] == view_b["product"]["headlines"]["balanced"]["model_probability"]
    assert view_a["product"]["headlines"]["balanced"]["lane"] == view_b["product"]["headlines"]["balanced"]["lane"]
    assert view_a["headline_overlays"]["balanced"]["recommended_dollars"] == "3.50"
    assert view_b["headline_overlays"]["balanced"]["recommended_dollars"] == "18.50"

    logged = relog_a.post(
        "/api/v1/wagers",
        json={
            "source_type": "HEADLINE",
            "product_version": product["product_version"],
            "lane": "BALANCED",
            "actual_units": 0.75,
            "actual_dollars": "4.00",
            "idempotency_key": "integration-a-balanced-1",
        },
    )
    assert logged.status_code == 201, logged.text
    wager_id = logged.json()["wager"]["wager_id"]

    # Close/reopen the client while preserving the persistent session cookie.
    saved_cookies = dict(relog_a.cookies)
    reopened = TestClient(app)
    reopened.cookies.update(saved_cookies)
    assert reopened.get("/api/v1/auth/me").json()["user"]["user_id"] == a_id
    assert reopened.get(f"/api/v1/wagers/{wager_id}").status_code == 200
    attached = reopened.get("/api/v1/product/latest").json()["headline_overlays"]["balanced"]
    assert attached["wager_logged"] is True
    assert attached["logged_wager_id"] == wager_id
    assert user_b.get(f"/api/v1/wagers/{wager_id}").status_code == 404
    assert user_b.get("/api/v1/wagers").json()["wagers"] == []

    # Restart the backend process object: SQLite/session/product state remains authoritative.
    restarted = TestClient(create_app(settings))
    restarted.cookies.update(saved_cookies)
    assert restarted.get("/api/v1/auth/me").json()["user"]["user_id"] == a_id
    assert restarted.get("/api/v1/profile").json()["bankroll"] == "500.00"
    assert restarted.get(f"/api/v1/wagers/{wager_id}").json()["actual_dollars"] == "4.00"
    assert restarted.get("/api/v1/product/latest").json()["headline_overlays"]["balanced"]["wager_logged"] is True

    # HTTP requests below must stay inside the loaded snapshot/frozen-state path.
    import requests
    from nfl_edge.live import markets_2026, product_2026, product_state_2026, scorer_2026

    def forbidden(*args, **kwargs):
        raise AssertionError("live acquisition/scoring/materialization/generation invoked by integration request")

    monkeypatch.setattr(requests, "get", forbidden)
    monkeypatch.setattr(requests, "post", forbidden)
    monkeypatch.setattr(markets_2026, "acquire_live_response", forbidden)
    monkeypatch.setattr(scorer_2026, "score_week1", forbidden)
    monkeypatch.setattr(product_state_2026, "materialize_entering_2026_product_state", forbidden)
    monkeypatch.setattr(product_2026, "build_product_snapshot", forbidden)

    dk = restarted.post(
        "/api/v1/evaluate-offer",
        json={
            "game_id": "mock-2026-w01-AAA-BBB",
            "market_type": "MONEYLINE",
            "selection": "BBB",
            "book": "DRAFTKINGS",
            "line": None,
            "price": -115,
        },
    )
    fd = restarted.post(
        "/api/v1/evaluate-offer",
        json={
            "game_id": "mock-2026-w01-AAA-BBB",
            "market_type": "MONEYLINE",
            "selection": "BBB",
            "book": "FANDUEL",
            "line": None,
            "price": -112,
        },
    )
    assert dk.status_code == 200, dk.text
    assert fd.status_code == 200, fd.text
    assert dk.json()["product_version"] == fd.json()["product_version"] == product["product_version"]
