"""Offline exact-game regressions; frozen upstream rows are independent of registry."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from nfl_edge.live import surface_evidence_2026 as surfaces
from nfl_edge.live.historical_schedule_2026 import HistoricalScheduleError, checkpoint, reuse, sha
from nfl_edge.live.schedule_materializer_2026 import build_week_schedule
from nfl_edge.live.week5_surface_evidence_2026 import IDENTITY_FIELDS

REPORTS = Path(__file__).resolve().parents[2] / 'reports/surface_recovery_phase1_2026'
SNAPSHOT = json.loads((REPORTS / 'nflverse_identity_snapshot.json').read_text())
ROWS = {r['game_id']: r for r in SNAPSHOT['rows']}
CASES = [
    ('2026_09_JAX_BAL', '2026-11-05', 'M&T Bank Stadium', 'BAL00', 'grass'),
    ('2026_10_WAS_NYG', '2026-11-12', 'MetLife Stadium', 'NYC01', 'fieldturf'),
]
NOW = '2026-11-13T16:00:00Z'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('network forbidden in surface regression')
    monkeypatch.setattr('requests.sessions.Session.request', forbidden)


@pytest.mark.parametrize('gid,day,venue,venue_id,token', CASES)
def test_exact_game_surface_materialization(gid, day, venue, venue_id, token):
    row = deepcopy(ROWS[gid])
    before = deepcopy(row)
    assert (row['gameday'], row['stadium'], row['stadium_id'], row['surface']) == (day, venue, venue_id, '')
    week = int(row['week'])
    result = build_week_schedule([row], season=2026, week=week, observed_at_utc=NOW)
    assert result == build_week_schedule([row], season=2026, week=week, observed_at_utc=NOW)
    assert row == before
    game, = result['games']
    assert (game['game_id'], game['surface'], game['venue'], game['venue_id']) == (gid, token, venue, venue_id)
    recovery, = result['surface_recovery']
    assert recovery['original_surface'] == ''
    assert recovery['source_identity'] == {k: row[k] for k in IDENTITY_FIELDS}
    evidence = recovery['evidence']
    assert evidence['canonical_game_id'] == gid
    assert evidence['surface_subtype_known'] is True
    assert evidence['verified_surface_class'] == ('grass' if token == 'grass' else 'artificial')
    assert recovery['evidence_sha256'] == surfaces.digest(evidence)
    assert any('/gamecenter/' in u and u.endswith('.pdf') for u in evidence['source_urls'])
    assert evidence['original_source_sha256'] == SNAPSHOT['raw_sha256']


@pytest.mark.parametrize('gid', [c[0] for c in CASES])
@pytest.mark.parametrize('field', ['game_id', 'gameday', 'away_team', 'home_team', 'stadium', 'stadium_id'])
def test_each_game_rejects_identity_mismatch(gid, field):
    row = deepcopy(ROWS[gid])
    row[field] = 'WRONG'
    with pytest.raises(surfaces.SurfaceEvidenceError, match='identity mismatch'):
        surfaces.recover_missing_surface(row, canonical_game_id=gid)


@pytest.mark.parametrize('gid', [c[0] for c in CASES])
@pytest.mark.parametrize('field,value', [('season', '2025'), ('game_type', 'POST'), ('week', '8')])
def test_each_game_cannot_escape_scope(gid, field, value):
    row = deepcopy(ROWS[gid])
    row[field] = value
    if field == 'week':
        with pytest.raises(surfaces.SurfaceEvidenceError, match='identity mismatch'):
            surfaces.recover_missing_surface(row, canonical_game_id=gid)
    else:
        assert surfaces.recover_missing_surface(row, canonical_game_id=gid) is None


@pytest.mark.parametrize('gid', [c[0] for c in CASES])
def test_nonblank_upstream_is_never_overridden(gid):
    row = dict(ROWS[gid], surface='astroturf')
    assert surfaces.recover_missing_surface(row, canonical_game_id=gid) is None


@pytest.mark.parametrize('gid', [c[0] for c in CASES])
def test_each_game_evidence_digest_is_checked(gid, tmp_path, monkeypatch):
    data = json.loads(surfaces.EVIDENCE_PATH.read_text())
    entry = next(e for e in data['games'] if e['evidence']['canonical_game_id'] == gid)
    entry['evidence']['note'] += 'tampered'
    path = tmp_path / 'registry.json'
    path.write_text(json.dumps(data))
    monkeypatch.setattr(surfaces, 'EVIDENCE_PATH', path)
    with pytest.raises(surfaces.SurfaceEvidenceError, match='digest mismatch'):
        surfaces.load_surface_evidence()


def test_unlisted_game_has_no_team_or_stadium_default():
    row = dict(ROWS['2026_09_JAX_BAL'], game_id='2026_09_LAC_BAL', away_team='LAC')
    assert surfaces.recover_missing_surface(row, canonical_game_id=row['game_id']) is None


def test_lv_sf_gametime_conflict_remains_fail_closed(tmp_path):
    inventory = json.loads((REPORTS / 'runtime_preservation_inventory.json').read_text())
    conflict = inventory['checkpoints']['9']['lv_sf']
    old = conflict['archived_source_row']
    current = ROWS['2026_09_LV_SF']
    assert old['gametime'] == '16:05' and current['gametime'] == '16:25'
    payload = build_week_schedule([old], season=2026, week=9, observed_at_utc=NOW)
    bundle = checkpoint([old], payload)
    ref = sha(bundle)
    (tmp_path / 'schedule_checkpoints').mkdir()
    (tmp_path / 'schedule_checkpoints' / f'{ref}.json').write_text(json.dumps(bundle))
    (tmp_path / 'settled_evidence_manifest.json').write_text(json.dumps({
        'schema_version': 'nfl-edge-settled-2026-evidence-v1', 'season': 2026,
        'active_week': 9, 'schedule_checkpoints': {'9': ref},
    }))
    before = {p: p.read_bytes() for p in tmp_path.rglob('*.json')}
    with pytest.raises(HistoricalScheduleError, match='conflict field=gametime recovery=REJECTED'):
        reuse(tmp_path, [current], 9)
    assert {p: p.read_bytes() for p in tmp_path.rglob('*.json')} == before
