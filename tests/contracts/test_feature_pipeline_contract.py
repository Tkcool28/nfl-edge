"""Feature-v1 fixture and target-label contract tests."""

from pathlib import Path

import polars as pl

from nfl_edge.features.pipeline import FeatureInputs, build_feature_bundle, load_feature_config

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data" / "fixtures"


def _empty_rosters() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "season": pl.Int64,
            "week": pl.Int64,
            "team": pl.String,
            "player_id": pl.String,
            "position": pl.String,
            "timestamp_quality": pl.String,
        }
    )


def test_feature_v1_fixture_covers_required_edge_cases() -> None:
    games = pl.read_csv(FIXTURES / "feature_games_v1.csv")
    depth = pl.read_csv(FIXTURES / "feature_depth_evidence_v1.csv")
    qb = pl.read_csv(FIXTURES / "feature_qb_game_stats_v1.csv")
    postgame = pl.read_csv(FIXTURES / "feature_postgame_evidence_v1.csv")

    assert games.filter(pl.col("week") == 4).is_empty()  # Bye before week 5.
    assert games.filter(pl.col("neutral_site_source") == "Neutral").height == 1
    assert games.filter(pl.col("home_score") == pl.col("away_score")).height == 1
    assert games.filter(pl.col("home_score").is_null()).height == 1
    assert games.filter(pl.col("season_type") != "REG").height == 2
    assert games.filter(pl.col("gameday") == "2025-01-21").height == 1
    assert {
        "one_second_before_cutoff",
        "exactly_at_cutoff",
        "one_second_after_cutoff",
        "conflicting_depth_rank",
        "starting_qb_change",
        "missing_player_id",
    }.issubset(set(depth["case_label"].to_list()))
    assert qb["player_id"].null_count() == 1
    assert qb.filter(pl.col("attempts") == 0).height == 1
    assert "must_not_raise_certainty" in postgame["case_label"].to_list()


def test_fixture_model_rows_preserve_tie_future_target_and_postseason_identity() -> None:
    config = load_feature_config(ROOT / "config" / "features.yaml")
    inputs = FeatureInputs(
        games=pl.read_csv(FIXTURES / "feature_games_v1.csv"),
        team_stats=pl.read_csv(FIXTURES / "feature_team_game_stats_v1.csv"),
        qb_stats=pl.read_csv(FIXTURES / "feature_qb_game_stats_v1.csv"),
        depth_charts=pl.read_csv(FIXTURES / "feature_depth_evidence_v1.csv"),
        rosters=_empty_rosters(),
        postgame_evidence=pl.read_csv(FIXTURES / "feature_postgame_evidence_v1.csv"),
    )
    bundle = build_feature_bundle(inputs, config)
    tie = bundle.game_features.filter(pl.col("game_id") == "fx-003").to_dicts()[0]
    future = bundle.game_features.filter(pl.col("game_id") == "fx-005").to_dicts()[0]
    unusual = bundle.game_features.filter(pl.col("game_id") == "fx-007").to_dicts()[0]

    assert tie["target_available"] is True
    assert tie["target_tie"] is True
    assert tie["target_home_win"] is None
    assert tie["target_margin"] == 0.0
    assert future["target_available"] is False
    assert future["target_home_win"] is None
    assert future["target_margin"] is None
    assert unusual["season_type"] == "DIV"
    assert unusual["feature_as_of_utc"].tzinfo is not None
