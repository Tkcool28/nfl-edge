from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from nfl_edge.backend.app import create_app
from nfl_edge.backend.publication import ProductStore
from nfl_edge.backend.settings import BackendSettings
from nfl_edge.value.play_through import assess_play_through

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


def test_manual_moneyline_targets_do_not_chase_entered_price(tmp_path: Path) -> None:
    client = _client(tmp_path)
    evaluations = []
    for price in (-115, -150, -200, -300):
        response = client.post("/api/v1/evaluate-offer", json=_offer(book="MANUAL", price=price))
        assert response.status_code == 200, response.text
        evaluation = response.json()["evaluation"]
        assert evaluation["verdict"] != "TARGET_ONLY"
        assert evaluation["value_at"] is None
        evaluations.append(evaluation)

    # This fixture is allowed to have no published Play Through target. What must
    # remain invariant across entered prices is the model/trust probability surface.
    assert len({evaluation["probability"] for evaluation in evaluations}) == 1
    assert len({evaluation["trust_probability"] for evaluation in evaluations}) == 1
    non_null_targets = [evaluation["play_through"] for evaluation in evaluations if evaluation["play_through"] is not None]
    assert len({json.dumps(target, sort_keys=True) for target in non_null_targets}) <= 1


def test_play_through_threshold_is_independent_of_current_entered_price() -> None:
    # The frozen Play Through threshold is determined by conditional non-push
    # probability, reliability, and uncertainty. Current price only changes the
    # status classification through its break-even probability.
    assessments = [
        assess_play_through(
            supported=True,
            strict_expected_value=ev,
            conditional_nonpush_probability=0.62,
            current_break_even_probability=break_even,
            reliability="HIGH",
            uncertainty_radius=0.02,
        )
        for ev, break_even in ((0.20, 0.53), (0.10, 0.60), (-0.02, 0.67), (-0.08, 0.75))
    ]
    first = assessments[0]
    assert first.play_through_price_american is not None
    assert all(a.play_through_price_american == first.play_through_price_american for a in assessments[1:])
    assert all(a.play_through_break_even_probability == first.play_through_break_even_probability for a in assessments[1:])


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
