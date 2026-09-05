from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from nfl_edge.backend.app import create_app
from nfl_edge.backend.publication import ProductStore
from nfl_edge.backend.settings import BackendSettings

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/contracts/nfl_edge_product_api_v1_week1_mock.json"
STATE = ROOT / "data/live/2026/entering_product_state_v1.json"


def _client(tmp_path: Path) -> TestClient:
    settings = BackendSettings(
        db_path=tmp_path / "users.sqlite3",
        product_dir=tmp_path / "publication",
        decision_state_path=STATE,
        cookie_secure=False,
        allowed_origin="http://testserver",
        allowed_hosts=("testserver",),
        auth_rate_limit_per_minute=100,
    )
    ProductStore(settings.product_dir).publish(json.loads(FIXTURE.read_text(encoding="utf-8")))
    return TestClient(create_app(settings))


def _offer(*, book: str, price: int = -115) -> dict:
    return {
        "game_id": "mock-2026-w01-AAA-BBB",
        "market_type": "MONEYLINE",
        "selection": "BBB",
        "book": book,
        "line": None,
        "price": price,
    }


def test_manual_offer_is_evaluated_without_dk_fd_dependency(tmp_path: Path) -> None:
    client = _client(tmp_path)
    retail = client.post("/api/v1/evaluate-offer", json=_offer(book="DRAFTKINGS"))
    manual = client.post("/api/v1/evaluate-offer", json=_offer(book="MANUAL"))
    assert retail.status_code == 200, retail.text
    assert manual.status_code == 200, manual.text
    assert manual.json()["evaluation"] == retail.json()["evaluation"]


def test_manual_offer_persists_with_neutral_source_identity(tmp_path: Path) -> None:
    client = _client(tmp_path)
    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "manual_offer_user", "password": "correct horse battery staple"},
    )
    assert registered.status_code == 201, registered.text
    assert client.put(
        "/api/v1/profile",
        json={"bankroll": "1000.00", "risk_profile": "Normal"},
    ).status_code == 200

    chosen = _offer(book="MANUAL", price=-115)
    evaluated = client.post("/api/v1/evaluate-offer", json=chosen)
    assert evaluated.status_code == 200, evaluated.text

    created = client.post(
        "/api/v1/wagers",
        json={
            "source_type": "EXACT_OFFER",
            "product_version": "mock-week1-contract-v1",
            "exact_offer": chosen,
            "actual_units": 0.5,
            "actual_dollars": "5.00",
            "idempotency_key": "manual-offer-log-1",
        },
    )
    assert created.status_code == 201, created.text
    wager = created.json()["wager"]
    assert wager["source_type"] == "EXACT_OFFER"
    assert wager["book"] == "MANUAL"
    assert wager["actual_dollars"] == "5.00"
