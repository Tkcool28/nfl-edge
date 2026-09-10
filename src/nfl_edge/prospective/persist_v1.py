"""Controlled persistence of runtime prospective evidence into an isolated Git worktree.

This module does not execute Git. It validates/copies immutable runtime publications
into a caller-supplied evidence repository root and deterministically refreshes the
week-level derived artifacts. Git synchronization is owned by the separate deployment
worker so the public backend never acquires repository credentials or commit ability.
"""
from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from nfl_edge.prospective.capture_v1 import load_publications, write_publication_snapshot
from nfl_edge.prospective.common_v1 import (
    PUBLICATION_SCHEMA_VERSION,
    RESULT_SCHEMA_VERSION,
    ProspectiveCardError,
    canonical_json_bytes,
)
from nfl_edge.prospective.derive_v1 import derive_episodes, resolve_official
from nfl_edge.prospective.results_v1 import build_pending_results, build_summary
from nfl_edge.prospective.runtime_v1 import runtime_publications_dir

PERSISTENCE_SCHEMA_VERSION = "NFL_EDGE_PROSPECTIVE_CARD_PERSISTENCE_V1"
EVIDENCE_PREFIX = Path("prospective/cards")
_SCHEMA_FILES = {
    "publication": "NFL_EDGE_PROSPECTIVE_CARD_PUBLICATION_V1.schema.json",
    "episodes": "NFL_EDGE_PROSPECTIVE_CARD_EPISODES_V1.schema.json",
    "official": "NFL_EDGE_PROSPECTIVE_CARD_OFFICIAL_V1.schema.json",
    "results": "NFL_EDGE_PROSPECTIVE_CARD_RESULT_V1.schema.json",
    "summary": "NFL_EDGE_PROSPECTIVE_CARD_SUMMARY_V1.schema.json",
}


class EvidencePersistenceError(ProspectiveCardError):
    """Raised when runtime evidence cannot be persisted without violating contracts."""


def evidence_week_root(evidence_repo_root: str | Path, *, season: int, week: int) -> Path:
    return Path(evidence_repo_root) / EVIDENCE_PREFIX / str(int(season)) / f"week-{int(week):02d}"


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_json_bytes(dict(payload))
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}-", delete=False) as handle:
            temp = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _validate_schema(evidence_repo_root: str | Path, schema_key: str, payload: Mapping[str, Any]) -> None:
    schema_path = Path(evidence_repo_root) / "schemas" / _SCHEMA_FILES[schema_key]
    if not schema_path.is_file():
        raise EvidencePersistenceError(f"required schema is missing from evidence worktree: {schema_path}")
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(dict(payload))
    except (OSError, ValueError, SchemaError, ValidationError) as exc:
        raise EvidencePersistenceError(f"{schema_key} schema validation failed: {exc}") from exc


def _validate_runtime_publication(
    row: Mapping[str, Any],
    *,
    evidence_repo_root: str | Path,
    season: int,
    week: int,
) -> None:
    _validate_schema(evidence_repo_root, "publication", row)
    if row.get("schema_version") != PUBLICATION_SCHEMA_VERSION:
        raise EvidencePersistenceError("runtime publication has unexpected schema version")
    if int(row.get("season", -1)) != int(season) or int(row.get("week", -1)) != int(week):
        raise EvidencePersistenceError("runtime publication season/week does not match target week")
    if row.get("capture_mode") != "NATIVE_PROSPECTIVE":
        raise EvidencePersistenceError("runtime persistence accepts only NATIVE_PROSPECTIVE captures")
    provenance = dict(row.get("creation_provenance") or {})
    if provenance.get("provider_calls") != 0:
        raise EvidencePersistenceError("prospective evidence must record zero provider calls")
    if provenance.get("user_specific_data_included") is not False:
        raise EvidencePersistenceError("prospective evidence may not contain user-specific data")


def _result_key(row: Mapping[str, Any], *, portfolio: bool) -> str:
    key = "portfolio_entry_id" if portfolio else "result_id"
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise EvidencePersistenceError(f"result row missing {key}")
    return value


def _merge_result_rows(
    previous_rows: list[Mapping[str, Any]],
    pending_rows: list[Mapping[str, Any]],
    *,
    portfolio: bool,
) -> list[dict[str, Any]]:
    previous = {_result_key(row, portfolio=portfolio): dict(row) for row in previous_rows}
    current_ids = {_result_key(row, portfolio=portfolio) for row in pending_rows}

    # A settled result disappearing from the current official set would destroy
    # historical evidence. Fail closed instead of silently rewriting history.
    for key, row in previous.items():
        if key not in current_ids and str(row.get("grade") or "").upper() != "PENDING":
            raise EvidencePersistenceError(
                f"settled result {key} is absent from regenerated official card"
            )

    merged: list[dict[str, Any]] = []
    for pending in pending_rows:
        key = _result_key(pending, portfolio=portfolio)
        old = previous.get(key)
        if old is None:
            merged.append(deepcopy(dict(pending)))
            continue
        # Preserve settlement/correction fields exactly for an existing identity.
        merged.append(deepcopy(old))
    return merged


def _merge_results(previous: Mapping[str, Any] | None, pending: Mapping[str, Any]) -> dict[str, Any]:
    if previous is None:
        return deepcopy(dict(pending))
    if previous.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise EvidencePersistenceError("existing results.json has unexpected schema version")
    if int(previous.get("season", -1)) != int(pending["season"]) or int(previous.get("week", -1)) != int(pending["week"]):
        raise EvidencePersistenceError("existing results.json belongs to a different week")

    lane_results = _merge_result_rows(
        list(previous.get("lane_results") or []),
        list(pending.get("lane_results") or []),
        portfolio=False,
    )
    portfolio_results = _merge_result_rows(
        list(previous.get("portfolio_results") or []),
        list(pending.get("portfolio_results") or []),
        portfolio=True,
    )
    all_rows = lane_results + portfolio_results
    pending_count = sum(str(row.get("grade") or "").upper() == "PENDING" for row in all_rows)
    settled_count = len(all_rows) - pending_count
    if pending_count and settled_count:
        settlement_status = "PARTIAL"
    elif pending_count:
        settlement_status = "PENDING"
    else:
        settlement_status = "SETTLED"
    return {
        **deepcopy(dict(pending)),
        "settlement_status": settlement_status,
        "lane_results": lane_results,
        "portfolio_results": portfolio_results,
    }


def sync_runtime_week(
    *,
    runtime_root: str | Path,
    evidence_repo_root: str | Path,
    season: int,
    week: int,
) -> dict[str, Any]:
    """Persist one season/week from runtime staging into an isolated evidence tree.

    Immutable publications use O_EXCL semantics through write_publication_snapshot.
    Derived week artifacts are deterministic rebuilds from the complete immutable
    publication set. Existing settled result rows are preserved by stable identity.
    """
    runtime_dir = runtime_publications_dir(runtime_root, season=season, week=week)
    runtime_publications = load_publications(runtime_dir)
    if not runtime_publications:
        return {
            "schema_version": PERSISTENCE_SCHEMA_VERSION,
            "status": "NO_RUNTIME_PUBLICATIONS",
            "season": int(season),
            "week": int(week),
            "runtime_publication_count": 0,
            "created_publication_count": 0,
        }

    for row in runtime_publications:
        _validate_runtime_publication(
            row,
            evidence_repo_root=evidence_repo_root,
            season=season,
            week=week,
        )

    week_root = evidence_week_root(evidence_repo_root, season=season, week=week)
    publications_dir = week_root / "publications"
    created = 0
    for row in runtime_publications:
        _, was_created = write_publication_snapshot(row, publications_dir)
        created += int(was_created)

    publications = load_publications(publications_dir)
    episodes = derive_episodes(publications)
    official = resolve_official(publications)
    pending = build_pending_results(official)

    results_path = week_root / "results.json"
    previous_results: dict[str, Any] | None = None
    if results_path.exists():
        loaded = json.loads(results_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise EvidencePersistenceError("existing results.json is not an object")
        previous_results = loaded
    results = _merge_results(previous_results, pending)
    summary = build_summary(official=official, results=results, episodes=episodes)

    _validate_schema(evidence_repo_root, "episodes", episodes)
    _validate_schema(evidence_repo_root, "official", official)
    _validate_schema(evidence_repo_root, "results", results)
    _validate_schema(evidence_repo_root, "summary", summary)

    _atomic_json(week_root / "episodes.json", episodes)
    _atomic_json(week_root / "official.json", official)
    _atomic_json(results_path, results)
    _atomic_json(week_root / "summary.json", summary)

    return {
        "schema_version": PERSISTENCE_SCHEMA_VERSION,
        "status": "SYNCED",
        "season": int(season),
        "week": int(week),
        "runtime_publication_count": len(runtime_publications),
        "repository_publication_count": len(publications),
        "created_publication_count": created,
        "episode_count": len(episodes["episodes"]),
        "official_wager_count": len(official["official_wagers"]),
        "portfolio_entry_count": len(official["portfolio_entries"]),
        "evidence_week_root": str(week_root),
    }


__all__ = [
    "EVIDENCE_PREFIX",
    "PERSISTENCE_SCHEMA_VERSION",
    "EvidencePersistenceError",
    "evidence_week_root",
    "sync_runtime_week",
]
