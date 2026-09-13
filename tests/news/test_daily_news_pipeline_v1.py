from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nfl_edge.news.pipeline_v1 import (
    NewsPipelineError,
    _previous_research_view,
    build_card_context,
    run_pipeline,
    verify_article,
)


def _evidence_root(tmp_path: Path) -> Path:
    root = tmp_path / "evidence"
    week = root / "prospective/cards/2026/week-01"
    pubs = week / "publications"
    pubs.mkdir(parents=True)
    (pubs / "a.json").write_text(
        json.dumps(
            {
                "season": 2026,
                "week": 1,
                "publication_id": "p1",
                "published_at_utc": "2026-09-12T12:20:00Z",
            }
        ),
        encoding="utf-8",
    )
    (pubs / "b.json").write_text(
        json.dumps(
            {
                "season": 2026,
                "week": 1,
                "publication_id": "p2",
                "published_at_utc": "2026-09-13T00:20:00Z",
            }
        ),
        encoding="utf-8",
    )
    (week / "episodes.json").write_text(
        json.dumps(
            {
                "episodes": [
                    {
                        "episode_id": "e1",
                        "lane": "BALANCED",
                        "state": "OPEN",
                        "selection": "MIN",
                        "market": "MONEYLINE",
                        "book": "DRAFTKINGS",
                        "kickoff_at_utc": "2026-09-13T20:25:00Z",
                        "returned_after_gap": False,
                        "terminal_reason": None,
                        "observations": [
                            {"published_at_utc": "2026-09-12T12:20:00Z", "american_odds": -122},
                            {"published_at_utc": "2026-09-13T00:20:00Z", "american_odds": -125},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return root


def _script(path: Path, body: str) -> str:
    path.write_text(body, encoding="utf-8")
    return f"{sys.executable} {path}"


def test_card_context_uses_latest_and_previous_observation(tmp_path: Path) -> None:
    context = build_card_context(_evidence_root(tmp_path))
    assert context["latest_publication_id"] == "p2"
    assert context["previous_publication_id"] == "p1"
    assert context["episodes"][0]["latest"]["american_odds"] == -125
    assert context["episodes"][0]["previous"]["american_odds"] == -122
    assert context["provider_calls"] == 0


def test_pipeline_publishes_only_verified_article(tmp_path: Path) -> None:
    evidence = _evidence_root(tmp_path)
    runtime = tmp_path / "runtime"
    research = _script(
        tmp_path / "research.py",
        """import json,sys
request=json.load(sys.stdin)
assert request["schema_version"]=="NFL_EDGE_DAILY_NEWS_RESEARCH_REQUEST_V1"
assert request["card_context"]["latest_publication_id"]=="p2"
assert request["previous_article"] is None
assert request["previous_research"] is None
print(json.dumps({"schema_version":"NFL_EDGE_DAILY_NEWS_EXTERNAL_RESEARCH_V1","evidence":[{"evidence_id":"injury:1","category":"injury","verification":"OFFICIAL","fact":"Player is out.","interpretation":"Availability changed.","app_guidance":"Re-check the current card.","sources":[{"label":"NFL","url":"https://www.nfl.com/example"}]}]}))
""",
    )
    writer = _script(
        tmp_path / "writer.py",
        """import json,sys
packet=json.load(sys.stdin)
article={"schema_version":"NFL_EDGE_DAILY_NEWS_V1","published_at_utc":"2026-09-13T00:20:00Z","edition":"Saturday Night Check","title":"NFL EDGE Saturday Night Brief","sections":[
{"id":"what-matters","title":"What Matters Today","icon":"🏈","items":[{"headline":"Availability changed","paragraphs":["A player was ruled out."],"takeaway":"Re-check the current card.","evidence_ids":["injury:1"],"sources":[{"label":"NFL","url":"https://www.nfl.com/example"}]}]},
{"id":"fade","title":"The Fade","icon":"🔥","items":[{"headline":"No strong split tonight","paragraphs":["There is no verified retail-versus-sharper split worth forcing."],"takeaway":"Do not manufacture a Fade. Use the current NFL EDGE card and wait for a verified price signal before changing timing.","evidence_ids":["card:latest-prospective-context"],"sources":[]}]},
{"id":"market-watch","title":"Market Watch","icon":"📈","items":[{"headline":"Minnesota got more expensive","paragraphs":["The tracked price moved from -122 to -125."],"takeaway":"Check the current Play Through before betting.","evidence_ids":["card:latest-prospective-context"],"sources":[]}]},
{"id":"today-tip","title":"Today's Tip","icon":"💡","items":[{"headline":"Price matters","paragraphs":["The same team at a worse price is a different bet."],"takeaway":"Use the current number, not a screenshot from yesterday.","editorial_only":True,"evidence_ids":[],"sources":[]}]}
]}
print(json.dumps(article))
""",
    )

    result = run_pipeline(
        evidence_root=evidence,
        runtime_root=runtime,
        research_command=research,
        writer_command=writer,
        now_utc=datetime(2026, 9, 13, 0, 20, tzinfo=timezone.utc),
    )

    assert result["status"] == "PUBLISHED"
    latest = json.loads((runtime / "latest.json").read_text(encoding="utf-8"))
    assert latest["title"] == "NFL EDGE Saturday Night Brief"
    assert (runtime / "research/latest.json").is_file()
    assert list((runtime / "archive").glob("*.json"))


def test_failed_candidate_does_not_replace_last_good(tmp_path: Path) -> None:
    evidence = _evidence_root(tmp_path)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    old = {
        "schema_version": "NFL_EDGE_DAILY_NEWS_V1",
        "published_at_utc": "2026-09-12T12:20:00Z",
        "title": "Last good",
        "sections": [],
        "research_generated_at_utc": "2026-09-12T12:20:00Z",
    }
    old_research = {
        "schema_version": "NFL_EDGE_DAILY_NEWS_RESEARCH_V1",
        "generated_at_utc": "2026-09-12T12:20:00Z",
        "evidence": [{"evidence_id": "old"}],
    }
    (runtime / "latest.json").write_text(json.dumps(old), encoding="utf-8")
    (runtime / "research").mkdir()
    (runtime / "research/latest.json").write_text(json.dumps(old_research), encoding="utf-8")
    research = _script(
        tmp_path / "research.py",
        """import json,sys
request=json.load(sys.stdin)
assert request["previous_article"]["title"]=="Last good"
assert request["previous_research"]["evidence"][0]["evidence_id"]=="old"
print(json.dumps({"schema_version":"NFL_EDGE_DAILY_NEWS_EXTERNAL_RESEARCH_V1","evidence":[{"evidence_id":"x","fact":"fact","sources":[{"label":"source","url":"https://example.com"}]}]}))
""",
    )
    bad_writer = _script(
        tmp_path / "writer.py",
        """import json,sys
json.load(sys.stdin)
print(json.dumps({"schema_version":"NFL_EDGE_DAILY_NEWS_V1","published_at_utc":"2026-09-13T00:20:00Z","title":"Bad","sections":[{"id":"fade","title":"The Fade","items":[{"headline":"Unsupported","paragraphs":["Made up."],"evidence_ids":["missing"],"takeaway":"This is deliberately long enough to pass the length check but references missing evidence."}]}]}))
""",
    )

    with pytest.raises(NewsPipelineError):
        run_pipeline(
            evidence_root=evidence,
            runtime_root=runtime,
            research_command=research,
            writer_command=bad_writer,
        )

    assert json.loads((runtime / "latest.json").read_text(encoding="utf-8")) == old
    assert json.loads((runtime / "research/latest.json").read_text(encoding="utf-8")) == old_research
    assert (runtime / "research/candidate.json").is_file()


def test_verifier_rejects_untraceable_source() -> None:
    packet = {
        "evidence": [
            {
                "evidence_id": "x",
                "sources": [{"label": "NFL", "url": "https://www.nfl.com/x"}],
            }
        ]
    }
    article = {
        "schema_version": "NFL_EDGE_DAILY_NEWS_V1",
        "published_at_utc": "2026-09-13T00:20:00Z",
        "title": "Test",
        "sections": [
            {
                "id": "what-matters",
                "items": [
                    {
                        "headline": "Bad source",
                        "paragraphs": ["Claim."],
                        "evidence_ids": ["x"],
                        "sources": [{"label": "Other", "url": "https://example.com/not-in-packet"}],
                    }
                ],
            }
        ],
    }
    with pytest.raises(NewsPipelineError):
        verify_article(article, packet)


def test_editorial_only_cannot_bypass_evidence_outside_tip() -> None:
    packet = {"evidence": []}
    article = {
        "schema_version": "NFL_EDGE_DAILY_NEWS_V1",
        "published_at_utc": "2026-09-13T00:20:00Z",
        "title": "Test",
        "sections": [
            {
                "id": "what-matters",
                "items": [
                    {
                        "headline": "Unsupported",
                        "paragraphs": ["A factual claim."],
                        "editorial_only": True,
                        "evidence_ids": [],
                    }
                ],
            }
        ],
    }
    with pytest.raises(NewsPipelineError):
        verify_article(article, packet)


def test_previous_research_view_drops_recursive_history() -> None:
    payload = {
        "schema_version": "NFL_EDGE_DAILY_NEWS_RESEARCH_V1",
        "evidence": [{"evidence_id": "x"}],
        "previous_article": {"title": "older"},
        "previous_research": {"previous_research": {"too": "deep"}},
    }
    view = _previous_research_view(payload)
    assert view is not None
    assert "previous_article" not in view
    assert "previous_research" not in view
    assert view["evidence"] == [{"evidence_id": "x"}]
