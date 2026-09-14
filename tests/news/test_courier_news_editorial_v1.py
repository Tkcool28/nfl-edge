from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "courier_news_editorial_v1.py"
SPEC = importlib.util.spec_from_file_location("courier_news_editorial_v1", SCRIPT)
assert SPEC and SPEC.loader
courier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(courier)


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


def _raw(value: dict[str, object]) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def test_courier_stages_exact_git_bytes_and_writes_non_secret_receipt(tmp_path: Path) -> None:
    now = datetime(2026, 9, 14, 15, 33, 35, tzinfo=timezone.utc)
    raw = _raw(_submission(now))
    calls: list[dict[str, object]] = []

    def source_loader(_: Path) -> tuple[str, bytes]:
        return "a" * 40, raw

    def stage(**kwargs: object) -> None:
        calls.append(kwargs)

    result = courier.run_courier(
        repo=tmp_path,
        receipt_path=tmp_path / "receipt.json",
        endpoint="http://127.0.0.1:8769/api/v1/news/editorial",
        token="secret-not-in-receipt",
        now_utc=now,
        source_loader=source_loader,
        stage=stage,
    )

    assert result["status"] == "STAGED"
    assert len(calls) == 1
    assert calls[0]["raw"] == raw
    receipt = json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["source_git_sha"] == "a" * 40
    assert receipt["source_sha256"] == courier._sha256(raw)
    assert receipt["submission_sha256"] == calls[0]["expected_submission_sha"]
    assert "secret-not-in-receipt" not in (tmp_path / "receipt.json").read_text(encoding="utf-8")


def test_courier_fails_closed_on_stale_or_invalid_source_without_delivery(tmp_path: Path) -> None:
    now = datetime(2026, 9, 14, 15, 33, 35, tzinfo=timezone.utc)
    stale = _raw(_submission(now - timedelta(minutes=46)))
    delivered = False

    def stage(**_: object) -> None:
        nonlocal delivered
        delivered = True

    with pytest.raises(courier.CourierError, match="45-minute freshness"):
        courier.run_courier(
            repo=tmp_path,
            receipt_path=tmp_path / "receipt.json",
            endpoint="http://127.0.0.1:8769/api/v1/news/editorial",
            token="configured",
            now_utc=now,
            source_loader=lambda _: ("b" * 40, stale),
            stage=stage,
        )
    assert not delivered
    assert not (tmp_path / "receipt.json").exists()

    with pytest.raises(courier.CourierError, match="schema validation failed"):
        courier.run_courier(
            repo=tmp_path,
            receipt_path=tmp_path / "receipt.json",
            endpoint="http://127.0.0.1:8769/api/v1/news/editorial",
            token="configured",
            now_utc=now,
            source_loader=lambda _: ("c" * 40, b'{"schema_version":"wrong"}'),
            stage=stage,
        )
    assert not delivered


def test_courier_is_idempotent_for_confirmed_source_and_submission(tmp_path: Path) -> None:
    now = datetime(2026, 9, 14, 15, 33, 35, tzinfo=timezone.utc)
    raw = _raw(_submission(now))
    calls = 0

    def stage(**_: object) -> None:
        nonlocal calls
        calls += 1

    args = dict(
        repo=tmp_path,
        receipt_path=tmp_path / "receipt.json",
        endpoint="http://127.0.0.1:8769/api/v1/news/editorial",
        token="configured",
        now_utc=now,
        source_loader=lambda _: ("d" * 40, raw),
        stage=stage,
    )
    assert courier.run_courier(**args)["status"] == "STAGED"
    assert courier.run_courier(**args)["status"] == "NOOP_ALREADY_STAGED"
    assert calls == 1


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args],
        check=True,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout


def test_fetch_source_initializes_and_writes_only_dedicated_bare_cache(tmp_path: Path) -> None:
    now = datetime(2026, 9, 14, 15, 33, 35, tzinfo=timezone.utc)
    remote = tmp_path / "remote.git"
    writer = tmp_path / "writer"
    _git("init", "--bare", str(remote))
    _git("init", str(writer))
    _git("config", "user.email", "courier-test@example.invalid", cwd=writer)
    _git("config", "user.name", "Courier Test", cwd=writer)
    source_path = writer / courier.SOURCE_PATH
    source_path.parent.mkdir(parents=True)
    raw = _raw(_submission(now))
    source_path.write_bytes(raw)
    _git("add", courier.SOURCE_PATH, cwd=writer)
    _git("commit", "-m", "editorial", cwd=writer)
    _git("branch", "-M", courier.SOURCE_BRANCH, cwd=writer)
    _git("remote", "add", "origin", str(remote), cwd=writer)
    _git("push", "origin", f"HEAD:refs/heads/{courier.SOURCE_BRANCH}", cwd=writer)

    cache = tmp_path / "runtime" / "editorial_courier" / "source.git"
    source_sha, fetched_raw = courier.fetch_source(cache, str(remote))

    assert fetched_raw == raw
    assert source_sha == _git("rev-parse", "HEAD", cwd=writer).strip()
    assert _git("rev-parse", "--is-bare-repository", cwd=cache).strip() == "true"
    assert _git("rev-parse", f"refs/remotes/origin/{courier.SOURCE_BRANCH}", cwd=cache).strip() == source_sha
    assert not (cache / "news").exists()


def test_service_grants_git_cache_write_path_not_production_git_metadata() -> None:
    unit = (ROOT / "deploy/systemd/nfl-edge-news-editorial-courier.service").read_text(encoding="utf-8")
    cache = "/var/lib/nfl-edge-news-editorial-courier/source.git"
    assert f"NFL_EDGE_EDITORIAL_COURIER_REPO={cache}" in unit
    assert "StateDirectory=nfl-edge-news-editorial-courier" in unit
    assert "ReadWritePaths=/var/lib/nfl-edge-news-editorial-courier" in unit
    assert "/root/nfl-edge/.git" not in unit
    assert "ProtectHome=read-only" in unit
