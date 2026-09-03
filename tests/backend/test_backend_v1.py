from __future__ import annotations

import json
import os
import sqlite3
import threading
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Avoid module-level production-app construction touching the repository during test collection.
os.environ.setdefault("NFL_EDGE_DB_PATH", "/tmp/nfl-edge-backend-v1-import.sqlite3")
os.environ.setdefault("NFL_EDGE_PRODUCT_DIR", "/tmp/nfl-edge-backend-v1-import-product")
os.environ.setdefault("NFL_EDGE_COOKIE_SECURE", "false")

from nfl_edge.backend.app import create_app  # noqa: E402
from nfl_edge.backend.publication import ProductStore  # noqa: E402
from nfl_edge.backend.settings import BackendSettings  # noqa: E402
from nfl_edge.contracts.live_product_v1 import ContractValidationError, validate_product_snapshot  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/contracts/nfl_edge_product_api_v1_week1_mock.json"
STATE = ROOT / "data/live/2026/entering_product_state_v1.json"


def _offer(template: dict, *, offer_id: str, selection: str, line, price: int) -> dict:
    row = deepcopy(template)
    row.update(
        offer_id=offer_id,
        selection=selection,
        normalized_selection=selection,
        line=line,
        price=price,
    )
    return row


def _product(*, version: str = "backend-test-v1", generated: str = "2026-09-03T14:00:00Z") -> dict:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["product_version"] = version
    payload["generated_at_utc"] = generated
    payload["freshness"]["observed_at_utc"] = generated
    payload["games"][0]["updated_at_utc"] = generated
    board = payload["games"][0]["market_board"]

    # The contract fixture intentionally demonstrates sparse books. Backend exact-offer
    # tests add synthetic opposing Pinnacle sides in-memory so no-vig anchors are complete.
    board["moneyline"]["PINNACLE"].append(
        _offer(
            board["moneyline"]["PINNACLE"][0],
            offer_id="mock-pin-ml-aaa",
            selection="AAA",
            line=None,
            price=102,
        )
    )
    board["spread"]["PINNACLE"].append(
        _offer(
            board["spread"]["PINNACLE"][0],
            offer_id="mock-pin-spread-bbb",
            selection="BBB",
            line=-2.5,
            price=-106,
        )
    )
    board["total"]["PINNACLE"].append(
        _offer(
            board["total"]["PINNACLE"][0],
            offer_id="mock-pin-total-under",
            selection="UNDER",
            line=44.5,
            price=-107,
        )
    )
    validate_product_snapshot(payload)
    return payload


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


def _client(tmp_path: Path, product: dict | None = None) -> tuple[TestClient, BackendSettings]:
    settings = _settings(tmp_path)
    store = ProductStore(settings.product_dir)
    store.publish(product or _product())
    return TestClient(create_app(settings)), settings


def _register(client: TestClient, username: str, password: str = "correct horse battery staple") -> dict:
    response = client.post("/api/v1/auth/register", json={"username": username, "password": password})
    assert response.status_code == 201, response.text
    return response.json()["user"]


def _set_profile(client: TestClient, bankroll: str, risk: str) -> dict:
    response = client.put("/api/v1/profile", json={"bankroll": bankroll, "risk_profile": risk})
    assert response.status_code == 200, response.text
    return response.json()


def test_health_product_games_and_game_detail(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    body = health.json()
    assert body["api_healthy"] is True
    assert body["database_healthy"] is True
    assert body["product_available"] is True
    assert body["product_version"] == "backend-test-v1"

    product = client.get("/api/v1/product/latest").json()
    assert product["schema_version"] == "NFL_EDGE_PRODUCT_VIEW_V1"
    assert product["product"]["schema_version"] == "NFL_EDGE_PRODUCT_API_V1"
    assert product["user"] is None
    assert product["headline_overlays"]["balanced"]["recommended_dollars"] is None

    games = client.get("/api/v1/games").json()
    assert games["product_version"] == product["product"]["product_version"]
    gid = games["games"][0]["game_id"]
    detail = client.get(f"/api/v1/games/{gid}")
    assert detail.status_code == 200
    assert detail.json()["game"] == games["games"][0]
    assert client.get("/api/v1/games/not-a-game").status_code == 404


def test_registration_duplicate_login_logout_and_secret_hygiene(tmp_path: Path) -> None:
    client, settings = _client(tmp_path)
    password = "a password with spaces + symbols!"
    user = _register(client, "Todd.Test", password)
    assert user["schema_version"] == "NFL_EDGE_USER_STATE_V1"
    assert user["username"] == "Todd.Test"
    assert user["bankroll"] == "0.00"
    assert user["risk_profile"] == "Normal"
    assert "password" not in json.dumps(user).lower()

    duplicate = client.post("/api/v1/auth/register", json={"username": "todd.test", "password": password})
    assert duplicate.status_code == 409

    with sqlite3.connect(settings.db_path) as conn:
        stored = conn.execute("SELECT password_hash FROM users WHERE username_norm='todd.test'").fetchone()[0]
    assert stored != password
    assert stored.startswith("$argon2id$")
    assert stored not in json.dumps(client.get("/api/v1/auth/me").json())

    assert client.post("/api/v1/auth/login", json={"username": "Todd.Test", "password": "wrong password"}).status_code == 401
    login = client.post("/api/v1/auth/login", json={"username": "TODD.TEST", "password": password})
    assert login.status_code == 200
    assert login.json()["user"]["user_id"] == user["user_id"]

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_session_persists_across_client_and_app_restart_and_expires(tmp_path: Path) -> None:
    client, settings = _client(tmp_path)
    user = _register(client, "session_user")
    cookies = dict(client.cookies)

    restarted = TestClient(create_app(settings))
    restarted.cookies.update(cookies)
    me = restarted.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["user_id"] == user["user_id"]

    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00Z' WHERE user_id=?", (user["user_id"],))
        conn.commit()
    assert restarted.get("/api/v1/auth/me").status_code == 401


def test_profile_validation_and_restart_persistence(tmp_path: Path) -> None:
    client, settings = _client(tmp_path)
    user = _register(client, "profile_user")
    updated = _set_profile(client, "1234.56", "Aggressive")
    assert updated["user_id"] == user["user_id"]
    assert updated["username"] == "profile_user"
    assert updated["bankroll"] == "1234.56"
    assert updated["risk_profile"] == "Aggressive"
    assert updated["created_at"] == user["created_at"]

    assert client.put("/api/v1/profile", json={"bankroll": 10.001}).status_code == 422
    assert client.put("/api/v1/profile", json={"bankroll": -0.01}).status_code == 422
    assert client.put("/api/v1/profile", json={"bankroll": "1000000000.01"}).status_code == 422
    assert client.put("/api/v1/profile", json={"risk_profile": "YOLO"}).status_code == 422
    nonfinite = client.put(
        "/api/v1/profile",
        content='{"bankroll": NaN}',
        headers={"content-type": "application/json", "origin": "http://testserver"},
    )
    assert nonfinite.status_code == 422

    cookies = dict(client.cookies)
    restarted = TestClient(create_app(settings))
    restarted.cookies.update(cookies)
    persisted = restarted.get("/api/v1/profile")
    assert persisted.status_code == 200
    assert persisted.json()["bankroll"] == "1234.56"
    assert persisted.json()["risk_profile"] == "Aggressive"


def test_profile_isolation_and_personalized_stake_only_changes_dollars(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    ProductStore(settings.product_dir).publish(_product())
    app = create_app(settings)
    user_a = TestClient(app)
    user_b = TestClient(app)

    _register(user_a, "user_a")
    _set_profile(user_a, "500.00", "Normal")
    _register(user_b, "user_b")
    _set_profile(user_b, "2000.00", "Aggressive")

    view_a = user_a.get("/api/v1/product/latest").json()
    view_b = user_b.get("/api/v1/product/latest").json()
    assert view_a["product"] == view_b["product"]
    for field in (
        "selection", "american_odds", "model_probability", "trust_probability", "lane",
        "recommended_units", "play_through", "value_at",
    ):
        assert view_a["product"]["headlines"]["balanced"][field] == view_b["product"]["headlines"]["balanced"][field]
    dollars_a = view_a["headline_overlays"]["balanced"]["recommended_dollars"]
    dollars_b = view_b["headline_overlays"]["balanced"]["recommended_dollars"]
    assert dollars_a == "3.50"
    assert dollars_b == "18.50"
    assert dollars_a != dollars_b
    assert user_a.get("/api/v1/profile").json()["bankroll"] == "500.00"
    assert user_b.get("/api/v1/profile").json()["bankroll"] == "2000.00"


def test_wager_logging_idempotency_isolation_filters_and_restart(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    ProductStore(settings.product_dir).publish(_product())
    app = create_app(settings)
    a = TestClient(app)
    b = TestClient(app)
    user_a = _register(a, "wager_a")
    _set_profile(a, "1000.00", "Normal")
    _register(b, "wager_b")

    payload = {
        "source_type": "HEADLINE",
        "product_version": "backend-test-v1",
        "lane": "BALANCED",
        "actual_units": 1.0,
        "actual_dollars": "10.00",
        "status": "OPEN",
        "note": "manual sportsbook wager",
        "idempotency_key": "frontend-submit-1",
    }
    created = a.post("/api/v1/wagers", json=payload)
    assert created.status_code == 201, created.text
    wager = created.json()["wager"]
    assert created.json()["idempotent_replay"] is False
    assert wager["product_version"] == "backend-test-v1"
    assert wager["recommended_units"] == 0.75
    assert wager["recommended_dollars"] == "7.50"
    assert wager["actual_units"] == 1.0
    assert wager["actual_dollars"] == "10.00"
    assert wager["actual_dollars"] != wager["recommended_dollars"]
    assert wager["provenance"]["headline"]["recommended_units"] == 0.75

    replay = a.post("/api/v1/wagers", json=payload)
    assert replay.status_code == 201
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["wager"]["wager_id"] == wager["wager_id"]
    conflict_payload = {**payload, "actual_dollars": "11.00"}
    assert a.post("/api/v1/wagers", json=conflict_payload).status_code == 409

    assert a.get(f"/api/v1/wagers/{wager['wager_id']}").status_code == 200
    assert b.get(f"/api/v1/wagers/{wager['wager_id']}").status_code == 404
    assert b.get("/api/v1/wagers").json()["wagers"] == []

    current = a.get("/api/v1/product/latest").json()
    overlay = current["headline_overlays"]["balanced"]
    assert overlay["wager_logged"] is True
    assert overlay["logged_wager_id"] == wager["wager_id"]
    assert overlay["actual_dollars"] == "10.00"

    assert len(a.get("/api/v1/wagers?state=open").json()["wagers"]) == 1
    patched = a.patch(f"/api/v1/wagers/{wager['wager_id']}", json={"status": "WON", "note": "settled manually"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "WON"
    assert a.get("/api/v1/wagers?state=open").json()["wagers"] == []
    assert len(a.get("/api/v1/wagers?state=settled").json()["wagers"]) == 1

    cookies = dict(a.cookies)
    restarted = TestClient(create_app(settings))
    restarted.cookies.update(cookies)
    assert restarted.get("/api/v1/auth/me").json()["user"]["user_id"] == user_a["user_id"]
    persisted = restarted.get(f"/api/v1/wagers/{wager['wager_id']}")
    assert persisted.status_code == 200
    assert persisted.json()["recommended_dollars"] == "7.50"
    assert persisted.json()["actual_dollars"] == "10.00"


def test_obsolete_product_click_is_rejected_not_silently_reattached(tmp_path: Path) -> None:
    client, settings = _client(tmp_path)
    _register(client, "obsolete_user")
    store = client.app.state.product_store
    store.publish(_product(version="backend-test-v2", generated="2026-09-03T15:00:00Z"))
    response = client.post(
        "/api/v1/wagers",
        json={
            "source_type": "HEADLINE",
            "product_version": "backend-test-v1",
            "lane": "BALANCED",
            "idempotency_key": "old-click",
        },
    )
    assert response.status_code == 409
    assert "refresh" in response.json()["detail"].lower()


def test_publication_valid_invalid_partial_atomic_and_concurrent_readers(tmp_path: Path) -> None:
    store = ProductStore(tmp_path)
    first = _product(version="publication-v1", generated="2026-09-03T14:00:00Z")
    store.publish(first)
    old_latest = store.latest_path.read_bytes()

    invalid = deepcopy(first)
    del invalid["schema_version"]
    with pytest.raises(ContractValidationError):
        store.publish(invalid)
    assert store.latest_path.read_bytes() == old_latest
    assert store.snapshot()["product_version"] == "publication-v1"
    status = store.metadata()
    assert status["last_failure"] is not None

    (tmp_path / ".latest-partial-test").write_text('{"broken":', encoding="utf-8")
    assert json.loads(store.latest_path.read_text(encoding="utf-8"))["product_version"] == "publication-v1"

    stop = threading.Event()
    observed: list[str] = []
    failures: list[BaseException] = []

    def reader() -> None:
        try:
            while not stop.is_set():
                raw = json.loads(store.latest_path.read_text(encoding="utf-8"))
                validate_product_snapshot(raw)
                observed.append(raw["product_version"])
        except BaseException as exc:  # pragma: no cover - assertion captures any reader failure
            failures.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for thread in threads:
        thread.start()
    second = _product(version="publication-v2", generated="2026-09-03T15:00:00Z")
    store.publish(second)
    for _ in range(100):
        json.loads(store.latest_path.read_text(encoding="utf-8"))
    stop.set()
    for thread in threads:
        thread.join(timeout=5)
    assert not failures
    assert observed
    assert set(observed) <= {"publication-v1", "publication-v2"}
    assert json.loads(store.latest_path.read_text(encoding="utf-8"))["product_version"] == "publication-v2"


def _exact_request(*, book: str = "DRAFTKINGS", price: int = -115, line=None, market: str = "MONEYLINE", selection: str = "BBB") -> dict:
    return {
        "game_id": "mock-2026-w01-AAA-BBB",
        "market_type": market,
        "selection": selection,
        "book": book,
        "line": line,
        "price": price,
    }


def test_exact_offer_dk_fd_manual_parity_changed_line_and_pinnacle_rejection(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    dk = _exact_request(book="DRAFTKINGS", price=-115)
    fd = _exact_request(book="FANDUEL", price=-112)
    dk_result = client.post("/api/v1/evaluate-offer", json=dk)
    fd_result = client.post("/api/v1/evaluate-offer", json=fd)
    assert dk_result.status_code == 200, dk_result.text
    assert fd_result.status_code == 200, fd_result.text
    assert dk_result.json()["schema_version"] == "NFL_EDGE_EXACT_OFFER_VIEW_V1"
    assert fd_result.json()["schema_version"] == "NFL_EDGE_EXACT_OFFER_VIEW_V1"

    typed_again = client.post("/api/v1/evaluate-offer", json=dict(dk))
    assert typed_again.status_code == 200
    assert typed_again.json()["evaluation"] == dk_result.json()["evaluation"]

    spread_25 = _exact_request(book="DRAFTKINGS", price=-108, line=2.5, market="SPREAD", selection="AAA")
    spread_30 = {**spread_25, "line": 3.0}
    r25 = client.post("/api/v1/evaluate-offer", json=spread_25)
    r30 = client.post("/api/v1/evaluate-offer", json=spread_30)
    assert r25.status_code == 200
    assert r30.status_code == 200
    assert r25.json()["evaluation"] != r30.json()["evaluation"]

    pinnacle = client.post("/api/v1/evaluate-offer", json={**dk, "book": "PINNACLE"})
    assert pinnacle.status_code == 422


def test_exact_offer_is_user_invariant_except_personal_dollars(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    ProductStore(settings.product_dir).publish(_product())
    app = create_app(settings)
    a = TestClient(app)
    b = TestClient(app)
    _register(a, "exact_a")
    _set_profile(a, "500.00", "Normal")
    _register(b, "exact_b")
    _set_profile(b, "2000.00", "Aggressive")

    chosen = None
    result_a = None
    for price in (-115, -105, 100, 120, 150, 200, 300):
        candidate = _exact_request(book="DRAFTKINGS", price=price)
        response = a.post("/api/v1/evaluate-offer", json=candidate)
        assert response.status_code == 200, response.text
        if response.json()["evaluation"]["verdict"] == "BET":
            chosen = candidate
            result_a = response.json()
            break
    assert chosen is not None, "synthetic supported exact offer never became actionable under frozen policy"
    assert result_a is not None
    result_b = b.post("/api/v1/evaluate-offer", json=chosen).json()
    assert result_a["evaluation"] == result_b["evaluation"]
    assert result_a["recommended_dollars"] != result_b["recommended_dollars"]
    assert result_a["recommended_dollars"] is not None
    assert result_b["recommended_dollars"] is not None


def test_exact_offer_missing_benchmark_fails_closed(tmp_path: Path) -> None:
    product = _product(version="unsupported-v1")
    product["games"][0]["market_board"]["moneyline"].pop("PINNACLE")
    validate_product_snapshot(product)
    client, _ = _client(tmp_path, product)
    result = client.post("/api/v1/evaluate-offer", json=_exact_request())
    assert result.status_code == 200
    evaluation = result.json()["evaluation"]
    assert evaluation["supported"] is False
    assert evaluation["verdict"] == "UNSUPPORTED"
    assert evaluation["recommended_units"] == 0


def test_http_requests_do_not_score_acquire_materialize_or_generate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import requests
    from nfl_edge.live import markets_2026, product_2026, product_state_2026, scorer_2026

    def forbidden(*args, **kwargs):
        raise AssertionError("forbidden live/scoring/materialization path invoked by HTTP request")

    monkeypatch.setattr(requests, "get", forbidden)
    monkeypatch.setattr(requests, "post", forbidden)
    monkeypatch.setattr(markets_2026, "acquire_live_response", forbidden)
    monkeypatch.setattr(scorer_2026, "score_week1", forbidden)
    monkeypatch.setattr(product_state_2026, "materialize_entering_2026_product_state", forbidden)
    monkeypatch.setattr(product_2026, "build_product_snapshot", forbidden)

    client, _ = _client(tmp_path)
    _register(client, "guard_user")
    _set_profile(client, "1000.00", "Normal")
    assert client.get("/api/v1/product/latest").status_code == 200
    assert client.get("/api/v1/games").status_code == 200
    assert client.post("/api/v1/evaluate-offer", json=_exact_request()).status_code == 200
    assert client.post(
        "/api/v1/wagers",
        json={
            "source_type": "HEADLINE",
            "product_version": "backend-test-v1",
            "lane": "BALANCED",
            "idempotency_key": "guard-wager",
        },
    ).status_code == 201


def test_cookie_security_origin_guard_and_no_sensitive_fields(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.post("/api/v1/auth/register", json={"username": "security_user", "password": "secure password 123"})
    assert response.status_code == 201
    cookie = response.headers.get("set-cookie", "")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    body = json.dumps(response.json()).lower()
    assert "password_hash" not in body
    assert "token_hash" not in body
    assert "session_id" not in body

    rejected = client.put(
        "/api/v1/profile",
        json={"bankroll": "100.00"},
        headers={"origin": "https://evil.example"},
    )
    assert rejected.status_code == 403


def test_zero_odds_api_credential_required_for_backend_ci() -> None:
    assert not os.getenv("ODDS_API_KEY")
    backend = (ROOT / "src/nfl_edge/backend").read_text() if (ROOT / "src/nfl_edge/backend").is_file() else None
    assert backend is None  # package directory, not a credential-bearing file
