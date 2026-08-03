"""Leakage proofs for team and quarterback history features."""

from copy import deepcopy

import polars as pl

from nfl_edge.features.availability import AvailabilityPolicy, build_weekly_availability
from nfl_edge.features.qb import build_qb_pregame_features
from nfl_edge.features.team import build_team_pregame_features

POLICY = AvailabilityPolicy(weekday=1, hour=12, minute=0, timezone_name="UTC")
CONFIG = {
    "rolling_windows": {"short_games": 4, "medium_games": 8, "minimum_games": 2},
    "prior_season_carryover": {"enabled": True, "max_games": 4},
    "fixed_priors": {
        "win_rate": 0.5,
        "points_scored": 21.0,
        "points_allowed": 21.0,
        "point_differential": 0.0,
        "passing_epa": 0.0,
        "rushing_epa": 0.0,
        "offensive_total_epa": 0.0,
        "defensive_epa_allowed": 0.0,
        "passing_yards": 225.0,
        "rushing_yards": 110.0,
    },
    "qb_features": {
        "shrinkage": {
            "k_dropbacks": 250.0,
            "priors": {
                "passing_epa_per_dropback": -0.05,
                "passing_cpoe": -1.0,
                "sack_rate": 0.08,
                "interception_rate": 0.03,
            },
        },
        "recency_games": 8,
        "recency_decay": 0.75,
        "low_sample_dropbacks": 100,
    },
}


def sample_games() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": ["g1", "g2", "g3"],
            "season": [2024, 2024, 2024],
            "season_type": ["REG", "REG", "REG"],
            "week": [1, 2, 3],
            "gameday": ["2024-09-05", "2024-09-12", "2024-09-19"],
            "home_team": ["AAA", "BBB", "AAA"],
            "away_team": ["BBB", "AAA", "BBB"],
            "home_score": [21, 14, 27],
            "away_score": [17, 10, 24],
            "neutral_site_source": ["Home", "Home", "Neutral"],
            "venue_id": ["v1", "v2", "v3"],
            "roof_type": ["outdoors", "dome", "open"],
            "scheduled_start_utc": [None, None, None],
        }
    )


def sample_team_stats() -> pl.DataFrame:
    rows = []
    values = {
        "g1": ((1.0, 0.2, 250, 100), (-0.4, -0.1, 180, 80)),
        "g2": ((0.1, 0.0, 205, 95), (0.8, 0.3, 240, 125)),
        "g3": ((0.5, 0.2, 230, 115), (0.2, 0.1, 210, 90)),
    }
    games = sample_games().to_dicts()
    for game in games:
        for team, opponent, metrics in (
            (game["home_team"], game["away_team"], values[game["game_id"]][0]),
            (game["away_team"], game["home_team"], values[game["game_id"]][1]),
        ):
            rows.append(
                {
                    "game_id": game["game_id"],
                    "season": game["season"],
                    "week": game["week"],
                    "season_type": game["season_type"],
                    "team": team,
                    "opponent": opponent,
                    "passing_epa": metrics[0],
                    "rushing_epa": metrics[1],
                    "passing_yards": metrics[2],
                    "rushing_yards": metrics[3],
                }
            )
    return pl.DataFrame(rows)


def row_for(frame: pl.DataFrame, game_id: str, team: str) -> dict:
    return frame.filter((pl.col("game_id") == game_id) & (pl.col("team") == team)).to_dicts()[0]


def feature_payload(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in {"source_available_at_utc"}}


def test_same_game_poisoning_does_not_change_its_own_rolling_std() -> None:
    games = sample_games()
    availability = build_weekly_availability(games, POLICY)
    baseline = build_team_pregame_features(games, sample_team_stats(), availability, CONFIG)
    poisoned_stats = sample_team_stats().clone()
    poisoned_stats = poisoned_stats.with_columns(
        pl.when((pl.col("game_id") == "g2") & (pl.col("team") == "AAA"))
        .then(pl.lit(99999.0))
        .otherwise(pl.col("passing_epa"))
        .alias("passing_epa")
    )
    poisoned_stats = poisoned_stats.with_columns(
        pl.when((pl.col("game_id") == "g2") & (pl.col("team") == "BBB"))
        .then(pl.lit(-99999.0))
        .otherwise(pl.col("passing_epa"))
        .alias("passing_epa")
    )
    poisoned = build_team_pregame_features(games, poisoned_stats, availability, CONFIG)
    std_columns = [column for column in baseline.columns if column.endswith("_std")]
    assert std_columns, "expected rolling std columns"
    base_row = row_for(baseline, "g2", "AAA")
    poisoned_row = row_for(poisoned, "g2", "AAA")
    for column in std_columns:
        assert base_row[column] == poisoned_row[column]


def test_future_row_poisoning_does_not_change_earlier_rolling_std() -> None:
    games = sample_games()
    availability = build_weekly_availability(games, POLICY)
    baseline = build_team_pregame_features(games, sample_team_stats(), availability, CONFIG)
    poisoned_stats = sample_team_stats().with_columns(
        pl.when(pl.col("game_id") == "g3")
        .then(pl.lit(-99999.0))
        .otherwise(pl.col("rushing_epa"))
        .alias("rushing_epa")
    )
    poisoned = build_team_pregame_features(games, poisoned_stats, availability, CONFIG)
    std_columns = [column for column in baseline.columns if column.endswith("_std")]
    base_row = row_for(baseline, "g2", "AAA")
    poisoned_row = row_for(poisoned, "g2", "AAA")
    for column in std_columns:
        assert base_row[column] == poisoned_row[column]


def test_std_null_below_two_observations_and_present_above_two() -> None:
    games = sample_games()
    availability = build_weekly_availability(games, POLICY)
    result = build_team_pregame_features(games, sample_team_stats(), availability, CONFIG)

    week1 = row_for(result, "g1", "AAA")
    week2 = row_for(result, "g2", "AAA")
    week3 = row_for(result, "g3", "AAA")
    for column in ("roll4_offensive_total_epa_std", "roll8_offensive_total_epa_std"):
        assert week1[column] is None
        assert week1[f"{column}_missing"] is True
        assert week2[column] is None
        assert week2[f"{column}_missing"] is True
        assert week3[column] is not None
        assert week3[f"{column}_missing"] is False
        assert week3[column] >= 0.0


def test_same_game_exclusion_and_shift_before_roll() -> None:
    games = sample_games()
    availability = build_weekly_availability(games, POLICY)
    baseline = build_team_pregame_features(games, sample_team_stats(), availability, CONFIG)
    poisoned_stats = sample_team_stats().with_columns(
        pl.when((pl.col("game_id") == "g2") & (pl.col("team") == "AAA"))
        .then(pl.lit(99999.0))
        .otherwise(pl.col("passing_epa"))
        .alias("passing_epa")
    )
    poisoned = build_team_pregame_features(games, poisoned_stats, availability, CONFIG)
    assert feature_payload(row_for(baseline, "g2", "AAA")) == feature_payload(row_for(poisoned, "g2", "AAA"))
    assert row_for(baseline, "g1", "AAA")["roll4_prior_games"] == 0
    assert row_for(baseline, "g2", "AAA")["roll4_prior_games"] == 1


def test_future_row_poisoning_does_not_change_earlier_team_features() -> None:
    games = sample_games()
    availability = build_weekly_availability(games, POLICY)
    baseline = build_team_pregame_features(games, sample_team_stats(), availability, CONFIG)
    poisoned_stats = sample_team_stats().with_columns(
        pl.when(pl.col("game_id") == "g3")
        .then(pl.lit(-99999.0))
        .otherwise(pl.col("rushing_epa"))
        .alias("rushing_epa")
    )
    poisoned = build_team_pregame_features(games, poisoned_stats, availability, CONFIG)
    assert feature_payload(row_for(baseline, "g2", "AAA")) == feature_payload(row_for(poisoned, "g2", "AAA"))


def test_qb_same_game_and_future_poisoning_are_excluded() -> None:
    games = sample_games()
    availability = build_weekly_availability(games, POLICY)
    stats = pl.DataFrame(
        {
            "game_id": ["g1", "g2", "g3"],
            "season": [2024, 2024, 2024],
            "week": [1, 2, 3],
            "season_type": ["REG", "REG", "REG"],
            "team": ["AAA", "AAA", "AAA"],
            "player_id": ["qb-a", "qb-a", "qb-a"],
            "passing_epa": [3.0, 4.0, 5.0],
            "passing_cpoe": [2.0, 3.0, 4.0],
            "attempts": [30, 30, 30],
            "sacks_suffered": [2, 2, 2],
            "passing_interceptions": [0, 1, 0],
        }
    )
    scenarios = pl.DataFrame(
        {
            "game_id": ["g1", "g2", "g3"],
            "team": ["AAA", "AAA", "AAA"],
            "side": ["home", "away", "home"],
            "candidate_rank": [1, 1, 1],
            "player_id": ["qb-a", "qb-a", "qb-a"],
            "starter_certainty": ["UNKNOWN", "DEPTH_CHART_SUPPORTED", "DEPTH_CHART_SUPPORTED"],
        }
    )
    baseline = build_qb_pregame_features(games, stats, scenarios, availability, CONFIG)
    current_poison = stats.with_columns(
        pl.when(pl.col("game_id") == "g2").then(pl.lit(9999.0)).otherwise(pl.col("passing_epa")).alias("passing_epa")
    )
    future_poison = stats.with_columns(
        pl.when(pl.col("game_id") == "g3").then(pl.lit(9999.0)).otherwise(pl.col("passing_epa")).alias("passing_epa")
    )
    current = build_qb_pregame_features(games, current_poison, scenarios, availability, CONFIG)
    future = build_qb_pregame_features(games, future_poison, scenarios, availability, CONFIG)
    keys = ["prior_games", "prior_dropback_or_attempt_volume", "passing_epa", "career_to_date_form"]
    base_row = baseline.filter(pl.col("game_id") == "g2").to_dicts()[0]
    current_row = current.filter(pl.col("game_id") == "g2").to_dicts()[0]
    future_row = future.filter(pl.col("game_id") == "g2").to_dicts()[0]
    assert {k: base_row[k] for k in keys} == {k: current_row[k] for k in keys}
    assert {k: base_row[k] for k in keys} == {k: future_row[k] for k in keys}


def test_qb_zero_sample_uses_fixed_prior_not_future_average() -> None:
    games = sample_games()
    availability = build_weekly_availability(games, POLICY)
    scenarios = pl.DataFrame(
        {
            "game_id": ["g1"],
            "team": ["AAA"],
            "side": ["home"],
            "candidate_rank": [1],
            "player_id": ["rookie"],
            "starter_certainty": ["ROSTER_SUPPORTED"],
        }
    )
    empty_stats = pl.DataFrame(
        schema={
            "game_id": pl.String,
            "season": pl.Int64,
            "week": pl.Int64,
            "season_type": pl.String,
            "team": pl.String,
            "player_id": pl.String,
            "passing_epa": pl.Float64,
            "passing_cpoe": pl.Float64,
            "attempts": pl.Int64,
            "sacks_suffered": pl.Int64,
            "passing_interceptions": pl.Int64,
        }
    )
    row = build_qb_pregame_features(games, empty_stats, scenarios, availability, deepcopy(CONFIG)).to_dicts()[0]
    assert row["passing_epa_shrinkage_weight"] == 0.0
    assert row["passing_epa"] == -0.05
    assert row["rookie_or_zero_sample"] is True
