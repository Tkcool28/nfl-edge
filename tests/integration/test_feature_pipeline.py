"""Contract and deterministic-integration tests for feature pipeline v1."""

import json
import os
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.features.pipeline import (
    FeatureInputs,
    build_feature_bundle,
    build_feature_registry,
    load_feature_config,
    write_feature_outputs,
)
from nfl_edge.features.validation import (
    MARKET_COLUMNS,
    assert_no_market_columns,
    assert_unique_keys,
    assert_utc_columns,
    logical_frame_fingerprint,
)

ROOT = Path(__file__).resolve().parents[2]


def test_market_columns_are_hard_rejected_from_model_matrix() -> None:
    safe = pl.DataFrame({"game_id": ["g"], "roll4_passing_epa": [0.1]})
    assert_no_market_columns(safe)
    for column in (
        "away_moneyline",
        "home_moneyline",
        "spread_line",
        "total_line",
        "away_spread_odds",
        "home_spread_odds",
        "under_odds",
        "over_odds",
    ):
        with pytest.raises(ValueError, match="market"):
            assert_no_market_columns(safe.with_columns(pl.lit(1.0).alias(column)))
    assert set(MARKET_COLUMNS).issuperset({"away_moneyline", "over_odds"})


def test_duplicate_game_and_team_game_keys_fail() -> None:
    with pytest.raises(ValueError, match="duplicate game"):
        assert_unique_keys(pl.DataFrame({"game_id": ["x", "x"]}), ["game_id"], "game")
    with pytest.raises(ValueError, match="duplicate team-game"):
        assert_unique_keys(
            pl.DataFrame({"game_id": ["x", "x"], "team": ["AAA", "AAA"]}),
            ["game_id", "team"],
            "team-game",
        )


def test_full_frozen_build_has_required_grains_utc_and_registry_coverage() -> None:
    config = load_feature_config(ROOT / "config" / "features.yaml")
    bundle = build_feature_bundle(FeatureInputs.from_repository(ROOT), config)
    assert bundle.game_features.height == 2227
    assert bundle.team_features.height == 4454
    assert bundle.starter_certainty.height == 2227
    assert bundle.qb_features.height >= 4454
    assert_unique_keys(bundle.game_features, ["game_id"], "game")
    assert_unique_keys(bundle.team_features, ["game_id", "team"], "team-game")
    assert_unique_keys(bundle.starter_certainty, ["game_id"], "starter game")
    assert_unique_keys(bundle.qb_features, ["game_id", "team", "candidate_rank"], "QB scenario")
    assert_no_market_columns(bundle.game_features)
    assert_utc_columns(
        bundle.game_features,
        ["feature_as_of_utc", "prediction_as_of_utc", "source_available_at_utc", "scheduled_start_utc"],
        allow_all_null=True,
    )
    assert_utc_columns(
        bundle.team_features,
        ["feature_as_of_utc", "source_available_at_utc"],
        allow_all_null=True,
    )
    assert_utc_columns(
        bundle.qb_features,
        ["feature_as_of_utc", "source_available_at_utc"],
        allow_all_null=True,
    )
    assert_utc_columns(bundle.starter_certainty, ["feature_as_of_utc"])
    assert_utc_columns(
        bundle.weekly_availability,
        [
            "prediction_as_of_utc",
            "week_completed_at_boundary_utc",
            "eligible_for_features_at_utc",
        ],
    )
    assert bundle.game_features.filter(
        pl.col("source_available_at_utc").is_not_null()
        & (pl.col("source_available_at_utc") > pl.col("feature_as_of_utc"))
    ).is_empty()
    for column in bundle.model_feature_columns:
        lower = column.lower()
        assert not any(token in lower for token in ("target_", "result", "winner", "home_score", "away_score"))
    registry = build_feature_registry(bundle.game_features, config, bundle.model_feature_columns)
    model_columns = set(bundle.model_feature_columns)
    assert model_columns == {item["feature_name"] for item in registry}
    assert all(item["owner_test"] for item in registry)
    count_columns = {
        "games_played_before_current_game",
        "roll4_prior_games",
        "roll8_prior_games",
        "season_to_date_prior_games",
        "early_season_sample",
        "prior_season_carryover_games",
        "prior_season_carryover_used",
        "roll4_minimum_sample_met",
        "roll8_minimum_sample_met",
        "season_to_date_minimum_sample_met",
    }
    prefixed_count_columns: set[str] = set()
    for base in count_columns:
        prefixed_count_columns.add(base)
        prefixed_count_columns.add(f"home_{base}")
        prefixed_count_columns.add(f"away_{base}")
    state_columns = {"is_home", "neutral_site", "venue_missing", "roof_missing"}
    short = int(config["rolling_windows"]["short_games"])
    medium = int(config["rolling_windows"]["medium_games"])
    for entry in registry:
        column = entry["feature_name"]
        if column in prefixed_count_columns:
            assert entry["classification"] == "count_or_sample_size"
            assert entry["window"] == "none"
        elif column in state_columns:
            assert entry["classification"] == "game_state_indicator"
            assert entry["window"] == "none"
        else:
            assert entry["classification"] == "rolling_metric"
            if column.startswith(f"roll{short}_"):
                assert entry["window"] == f"last_{short}_eligible_games"
            elif column.startswith(f"roll{medium}_"):
                assert entry["window"] == f"last_{medium}_eligible_games"
            elif column.startswith("season_to_date_"):
                assert entry["window"] == "current_season_prior_eligible_games"
    assert set(bundle.game_features["season"].unique().to_list()) == set(range(2018, 2026))


def test_holdout_outcome_presence_does_not_change_definitions_or_windows() -> None:
    config = load_feature_config(ROOT / "config" / "features.yaml")
    inputs = FeatureInputs.from_repository(ROOT)
    with_outcomes = build_feature_bundle(inputs, config)
    games_without_holdout_outcomes = inputs.games.with_columns(
        pl.when(pl.col("season") == 2025).then(None).otherwise(pl.col("home_score")).alias("home_score"),
        pl.when(pl.col("season") == 2025).then(None).otherwise(pl.col("away_score")).alias("away_score"),
    )
    poisoned_holdout_outcomes = inputs.games.with_columns(
        pl.when(pl.col("season") == 2025)
        .then(pl.lit(9999.0))
        .otherwise(pl.col("home_score"))
        .alias("home_score"),
        pl.when(pl.col("season") == 2025)
        .then(pl.lit(-9999.0))
        .otherwise(pl.col("away_score"))
        .alias("away_score"),
    )
    without_outcomes = build_feature_bundle(inputs.replace(games=games_without_holdout_outcomes), config)
    poisoned = build_feature_bundle(inputs.replace(games=poisoned_holdout_outcomes), config)
    assert with_outcomes.game_features.columns == without_outcomes.game_features.columns
    assert with_outcomes.model_feature_columns == without_outcomes.model_feature_columns
    assert build_feature_registry(
        with_outcomes.game_features, config, with_outcomes.model_feature_columns
    ) == build_feature_registry(
        without_outcomes.game_features, config, without_outcomes.model_feature_columns
    )
    assert poisoned.model_feature_columns == with_outcomes.model_feature_columns
    development_poisoned = poisoned.game_features.filter(pl.col("season") < 2025).select(
        list(poisoned.model_feature_columns)
    )
    development_baseline = with_outcomes.game_features.filter(pl.col("season") < 2025).select(
        list(with_outcomes.model_feature_columns)
    )
    assert development_poisoned.equals(development_baseline)
    assert config["rolling_windows"] == {"short_games": 4, "medium_games": 8, "minimum_games": 3}


def test_deterministic_replay_and_artifact_time_separation(tmp_path: Path) -> None:
    config = load_feature_config(ROOT / "config" / "features.yaml")
    inputs = FeatureInputs.from_repository(ROOT)
    first = build_feature_bundle(inputs, config)
    original_mtime = (ROOT / "data" / "frozen" / "games" / "games_2018_2025.parquet").stat().st_mtime
    os.utime(ROOT / "data" / "frozen" / "games" / "games_2018_2025.parquet", (original_mtime + 5, original_mtime + 5))
    try:
        second = build_feature_bundle(FeatureInputs.from_repository(ROOT), config)
    finally:
        os.utime(ROOT / "data" / "frozen" / "games" / "games_2018_2025.parquet", (original_mtime, original_mtime))
    assert logical_frame_fingerprint(first.game_features) == logical_frame_fingerprint(second.game_features)
    out1, out2 = tmp_path / "one", tmp_path / "two"
    manifest1 = write_feature_outputs(first, out1, ROOT, "2026-01-01T00:00:00Z")
    manifest2 = write_feature_outputs(second, out2, ROOT, "2026-02-01T00:00:00Z")
    for name in (
        "game_features_2018_2025.parquet",
        "team_pregame_features_2018_2025.parquet",
        "qb_pregame_features_2018_2025.parquet",
        "starter_certainty_2018_2025.parquet",
        "weekly_availability_2018_2025.parquet",
    ):
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes()
    assert manifest1["created_at_utc"] != manifest2["created_at_utc"]
    assert manifest1["configuration_fingerprint"] == manifest2["configuration_fingerprint"]
    assert all("created_at_utc" not in frame.columns for frame in first.frames())


def test_required_output_manifest_verifies(tmp_path: Path) -> None:
    config = load_feature_config(ROOT / "config" / "features.yaml")
    bundle = build_feature_bundle(FeatureInputs.from_repository(ROOT), config)
    manifest = write_feature_outputs(bundle, tmp_path, ROOT, "2026-01-01T00:00:00Z")
    assert manifest["feature_version"] == "features-v1"
    assert manifest["data_version"] == "frozen-baseline-v1"
    assert len(manifest["files"]) == 6
    for entry in manifest["files"]:
        path = tmp_path / Path(entry["file_path"]).name
        assert path.stat().st_size == entry["byte_size"]
        assert len(entry["sha256"]) == 64
        assert len(entry["schema_fingerprint"]) == 64
        assert entry["season_coverage"] == list(range(2018, 2026)) or entry["season_coverage"] == []
    on_disk = json.loads((tmp_path / "feature_manifest_v1.json").read_text())
    assert on_disk == manifest
