"""Historical replay checkpoints issued only with validated settled evidence.

A naked schedule JSON is never a checkpoint. The successful evidence manifest
pins a content-addressed source+schedule bundle; replay must reproduce it under
the current materializer. Only a newly blank surface or an equivalent canonical
roof context may differ upstream. Actual roof position remains settled evidence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .schedule_materializer_2026 import NFLVERSE_GAMES_URL, _roof, build_week_schedule

SCHEMA = 'NFL_EDGE_HISTORICAL_SCHEDULE_CHECKPOINT_V1'
REVIEWED_CHECKPOINTS = {6: 'be5817e96de05f363b23d58c0c2b6888ad911c5f9e4b71643a498d2face1ea5c'}
REVIEWED_ROOT = Path(__file__).resolve().parents[3] / 'config/historical_schedule_checkpoints_2026'
FIELDS = ('season', 'week', 'game_type', 'game_id', 'gameday', 'gametime',
          'away_team', 'home_team', 'stadium', 'stadium_id', 'location',
          'away_rest', 'home_rest', 'surface', 'roof')


class HistoricalScheduleError(RuntimeError):
    pass


def sha(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


def source_rows(rows, week):
    return [{k: r.get(k) for k in FIELDS} for r in rows
            if str(r.get('season')) == '2026' and str(r.get('week')) == str(week) and r.get('game_type') == 'REG']


def checkpoint(rows, payload):
    return {'schema_version': SCHEMA, 'source_url': NFLVERSE_GAMES_URL,
            'source_rows': source_rows(rows, payload['week']), 'schedule': payload}


def reuse(root: Path, rows, week: int, *, allow_reviewed: bool = False):
    manifest_path = root / 'settled_evidence_manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    ref = manifest.get('schedule_checkpoints', {}).get(str(week))
    if ref is None:
        ref = REVIEWED_CHECKPOINTS.get(week) if allow_reviewed else None
        if ref is None:
            return None  # Naked legacy JSON files are never trusted.
        path = REVIEWED_ROOT / f'{ref}.json'
    else:
        if (manifest.get('schema_version') != 'nfl-edge-settled-2026-evidence-v1'
                or manifest.get('season') != 2026 or week > manifest.get('active_week', -1)):
            raise HistoricalScheduleError(f'Week {week}: checkpoint manifest identity mismatch')
        path = root / 'schedule_checkpoints' / f'{ref}.json'
    if not isinstance(ref, str) or len(ref) != 64 or any(c not in '0123456789abcdef' for c in ref):
        raise HistoricalScheduleError(f'Week {week}: invalid checkpoint digest')
    bundle = json.loads(path.read_text())
    if sha(bundle) != ref or bundle.get('schema_version') != SCHEMA or bundle.get('source_url') != NFLVERSE_GAMES_URL:
        raise HistoricalScheduleError(f'Week {week}: checkpoint integrity/provenance mismatch')
    payload = bundle['schedule']
    if payload.get('season') != 2026 or payload.get('week') != week:
        raise HistoricalScheduleError(f'Week {week}: checkpoint identity mismatch')
    origin = bundle.get('archive_provenance')
    if origin:
        raw = (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
        if hashlib.sha256(raw).hexdigest() != origin.get('original_schedule_sha256'):
            raise HistoricalScheduleError(f'Week {week}: approved archive schedule digest mismatch')
    archived = bundle['source_rows']
    current = source_rows(rows, week)
    if len(current) != len(archived):
        raise HistoricalScheduleError(f'Week {week}: checkpoint slate completeness drift')
    for old, new in zip(sorted(archived, key=lambda r: str(r['game_id'])),
                        sorted(current, key=lambda r: str(r['game_id'])), strict=True):
        for field in FIELDS:
            if field == 'roof' and _roof(old) == _roof(new):
                continue  # OPEN/CLOSED actuals never alter canonical retractable context.
            if field == 'surface' and not str(new[field] or '').strip():
                continue
            if old[field] != new[field]:
                raise HistoricalScheduleError(
                    f"{new['game_id']}: checkpoint identity/context conflict field={field} recovery=REJECTED"
                )
    replay = build_week_schedule(archived, season=2026, week=week, observed_at_utc=payload['verified_at_utc'])
    if replay != payload:
        raise HistoricalScheduleError(f'Week {week}: checkpoint incompatible with current replay contract')
    return bundle
