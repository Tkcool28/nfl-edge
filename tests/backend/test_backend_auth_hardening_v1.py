from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

os.environ.setdefault("NFL_EDGE_DB_PATH", "/tmp/nfl-edge-backend-auth-import.sqlite3")
os.environ.setdefault("NFL_EDGE_PRODUCT_DIR", "/tmp/nfl-edge-backend-auth-import-product")
os.environ.setdefault("NFL_EDGE_COOKIE_SECURE", "false")

from nfl_edge.backend.app import create_app  # noqa: E402
from nfl_edge.backend.publication import ProductStore  # noqa: E402
from nfl_edge.backend.settings import BackendSettings  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/contracts/nfl_edge_product_api_v1_week1_mock.json"
STATE = ROOT / "data/live/2026/entering_product_state_v1.json"


def test_login_wrong_credentials_are_generic_even_when_shape_looks_invalid(tmp_path: Path) -> None:
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
    client = TestClient(create_app(settings))
    password = "correct horse battery staple"
    registered = client.post("/api/v1/auth/register", json={"username": "Auth.User", "password": password})
    assert registered.status_code == 201
    client.post("/api/v1/auth/logout")

    attempts = [
        {"username": "Auth.User", "password": "x"},
        {"username": "Auth.User", "password": "definitely wrong password"},
        {"username": "missing.user", "password": "definitely wrong password"},
        {"username": "??", "password": "definitely wrong password"},
    ]
    responses = [client.post("/api/v1/auth/login", json=payload) for payload in attempts]
    assert [response.status_code for response in responses] == [401, 401, 401, 401]
    assert [response.json() for response in responses] == [{"detail": "invalid credentials"}] * 4

    success = client.post("/api/v1/auth/login", json={"username": "auth.user", "password": password})
    assert success.status_code == 200
    assert success.json()["user"]["username"] == "Auth.User"