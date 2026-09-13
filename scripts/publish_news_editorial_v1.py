#!/usr/bin/env python3
"""Deterministically promote a staged Daily News editorial submission.

This command is the only bridge from the backend's editorial inbox into the
published Daily News runtime. It never invokes a model or a provider.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from nfl_edge.backend.news_editorial import validate_editorial_submission
from nfl_edge.news.pipeline_v1 import NewsPipelineError, _atomic_json, _load_object, _parse_utc, verify_article

FRESHNESS_LIMIT = timedelta(minutes=45)


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _submission_id(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _archive_name(article: Mapping[str, Any]) -> str:
    published = str(article["published_at_utc"]).replace(":", "").replace("-", "")
    return f"{published}.json"


def _packet(submission: Mapping[str, Any], previous_article: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "schema_version": "NFL_EDGE_DAILY_NEWS_RESEARCH_V1",
        "generated_at_utc": submission["research_generated_at_utc"],
        "editorial_rule": "Personality strong, evidence strict.",
        "audience": "NFL EDGE users",
        "card_context": {},
        "evidence": submission["evidence"],
        "writer_rules": {},
        "previous_article": previous_article,
    }


def _require_fresh(submission: Mapping[str, Any], now_utc: datetime) -> None:
    now = now_utc.astimezone(timezone.utc)
    for field in ("submitted_at_utc", "research_generated_at_utc"):
        value = _parse_utc(str(submission[field]))
        age = now - value
        if age > FRESHNESS_LIMIT or age < -FRESHNESS_LIMIT:
            raise NewsPipelineError(f"editorial submission {field} is outside the 45-minute freshness window")


def publish_editorial_submission(
    *, runtime_root: Path, inbox_path: Path | None = None, now_utc: datetime | None = None
) -> dict[str, Any]:
    """Verify and atomically promote one inbox candidate without replacing last-good on failure."""
    root = Path(runtime_root)
    inbox = Path(inbox_path) if inbox_path is not None else root / "editorial_submissions" / "candidate.json"
    if not inbox.is_file():
        raise NewsPipelineError(f"editorial submission inbox is missing: {inbox}")
    try:
        submission = validate_editorial_submission(_load_object(inbox))
    except ValueError as exc:
        raise NewsPipelineError(str(exc)) from exc
    article = dict(submission["article"])
    submission_id = _submission_id(submission)
    submissions_archive = root / "editorial_submissions" / "archive" / f"{submission_id}.json"
    latest = root / "latest.json"
    if submissions_archive.exists():
        if _load_object(submissions_archive) != submission:
            raise NewsPipelineError(f"editorial submission archive conflict: {submissions_archive}")
        if latest.exists() and _load_object(latest) == article:
            return {
                "schema_version": "NFL_EDGE_DAILY_NEWS_EDITORIAL_PUBLISH_RESULT_V1",
                "status": "NOOP_ALREADY_PUBLISHED",
                "submission_id": submission_id,
                "latest_path": str(latest),
            }

    now = now_utc or datetime.now(timezone.utc)
    _require_fresh(submission, now)
    previous_article = _load_object(latest) if latest.exists() else None
    packet = _packet(submission, previous_article)
    verify_article(article, packet)

    # Candidate and archives are diagnostic records; latest is promoted only after
    # all validation and immutable archive conflict checks have passed.
    _atomic_json(root / "candidate.json", article)
    public_archive = root / "archive" / _archive_name(article)
    if public_archive.exists():
        if _load_object(public_archive) != article:
            raise NewsPipelineError(f"article archive conflict: {public_archive}")
    else:
        _atomic_json(public_archive, article)
    if not submissions_archive.exists():
        _atomic_json(submissions_archive, submission)
    _atomic_json(latest, article)
    return {
        "schema_version": "NFL_EDGE_DAILY_NEWS_EDITORIAL_PUBLISH_RESULT_V1",
        "status": "PUBLISHED",
        "submission_id": submission_id,
        "latest_path": str(latest),
        "archive_path": str(public_archive),
        "submission_archive_path": str(submissions_archive),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a staged NFL EDGE Daily News editorial submission.")
    parser.add_argument("--runtime-root", default=os.getenv("NFL_EDGE_NEWS_RUNTIME_ROOT", "/var/lib/nfl-edge/news_v1"))
    parser.add_argument(
        "--inbox-path",
        default=os.getenv(
            "NFL_EDGE_NEWS_EDITORIAL_INBOX_PATH",
            "/var/lib/nfl-edge/news_v1/editorial_inbox/latest.json",
        ),
    )
    args = parser.parse_args()
    try:
        result = publish_editorial_submission(runtime_root=Path(args.runtime_root), inbox_path=Path(args.inbox_path))
    except NewsPipelineError as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
