from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nfl_edge.news.pipeline_v1 import NewsPipelineError

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "publish_news_editorial_v1.py"
SPEC = importlib.util.spec_from_file_location("publish_news_editorial_v1", SCRIPT)
assert SPEC and SPEC.loader
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


def _submission(now: datetime) -> dict[str, object]:
    stamp = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": "NFL_EDGE_DAILY_NEWS_EDITORIAL_SUBMISSION_V1",
        "submitted_at_utc": stamp,
        "research_generated_at_utc": stamp,
        "article": {
            "schema_version": "NFL_EDGE_DAILY_NEWS_V1",
            "published_at_utc": stamp,
            "title": "NFL EDGE Editorial Brief",
            "sections": [
                {
                    "id": "what-matters",
                    "title": "What Matters Today",
                    "items": [
                        {
                            "headline": "Verified update",
                            "paragraphs": ["The official update is relevant to the current card."],
                            "evidence_ids": ["official:1"],
                            "sources": [{"label": "NFL", "url": "https://www.nfl.com/example"}],
                        }
                    ],
                }
            ],
        },
        "evidence": [
            {
                "evidence_id": "official:1",
                "fact": "The official report changed.",
                "sources": [{"label": "NFL", "url": "https://www.nfl.com/example"}],
            }
        ],
    }


def _stage(root: Path, submission: dict[str, object]) -> Path:
    inbox = root / "editorial_submissions" / "candidate.json"
    inbox.parent.mkdir(parents=True)
    inbox.write_text(json.dumps(submission), encoding="utf-8")
    return inbox


def test_publisher_promotes_verified_fresh_submission_and_is_idempotent(tmp_path: Path) -> None:
    now = datetime(2026, 9, 13, 6, 30, tzinfo=timezone.utc)
    submission = _submission(now)
    _stage(tmp_path, submission)

    first = publisher.publish_editorial_submission(runtime_root=tmp_path, now_utc=now)
    latest_bytes = (tmp_path / "latest.json").read_bytes()
    second = publisher.publish_editorial_submission(runtime_root=tmp_path, now_utc=now)

    assert first["status"] == "PUBLISHED"
    assert second["status"] == "NOOP_ALREADY_PUBLISHED"
    assert (tmp_path / "latest.json").read_bytes() == latest_bytes
    assert list((tmp_path / "archive").glob("*.json"))
    assert list((tmp_path / "editorial_submissions" / "archive").glob("*.json"))
    assert json.loads(latest_bytes) == submission["article"]


def test_publisher_keeps_last_good_when_evidence_or_source_is_invalid(tmp_path: Path) -> None:
    now = datetime(2026, 9, 13, 6, 30, tzinfo=timezone.utc)
    old = {
        "schema_version": "NFL_EDGE_DAILY_NEWS_V1",
        "published_at_utc": "2026-09-13T06:00:00Z",
        "title": "Last good",
        "sections": [],
    }
    (tmp_path / "latest.json").write_text(json.dumps(old), encoding="utf-8")
    submission = _submission(now)
    article = submission["article"]
    assert isinstance(article, dict)
    article["sections"][0]["items"][0]["sources"] = [{"label": "Other", "url": "https://example.com/not-evidence"}]
    _stage(tmp_path, submission)

    with pytest.raises(NewsPipelineError, match="source not present"):
        publisher.publish_editorial_submission(runtime_root=tmp_path, now_utc=now)

    assert json.loads((tmp_path / "latest.json").read_text(encoding="utf-8")) == old
    assert not (tmp_path / "candidate.json").exists()
    assert not (tmp_path / "archive").exists()


def test_publisher_rejects_stale_submission_without_replacing_last_good(tmp_path: Path) -> None:
    now = datetime(2026, 9, 13, 6, 30, tzinfo=timezone.utc)
    old = {
        "schema_version": "NFL_EDGE_DAILY_NEWS_V1",
        "published_at_utc": "2026-09-13T06:00:00Z",
        "title": "Last good",
        "sections": [],
    }
    (tmp_path / "latest.json").write_text(json.dumps(old), encoding="utf-8")
    submission = _submission(now - timedelta(minutes=46))
    _stage(tmp_path, submission)

    with pytest.raises(NewsPipelineError, match="45-minute freshness"):
        publisher.publish_editorial_submission(runtime_root=tmp_path, now_utc=now)

    assert json.loads((tmp_path / "latest.json").read_text(encoding="utf-8")) == old


def test_publisher_rejects_external_evidence_without_sources(tmp_path: Path) -> None:
    now = datetime(2026, 9, 13, 6, 30, tzinfo=timezone.utc)
    old = {
        "schema_version": "NFL_EDGE_DAILY_NEWS_V1",
        "published_at_utc": "2026-09-13T06:00:00Z",
        "title": "Last good",
        "sections": [],
    }
    (tmp_path / "latest.json").write_text(json.dumps(old), encoding="utf-8")
    submission = _submission(now)
    evidence = submission["evidence"]
    assert isinstance(evidence, list)
    evidence[0]["sources"] = []
    article = submission["article"]
    assert isinstance(article, dict)
    article["sections"][0]["items"][0]["sources"] = []
    _stage(tmp_path, submission)

    with pytest.raises(NewsPipelineError, match="source"):
        publisher.publish_editorial_submission(runtime_root=tmp_path, now_utc=now)

    assert json.loads((tmp_path / "latest.json").read_text(encoding="utf-8")) == old
    assert not (tmp_path / "candidate.json").exists()
