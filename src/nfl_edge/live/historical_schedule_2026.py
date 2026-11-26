"""Schedule checkpoints issued with validated settled evidence.

The successful evidence manifest pins content-addressed source and schedule
bundles. Historical replay reproduces the pinned schedule while checking
upstream drift. Active recovery uses exact-game, dated venue context from a
pinned checkpoint and records the original observed source for later replay.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from functools import cache
from pathlib import Path

from .nflverse_2026_identity import (
    NFLVerse2026IdentityError, canonical_game_id, canonical_schedule_game_id,
)
from .schedule_materializer_2026 import (
    NFLVERSE_GAMES_URL, ScheduleMaterializationError, _kickoff_utc, _required, _roof, _utc,
    build_week_schedule,
)
from .schedule_verification_2026 import ScheduleVerificationError, historical_kickoff_evidence
from .surface_evidence_2026 import KNOWN_SURFACES

SURFACE_RECOVERY_SCHEMA = 'NFL_EDGE_EXACT_GAME_CHECKPOINT_SURFACE_V1'
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


def _load_bundle(directory, ref, week):
    if not isinstance(ref, str) or len(ref) != 64 or any(c not in '0123456789abcdef' for c in ref):
        raise HistoricalScheduleError(f'Week {week}: invalid checkpoint digest')
    bundle = json.loads((directory / f'{ref}.json').read_text())
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
    return bundle


def _manifest(root):
    path = root / 'settled_evidence_manifest.json'
    return json.loads(path.read_text()) if path.exists() else {}


def _pinned_ref(manifest, week):
    ref = manifest.get('schedule_checkpoints', {}).get(str(week))
    if ref is not None and (manifest.get('schema_version') != 'nfl-edge-settled-2026-evidence-v1'
                            or manifest.get('season') != 2026 or week > manifest.get('active_week', -1)):
        raise HistoricalScheduleError(f'Week {week}: checkpoint manifest identity mismatch')
    return ref


def _surface_context(row, game_id):
    week = int(row['week'])
    try:
        if (str(row.get('season')) != '2026' or row.get('game_type') != 'REG'
                or canonical_game_id(row.get('game_id')) != game_id
                or canonical_schedule_game_id(row, season=2026, week=week) != game_id):
            raise ScheduleMaterializationError(f'{game_id}: surface checkpoint matchup identity mismatch')
    except NFLVerse2026IdentityError as exc:
        raise ScheduleMaterializationError(f'{game_id}: invalid surface checkpoint identity: {exc}') from exc
    location = _required(row, 'location').lower()
    if location not in {'home', 'neutral'}:
        raise ScheduleMaterializationError(f'{game_id}: invalid surface checkpoint location {location!r}')
    return {
        'game_id': game_id,
        'gameday': _required(row, 'gameday'),
        'venue': _required(row, 'stadium'),
        'venue_id': _required(row, 'stadium_id'),
        'neutral_site': location == 'neutral',
        'roof_structure': _roof(row)[1],
    }


def _checkpoint_surface(bundle, ref, row, game_id, observed, reviewed):
    """Use an observed surface from the same game, even when replayed later."""
    schedule = bundle['schedule']
    week = schedule['week']
    matches = [old for old in bundle['source_rows']
               if canonical_schedule_game_id(old, season=2026, week=week) == game_id]
    games = [game for game in schedule['games'] if game['game_id'] == game_id]
    if len(matches) != 1 or len(games) != 1:
        raise ScheduleMaterializationError(f'{game_id}: missing or ambiguous exact-game surface checkpoint')
    old, = matches
    game, = games
    context = _surface_context(row, game_id)
    if context != _surface_context(old, game_id):
        raise ScheduleMaterializationError(f'{game_id}: surface checkpoint date/venue context mismatch')
    if any(game[k] != context[k] for k in ('venue', 'venue_id', 'neutral_site', 'roof_structure')):
        raise ScheduleMaterializationError(f'{game_id}: inconsistent surface checkpoint venue context')
    source_observed = schedule['verified_at_utc']
    if _utc(source_observed) > _utc(observed):
        raise ScheduleMaterializationError(f'{game_id}: surface checkpoint observed after materialization')
    surface = str(old.get('surface') or '').strip().lower()
    if surface not in KNOWN_SURFACES or game['surface'] != surface:
        raise ScheduleMaterializationError(f'{game_id}: checkpoint lacks a supported observed surface')
    if reviewed is not None and reviewed[0] != surface:
        raise ScheduleMaterializationError(f'{game_id}: conflicting exact-game surface evidence')
    return surface, {
        'schema_version': SURFACE_RECOVERY_SCHEMA,
        'source_checkpoint_sha256': ref,
        'source_observed_at_utc': source_observed,
        'original_surface': row.get('surface'),
        'surface': surface,
        'verified_surface_class': 'grass' if surface == 'grass' else 'artificial',
        'source_identity': context,
    }


def _replay(root, bundle):
    payload = bundle['schedule']
    week = payload['week']
    observed = payload['verified_at_utc']
    refs = {}
    for item in payload.get('surface_recovery', []):
        if item.get('schema_version') == SURFACE_RECOVERY_SCHEMA:
            game_id = item['source_identity']['game_id']
            if game_id in refs:
                raise HistoricalScheduleError(f'{game_id}: duplicate exact-game surface provenance')
            refs[game_id] = item['source_checkpoint_sha256']

    @cache
    def source(ref):
        return _load_bundle(root / 'schedule_checkpoints', ref, week)

    def resolve(row, game_id, reviewed):
        ref = refs.get(game_id)
        if ref is None or str(row.get('surface') or '').strip():
            return reviewed
        return _checkpoint_surface(source(ref), ref, row, game_id, observed, reviewed)

    try:
        replay = build_week_schedule(bundle['source_rows'], season=2026, week=week,
                                     observed_at_utc=observed, resolve_surface=resolve)
    except (ScheduleMaterializationError, NFLVerse2026IdentityError) as exc:
        raise HistoricalScheduleError(f'Week {week}: invalid checkpoint replay context: {exc}') from exc
    if replay != payload:
        raise HistoricalScheduleError(f'Week {week}: checkpoint incompatible with current replay contract')


def active_surface_resolver(root, observed):
    """Resolve active-week surface gaps using only the successful manifest's exact game."""
    @cache
    def prior(week):
        ref = _pinned_ref(_manifest(root), week)
        if ref is None:
            return None, None
        bundle = _load_bundle(root / 'schedule_checkpoints', ref, week)
        _replay(root, bundle)
        return ref, bundle

    def resolve(row, game_id, reviewed):
        if str(row.get('season')) != '2026' or row.get('game_type') != 'REG':
            return reviewed
        supplied = str(row.get('surface') or '').strip().lower()
        week = int(row['week'])
        try:
            ref, bundle = prior(week)
            if bundle is None:
                return reviewed
            schedule = bundle['schedule']
            if game_id not in {game['game_id'] for game in schedule['games']}:
                return reviewed
            recovery = next((item for item in schedule.get('surface_recovery', [])
                             if item.get('schema_version') == SURFACE_RECOVERY_SCHEMA
                             and item['source_identity']['game_id'] == game_id), None)
            if supplied:
                # A fresh field is authoritative unless it contradicts a recovery
                # for the same date and venue. Leave other upstream fields alone.
                if recovery and recovery['source_identity'] == _surface_context(row, game_id):
                    if recovery['surface'] != supplied:
                        raise ScheduleMaterializationError(f'{game_id}: conflicting upstream surface after recovery')
                return reviewed
            if recovery:
                # Keep a direct link to the observed source across repeated omissions.
                ref = recovery['source_checkpoint_sha256']
                bundle = _load_bundle(root / 'schedule_checkpoints', ref, week)
            elif reviewed is not None and any(
                item['source_identity']['game_id'] == game_id
                for item in schedule.get('surface_recovery', [])
            ):
                # Reviewed registry entries replay under their existing contract.
                return reviewed
            return _checkpoint_surface(bundle, ref, row, game_id, observed, reviewed)
        except (HistoricalScheduleError, NFLVerse2026IdentityError, OSError, ValueError, KeyError, TypeError) as exc:
            raise ScheduleMaterializationError(f'{game_id}: invalid surface checkpoint: {exc}') from exc

    return resolve


def reuse(
    root: Path, rows, week: int, *, allow_reviewed: bool = False,
    acquire_espn: Callable[[str], tuple[bytes, str]] | None = None,
    kickoff_audit: list[dict] | None = None,
):
    manifest = _manifest(root)
    ref = _pinned_ref(manifest, week)
    directory = root / 'schedule_checkpoints'
    if ref is None:
        ref = REVIEWED_CHECKPOINTS.get(week) if allow_reviewed else None
        if ref is None:
            return None  # Naked legacy JSON files are never trusted.
        directory = REVIEWED_ROOT
    bundle = _load_bundle(directory, ref, week)
    payload = bundle['schedule']
    archived = bundle['source_rows']
    current = source_rows(rows, week)
    if len(current) != len(archived):
        raise HistoricalScheduleError(f'Week {week}: checkpoint slate completeness drift')
    _replay(root, bundle)
    recovered_surfaces = {game['game_id']: game['surface'] for game in payload['games']}
    discrepancies = []
    for old, new in zip(sorted(archived, key=lambda r: str(r['game_id'])),
                        sorted(current, key=lambda r: str(r['game_id'])), strict=True):
        for field in FIELDS:
            if field == 'roof':
                try:
                    if _roof(old) == _roof(new):
                        continue  # OPEN/CLOSED actuals never alter canonical retractable context.
                except ScheduleMaterializationError as exc:
                    raise HistoricalScheduleError(
                        f"{new['game_id']}: invalid checkpoint roof context: {exc}"
                    ) from exc
            if field == 'surface':
                supplied = str(new[field] or '').strip().lower()
                if not supplied:
                    continue
                if not str(old[field] or '').strip():
                    # The replayed schedule binds the recovered value. Accept
                    # its later reappearance upstream, but reject a different value.
                    game_id = canonical_schedule_game_id(old, season=2026, week=week)
                    if supplied == recovered_surfaces[game_id]:
                        continue
            # One-time LV@SF source reconciliation; retain the pregame archive
            # (including 21:05Z and its as-of), never backdate corrected knowledge.
            # Official 13:25 PST gamebook and source hashes: see
            # reports/week9_kickoff_reconciliation_2026.md.
            if (field == 'gametime' and week == 9
                    and ref == 'b35fb2e0cabb01ef7d829e447c53918c69fe2922c76eabe908bb5c2f7b6cb191'
                    and all(old[k] == new[k] == v for k, v in {
                        'season': '2026', 'game_type': 'REG', 'week': '9',
                        'game_id': '2026_09_LV_SF', 'gameday': '2026-11-08',
                        'away_team': 'LV', 'home_team': 'SF',
                        'stadium': "Levi's Stadium", 'stadium_id': 'SFO01',
                    }.items())
                    and old[field] == '16:05' and new[field] == '16:25'):
                continue
            if field == 'gametime' and old[field] != new[field]:
                discrepancies.append(new)
                continue
            if old[field] != new[field]:
                raise HistoricalScheduleError(
                    f"{new['game_id']}: checkpoint identity/context conflict field={field} recovery=REJECTED"
                )
    try:
        verified = {}
        for decision in manifest.get('schedule_recovery_decisions', []):
            if decision.get('week') != week:
                continue
            for item in decision.get('kickoff_reconciliations', []):
                game_id = item['game_id']
                if decision['checkpoint_sha256'] != ref or game_id in verified:
                    raise HistoricalScheduleError(f'Week {week}: conflicting kickoff reconciliation manifest')
                confirmed = historical_kickoff_evidence(
                    root, payload, game_id, item['corrected_kickoff_utc'], checkpoint_sha256=ref,
                )
                if item != confirmed:
                    raise HistoricalScheduleError(f'{game_id}: kickoff reconciliation audit mismatch')
                verified[game_id] = confirmed

        for game in discrepancies:
            game_id = game['game_id']
            try:
                corrected = _kickoff_utc(game)
                # Equivalent representations of the same kickoff need no ESPN evidence.
                original = next(g['scheduled_start_utc'] for g in payload['games'] if g['game_id'] == game_id)
                if original == corrected:
                    continue
                verified[game_id] = historical_kickoff_evidence(
                    root, payload, game_id, corrected, checkpoint_sha256=ref, acquire=acquire_espn,
                )
            except (ScheduleVerificationError, ScheduleMaterializationError) as exc:
                raise HistoricalScheduleError(
                    f"{game_id}: checkpoint identity/context conflict field=gametime recovery=REJECTED: {exc}"
                ) from exc
    except (ScheduleVerificationError, KeyError, TypeError, ValueError) as exc:
        raise HistoricalScheduleError(f'Week {week}: kickoff reconciliation integrity rejected: {exc}') from exc
    if kickoff_audit is not None:
        kickoff_audit.extend(verified[gid] for gid in sorted(verified))
    return bundle
