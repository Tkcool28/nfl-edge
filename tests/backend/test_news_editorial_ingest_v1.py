from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from nfl_edge.backend.app import create_app
from nfl_edge.backend.settings import BackendSettings

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "data/live/2026/entering_product_state_v1.json"


def _article() -> dict[str, object]:
    return {
        "schema_version": "NFL_EDGE_DAILY_NEWS_V1",
        "published_at_utc": "2026-09-13T06:30:00Z",
        "title": "NFL EDGE Morning Brief",
        "sections": [
            {
                "id": "what-matters",
                "title": "What Matters Today",
                "items": [
                    {
                        "headline": "Availability update",
                        "paragraphs": ["A verified availability update matters for the current card."],
                        "evidence_ids": ["availability:1"],
                        "sources": [{"label": "NFL", "url": "https://www.nfl.com/example"}],
                    }
                ],
            }
        ],
    }


def _submission() -> dict[str, object]:
    return {
        "schema_version": "NFL_EDGE_DAILY_NEWS_EDITORIAL_SUBMISSION_V1",
        "submitted_at_utc": "2026-09-13T06:30:00Z",
        "research_generated_at_utc": "2026-09-13T06:30:00Z",
        "article": _article(),
        "evidence": [
            {
                "evidence_id": "availability:1",
                "fact": "The official injury report changed.",
                "sources": [{"label": "NFL", "url": "https://www.nfl.com/example"}],
            }
        ],
    }


def _settings(tmp_path: Path, token: str = "editorial-secret") -> BackendSettings:
    return BackendSettings(
        db_path=tmp_path / "users.sqlite3",
        product_dir=tmp_path / "product",
        decision_state_path=STATE,
        news_latest_path=tmp_path / "news" / "latest.json",
        news_editorial_inbox_path=tmp_path / "news" / "editorial_inbox" / "latest.json",
        news_editorial_bearer_token=token,
        cookie_secure=False,
        allowed_origin="http://testserver",
        allowed_hosts=("testserver",),
    )


def test_editorial_ingest_requires_bearer_and_stages_only_inbox(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    client = TestClient(create_app(settings))
    payload = _submission()

    assert client.post("/api/v1/news/editorial", json=payload).status_code == 401
    assert client.post(
        "/api/v1/news/editorial", json=payload, headers={"Authorization": "Bearer wrong"}
    ).status_code == 401

    response = client.post(
        "/api/v1/news/editorial", json=payload, headers={"Authorization": "Bearer editorial-secret"}
    )

    assert response.status_code == 202
    assert set(response.json()) == {"status", "submission_sha256"}
    assert response.json()["status"] == "STAGED"
    assert json.loads(settings.news_editorial_inbox_path.read_text(encoding="utf-8")) == payload
    assert not settings.news_latest_path.exists()
    assert not (tmp_path / "news" / "candidate.json").exists()
    assert not (tmp_path / "news" / "archive").exists()


def test_editorial_ingest_is_disabled_without_configured_token(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path, token="")))

    response = client.post(
        "/api/v1/news/editorial", json=_submission(), headers={"Authorization": "Bearer anything"}
    )

    assert response.status_code == 404


def test_editorial_ingest_rejects_non_strict_or_oversize_json(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    headers = {"Authorization": "Bearer editorial-secret", "Content-Type": "application/json"}

    duplicate = '{"schema_version":"x","schema_version":"y"}'
    assert client.post("/api/v1/news/editorial", content=duplicate, headers=headers).status_code == 422
    assert client.post(
        "/api/v1/news/editorial", content=b"{" + (b" " * 1_500_000) + b"}", headers=headers
    ).status_code == 413


def test_editorial_ingest_rejects_external_evidence_without_sources(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    payload = _submission()
    evidence = payload["evidence"]
    assert isinstance(evidence, list)
    evidence[0]["sources"] = []
    article = payload["article"]
    assert isinstance(article, dict)
    article["sections"][0]["items"][0]["sources"] = []

    response = client.post(
        "/api/v1/news/editorial",
        json=payload,
        headers={"Authorization": "Bearer editorial-secret"},
    )

    assert response.status_code == 422
    assert "source" in response.json()["detail"].lower()


def test_editorial_ingest_rejects_external_evidence_item_without_article_source(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    payload = _submission()
    article = payload["article"]
    assert isinstance(article, dict)
    article["sections"][0]["items"][0]["sources"] = []

    response = client.post(
        "/api/v1/news/editorial",
        json=payload,
        headers={"Authorization": "Bearer editorial-secret"},
    )

    assert response.status_code == 422
    assert "external evidence" in response.json()["detail"].lower()


def test_editorial_ingest_rejects_oversize_chunked_body_without_content_length(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    headers = {"Authorization": "Bearer editorial-secret", "Content-Type": "application/json"}

    def chunks():
        yield b'{"padding":"'
        for _ in range(4):
            yield b"x" * 500_000
        yield b'"}'

    response = client.post("/api/v1/news/editorial", content=chunks(), headers=headers)

    assert response.status_code == 413
