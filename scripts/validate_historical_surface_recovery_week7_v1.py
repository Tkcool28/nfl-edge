#!/usr/bin/env python3
"""Bounded free-input acquisition and authentic Week 7 recovery; no provider API.

Stop at the first missing mandatory gate. No synthetic schedules or timestamps.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import requests  # noqa: E402

from nfl_edge.live.evidence_2026 import (  # noqa: E402
    NFLVERSE_GAMES_URL,
    PBP_URL,
    PLAYER_STATS_URL,
    TEAM_STATS_URL,
    materialize_settled_evidence,
)
from nfl_edge.live.schedule_materializer_2026 import materialize_active_schedule  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    root = args.output_dir.resolve()
    (root / 'raw').mkdir(parents=True, exist_ok=True)
    allowed = {NFLVERSE_GAMES_URL: 'games.csv', TEAM_STATS_URL: 'team.parquet',
               PLAYER_STATS_URL: 'player.parquet', PBP_URL: 'pbp.parquet'}
    sources = []

    class FreeSession:
        def get(self, url, **kwargs):
            if url not in allowed:
                raise AssertionError(f'non-free-source request prohibited: {url}')
            response = requests.get(url, timeout=60)
            sources.append({'url': url, 'status': response.status_code,
                            'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
                            'sha256': hashlib.sha256(response.content).hexdigest(),
                            'bytes': len(response.content)})
            response.raise_for_status()
            (root / 'raw' / allowed[url]).write_bytes(response.content)
            return response

    result = {'verdict': 'CODE_READY_VALIDATION_BLOCKED', 'provider_request_count': 0,
              'odds_api_called': False, 'market_data_read': False, 'free_sources': sources}
    try:
        response = FreeSession().get(NFLVERSE_GAMES_URL)
        rows = list(csv.DictReader(io.StringIO(response.content.decode())))
        now = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        result['prediction_as_of_utc'] = now
        path, schedule = materialize_active_schedule(output_dir=root / 'evidence', rows=rows, active_as_of_utc=now)
        result['active_schedule'] = {'week': schedule['week'], 'game_count': len(schedule['games']),
                                     'game_ids': [g['game_id'] for g in schedule['games']],
                                     'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        if schedule['week'] != 7 or len(schedule['games']) != 14:
            raise RuntimeError('expected authentic Week 7 fourteen-game slate')
        result['week6_blank_surface_games'] = [r['game_id'] for r in rows
                                               if r['season'] == '2026' and r['week'] == '6'
                                               and r['game_type'] == 'REG' and not r['surface']]
        result['stage'] = 'SETTLED_WEEK6_RECONSTRUCTION'
        evidence = materialize_settled_evidence(output_dir=root / 'evidence', schedule_rows=rows,
                                                active_as_of_utc=now, session=FreeSession())
        result['settled_manifest'] = evidence.manifest
        result['verdict'] = 'SETTLED_READY_CANONICAL_PREFLIGHT_REQUIRED'
    except Exception as exc:
        result.update(error_type=type(exc).__name__, error=str(exc), traceback=traceback.format_exc())
    (root / 'validation-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['verdict'] == 'SETTLED_READY_CANONICAL_PREFLIGHT_REQUIRED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
