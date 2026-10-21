from __future__ import annotations

import json
from copy import deepcopy

import polars as pl
import pytest

from nfl_edge.features.totals_v1.pbp_semantics import REQUIRED_PBP_COLUMNS
from nfl_edge.live import evidence_2026 as ev
from nfl_edge.live import surface_evidence_2026 as surfaces
from nfl_edge.live.historical_schedule_2026 import HistoricalScheduleError, reuse, sha
from nfl_edge.live.schedule_materializer_2026 import (
    ScheduleMaterializationError,
    build_week_schedule,
    choose_active_schedule,
)

NOW = '2026-10-21T12:00:00Z'


def rows():
    dates = ['2026-09-10', '2026-09-17', '2026-09-24', '2026-10-01',
             '2026-10-08', '2026-10-15', '2026-10-22']
    return [dict(season='2026', week=str(w), game_type='REG', game_id=f'2026_{w:02d}_SEA_DEN',
                 gameday=day, gametime='20:15', away_team='SEA', home_team='DEN',
                 stadium='Empower Field at Mile High', stadium_id='DEN00', surface='grass',
                 roof='outdoors', location='Home', away_rest='7', home_rest='7',
                 away_score='14', home_score='17', away_qb_id='away', home_qb_id='home',
                 away_qb_name='Away', home_qb_name='Home') for w, day in enumerate(dates, 1)]


@pytest.fixture
def sources(monkeypatch):
    monkeypatch.setattr(ev, '_now', lambda: NOW)
    monkeypatch.setattr('requests.sessions.Session.request', lambda *a, **k: pytest.fail('network forbidden'))
    games = ev._canonical_games(rows(), through_week=6)
    team = pl.DataFrame([dict(game_id=g['game_id'], season=2026, week=g['week'], team=t,
                              passing_epa=1., rushing_epa=1., passing_yards=100., rushing_yards=50.)
                         for g in games.to_dicts() for t in ['SEA', 'DEN']])
    qb = team.with_columns(pl.lit('QB').alias('position'), pl.col('team').alias('player_id'),
                           pl.lit(20).alias('attempts'), pl.lit(1).alias('sacks_suffered'),
                           pl.lit(0.).alias('passing_cpoe'), pl.lit(0).alias('passing_interceptions'))
    pbp_rows = []
    for g in games.to_dicts():
        r = dict.fromkeys(REQUIRED_PBP_COLUMNS, 0)
        r.update(game_id=g['game_id'], season=2026, week=g['week'], qtr=5, play_id=200,
                 game_seconds_remaining=100., total_home_score=17, total_away_score=14,
                 posteam='SEA', defteam='DEN', home_team='DEN', away_team='SEA')
        pbp_rows.append(r)
    data = {ev.TEAM_STATS_URL: team, ev.PLAYER_STATS_URL: qb, ev.PBP_URL: pl.DataFrame(pbp_rows)}
    monkeypatch.setattr(ev, '_download_parquet', lambda url, **kw: (data[url], sha(data[url].to_dicts())))
    return data


def materialize(root, source):
    return ev.materialize_settled_evidence(output_dir=root, schedule_rows=source, active_as_of_utc=NOW)


def test_original_week6_shape_verified_and_deterministic():
    source = rows()[5]
    source['surface'] = ''
    before = deepcopy(source)
    a = build_week_schedule([source], season=2026, week=6, observed_at_utc=NOW)
    assert a == build_week_schedule([source], season=2026, week=6, observed_at_utc=NOW)
    assert a['games'][0]['surface'] == 'grass'
    assert a['surface_recovery'][0]['evidence']['verified_surface_class'] == 'grass'
    assert source == before


@pytest.mark.parametrize('field', ['gameday', 'stadium', 'stadium_id', 'game_id'])
def test_exact_game_evidence_rejects_identity_conflict(field):
    r = rows()[5]
    r.update(surface='')
    r[field] = 'wrong'
    with pytest.raises(ScheduleMaterializationError, match='identity mismatch'):
        build_week_schedule([r], season=2026, week=6, observed_at_utc=NOW)


@pytest.mark.parametrize('change', ['digest', 'provenance', 'class', 'duplicate', 'subtype'])
def test_bad_registry_fails_closed(tmp_path, monkeypatch, change):
    payload = json.loads(surfaces.EVIDENCE_PATH.read_text())
    entry = payload['games'][0]
    if change == 'digest':
        entry['evidence']['surface'] = 'fieldturf'
    else:
        if change == 'provenance':
            entry['evidence']['source_urls'] = []
        if change == 'class':
            entry['evidence']['verified_surface_class'] = 'artificial'
        if change == 'subtype':
            entry['evidence']['surface_subtype_known'] = False
        entry['evidence_sha256'] = surfaces.digest(entry['evidence'])
        if change == 'duplicate':
            payload['games'].append(deepcopy(entry))
    path = tmp_path / 'registry.json'
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(surfaces, 'EVIDENCE_PATH', path)
    with pytest.raises(surfaces.SurfaceEvidenceError):
        surfaces.load_surface_evidence()


def test_historical_blank_surface_replays_without_suppressing_week7(tmp_path, sources):
    source = rows()
    materialize(tmp_path, source)
    original = (tmp_path / 'week6_schedule_v1.json').read_bytes()
    # No game-specific Week 4 recovery exists: this must use the checkpoint.
    source[3]['surface'] = ''
    source[5]['surface'] = ''
    recovered = materialize(tmp_path, source)
    assert (tmp_path / 'week6_schedule_v1.json').read_bytes() == original
    assert json.loads((tmp_path / 'week7_schedule_v1.json').read_text())['week'] == 7
    assert recovered.through_week == 6
    assert all(d['decision'] == 'HASH_VALIDATED_IMMUTABLE_REPLAY'
               for d in recovered.manifest['schedule_recovery_decisions'])
    again = materialize(tmp_path, source)
    assert recovered.manifest == again.manifest


def test_naked_schedule_is_not_trusted_and_active_schedule_is_isolated(tmp_path, sources):
    materialize(tmp_path, rows())
    (tmp_path / 'settled_evidence_manifest.json').unlink()
    source = rows()
    source[3]['surface'] = ''
    with pytest.raises(ev.SettledEvidenceError, match='HISTORICAL_SCHEDULE_METADATA.*missing required surface'):
        materialize(tmp_path, source)
    assert json.loads((tmp_path / 'week7_schedule_v1.json').read_text())['week'] == 7


@pytest.mark.parametrize('field,value', [('surface', 'fieldturf'), ('stadium_id', 'OTHER'),
                                         ('gametime', '13:00'), ('away_rest', '4')])
def test_replay_context_conflicts_block(tmp_path, sources, field, value):
    materialize(tmp_path, rows())
    source = rows()
    source[3][field] = value
    with pytest.raises(ev.SettledEvidenceError, match='checkpoint identity/context conflict'):
        materialize(tmp_path, source)


def test_corrupt_checkpoint_and_schedule_block(tmp_path, sources):
    materialize(tmp_path, rows())
    schedule = tmp_path / 'week6_schedule_v1.json'
    payload = json.loads(schedule.read_text())
    payload['games'][0]['surface'] = 'fieldturf'
    schedule.write_text(json.dumps(payload))
    with pytest.raises(ev.SettledEvidenceError, match='HISTORICAL_REPLAY_INTEGRITY'):
        ev.load_settled_evidence(tmp_path)
    manifest = json.loads((tmp_path / 'settled_evidence_manifest.json').read_text())
    ref = manifest['schedule_checkpoints']['6']
    bundle = tmp_path / 'schedule_checkpoints' / f'{ref}.json'
    payload = json.loads(bundle.read_text())
    payload['source_url'] = 'https://untrusted.example/'
    bundle.write_text(json.dumps(payload))
    with pytest.raises(HistoricalScheduleError, match='integrity/provenance'):
        reuse(tmp_path, rows(), 6)


def test_cached_metadata_does_not_bypass_required_pbp_or_results(tmp_path, sources):
    materialize(tmp_path, rows())
    source = rows()
    source[3]['surface'] = ''
    sources[ev.PBP_URL] = sources[ev.PBP_URL].filter(pl.col('week') != 6)
    with pytest.raises(ev.SettledEvidenceError, match='PBP coverage missing completed games'):
        materialize(tmp_path, source)
    source[5]['home_score'] = ''
    with pytest.raises(ev.SettledEvidenceError, match='not fully settled'):
        materialize(tmp_path, source)


def test_active_week_cannot_reuse_checkpoint_or_guess_surface(tmp_path, sources):
    materialize(tmp_path, rows())
    old = (tmp_path / 'week7_schedule_v1.json').read_bytes()
    source = rows()
    source[6]['surface'] = ''
    with pytest.raises(ScheduleMaterializationError, match='missing required surface'):
        materialize(tmp_path, source)
    assert (tmp_path / 'week7_schedule_v1.json').read_bytes() == old


def test_exact_week7_tuesday_rollover():
    source = rows()
    for timestamp, week in [('2026-10-20T11:59:59Z', 6), ('2026-10-20T12:00:00Z', 7)]:
        assert choose_active_schedule(source, season=2026, active_as_of_utc=timestamp,
                                      observed_at_utc=timestamp)['week'] == week


def test_active_attestation_can_feed_next_week_history(tmp_path, sources):
    # The Week 6 active schedule is checkpointed after Week 5 evidence passes.
    source = rows()
    first = ev.materialize_settled_evidence(output_dir=tmp_path, schedule_rows=source,
                                           active_as_of_utc='2026-10-16T12:00:00Z')
    assert first.through_week == 5
    source[5]['surface'] = ''
    later = materialize(tmp_path, source)
    assert later.through_week == 6
    assert later.manifest['schedule_recovery_decisions'][-1]['decision'] == 'HASH_VALIDATED_IMMUTABLE_REPLAY'


def test_checkpoint_complete_slate_and_replay_contract(tmp_path, sources):
    materialize(tmp_path, rows())
    with pytest.raises(HistoricalScheduleError, match='slate completeness'):
        reuse(tmp_path, [r for r in rows() if r['week'] != '6'], 6)
    manifest_path = tmp_path / 'settled_evidence_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    path = tmp_path / 'schedule_checkpoints' / f"{manifest['schedule_checkpoints']['6']}.json"
    bundle = json.loads(path.read_text())
    bundle['schedule']['games'][0]['surface'] = 'fieldturf'
    ref = sha(bundle)
    (path.parent / f'{ref}.json').write_text(json.dumps(bundle))
    manifest['schedule_checkpoints']['6'] = ref
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(HistoricalScheduleError, match='incompatible with current replay'):
        reuse(tmp_path, rows(), 6)


def test_preprovider_reports_blocked_stage_without_provider(tmp_path, monkeypatch, capsys):
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / 'scripts/verify_live_2026_preprovider_v1.py'
    spec = importlib.util.spec_from_file_location('week7_preprovider_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(sys, 'argv', [str(path), '--schedule-root', str(tmp_path),
                                    '--evidence-root', str(tmp_path), '--run-root', str(tmp_path),
                                    '--prediction-as-of-utc', NOW])
    monkeypatch.setattr('requests.sessions.Session.request', lambda *a, **k: pytest.fail('provider forbidden'))
    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result['verdict'] == 'NFL_EDGE_PREPROVIDER_BLOCKED'
    assert result['blocked_stage'] == 'ACTIVE_WEEK_SCHEDULE'
    assert result['provider_request_count'] == 0


def test_reviewed_week6_archive_reproduces_original_production_bytes(tmp_path):
    import hashlib

    from nfl_edge.live.historical_schedule_2026 import REVIEWED_CHECKPOINTS, REVIEWED_ROOT

    ref = REVIEWED_CHECKPOINTS[6]
    bundle = json.loads((REVIEWED_ROOT / f'{ref}.json').read_text())
    assert sha(bundle) == ref
    source = deepcopy(bundle['source_rows'])
    for r in source:
        r['surface'] = ''
    recovered = reuse(tmp_path, source, 6, allow_reviewed=True)
    raw = (json.dumps(recovered['schedule'], sort_keys=True, indent=2) + '\n').encode()
    assert hashlib.sha256(raw).hexdigest() == '8a2ace347b2d2fbe0c0c08d50cbe803efbba26b6ec4e63cf1802e3b90dc2e76e'
    assert len(recovered['schedule']['games']) == 14
    # This attestation cannot authorize unknown active-week metadata.
    with pytest.raises(ScheduleMaterializationError, match='missing required surface'):
        choose_active_schedule(source, season=2026, active_as_of_utc='2026-10-16T12:00:00Z',
                               observed_at_utc=NOW)
    source[0]['surface'] = 'unverified'
    with pytest.raises(HistoricalScheduleError, match='field=surface'):
        reuse(tmp_path, source, 6, allow_reviewed=True)


def test_replay_preserves_retractable_structure_and_fresh_actual_position(tmp_path):
    from nfl_edge.live.historical_schedule_2026 import REVIEWED_CHECKPOINTS, REVIEWED_ROOT

    bundle = json.loads((REVIEWED_ROOT / f'{REVIEWED_CHECKPOINTS[6]}.json').read_text())
    source = deepcopy(bundle['source_rows'])
    for r in source:
        if r['home_team'] in {'ATL', 'IND'}:
            r['roof'] = 'closed'
    recovered = reuse(tmp_path, source, 6, allow_reviewed=True)
    assert all(g['roof_type'] is None for g in recovered['schedule']['games']
               if g['home_team'] in {'ATL', 'IND'})
    source[0]['roof'] = 'outdoors'  # SoFi cannot become an outdoor venue.
    with pytest.raises(HistoricalScheduleError, match='field=roof'):
        reuse(tmp_path, source, 6, allow_reviewed=True)


def test_checkpoint_keeps_week5_provenance_order(tmp_path):
    from nfl_edge.live.historical_schedule_2026 import checkpoint
    from nfl_edge.live.week5_surface_evidence_2026 import IDENTITY_FIELDS, load_surface_evidence

    source = [{**{k: r[k] for k in IDENTITY_FIELDS}, 'surface': '', 'roof': 'outdoors',
               'gametime': '13:00', 'away_rest': '7', 'home_rest': '7', 'location': 'Home'}
              for r in load_surface_evidence().values()]
    payload = build_week_schedule(source, season=2026, week=5, observed_at_utc=NOW)
    bundle = checkpoint(source, payload)
    ref = sha(bundle)
    (tmp_path / 'schedule_checkpoints').mkdir()
    (tmp_path / 'schedule_checkpoints' / f'{ref}.json').write_text(json.dumps(bundle))
    (tmp_path / 'settled_evidence_manifest.json').write_text(json.dumps({
        'schema_version': ev.EVIDENCE_SCHEMA, 'season': 2026, 'active_week': 6,
        'through_week': 5, 'schedule_checkpoints': {'5': ref}}))
    assert reuse(tmp_path, list(reversed(source)), 5)['schedule'] == payload
