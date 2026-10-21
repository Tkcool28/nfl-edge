"""Exact, reviewed game evidence for blank 2026 REG surfaces.

The legacy Week 5 registry and its provenance bytes remain authoritative.
Additional records are bounded by full game/venue identity, never team defaults.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from .week5_surface_evidence_2026 import (
    IDENTITY_FIELDS,
    KNOWN_SURFACES,
    Week5SurfaceEvidenceError,
)
from .week5_surface_evidence_2026 import (
    load_surface_evidence as load_week5,
)
from .week5_surface_evidence_2026 import (
    recover_missing_surface as recover_week5,
)

EVIDENCE_PATH = Path(__file__).resolve().parents[3] / "config/surface_evidence_2026_v1.json"
SCHEMA = "NFL_EDGE_SURFACE_EVIDENCE_2026_V1"
SurfaceEvidenceError = Week5SurfaceEvidenceError


def digest(record: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


def load_surface_evidence() -> dict[str, dict[str, Any]]:
    payload = json.loads(EVIDENCE_PATH.read_text())
    if payload.get("schema_version") != SCHEMA or not isinstance(payload.get("games"), list):
        raise SurfaceEvidenceError("2026 surface evidence schema drift")
    result = {}
    legacy = load_week5()
    for entry in payload["games"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("evidence"), dict):
            raise SurfaceEvidenceError("2026 surface evidence record must be an object")
        record = entry["evidence"]
        gid = record.get("canonical_game_id")
        if entry.get("evidence_sha256") != digest(record):
            raise SurfaceEvidenceError(f"{gid}: surface evidence digest mismatch")
        if any(not isinstance(record.get(k), str) or not record[k] for k in IDENTITY_FIELDS):
            raise SurfaceEvidenceError(f"{gid}: missing exact game/venue identity")
        try:
            week = int(record["week"])
            date.fromisoformat(record["gameday"])
            date.fromisoformat(record["retrieved_on"])
        except (KeyError, ValueError, TypeError) as exc:
            raise SurfaceEvidenceError(f"{gid}: invalid evidence date/week") from exc
        expected = f"2026_{week:02d}_{record['away_team']}_{record['home_team']}"
        if (record['season'], record['game_type']) != ('2026', 'REG') or not 1 <= week <= 18:
            raise SurfaceEvidenceError(f"{gid}: surface evidence escaped 2026 REG")
        if gid != expected or record['game_id'] != expected or gid in result or gid in legacy:
            raise SurfaceEvidenceError(f"{gid}: conflicting/duplicate evidence identity")
        surface = record.get('surface')
        if surface not in KNOWN_SURFACES or record.get('surface_subtype_known') is not True:
            raise SurfaceEvidenceError(f"{gid}: unsupported or uncertain surface subtype")
        if record.get('verified_surface_class') != ('grass' if surface == 'grass' else 'artificial'):
            raise SurfaceEvidenceError(f"{gid}: conflicting surface class")
        urls = record.get('source_urls')
        if (not isinstance(urls, list) or not urls
                or any(not isinstance(u, str) or not u.startswith('https://') for u in urls)
                or not record.get('evidence_quality') or not record.get('note')):
            raise SurfaceEvidenceError(f"{gid}: missing surface provenance")
        result[gid] = record
    return result


def recover_missing_surface(row: Mapping[str, Any], *, canonical_game_id: str):
    if str(row.get('surface') or '').strip():
        return None
    if str(row.get('season')) != '2026' or row.get('game_type') != 'REG':
        return None
    record = load_surface_evidence().get(canonical_game_id)
    if record is None:
        return recover_week5(row, canonical_game_id=canonical_game_id)
    mismatches = [k for k in IDENTITY_FIELDS if str(row.get(k) or '') != record[k]]
    if mismatches:
        raise SurfaceEvidenceError(f"{canonical_game_id}: surface evidence identity mismatch in {mismatches}")
    return record['surface'], {
        'schema_version': SCHEMA,
        'evidence_sha256': digest(record),
        'original_surface': row.get('surface'),
        'source_identity': {k: row[k] for k in IDENTITY_FIELDS},
        'evidence': dict(record),
    }
