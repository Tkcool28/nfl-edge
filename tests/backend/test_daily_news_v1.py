from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from nfl_edge.backend.app import create_app
from nfl_edge.backend.settings import BackendSettings

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "data/live/2026/entering_product_state_v1.json"


def _settings(tmp_path: Path) -> BackendSettings:
    return BackendSettings(
        db_path=tmp_path / "users.sqlite3",
        product_dir=tmp_path / "product",
        decision_state_path=STATE,
        news_latest_path=tmp_path / "news" / "latest.json",
        cookie_secure=False,
        allowed_origin="http://testserver",
        allowed_hosts=("testserver",),
    )


def test_news_latest_serves_valid_artifact(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.news_latest_path.parent.mkdir(parents=True)
    payload = {
        "schema_version": "NFL_EDGE_DAILY_NEWS_V1",
        "published_at_utc": "2026-09-13T00:20:00Z",
        "edition": "Saturday Night Check",
        "title": "NFL EDGE Saturday Night Brief",
        "sections": [],
    }
    settings.news_latest_path.write_text(json.dumps(payload), encoding="utf-8")

    response = TestClient(create_app(settings)).get("/api/v1/news/latest")

    assert response.status_code == 200
    assert response.json() == payload


def test_missing_news_fails_news_only(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    client = TestClient(create_app(settings))

    response = client.get("/api/v1/news/latest")

    assert response.status_code == 404
    assert response.json() == {"detail": "daily news not published yet"}


def test_invalid_news_fails_closed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.news_latest_path.parent.mkdir(parents=True)
    settings.news_latest_path.write_text(
        json.dumps(
            {
                "schema_version": "WRONG",
                "published_at_utc": "2026-09-13T00:20:00Z",
                "title": "Bad artifact",
                "sections": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(settings))

    response = client.get("/api/v1/news/latest")

    assert response.status_code == 503
    assert response.json() == {"detail": "daily news temporarily unavailable"}
