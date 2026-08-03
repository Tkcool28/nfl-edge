"""CLI for deterministic NFL feature artifact generation and audit summaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

from .pipeline import FeatureBundle, FeatureInputs, build_feature_bundle, load_feature_config, write_feature_outputs
from .validation import assert_no_market_columns, assert_unique_keys


def _summary(bundle: FeatureBundle, manifest: dict) -> dict:
    game = bundle.game_features
    team = bundle.team_features
    qb = bundle.qb_features
    starters = bundle.starter_certainty
    assert_unique_keys(game, ["game_id"], "game")
    assert_unique_keys(team, ["game_id", "team"], "team-game")
    assert_unique_keys(qb, ["game_id", "team", "candidate_rank"], "QB scenario")
    assert_no_market_columns(game)
    nulls = {
        column: game[column].null_count()
        for column in game.columns
        if game[column].null_count() > 0
    }
    sample_counts = team.select(
        [
            pl.col(column).min().alias(f"{column}_min")
            if column.endswith("_prior_games") or column == "games_played_before_current_game"
            else pl.col(column)
            for column in team.columns
            if column.endswith("_prior_games") or column == "games_played_before_current_game"
        ]
    ).to_dicts()[0]
    sample_counts.update(
        {
            column: team[column].max()
            for column in team.columns
            if column.endswith("_prior_games") or column == "games_played_before_current_game"
        }
    )
    return {
        "outputs": {
            "game_features": [game.height, game.width],
            "team_features": [team.height, team.width],
            "qb_features": [qb.height, qb.width],
            "starter_certainty": [starters.height, starters.width],
            "weekly_availability": [bundle.weekly_availability.height, bundle.weekly_availability.width],
        },
        "season_type_counts": game.group_by(["season", "season_type"]).len().sort(
            ["season", "season_type"]
        ).to_dicts(),
        "starter_state_counts": starters.group_by("starter_certainty").len().sort("starter_certainty").to_dicts(),
        "null_counts_nonzero": nulls,
        "sample_count_summary": sample_counts,
        "manifest": manifest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--config", default="config/features.yaml")
    parser.add_argument("--output-dir", default="data/derived/features_v1")
    parser.add_argument("--created-at-utc", default=None)
    parser.add_argument("--summary-json", default=None)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    config = load_feature_config(root / args.config)
    bundle = build_feature_bundle(FeatureInputs.from_repository(root), config)
    output = root / args.output_dir
    manifest = write_feature_outputs(bundle, output, root, args.created_at_utc)
    summary = _summary(bundle, manifest)
    rendered = json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n"
    if args.summary_json:
        (root / args.summary_json).write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
