"""Build Task04B v2 oracle QB entering-state artifacts.

The v2 numerical fields are produced by the canonical QB pregame feature
builder.  Postgame actual starters provide historical identity labels only.
This command never runs QB-Elo.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl

from nfl_edge.features.availability import AvailabilityPolicy, build_weekly_availability
from nfl_edge.features.oracle_qb_entering_state_v2 import build_oracle_qb_entering_state_v2
from nfl_edge.features.pipeline import load_feature_config

ROOT = Path(__file__).resolve().parents[1]
STARTERS = (
    ROOT
    / "data/derived/stathead_actual_starters_v1/final_oracle_starters/actual_starting_qb_game_sides_2018_2024_v1.csv"
)
GAMES = ROOT / "data/frozen/games/games_2018_2025.parquet"
QB_STATS = ROOT / "data/frozen/qb_game_stats/qb_game_stats_2018_2025.parquet"
CONFIG = ROOT / "config/features.yaml"
OUT = ROOT / "data/derived/oracle_qb_entering_state_v2"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _policy(config: dict) -> AvailabilityPolicy:
    source = config["availability"]
    return AvailabilityPolicy(
        weekday=int(source["weekly_publication_weekday"]),
        hour=int(source["weekly_publication_hour"]),
        minute=int(source["weekly_publication_minute"]),
        timezone_name=source["timezone"],
        unusual_date_policy=source["unusual_date_policy"].upper(),
    )


def _game_rows(game_sides: pl.DataFrame) -> pl.DataFrame:
    rows: list[dict] = []
    for game_id, frame in game_sides.group_by("game_id", maintain_order=True):
        game_id = game_id[0] if isinstance(game_id, tuple) else game_id
        away, home = sorted(frame.to_dicts(), key=lambda row: row["side"])
        if away["side"] != "away" or home["side"] != "home":
            raise ValueError(f"expected exactly away/home sides for {game_id}")
        rows.append(
            {
                "season": away["season"],
                "week": away["week"],
                "season_type": away["season_type"],
                "game_id": game_id,
                "away_team": away["team"],
                "home_team": home["team"],
                "feature_as_of_utc": away["feature_as_of_utc"],
                "historical_identity_usage": away["historical_identity_usage"],
                "feature_builder": away["feature_builder"],
                "away_actual_starting_qb_gsis_id": away["actual_starting_qb_gsis_id"],
                "home_actual_starting_qb_gsis_id": home["actual_starting_qb_gsis_id"],
                "away_passing_epa": away["passing_epa"],
                "home_passing_epa": home["passing_epa"],
                "away_prior_dropbacks": away["prior_dropback_or_attempt_volume"],
                "home_prior_dropbacks": home["prior_dropback_or_attempt_volume"],
                "qb_passing_epa_net_home_minus_away": home["passing_epa"] - away["passing_epa"],
            }
        )
    return pl.DataFrame(rows).sort(["season", "week", "game_id"])


def main() -> None:
    config = load_feature_config(CONFIG)
    games = pl.read_parquet(GAMES)
    qb_stats = pl.read_parquet(QB_STATS)
    starters = pl.read_csv(STARTERS).with_columns(pl.col("season").cast(pl.Int32), pl.col("week").cast(pl.Int32))
    availability = build_weekly_availability(games, _policy(config))
    built = build_oracle_qb_entering_state_v2(games, qb_stats, starters, availability, config)
    sides = built.game_sides
    games_out = _game_rows(sides)
    if sides.height != starters.height or sides.filter(pl.col("season") >= 2025).height:
        raise ValueError("unexpected v2 starter/output coverage")

    OUT.mkdir(parents=True, exist_ok=True)
    side_csv = OUT / "oracle_qb_entering_state_game_sides_2018_2024_v2.csv"
    side_parquet = OUT / "oracle_qb_entering_state_game_sides_2018_2024_v2.parquet"
    game_csv = OUT / "oracle_qb_pregame_features_by_game_2018_2024_v2.csv"
    game_parquet = OUT / "oracle_qb_pregame_features_by_game_2018_2024_v2.parquet"
    sides.write_csv(side_csv, line_terminator="\n")
    sides.write_parquet(side_parquet)
    games_out.write_csv(game_csv, line_terminator="\n")
    games_out.write_parquet(game_parquet)
    report = {
        "artifact_version": "oracle-qb-entering-state-v2",
        "feature_builder": "nfl_edge.features.qb.build_qb_pregame_features",
        "availability_builder": "nfl_edge.features.availability.build_weekly_availability",
        "historical_identity_usage": "POSTGAME_ACTUAL_STARTER_IDENTITY_ONLY",
        "qb_elo_executed": False,
        "game_side_rows": sides.height,
        "unique_game_side_keys": sides.select("game_id", "side").unique().height,
        "game_rows": games_out.height,
        "unique_game_ids": games_out.select("game_id").unique().height,
        "source_availability_audit": built.source_availability_audit,
        "starter_input_sha256": sha256(STARTERS),
        "games_source_sha256": sha256(GAMES),
        "qb_stats_source_sha256": sha256(QB_STATS),
        "feature_config_sha256": sha256(CONFIG),
        "output_sha256": {
            side_csv.name: sha256(side_csv),
            game_csv.name: sha256(game_csv),
            side_parquet.name: sha256(side_parquet),
            game_parquet.name: sha256(game_parquet),
        },
    }
    (OUT / "oracle_qb_entering_state_validation_report_v2.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
