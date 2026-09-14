#!/usr/bin/env python3
"""Fetch, validate, and stage a ChatGPT-authored Daily News editorial unchanged.

This courier never generates, edits, publishes, or promotes editorial content.
It reads exactly one Git object, validates it with the existing submission
validator, and sends those exact bytes to the existing authenticated ingest.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from nfl_edge.backend.news_editorial import validate_editorial_submission
from nfl_edge.news.pipeline_v1 import _parse_utc

SOURCE_BRANCH = "ops/daily-news-editorial-v1"
SOURCE_PATH = "news/editorial/inbox/latest.json"
DEFAULT_REMOTE_URL = "https://github.com/Tkcool28/nfl-edge.git"
DEFAULT_CACHE_REPO = Path("/var/lib/nfl-edge-news-editorial-courier/source.git")
FRESHNESS_LIMIT = timedelta(minutes=45)
RECEIPT_SCHEMA = "NFL_EDGE_DAILY_NEWS_EDITORIAL_COURIER_RECEIPT_V1"


class CourierError(RuntimeError):
    """A fail-closed courier error safe to report without response bodies."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _canonical_submission_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_fresh(submission: Mapping[str, Any], now_utc: datetime) -> None:
    now = now_utc.astimezone(timezone.utc)
    for field in ("submitted_at_utc", "research_generated_at_utc"):
        try:
            age = now - _parse_utc(str(submission[field]))
        except (KeyError, ValueError, TypeError) as exc:
            raise CourierError(f"editorial submission has invalid {field}") from exc
        if age > FRESHNESS_LIMIT or age < -FRESHNESS_LIMIT:
            raise CourierError(f"editorial submission {field} is outside the 45-minute freshness window")


def _run_git(repo: Path, args: list[str]) -> bytes:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CourierError("editorial source fetch or read failed") from exc


def _ensure_bare_cache(repo: Path) -> None:
    """Initialize only the courier-owned bare cache; never touch a checkout."""
    if not repo.exists():
        try:
            repo.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "init", "--bare", str(repo)],
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise CourierError("editorial source cache initialization failed") from exc
    if _run_git(repo, ["rev-parse", "--is-bare-repository"]).strip() != b"true":
        raise CourierError("editorial source cache is not a bare Git repository")


def fetch_source(repo: Path, remote_url: str = DEFAULT_REMOTE_URL) -> tuple[str, bytes]:
    """Fetch only the editorial ref into a courier-owned bare cache."""
    if not remote_url:
        raise CourierError("editorial source remote is not configured")
    _ensure_bare_cache(repo)
    remote_ref = f"refs/remotes/origin/{SOURCE_BRANCH}"
    _run_git(repo, ["fetch", "--no-tags", remote_url, f"+refs/heads/{SOURCE_BRANCH}:{remote_ref}"])
    source_sha = _run_git(repo, ["rev-parse", f"{remote_ref}^{{commit}}"]).decode("ascii").strip()
    raw = _run_git(repo, ["show", f"{source_sha}:{SOURCE_PATH}"])
    if not raw:
        raise CourierError("editorial source JSON is empty")
    return source_sha, raw


def validate_source(raw: bytes, now_utc: datetime) -> tuple[dict[str, Any], str]:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CourierError("editorial source JSON is invalid") from exc
    if not isinstance(parsed, dict):
        raise CourierError("editorial source JSON must be an object")
    try:
        submission = validate_editorial_submission(parsed)
    except ValueError as exc:
        raise CourierError(str(exc)) from exc
    _require_fresh(submission, now_utc)
    return submission, _sha256(_canonical_submission_bytes(submission))


def _read_receipt(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CourierError("editorial courier receipt is unreadable") from exc
    if not isinstance(value, dict) or value.get("schema_version") != RECEIPT_SCHEMA:
        raise CourierError("editorial courier receipt is invalid")
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(_canonical_submission_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def stage_exact_json(*, endpoint: str, token: str, raw: bytes, expected_submission_sha: str) -> None:
    if not token:
        raise CourierError("editorial ingest token is not configured")
    request = Request(
        endpoint,
        data=raw,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            if response.status != 202:
                raise CourierError("editorial ingest did not confirm staging")
            try:
                body = json.loads(response.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CourierError("editorial ingest returned an invalid staging confirmation") from exc
    except HTTPError as exc:
        raise CourierError(f"editorial ingest failed closed with HTTP {exc.code}") from exc
    except (URLError, OSError) as exc:
        raise CourierError("editorial ingest delivery failed") from exc
    confirmed = (
        isinstance(body, dict)
        and body.get("status") == "STAGED"
        and body.get("submission_sha256") == expected_submission_sha
    )
    if not confirmed:
        raise CourierError("editorial ingest did not confirm the expected submission")


def run_courier(
    *,
    repo: Path,
    receipt_path: Path,
    endpoint: str,
    token: str,
    now_utc: datetime | None = None,
    source_loader: Callable[[Path], tuple[str, bytes]] = fetch_source,
    stage: Callable[..., None] = stage_exact_json,
) -> dict[str, str]:
    """Perform one fail-closed, idempotent courier attempt."""
    source_sha, raw = source_loader(Path(repo))
    submission, submission_sha = validate_source(raw, now_utc or _utc_now())
    source_sha256 = _sha256(raw)
    existing = _read_receipt(receipt_path)
    already_staged = (
        existing is not None
        and existing.get("source_git_sha") == source_sha
        and existing.get("submission_sha256") == submission_sha
    )
    if already_staged:
        return {
            "schema_version": RECEIPT_SCHEMA,
            "status": "NOOP_ALREADY_STAGED",
            "source_git_sha": source_sha,
            "source_sha256": source_sha256,
            "submission_sha256": submission_sha,
        }
    stage(endpoint=endpoint, token=token, raw=raw, expected_submission_sha=submission_sha)
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "status": "STAGED",
        "source_git_sha": source_sha,
        "source_sha256": source_sha256,
        "submission_sha256": submission_sha,
        "staged_at_utc": (now_utc or _utc_now()).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _atomic_json(receipt_path, receipt)
    return {key: str(value) for key, value in receipt.items()}


def main() -> int:
    repo = Path(os.getenv("NFL_EDGE_EDITORIAL_COURIER_REPO", str(DEFAULT_CACHE_REPO)))
    remote_url = os.getenv("NFL_EDGE_EDITORIAL_COURIER_REMOTE_URL", DEFAULT_REMOTE_URL)
    receipt_path = Path(
        os.getenv("NFL_EDGE_EDITORIAL_COURIER_RECEIPT_PATH", "/var/lib/nfl-edge-news-editorial-courier/receipt.json")
    )
    port = os.getenv("NFL_EDGE_BACKEND_PORT", "8769")
    endpoint = os.getenv("NFL_EDGE_EDITORIAL_INGEST_URL", f"http://127.0.0.1:{port}/api/v1/news/editorial")
    try:
        result = run_courier(
            repo=repo,
            receipt_path=receipt_path,
            endpoint=endpoint,
            token=os.getenv("NFL_EDGE_NEWS_EDITORIAL_TOKEN", ""),
            source_loader=lambda cache_repo: fetch_source(cache_repo, remote_url),
        )
    except CourierError as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
