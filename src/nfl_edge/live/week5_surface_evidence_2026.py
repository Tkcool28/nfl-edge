"""Bounded game/venue evidence for missing 2026 REG Week 5 surfaces."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping

EVIDENCE_PATH = Path(__file__).resolve().parents[3] / "config/week5_surface_evidence_2026_v1.json"
SCHEMA = "NFL_EDGE_WEEK5_SURFACE_EVIDENCE_V1"
IDENTITY_FIELDS = (
    "season",
    "week",
    "game_type",
    "game_id",
    "gameday",
    "away_team",
    "home_team",
    "stadium",
    "stadium_id",
)
KNOWN_SURFACES = frozenset({"grass", "a_turf", "fieldturf", "matrixturf", "sportturf", "astroturf"})
TOTTENHAM_GAME = "2026_05_PHI_JAX"


class Week5SurfaceEvidenceError(ValueError):
    """Missing evidence or source game/venue identity mismatch."""


def load_surface_evidence() -> dict[str, dict[str, Any]]:
    payload = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA:
        raise Week5SurfaceEvidenceError("Week 5 surface evidence schema drift")
    records = payload.get("games")
    if not isinstance(records, list) or len(records) != 14:
        raise Week5SurfaceEvidenceError("Week 5 surface evidence must contain exactly 14 games")
    result = {}
    for record in records:
        if not isinstance(record, dict) or any(not record.get(k) for k in IDENTITY_FIELDS):
            raise Week5SurfaceEvidenceError("Week 5 surface evidence missing game/venue identity")
        if (record["season"], record["week"], record["game_type"]) != ("2026", "5", "REG"):
            raise Week5SurfaceEvidenceError("surface evidence escaped 2026 REG Week 5")
        gid = record.get("canonical_game_id")
        if not gid or gid in result:
            raise Week5SurfaceEvidenceError(f"missing/duplicate surface evidence game: {gid}")
        surface = record.get("surface")
        exception = gid == TOTTENHAM_GAME and surface == "artificial"
        if surface not in KNOWN_SURFACES and not exception:
            raise Week5SurfaceEvidenceError(f"unsupported recovery surface: {surface!r}")
        if exception and (
            record.get("surface_subtype_known") is not False
            or record.get("verified_surface_class") != "artificial"
            or record["stadium"] != "Tottenham Hotspur Stadium"
        ):
            raise Week5SurfaceEvidenceError("Tottenham unknown-subtype provenance drift")
        urls = record.get("source_urls")
        if not isinstance(urls, list) or not urls or any(not str(u).startswith("https://") for u in urls):
            raise Week5SurfaceEvidenceError(f"missing surface provenance: {gid}")
        try:
            date.fromisoformat(record["retrieved_on"])
        except (KeyError, TypeError, ValueError) as exc:
            raise Week5SurfaceEvidenceError(f"missing surface retrieval date: {gid}") from exc
        if not record.get("note") or not record.get("evidence_quality"):
            raise Week5SurfaceEvidenceError(f"missing surface evidence description: {gid}")
        result[gid] = record
    return result


def recover_missing_surface(row: Mapping[str, Any], *, canonical_game_id: str) -> tuple[str, dict[str, Any]] | None:
    """Fill only a blank field with exact evidence; do not mutate source rows."""
    if str(row.get("surface") or "").strip():
        return None
    if tuple(str(row.get(k) or "") for k in ("season", "week", "game_type")) != ("2026", "5", "REG"):
        return None
    record = load_surface_evidence().get(canonical_game_id)
    if record is None:
        return None
    mismatches = [k for k in IDENTITY_FIELDS if str(row.get(k) or "") != record[k]]
    if mismatches:
        raise Week5SurfaceEvidenceError(f"{canonical_game_id}: surface evidence identity mismatch in {mismatches}")
    provenance = {
        "schema_version": SCHEMA,
        "evidence_sha256": hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest(),
        "original_surface": row.get("surface"),
        "source_identity": {k: row[k] for k in IDENTITY_FIELDS},
        "evidence": dict(record),
    }
    return record["surface"], provenance
