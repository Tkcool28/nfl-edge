"""Real immutable Week9 checkpoint; no live input or provider access."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from nfl_edge.live.historical_schedule_2026 import FIELDS, HistoricalScheduleError, reuse, sha

REF = 'b35fb2e0cabb01ef7d829e447c53918c69fe2922c76eabe908bb5c2f7b6cb191'
FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures/week9_lv_sf_checkpoint.json'
GID = '2026_09_LV_SF'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('network forbidden in kickoff reconciliation')
    monkeypatch.setattr('socket.socket.connect', forbidden)
    monkeypatch.setattr('requests.sessions.Session.request', forbidden)


@pytest.fixture
def replay(tmp_path):
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '214603b8bdc065f71f95c7906ca60d04f0994259bbc24e717b1caa5002c6da17'
    bundle = json.loads(raw)
    assert sha(bundle) == REF
    directory = tmp_path / 'schedule_checkpoints'
    directory.mkdir()
    (directory / f'{REF}.json').write_bytes(raw)
    (tmp_path / 'settled_evidence_manifest.json').write_text(json.dumps({
        'schema_version': 'nfl-edge-settled-2026-evidence-v1', 'season': 2026,
        'active_week': 9, 'schedule_checkpoints': {'9': REF},
    }))
    rows = deepcopy(bundle['source_rows'])
    next(r for r in rows if r['game_id'] == GID)['gametime'] = '16:25'
    return tmp_path, bundle, rows


def test_exact_reconciliation_preserves_prediction_as_of_archive(replay):
    root, bundle, rows = replay
    before = {p: p.read_bytes() for p in root.rglob('*.json')}
    original_rows = deepcopy(rows)
    assert reuse(root, rows, 9) == bundle
    assert reuse(root, rows, 9) == bundle
    assert rows == original_rows
    game = next(g for g in bundle['schedule']['games'] if g['game_id'] == GID)
    assert game['scheduled_start_utc'] == '2026-11-08T21:05:00Z'
    assert game['context_source_at_utc'] == '2026-11-06T00:01:01Z'
    assert {p: p.read_bytes() for p in root.rglob('*.json')} == before


@pytest.mark.parametrize('field', [f for f in FIELDS if f != 'gametime'])
def test_other_identity_or_context_drift_is_rejected(replay, field):
    root, _, rows = replay
    next(r for r in rows if r['game_id'] == GID)[field] = 'dome' if field == 'roof' else 'WRONG'
    with pytest.raises(HistoricalScheduleError):
        reuse(root, rows, 9)


@pytest.mark.parametrize('time', ['16:24', '16:26', '13:25', ''])
def test_other_corrected_time_is_rejected(replay, time):
    root, _, rows = replay
    next(r for r in rows if r['game_id'] == GID)['gametime'] = time
    with pytest.raises(HistoricalScheduleError, match='field=gametime'):
        reuse(root, rows, 9)


def test_other_game_time_drift_is_rejected(replay):
    root, _, rows = replay
    next(r for r in rows if r['game_id'] != GID)['gametime'] = '16:25'
    with pytest.raises(HistoricalScheduleError, match='field=gametime'):
        reuse(root, rows, 9)


@pytest.mark.parametrize('readdress', [False, True])
@pytest.mark.parametrize('field', ['gametime', 'gameday', 'stadium', 'surface', 'roof'])
def test_altered_original_checkpoint_is_rejected(replay, field, readdress):
    root, bundle, rows = replay
    next(r for r in bundle['source_rows'] if r['game_id'] == GID)[field] = 'WRONG'
    ref = sha(bundle) if readdress else REF
    (root / 'schedule_checkpoints' / f'{ref}.json').write_text(json.dumps(bundle))
    manifest_path = root / 'settled_evidence_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['schedule_checkpoints']['9'] = ref
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(HistoricalScheduleError):
        reuse(root, rows, 9)


def test_existing_blank_surface_allowance_is_preserved(replay):
    root, bundle, rows = replay
    next(r for r in rows if r['game_id'] == GID)['surface'] = ''
    assert reuse(root, rows, 9) == bundle
