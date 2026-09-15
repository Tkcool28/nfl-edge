from __future__ import annotations

import polars as pl
import pytest

from nfl_edge.features.totals_v1.pbp_semantics import REQUIRED_PBP_COLUMNS
from nfl_edge.live.evidence_2026 import (
    SettledActualQBResolver,
    SettledEvidenceError,
    _canonical_games,
    _filter_stats,
    validate_settled_evidence,
)


def _schedule_row(*, week: int = 1, home_score=27, away_score=20) -> dict:
    return {
        "season": "2026",
        "game_type": "REG",
        "week": str(week),
        "gameday": "2026-09-10",
        "away_team": "NE",
        "home_team": "SEA",
        "away_score": away_score,
        "home_score": home_score,
        "away_qb_id": "00-1111111",
        "home_qb_id": "00-2222222",
        "away_qb_name": "Away QB",
        "home_qb_name": "Home QB",
        "roof": "outdoors",
    }


def test_canonical_settled_games_include_targets_and_actual_qbs() -> None:
    games = _canonical_games([_schedule_row()], through_week=1)
    row = games.to_dicts()[0]
    assert row["game_id"] == "2026_01_NE_SEA"
    assert row["target_available"] is True
    assert row["target_margin"] == 7
    assert row["target_home_win"] is True
    assert row["target_total_points"] == 47
    assert row["home_qb_id"] == "00-2222222"
    assert row["roof_actual"] == "outdoors"


def test_unsettled_prior_week_fails_closed() -> None:
    with pytest.raises(SettledEvidenceError, match="not fully settled"):
        _canonical_games(
            [_schedule_row(home_score=None, away_score=None)],
            through_week=1,
        )


def test_settled_actual_qb_resolver_is_postgame_and_deterministic() -> None:
    games = _canonical_games([_schedule_row()], through_week=1)
    resolver = SettledActualQBResolver(
        games,
        observed_at_utc="2026-09-15T12:00:00Z",
    )
    resolved = resolver.resolve_game({"game_id": "2026_01_NE_SEA", "home_team": "SEA", "away_team": "NE"})
    assert resolved["home"].model_qb_state_id == "00-2222222"
    assert resolved["away"].model_qb_state_id == "00-1111111"
    assert resolved["home"].depth_designation == "POSTGAME_ACTUAL_STARTER"
    assert resolved["overrides"] == []


def test_evidence_requires_complete_team_and_pbp_coverage() -> None:
    games = _canonical_games([_schedule_row()], through_week=1)
    team = pl.DataFrame(
        [
            {"game_id": "2026_01_NE_SEA", "season": 2026, "week": 1, "team": "SEA"},
        ]
    )
    qb = pl.DataFrame(
        [
            {
                "game_id": "2026_01_NE_SEA",
                "season": 2026,
                "week": 1,
                "team": "SEA",
                "player_id": "00-2222222",
            }
        ]
    )
    pbp = pl.DataFrame({"game_id": ["2026_01_NE_SEA"]})
    with pytest.raises(SettledEvidenceError, match="team-stat coverage drift"):
        validate_settled_evidence(
            games=games,
            team_stats=team,
            qb_stats=qb,
            pbp=pbp,
            through_week=1,
        )


def test_partial_pbp_cannot_advance_completed_game_evidence() -> None:
    games = _canonical_games([_schedule_row()], through_week=1)
    team = pl.DataFrame(
        [
            {"game_id": "2026_01_NE_SEA", "season": 2026, "week": 1, "team": "SEA"},
            {"game_id": "2026_01_NE_SEA", "season": 2026, "week": 1, "team": "NE"},
        ]
    )
    qb = pl.DataFrame(
        [{"game_id": "2026_01_NE_SEA", "season": 2026, "week": 1, "team": "SEA", "player_id": "qb"}]
    )
    pbp = pl.DataFrame({column: [0] for column in REQUIRED_PBP_COLUMNS}).with_columns(
        pl.lit("2026_01_NE_SEA").alias("game_id"),
        pl.lit(3).alias("qtr"),
        pl.lit(20.0).alias("game_seconds_remaining"),
        pl.lit(0).alias("total_home_score"),
        pl.lit(0).alias("total_away_score"),
    )
    with pytest.raises(SettledEvidenceError, match="completion invariant"):
        validate_settled_evidence(games=games, team_stats=team, qb_stats=qb, pbp=pbp, through_week=1)


def test_overtime_game_requires_terminal_pbp_score_to_match_official_final() -> None:
    """A regulation 0:00 row must not certify an OT final whose PBP is missing."""
    games = _canonical_games([_schedule_row(home_score=23, away_score=20)], through_week=1)
    team = pl.DataFrame(
        [
            {"game_id": "2026_01_NE_SEA", "season": 2026, "week": 1, "team": "SEA"},
            {"game_id": "2026_01_NE_SEA", "season": 2026, "week": 1, "team": "NE"},
        ]
    )
    qb = pl.DataFrame(
        [{"game_id": "2026_01_NE_SEA", "season": 2026, "week": 1, "team": "SEA", "player_id": "qb"}]
    )
    pbp = pl.DataFrame({column: [0] for column in REQUIRED_PBP_COLUMNS}).with_columns(
        pl.lit("2026_01_NE_SEA").alias("game_id"),
        pl.lit(4).alias("qtr"),
        pl.lit(0.0).alias("game_seconds_remaining"),
        pl.lit(20).alias("total_home_score"),
        pl.lit(20).alias("total_away_score"),
    )

    with pytest.raises(SettledEvidenceError, match="terminal row matching the official final score"):
        validate_settled_evidence(games=games, team_stats=team, qb_stats=qb, pbp=pbp, through_week=1)


def test_upstream_feature_schema_drift_fails_closed() -> None:
    team = pl.DataFrame([{"game_id": "2026_01_NE_SEA", "season": 2026, "week": 1, "team": "SEA"}])
    with pytest.raises(SettledEvidenceError, match="team stats missing required columns"):
        _filter_stats(team, game_ids={"2026_01_NE_SEA"}, kind="team")

    player = team.with_columns(pl.lit("QB").alias("position"), pl.lit("qb").alias("player_id"))
    with pytest.raises(SettledEvidenceError, match="player stats missing required columns"):
        _filter_stats(player, game_ids={"2026_01_NE_SEA"}, kind="player")
