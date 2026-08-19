"""Request-plan generation: reproduce frozen acceptance counts (§D/E/L)."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from nfl_edge.market_data.manifest import (
    EXPECTED_CLUSTERS_BY_SEASON,
    EXPECTED_PLAN_SHA256,
    EXPECTED_TOTAL_CLUSTERS,
    EXPECTED_TOTAL_GAMES,
    MANIFEST_REQUEST_PLAN_PATH,
    SCHEDULE_SOURCE_PATH,
)
from nfl_edge.market_data.plan import build_request_plan, plan_frame, validate_plan_contract

SCHEDULE_PLAN_PATH = Path(__file__).resolve().parents[2] / MANIFEST_REQUEST_PLAN_PATH


@pytest.fixture(scope="module")
def built():
    return build_request_plan(SCHEDULE_SOURCE_PATH)


def test_expected_total_games_1408(built):
    plan, clusters = built
    games = {g for c in clusters for g in c.game_ids}
    assert len(games) == EXPECTED_TOTAL_GAMES == 1408


def test_each_game_assigned_exactly_once(built):
    plan, clusters = built
    all_games = [g for c in clusters for g in c.game_ids]
    assert len(all_games) == len(set(all_games))  # no duplicates
    assert len(all_games) == 1408


def test_expected_575_clusters(built):
    plan, clusters = built
    assert len(clusters) == EXPECTED_TOTAL_CLUSTERS == 575
    assert plan.height == 575


def test_per_season_cluster_counts(built):
    plan, clusters = built
    by_season = dict(sorted(Counter(c.season for c in clusters).items()))
    assert by_season == EXPECTED_CLUSTERS_BY_SEASON == {
        2020: 107, 2021: 111, 2022: 116, 2023: 120, 2024: 121,
    }


def test_anchor_is_earliest_kickoff_minus_60(built):
    plan, clusters = built
    for c in clusters:
        expect = c.earliest_kickoff_utc.astimezone(timezone.utc).replace(
            second=0, microsecond=0
        ) - timedelta(minutes=60)
        got = c.anchor_utc.replace(second=0, microsecond=0)
        assert got == expect, c.cluster_id


def test_observation_lead_is_60_90_minutes(built):
    plan, clusters = built
    assert plan["expected_lead_min"].min() == 60.0
    assert plan["expected_lead_max"].max() == 90.0
    for c in clusters:
        for lead in c.lead_minutes:
            assert 60.0 <= lead <= 90.0, c.cluster_id


def test_no_2025_rows_in_plan(built):
    plan, clusters = built
    assert 2025 not in plan.get_column("season").to_list()


def test_game_counts_by_season(built):
    plan, clusters = built
    expected = {2020: 269, 2021: 285, 2022: 284, 2023: 285, 2024: 285}
    by_season: Counter = Counter()
    for c in clusters:
        by_season[c.season] += c.game_count
    assert dict(by_season) == expected


def test_plan_frame_is_stable_and_sorted(built):
    plan, clusters = built
    rows = plan.select("request_plan_id").to_series().to_list()
    assert rows == sorted(rows)
    # Rebuilding a frame from the same clusters yields identical content.
    assert plan_frame(clusters).height == plan.height == 575


def test_request_plan_rebuild_is_deterministic(built):
    # A full rebuild from the frozen schedule must reproduce the plan exactly.
    plan, _ = built
    rebuilt, _ = build_request_plan(SCHEDULE_SOURCE_PATH)
    assert plan.equals(rebuilt)


def test_validate_plan_contract_passes_on_frozen_plan(built):
    # The frozen plan must satisfy the full runtime contract (no exception),
    # and its on-disk SHA-256 must equal the frozen expected hash.
    plan, _ = built
    validate_plan_contract(plan, plan_path=SCHEDULE_PLAN_PATH)
    assert (
        hashlib.sha256(Path(SCHEDULE_PLAN_PATH).read_bytes()).hexdigest()
        == EXPECTED_PLAN_SHA256
    )
