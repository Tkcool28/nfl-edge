from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

# Avoid module-level production-app construction touching the repository during test collection.
os.environ.setdefault("NFL_EDGE_DB_PATH", "/tmp/nfl-edge-backend-session-read-import.sqlite3")
os.environ.setdefault("NFL_EDGE_PRODUCT_DIR", "/tmp/nfl-edge-backend-session-read-import-product")
os.environ.setdefault("NFL_EDGE_COOKIE_SECURE", "false")

from nfl_edge.backend.app import create_app  # noqa: E402
from nfl_edge.backend.publication import ProductStore  # noqa: E402
from nfl_edge.backend.settings import BackendSettings  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/contracts/nfl_edge_product_api_v1_week1_mock.json"
STATE = ROOT / "data/live/2026/entering_product_state_v1.json"
PASSWORD = "correct horse battery staple"


def _settings(tmp_path: Path) -> BackendSettings:
    return BackendSettings(
        db_path=tmp_path / "users.sqlite3",
        product_dir=tmp_path / "publication",
        decision_state_path=STATE,
        cookie_secure=False,
        allowed_origin="http://testserver",
        allowed_hosts=("testserver", "localhost", "127.0.0.1"),
        auth_rate_limit_per_minute=1000,
    )


def _session_row(db_path: Path, user_id: str) -> sqlite3.Row:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT session_id, created_at, expires_at, last_seen_at, revoked_at "
            "FROM sessions WHERE user_id=? ORDER BY rowid ASC LIMIT 1",
            (user_id,),
        ).fetchone()
        assert row is not None
        return row
    finally:
        conn.close()


def test_authenticated_gets_resolve_session_without_writes_and_session_lifecycle_still_holds(
    tmp_path: Path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    ProductStore(settings.product_dir).publish(json.loads(FIXTURE.read_text(encoding="utf-8")))
    app = create_app(settings)
    client = TestClient(app)

    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "session_read_user", "password": PASSWORD},
    )
    assert registered.status_code == 201, registered.text
    user_id = registered.json()["user"]["user_id"]
    cookies = dict(client.cookies)

    before = _session_row(settings.db_path, user_id)
    assert before["last_seen_at"] == before["created_at"]
    assert before["revoked_at"] is None

    def forbidden_write():
        raise AssertionError("authenticated GET attempted BackendDatabase._write()")

    with monkeypatch.context() as patch:
        patch.setattr(app.state.db, "_write", forbidden_write)
        for _ in range(3):
            assert client.get("/api/v1/auth/me").status_code == 200
            assert client.get("/api/v1/profile").status_code == 200
            assert client.get("/api/v1/product/latest").status_code == 200
            assert client.get("/api/v1/wagers").status_code == 200

    after_reads = _session_row(settings.db_path, user_id)
    assert after_reads["last_seen_at"] == before["last_seen_at"]
    assert after_reads["revoked_at"] is None

    restarted = TestClient(create_app(settings))
    restarted.cookies.update(cookies)
    assert restarted.get("/api/v1/auth/me").status_code == 200
    after_restart = _session_row(settings.db_path, user_id)
    assert after_restart["last_seen_at"] == before["last_seen_at"]

    logout = restarted.post("/api/v1/auth/logout")
    assert logout.status_code == 204
    revoked = _session_row(settings.db_path, user_id)
    assert revoked["revoked_at"] is not None
    assert restarted.get("/api/v1/auth/me").status_code == 401

    login = restarted.post(
        "/api/v1/auth/login",
        json={"username": "SESSION_READ_USER", "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    with sqlite3.connect(settings.db_path) as conn:
        active_session_id = conn.execute(
            "SELECT session_id FROM sessions WHERE user_id=? AND revoked_at IS NULL ORDER BY rowid DESC LIMIT 1",
            (user_id,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE sessions SET expires_at='2000-01-01T00:00:00Z' WHERE session_id=?",
            (active_session_id,),
        )
        conn.commit()
    assert restarted.get("/api/v1/auth/me").status_code == 401
