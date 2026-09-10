"""Safe synchronization of prospective runtime observations into an isolated repository checkout."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from nfl_edge.prospective.capture_v1 import load_publications, publication_filename
from nfl_edge.prospective.common_v1 import (
    PUBLICATION_SCHEMA_VERSION,
    AppendOnlyViolation,
    ProspectiveCardError,
    canonical_json_bytes,
    parse_utc,
)
from nfl_edge.prospective.derive_v1 import derive_episodes, resolve_official
from nfl_edge.prospective.results_v1 import build_pending_results, build_summary

PERSISTENCE_SCHEMA_VERSION = "NFL_EDGE_PROSPECTIVE_CARD_PERSISTENCE_V1"


def _assert_isolated(
    *,
    evidence_root: Path,
    production_worktree: Path | None,
) -> None:
    evidence = evidence_root.resolve()
    if production_worktree is None:
        return
    production = production_worktree.resolve()
    if evidence == production or evidence.is_relative_to(production) or production.is_relative_to(evidence):
        raise ProspectiveCardError(
            "evidence checkout and production worktree must be separate, non-nested paths"
        )


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_json_bytes(dict(payload))
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=path.parent,
            prefix=f".{path.name}-",
            delete=False,
        ) as handle:
            temp = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _write_once(path: Path, payload: Mapping[str, Any]) -> bool:
    raw = canonical_json_bytes(dict(payload))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == raw:
            return False
        raise AppendOnlyViolation(f"finalized prospective evidence conflicts with existing file: {path}")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    except FileExistsError:
        if path.read_bytes() == raw:
            return False
        raise AppendOnlyViolation(f"finalized prospective evidence raced with conflicting file: {path}")
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return True


def _load_runtime_publication(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ProspectiveCardError(f"runtime prospective publication is invalid JSON: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != PUBLICATION_SCHEMA_VERSION:
        raise ProspectiveCardError(f"runtime prospective publication has unexpected schema: {path}")
    if raw != canonical_json_bytes(payload):
        raise ProspectiveCardError(f"runtime prospective publication is not canonical deterministic JSON: {path}")
    if publication_filename(payload) != path.name:
        raise ProspectiveCardError(f"runtime prospective publication filename does not match source identity: {path}")
    if payload.get("creation_provenance", {}).get("provider_calls") != 0:
        raise ProspectiveCardError(f"prospective publication unexpectedly reports provider calls: {path}")
    if payload.get("creation_provenance", {}).get("user_specific_data_included") is not False:
        raise ProspectiveCardError(f"prospective publication may contain user-specific data: {path}")
    parse_utc(str(payload["published_at_utc"]))
    return payload


def _copy_immutable(source: Path, target: Path) -> bool:
    raw = source.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() == raw:
            return False
        raise AppendOnlyViolation(f"repository publication conflicts with runtime evidence: {target}")
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    except FileExistsError:
        if target.read_bytes() == raw:
            return False
        raise AppendOnlyViolation(f"repository publication raced with conflicting evidence: {target}")
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return True


def _week_target(evidence_root: Path, season: int, week: int) -> Path:
    return evidence_root / "prospective" / "cards" / str(season) / f"week-{week:02d}"


def sync_runtime_evidence(
    *,
    runtime_root: str | Path,
    evidence_root: str | Path,
    production_worktree: str | Path | None = None,
) -> dict[str, Any]:
    """Copy only validated immutable runtime publications into an isolated checkout.

    The function performs no Git operations. A separate deployment wrapper owns
    branch verification, commit path restrictions, and push behavior.
    """
    runtime = Path(runtime_root)
    evidence = Path(evidence_root)
    production = None if production_worktree is None else Path(production_worktree)
    _assert_isolated(evidence_root=evidence, production_worktree=production)

    seen_source_hashes: set[str] = set()
    copied = 0
    deduplicated = 0
    touched: set[tuple[int, int]] = set()

    paths = sorted(runtime.glob("*/week-*/publications/*.json")) if runtime.exists() else []
    for source in paths:
        payload = _load_runtime_publication(source)
        season = int(payload["season"])
        week = int(payload["week"])
        expected_parent = (str(season), f"week-{week:02d}")
        if source.parents[2].name != expected_parent[0] or source.parents[1].name != expected_parent[1]:
            raise ProspectiveCardError(f"runtime path disagrees with publication season/week: {source}")
        source_hash = str(payload["source_product_sha256"])
        if source_hash in seen_source_hashes:
            raise ProspectiveCardError(f"duplicate source product hash in runtime evidence: {source_hash}")
        seen_source_hashes.add(source_hash)

        target = _week_target(evidence, season, week) / "publications" / source.name
        if _copy_immutable(source, target):
            copied += 1
        else:
            deduplicated += 1
        touched.add((season, week))

    for season, week in sorted(touched):
        week_root = _week_target(evidence, season, week)
        publications = load_publications(week_root / "publications")
        episodes = derive_episodes(publications)
        official_path = week_root / "official.json"
        results_path = week_root / "results.json"
        if official_path.exists():
            if not results_path.exists():
                raise ProspectiveCardError(
                    f"finalized official evidence exists without results contract: {week_root}"
                )
            stored_official = json.loads(official_path.read_text(encoding="utf-8"))
            recomputed_official = resolve_official(publications)
            comparison_fields = (
                "resolutions",
                "official_wagers",
                "portfolio_entries",
                "overlap_count",
            )
            if any(
                stored_official.get(field) != recomputed_official.get(field)
                for field in comparison_fields
            ):
                raise AppendOnlyViolation(
                    "newly synchronized evidence would change already-finalized official card"
                )
            stored_results = json.loads(results_path.read_text(encoding="utf-8"))
            _atomic_json(
                week_root / "summary.json",
                build_summary(
                    official=stored_official,
                    results=stored_results,
                    episodes=episodes,
                ),
            )
        _atomic_json(week_root / "episodes.json", episodes)

    return {
        "schema_version": PERSISTENCE_SCHEMA_VERSION,
        "runtime_root": str(runtime),
        "evidence_root": str(evidence),
        "production_worktree": None if production is None else str(production),
        "runtime_publications_seen": len(paths),
        "publications_copied": copied,
        "publications_deduplicated": deduplicated,
        "weeks_updated": [
            {"season": season, "week": week}
            for season, week in sorted(touched)
        ],
        "provider_calls": 0,
    }


def finalize_week_evidence(
    *,
    evidence_root: str | Path,
    season: int,
    week: int,
    finalized_at_utc: str,
    week_last_kickoff_at_utc: str,
) -> dict[str, Any]:
    """Finalize official/results/summary only after an explicit full-week boundary."""
    finalized = parse_utc(finalized_at_utc)
    last_kickoff = parse_utc(week_last_kickoff_at_utc)
    if finalized <= last_kickoff:
        raise ProspectiveCardError(
            "week cannot be finalized until strictly after the authoritative last kickoff"
        )

    week_root = _week_target(Path(evidence_root), int(season), int(week))
    publications = load_publications(week_root / "publications")
    if not publications:
        raise ProspectiveCardError("cannot finalize a week without prospective publications")

    # Every kickoff carried by a tracked recommendation must also be behind the
    # explicit whole-week boundary. The operator-supplied last kickoff protects
    # against finalizing merely because the currently selected lanes are early games.
    for publication in publications:
        for lane in publication["lanes"].values():
            kickoff = lane.get("kickoff_at_utc")
            if kickoff is not None and parse_utc(str(kickoff)) > last_kickoff:
                raise ProspectiveCardError(
                    "tracked recommendation kickoff exceeds supplied week-last-kickoff boundary"
                )

    episodes = derive_episodes(publications)
    official = resolve_official(publications)
    official["finalized_at_utc"] = str(finalized_at_utc)
    official["week_last_kickoff_at_utc"] = str(week_last_kickoff_at_utc)
    results = build_pending_results(official)
    summary = build_summary(official=official, results=results, episodes=episodes)

    _atomic_json(week_root / "episodes.json", episodes)
    official_created = _write_once(week_root / "official.json", official)
    results_created = _write_once(week_root / "results.json", results)
    _atomic_json(week_root / "summary.json", summary)

    return {
        "schema_version": PERSISTENCE_SCHEMA_VERSION,
        "season": int(season),
        "week": int(week),
        "finalized_at_utc": str(finalized_at_utc),
        "week_last_kickoff_at_utc": str(week_last_kickoff_at_utc),
        "official_created": official_created,
        "results_created": results_created,
        "official_wagers": len(official["official_wagers"]),
        "portfolio_entries": len(official["portfolio_entries"]),
        "provider_calls": 0,
    }


__all__ = [
    "PERSISTENCE_SCHEMA_VERSION",
    "finalize_week_evidence",
    "sync_runtime_evidence",
]
