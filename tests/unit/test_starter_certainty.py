"""Starter-evidence separation and conservative uncertainty tests."""

import polars as pl
import pytest

from nfl_edge.features.availability import AvailabilityPolicy, build_weekly_availability
from nfl_edge.features.starters import resolve_starter_certainty, starter_scenarios

POLICY = AvailabilityPolicy(weekday=1, hour=12, minute=0, timezone_name="UTC")


def games() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": ["g1", "g2"],
            "season": [2024, 2024],
            "season_type": ["REG", "REG"],
            "week": [1, 2],
            "gameday": ["2024-09-05", "2024-09-12"],
            "home_team": ["AAA", "BBB"],
            "away_team": ["BBB", "AAA"],
        }
    )


def test_postgame_evidence_cannot_raise_pregame_certainty() -> None:
    frame = games()
    availability = build_weekly_availability(frame, POLICY)
    postgame = pl.DataFrame(
        {
            "game_id": ["g1", "g1"],
            "team": ["AAA", "BBB"],
            "player_id": ["actual-a", "actual-b"],
            "evidence_type": ["WEEKLY_STATS_POSTGAME", "SNAP_COUNTS_POSTGAME"],
        }
    )
    result = resolve_starter_certainty(
        frame,
        availability,
        depth_evidence=None,
        rosters=None,
        postgame_evidence=postgame,
    )
    row = result.filter(pl.col("game_id") == "g1").to_dicts()[0]
    assert row["home_starter_certainty"] == "POSTGAME_ONLY_EVIDENCE"
    assert row["away_starter_certainty"] == "POSTGAME_ONLY_EVIDENCE"
    assert row["home_qb_candidate_1"] is None
    assert row["away_qb_candidate_1"] is None
    assert row["home_postgame_qb_evidence_id"] == "actual-a"


def test_unknown_starter_remains_unknown_without_any_evidence() -> None:
    frame = games()
    result = resolve_starter_certainty(
        frame,
        build_weekly_availability(frame, POLICY),
        depth_evidence=None,
        rosters=None,
        postgame_evidence=None,
    )
    row = result.filter(pl.col("game_id") == "g1").to_dicts()[0]
    assert row["starter_certainty"] == "UNKNOWN"
    assert row["home_qb_candidate_1"] is None
    assert row["away_qb_candidate_1"] is None


def test_exact_depth_cutoff_and_ambiguous_rank_conflict() -> None:
    frame = games()
    availability = build_weekly_availability(frame, POLICY)
    depth = pl.DataFrame(
        {
            "season": [2024, 2024, 2024, 2024],
            "week": [2, 2, 2, 2],
            "team": ["BBB", "BBB", "AAA", "AAA"],
            "player_id": ["bbb-1", "bbb-late", "aaa-1", "aaa-2"],
            "position": ["QB", "QB", "QB", "QB"],
            "depth_rank": [1, 1, 1, 1],
            "source_dt": [
                "2024-09-10T12:00:00Z",
                "2024-09-10T12:00:01Z",
                "2024-09-10T11:59:59Z",
                "2024-09-10T12:00:00Z",
            ],
            "timestamp_quality": ["source_timestamp_preserved"] * 4,
        }
    )
    result = resolve_starter_certainty(frame, availability, depth_evidence=depth)
    row = result.filter(pl.col("game_id") == "g2").to_dicts()[0]
    assert row["home_starter_certainty"] == "DEPTH_CHART_SUPPORTED"
    assert row["home_qb_candidate_1"] == "bbb-1"
    assert "bbb-late" not in {row["home_qb_candidate_1"], row["home_qb_candidate_2"]}
    assert row["away_starter_certainty"] == "AMBIGUOUS"
    assert {row["away_qb_candidate_1"], row["away_qb_candidate_2"]} == {"aaa-1", "aaa-2"}


def test_scenario_rows_preserve_missing_player_id() -> None:
    frame = games()
    result = resolve_starter_certainty(frame, build_weekly_availability(frame, POLICY), None, None, None)
    scenarios = starter_scenarios(result)
    assert scenarios.height == frame.height * 2
    assert scenarios["player_id"].null_count() == scenarios.height


def test_conflicting_confirmed_overrides_fail_clearly() -> None:
    frame = games()
    overrides = pl.DataFrame(
        {
            "game_id": ["g1", "g1"],
            "team": ["AAA", "AAA"],
            "expected_starter_id": ["a", "b"],
            "observed_at_utc": ["2024-09-03T11:00:00Z", "2024-09-03T11:30:00Z"],
            "source": ["official", "official"],
        }
    )
    with pytest.raises(ValueError, match="conflicting starter override"):
        resolve_starter_certainty(
            frame,
            build_weekly_availability(frame, POLICY),
            None,
            None,
            None,
            overrides=overrides,
        )


def test_missing_observed_at_utc_column_fails_clearly() -> None:
    frame = games()
    overrides = pl.DataFrame(
        {
            "game_id": ["g1"],
            "team": ["AAA"],
            "expected_starter_id": ["a"],
            "source": ["official"],
        }
    )
    with pytest.raises(ValueError, match="missing observed_at_utc column"):
        resolve_starter_certainty(
            frame,
            build_weekly_availability(frame, POLICY),
            None,
            None,
            None,
            overrides=overrides,
        )


def test_null_observed_at_utc_fails_clearly() -> None:
    frame = games()
    overrides = pl.DataFrame(
        {
            "game_id": ["g1"],
            "team": ["AAA"],
            "expected_starter_id": ["a"],
            "observed_at_utc": [None],
            "source": ["official"],
        }
    )
    with pytest.raises(ValueError, match="timezone-aware observed_at_utc"):
        resolve_starter_certainty(
            frame,
            build_weekly_availability(frame, POLICY),
            None,
            None,
            None,
            overrides=overrides,
        )


def test_naive_observed_at_utc_fails_clearly() -> None:
    frame = games()
    overrides = pl.DataFrame(
        {
            "game_id": ["g1"],
            "team": ["AAA"],
            "expected_starter_id": ["a"],
            "observed_at_utc": ["2024-09-03 11:00:00"],
            "source": ["official"],
        }
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_starter_certainty(
            frame,
            build_weekly_availability(frame, POLICY),
            None,
            None,
            None,
            overrides=overrides,
        )


def test_valid_utc_override_is_accepted() -> None:
    frame = games()
    overrides = pl.DataFrame(
        {
            "game_id": ["g1"],
            "team": ["AAA"],
            "expected_starter_id": ["override-a"],
            "observed_at_utc": ["2024-09-03T11:00:00Z"],
            "source": ["official"],
        }
    )
    result = resolve_starter_certainty(
        frame,
        build_weekly_availability(frame, POLICY),
        None,
        None,
        None,
        overrides=overrides,
    )
    row = result.filter(pl.col("game_id") == "g1").to_dicts()[0]
    assert row["home_starter_certainty"] == "CONFIRMED_PRE_CUTOFF"
    assert row["home_qb_candidate_1"] == "override-a"
