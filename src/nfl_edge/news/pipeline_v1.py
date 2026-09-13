"""NFL EDGE Daily News V1 pipeline.

The pipeline is deliberately downstream of the betting product:
card evidence + external research -> governed research packet -> writer -> verification -> atomic publish.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

RESEARCH_SCHEMA = "NFL_EDGE_DAILY_NEWS_RESEARCH_V1"
ARTICLE_SCHEMA = "NFL_EDGE_DAILY_NEWS_V1"
SECTION_ORDER = (
    "what-matters",
    "what-it-means",
    "fade",
    "market-watch",
    "today-tip",
)
_SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "schemas"


class NewsPipelineError(RuntimeError):
    pass




def _parse_utc(value: str) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise NewsPipelineError(f"invalid UTC timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise NewsPipelineError(f"timestamp must include timezone: {value}")
    return parsed.astimezone(timezone.utc)


def _validate_schema_file(filename: str, payload: Mapping[str, Any]) -> None:
    path = _SCHEMA_ROOT / filename
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(dict(payload))
    except (OSError, ValueError, SchemaError, ValidationError) as exc:
        raise NewsPipelineError(f"schema validation failed for {filename}: {exc}") from exc


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NewsPipelineError(f"could not read JSON object: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise NewsPipelineError(f"expected JSON object: {path}")
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}-", delete=False) as handle:
            temp = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _latest_week_root(evidence_root: Path) -> Path:
    candidates = [p.parent for p in evidence_root.glob("prospective/cards/*/week-*/episodes.json")]
    if not candidates:
        raise NewsPipelineError(f"no prospective episodes found under {evidence_root}")
    return sorted(candidates, key=lambda p: (int(p.parent.name), int(p.name.split("-")[-1])))[-1]


def _publication_files(week_root: Path) -> list[Path]:
    return sorted((week_root / "publications").glob("*.json"))


def build_card_context(evidence_root: Path) -> dict[str, Any]:
    week_root = _latest_week_root(evidence_root)
    episodes = _load_object(week_root / "episodes.json")
    publications = [_load_object(path) for path in _publication_files(week_root)]
    if not publications:
        raise NewsPipelineError("prospective week has no publications")
    publications.sort(key=lambda x: str(x.get("published_at_utc") or ""))
    latest = publications[-1]
    previous = publications[-2] if len(publications) > 1 else None

    observations: list[dict[str, Any]] = []
    for episode in episodes.get("episodes", []):
        if not isinstance(episode, dict):
            continue
        obs = episode.get("observations") or []
        if not obs:
            continue
        observations.append(
            {
                "episode_id": episode.get("episode_id"),
                "lane": episode.get("lane"),
                "state": obs[-1].get("state"),
                "selection": episode.get("selection") or episode.get("normalized_selection"),
                "market": episode.get("market"),
                "book": obs[-1].get("book"),
                "kickoff_at_utc": episode.get("kickoff_at_utc"),
                "first": obs[0],
                "latest": obs[-1],
                "previous": obs[-2] if len(obs) > 1 else None,
                "returned_after_gap": bool(episode.get("returned_after_gap")),
                "present_in_latest": obs[-1].get("publication_id") == latest.get("publication_id"),
                "terminal_reason": episode.get("terminal_reason"),
            }
        )

    return {
        "schema_version": "NFL_EDGE_DAILY_NEWS_CARD_CONTEXT_V1",
        "season": latest.get("season"),
        "week": latest.get("week"),
        "latest_publication_id": latest.get("publication_id"),
        "latest_published_at_utc": latest.get("published_at_utc"),
        "previous_publication_id": None if previous is None else previous.get("publication_id"),
        "previous_published_at_utc": None if previous is None else previous.get("published_at_utc"),
        "episodes": observations,
        "provider_calls": 0,
    }




def _previous_research_view(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    view = dict(payload)
    view.pop("previous_research", None)
    view.pop("previous_article", None)
    return view


def build_research_request(
    *,
    card_context: Mapping[str, Any],
    generated_at_utc: str,
    previous_article: Mapping[str, Any] | None,
    previous_research: Mapping[str, Any] | None,
) -> dict[str, Any]:
    request = {
        "schema_version": "NFL_EDGE_DAILY_NEWS_RESEARCH_REQUEST_V1",
        "generated_at_utc": generated_at_utc,
        "card_context": dict(card_context),
        "previous_article": None if previous_article is None else dict(previous_article),
        "previous_research": None if previous_research is None else dict(previous_research),
        "comparison_instructions": (
            "Identify only verified changes since the previous research/article: injuries, QB status, weather, "
            "retail-vs-Circa Fade evidence, and other slate-relevant developments. Preserve 'no change' when supported."
        ),
    }
    _validate_schema_file("NFL_EDGE_DAILY_NEWS_RESEARCH_REQUEST_V1.schema.json", request)
    return request


def _run_json_command(command: str, payload: Mapping[str, Any], *, timeout: int) -> dict[str, Any]:
    argv = shlex.split(command)
    if not argv:
        raise NewsPipelineError("configured command is empty")
    proc = subprocess.run(
        argv,
        input=json.dumps(dict(payload), ensure_ascii=False).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env=os.environ.copy(),
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")[-2000:]
        raise NewsPipelineError(f"command failed ({proc.returncode}): {argv[0]}: {err}")
    try:
        value = json.loads(proc.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise NewsPipelineError(f"command did not return JSON: {argv[0]}") from exc
    if not isinstance(value, dict):
        raise NewsPipelineError(f"command must return a JSON object: {argv[0]}")
    return value


def build_research_packet(
    *,
    card_context: Mapping[str, Any],
    external: Mapping[str, Any],
    generated_at_utc: str,
) -> dict[str, Any]:
    if external.get("schema_version") != "NFL_EDGE_DAILY_NEWS_EXTERNAL_RESEARCH_V1":
        raise NewsPipelineError("external research has unexpected schema")
    _validate_schema_file("NFL_EDGE_DAILY_NEWS_EXTERNAL_RESEARCH_V1.schema.json", external)
    evidence = external.get("evidence")
    if not isinstance(evidence, list):
        raise NewsPipelineError("external research evidence must be a list")

    ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for item in evidence:
        if not isinstance(item, dict):
            raise NewsPipelineError("external evidence item must be an object")
        evidence_id = str(item.get("evidence_id") or "").strip()
        if not evidence_id or evidence_id in ids:
            raise NewsPipelineError("external evidence IDs must be non-empty and unique")
        ids.add(evidence_id)
        if not str(item.get("fact") or "").strip():
            raise NewsPipelineError(f"evidence {evidence_id} is missing fact")
        sources = item.get("sources")
        if not isinstance(sources, list) or not sources:
            raise NewsPipelineError(f"evidence {evidence_id} must have at least one source")
        for source in sources:
            if not isinstance(source, dict) or not str(source.get("url") or "").startswith(("http://", "https://")):
                raise NewsPipelineError(f"evidence {evidence_id} has invalid source")
        normalized.append(dict(item))

    card_evidence_id = "card:latest-prospective-context"
    normalized.append(
        {
            "evidence_id": card_evidence_id,
            "category": "market_watch",
            "verification": "INTERNAL_CANONICAL",
            "fact": "Latest and prior prospective card observations are attached in card_context.",
            "interpretation": "Use only observed tracker changes; do not infer movement from a single observation.",
            "app_guidance": "Explain current price, Play Through changes/crossings, replacements, disappearances, and returns exactly as supported.",
            "sources": [],
        }
    )
    for episode in card_context.get("episodes", []):
        if not isinstance(episode, dict):
            continue
        episode_id = str(episode.get("episode_id") or "").strip()
        if not episode_id:
            continue
        latest_obs = episode.get("latest") if isinstance(episode.get("latest"), dict) else {}
        previous_obs = episode.get("previous") if isinstance(episode.get("previous"), dict) else None
        fact = (
            f"{episode.get('lane')} {episode.get('selection')} {episode.get('market')}: "
            f"latest book={latest_obs.get('book')}, line={latest_obs.get('line')}, "
            f"price={latest_obs.get('american_odds')}, play_through={latest_obs.get('play_through')}, "
            f"state={latest_obs.get('state')}, present_in_latest={bool(episode.get('present_in_latest'))}."
        )
        if previous_obs is not None:
            fact += (
                f" Previous observation: book={previous_obs.get('book')}, line={previous_obs.get('line')}, "
                f"price={previous_obs.get('american_odds')}, play_through={previous_obs.get('play_through')}, "
                f"state={previous_obs.get('state')}."
            )
        normalized.append(
            {
                "evidence_id": f"card:{episode_id}",
                "category": "market_watch",
                "verification": "INTERNAL_CANONICAL",
                "fact": fact,
                "interpretation": (
                    "Compare the latest and previous observations only. "
                    "If present_in_latest is false, do not describe this as a current recommendation."
                ),
                "app_guidance": (
                    "Explain the observed price/line/Play Through change in plain language and whether the "
                    "recommendation remains current. Do not expose internal metrics opportunistically."
                ),
                "sources": [],
            }
        )
    packet = {
        "schema_version": RESEARCH_SCHEMA,
        "generated_at_utc": generated_at_utc,
        "editorial_rule": "Personality strong, evidence strict.",
        "audience": "Football fans who bet, including casual and newer bettors.",
        "card_context": dict(card_context),
        "evidence": normalized,
        "writer_rules": {
            "section_order": list(SECTION_ORDER),
            "plain_language": True,
            "no_new_catchphrases": True,
            "approved_catchphrases": ["Monday game? Monday check.", "Thursday game? Thursday check."],
            "fade_must_explain_usage": True,
            "no_blind_fade_signal": True,
            "news_cannot_change_model": True,
        },
    }
    _validate_schema_file("NFL_EDGE_DAILY_NEWS_RESEARCH_V1.schema.json", packet)
    return packet


def verify_article(article: Mapping[str, Any], packet: Mapping[str, Any]) -> None:
    if article.get("schema_version") != ARTICLE_SCHEMA:
        raise NewsPipelineError("article has unexpected schema")
    _validate_schema_file("NFL_EDGE_DAILY_NEWS_V1.schema.json", article)
    for key in ("published_at_utc", "title", "sections"):
        if key not in article:
            raise NewsPipelineError(f"article missing {key}")
    sections = article.get("sections")
    if not isinstance(sections, list) or not sections:
        raise NewsPipelineError("article sections must be a non-empty list")

    published_at = _parse_utc(str(article["published_at_utc"]))
    generated_at = _parse_utc(str(packet.get("generated_at_utc") or ""))
    if abs((published_at - generated_at).total_seconds()) > 20 * 60:
        raise NewsPipelineError("article publication time is too far from the current research run")
    previous_article = packet.get("previous_article")
    if isinstance(previous_article, dict) and previous_article.get("published_at_utc"):
        previous_published = _parse_utc(str(previous_article["published_at_utc"]))
        if published_at <= previous_published:
            raise NewsPipelineError("article publication time must advance beyond the previous brief")

    evidence_by_id = {
        str(item["evidence_id"]): item
        for item in packet.get("evidence", [])
        if isinstance(item, dict) and item.get("evidence_id")
    }
    order = [str(s.get("id")) for s in sections if isinstance(s, dict)]
    expected_positions = [SECTION_ORDER.index(x) for x in order if x in SECTION_ORDER]
    if expected_positions != sorted(expected_positions) or len(expected_positions) != len(order):
        raise NewsPipelineError("article sections are unknown or out of order")

    for section in sections:
        if not isinstance(section, dict):
            raise NewsPipelineError("article section must be an object")
        sid = str(section.get("id") or "")
        items = section.get("items")
        if not isinstance(items, list) or not items:
            raise NewsPipelineError(f"section {sid} must contain at least one item")
        for item in items:
            if not isinstance(item, dict):
                raise NewsPipelineError(f"section {sid} item must be an object")
            if not str(item.get("headline") or "").strip():
                raise NewsPipelineError(f"section {sid} item missing headline")
            paragraphs = item.get("paragraphs")
            if not isinstance(paragraphs, list) or not any(str(p).strip() for p in paragraphs):
                raise NewsPipelineError(f"section {sid} item missing paragraphs")
            evidence_ids = item.get("evidence_ids", [])
            editorial_only = bool(item.get("editorial_only"))
            if editorial_only and sid != "today-tip":
                raise NewsPipelineError("editorial_only is permitted only in Today's Tip")
            if sid != "today-tip" and not evidence_ids:
                raise NewsPipelineError(f"section {sid} item must cite evidence_ids")
            if not isinstance(evidence_ids, list) or any(str(x) not in evidence_by_id for x in evidence_ids):
                raise NewsPipelineError(f"section {sid} item cites unknown evidence")
            allowed_urls = {
                str(src.get("url"))
                for evidence_id in evidence_ids
                for src in evidence_by_id[str(evidence_id)].get("sources", [])
                if isinstance(src, dict) and src.get("url")
            }
            for source in item.get("sources", []):
                if not isinstance(source, dict) or str(source.get("url") or "") not in allowed_urls:
                    raise NewsPipelineError(f"section {sid} contains a source not present in cited evidence")
            if sid == "fade":
                takeaway = str(item.get("takeaway") or "").strip()
                if not takeaway:
                    raise NewsPipelineError("The Fade must include concrete user guidance in takeaway")
                if len(takeaway) < 40:
                    raise NewsPipelineError("The Fade takeaway is too thin to explain how to use the information")


@dataclass(frozen=True)
class PipelinePaths:
    runtime_root: Path

    @property
    def latest(self) -> Path:
        return self.runtime_root / "latest.json"

    @property
    def research_latest(self) -> Path:
        return self.runtime_root / "research" / "latest.json"

    @property
    def research_candidate(self) -> Path:
        return self.runtime_root / "research" / "candidate.json"

    @property
    def candidate(self) -> Path:
        return self.runtime_root / "candidate.json"

    @property
    def archive(self) -> Path:
        return self.runtime_root / "archive"


def run_pipeline(
    *,
    evidence_root: Path,
    runtime_root: Path,
    research_command: str,
    writer_command: str,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    now = now_utc or datetime.now(timezone.utc)
    generated = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    paths = PipelinePaths(runtime_root)

    card = build_card_context(evidence_root)
    previous_article = _load_object(paths.latest) if paths.latest.exists() else None
    previous_research_raw = _load_object(paths.research_latest) if paths.research_latest.exists() else None
    if (
        previous_article is not None
        and previous_research_raw is not None
        and previous_article.get("research_generated_at_utc") == previous_research_raw.get("generated_at_utc")
    ):
        previous_research = _previous_research_view(previous_research_raw)
    else:
        previous_research = None
    research_request = build_research_request(
        card_context=card,
        generated_at_utc=generated,
        previous_article=previous_article,
        previous_research=previous_research,
    )
    external = _run_json_command(research_command, research_request, timeout=180)
    packet = build_research_packet(card_context=card, external=external, generated_at_utc=generated)
    packet["previous_article"] = previous_article
    packet["previous_research"] = previous_research
    _validate_schema_file("NFL_EDGE_DAILY_NEWS_RESEARCH_V1.schema.json", packet)
    _atomic_json(paths.research_candidate, packet)

    article = _run_json_command(writer_command, packet, timeout=180)
    article["research_generated_at_utc"] = generated
    verify_article(article, packet)
    _atomic_json(paths.candidate, article)

    published_at = str(article["published_at_utc"]).replace(":", "").replace("-", "")
    archive_path = paths.archive / f"{published_at}.json"
    if archive_path.exists():
        if _load_object(archive_path) != article:
            raise NewsPipelineError(f"archive conflict: {archive_path}")
    else:
        _atomic_json(archive_path, article)
    _atomic_json(paths.research_latest, packet)
    _atomic_json(paths.latest, article)
    return {
        "schema_version": "NFL_EDGE_DAILY_NEWS_PIPELINE_RESULT_V1",
        "status": "PUBLISHED",
        "published_at_utc": article["published_at_utc"],
        "latest_path": str(paths.latest),
        "archive_path": str(archive_path),
        "research_path": str(paths.research_latest),
        "provider_calls_added_by_nfl_edge": 0,
    }
