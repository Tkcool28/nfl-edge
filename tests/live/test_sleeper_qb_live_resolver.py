from pathlib import Path

import polars as pl

from nfl_edge.contracts.market_qb_v1 import validate_qb_context
from nfl_edge.live.sleeper_qb import (
    SleeperExpectedQBResolver,
    SleeperQBSource,
    detect_starter_change,
)


def _source(*, method="exact_sleeper_id", matched=True, review=False, years_exp=5, gsis="00-AAA", freshness="FRESH"):
    snapshots = pl.DataFrame([
        {
            "snapshot_id": "snap-1", "fetched_at_utc": "2026-09-02T12:00:00Z",
            "sleeper_player_id": "s1", "gsis_id": gsis, "full_name": "Quarter Back",
            "team": "SEA", "active": True, "years_exp": years_exp,
            "injury_status": None, "depth_chart_position": "QB", "depth_chart_order": 1,
        },
        {
            "snapshot_id": "snap-1", "fetched_at_utc": "2026-09-02T12:00:00Z",
            "sleeper_player_id": "s2", "gsis_id": "00-BBB", "full_name": "Backup QB",
            "team": "SEA", "active": True, "years_exp": 3,
            "injury_status": None, "depth_chart_position": "QB", "depth_chart_order": 2,
        },
    ])
    crosswalk = pl.DataFrame([
        {
            "snapshot_id": "snap-1", "sleeper_player_id": "s1", "gsis_id": gsis,
            "nflverse_player_id": gsis, "match_method": method,
            "is_matched": matched, "review_required": review, "conflict_reason": None,
        },
        {
            "snapshot_id": "snap-1", "sleeper_player_id": "s2", "gsis_id": "00-BBB",
            "nflverse_player_id": "00-BBB", "match_method": "exact_sleeper_id",
            "is_matched": True, "review_required": False, "conflict_reason": None,
        },
    ])
    evidence = pl.DataFrame([
        {"snapshot_id": "snap-1", "sleeper_player_id": "s1", "evidence_state": "DEPTH_CHART_EXPECTED_HEALTHY"},
        {"snapshot_id": "snap-1", "sleeper_player_id": "s2", "evidence_state": "BACKUP_CANDIDATE"},
    ])
    changes = pl.DataFrame([
        {
            "sleeper_player_id": "s1", "team": "SEA",
            "first_observed_changed_at_utc": "2026-09-02T12:00:00Z",
        }
    ])
    return SleeperQBSource(
        audit_root=Path("data/source_audits/sleeper_qb_v1"),
        snapshot_id="snap-1",
        observed_at_utc="2026-09-02T12:00:00Z",
        staleness_threshold_seconds=21600.0,
        freshness_state=freshness,
        age_seconds=3600.0 if freshness != "UNAVAILABLE" else None,
        source_warning_state=None,
        snapshots=snapshots,
        crosswalk=crosswalk,
        evidence=evidence,
        changes=changes,
    )


def test_stable_identity_resolves_and_validates_product_context():
    resolver = SleeperExpectedQBResolver(_source())
    resolution, audit = resolver.resolve_team(game_id="2026_01_NE_SEA", team="SEA")
    assert audit is None
    assert resolution.resolution_status == "RESOLVED"
    assert resolution.canonical_qb_id == "00-AAA"
    context = resolver.to_product_context(resolution)
    validate_qb_context(context, "qb")
    assert context["last_changed_at_utc"] == "2026-09-02T12:00:00Z"


def test_name_team_fallback_is_never_silently_promoted():
    resolver = SleeperExpectedQBResolver(_source(method="name_team_fallback", matched=True, review=True))
    resolution, _ = resolver.resolve_team(game_id="2026_01_NE_SEA", team="SEA")
    assert resolution.resolution_status == "UNRESOLVED"
    assert resolution.canonical_qb_id is None
    assert "NON_STABLE_IDENTITY" in (resolution.source_warning_state or "")


def test_new_rookie_with_direct_gsis_is_explicit_new_player():
    resolver = SleeperExpectedQBResolver(_source(method="none", matched=False, review=False, years_exp=0, gsis="00-ROOK"))
    resolution, _ = resolver.resolve_team(game_id="2026_01_NE_SEA", team="SEA")
    assert resolution.resolution_status == "NEW_PLAYER"
    assert resolution.canonical_qb_id == "00-ROOK"
    assert resolution.model_qb_state_id == "00-ROOK"


def test_out_top_qb_promotes_unique_depth_two_with_warning():
    source = _source()
    evidence = source.evidence.with_columns(
        pl.when(pl.col("sleeper_player_id") == "s1")
        .then(pl.lit("DEPTH_CHART_EXPECTED_OUT"))
        .otherwise(pl.col("evidence_state"))
        .alias("evidence_state")
    )
    source = source.__class__(**{**source.__dict__, "evidence": evidence})
    resolver = SleeperExpectedQBResolver(source)
    resolution, _ = resolver.resolve_team(game_id="2026_01_NE_SEA", team="SEA")
    assert resolution.resolution_status == "RESOLVED"
    assert resolution.canonical_qb_id == "00-BBB"
    assert "BACKUP_PROMOTION" in (resolution.source_warning_state or "")


def test_manual_override_is_audited_and_creates_new_provenance():
    override = {
        ("2026_01_NE_SEA", "SEA"): {
            "game_id": "2026_01_NE_SEA", "team": "SEA", "expected_starter": "Override QB",
            "sleeper_player_id": "s9", "canonical_qb_id": "00-OVR", "gsis_id": "00-OVR",
            "reason": "team announcement", "evidence_source": "official team",
            "operator": "test", "changed_at_utc": "2026-09-02T18:00:00Z",
        }
    }
    resolver = SleeperExpectedQBResolver(_source(), overrides=override)
    resolution, audit = resolver.resolve_team(game_id="2026_01_NE_SEA", team="SEA")
    assert resolution.resolution_status == "OVERRIDDEN"
    assert resolution.canonical_qb_id == "00-OVR"
    assert audit is not None
    assert audit.previous_provenance_id != audit.new_provenance_id
    assert audit.rescore_required is True


def test_starter_change_requires_rescore():
    resolver = SleeperExpectedQBResolver(_source())
    previous, _ = resolver.resolve_team(game_id="2026_01_NE_SEA", team="SEA")
    override = {
        ("2026_01_NE_SEA", "SEA"): {
            "game_id": "2026_01_NE_SEA", "team": "SEA", "expected_starter": "Override QB",
            "sleeper_player_id": "s9", "canonical_qb_id": "00-OVR", "gsis_id": "00-OVR",
            "reason": "team announcement", "evidence_source": "official team",
            "operator": "test", "changed_at_utc": "2026-09-02T18:00:00Z",
        }
    }
    current, _ = SleeperExpectedQBResolver(_source(), overrides=override).resolve_team(
        game_id="2026_01_NE_SEA", team="SEA"
    )
    event = detect_starter_change(previous, current, changed_at_utc="2026-09-02T18:00:00Z")
    assert event is not None
    assert event.rescore_required is True


def test_source_unavailable_is_not_disguised_as_fresh():
    resolver = SleeperExpectedQBResolver(_source(freshness="UNAVAILABLE"))
    resolution, _ = resolver.resolve_team(game_id="2026_01_NE_SEA", team="SEA")
    context = resolver.to_product_context(resolution)
    validate_qb_context(context, "qb")
    assert context["freshness"] == {
        "state": "UNAVAILABLE", "observed_at_utc": None, "age_seconds": None,
        "threshold_seconds": 21600.0,
    }
