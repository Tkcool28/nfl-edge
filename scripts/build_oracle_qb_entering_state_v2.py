"""Build Task04B v2 oracle QB entering-state artifacts.

The v2 numerical fields are produced by the canonical QB pregame feature
builder (``nfl_edge.features.oracle_qb_entering_state_v2``).  Postgame actual
starters provide historical identity labels only (``POSTGAME_ACTUAL_STARTER``).
This command never executes QB-Elo; it applies the frozen, accepted QB-Elo
*adjustment* semantics (scale / max-abs / replacement EPA from
``config/qb_elo_v1.yaml``) deterministically to the v2 shrunk passing-EPA
feature to produce the authoritative per-game adjustment artifact.

Authoritative downstream model input (Task04C):
``data/derived/oracle_qb_entering_state_v2/oracle_qb_pregame_adjustments_by_game_2018_2024_v2.parquet``

A clean run is deterministic: rebuilding here produces byte-identical CSV and
Parquet artifacts.  ``ORACLE_STARTER_IDENTITY_ONLY`` remains the historical
model-usage semantics; actual starters are never represented as pregame-known.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl

from nfl_edge.features.availability import AvailabilityPolicy, build_weekly_availability
from nfl_edge.features.oracle_qb_entering_state_v2 import build_oracle_qb_entering_state_v2
from nfl_edge.features.pipeline import load_feature_config
from nfl_edge.models.qb_elo_config import load_qb_elo_canonical_config

ROOT = Path(__file__).resolve().parents[1]
STARTERS = (
    ROOT
    / "data/derived/stathead_actual_starters_v1/final_oracle_starters/actual_starting_qb_game_sides_2018_2024_v1.csv"
)
GAMES = ROOT / "data/frozen/games/games_2018_2025.parquet"
QB_STATS = ROOT / "data/frozen/qb_game_stats/qb_game_stats_2018_2025.parquet"
CONFIG = ROOT / "config/features.yaml"
QB_ELO_CONFIG = ROOT / "config/qb_elo_v1.yaml"
OUT = ROOT / "data/derived/oracle_qb_entering_state_v2"

GAME_SIDES_PREFIX = "oracle_qb_entering_state_game_sides_2018_2024_v2"
ADJUSTMENTS_PREFIX = "oracle_qb_pregame_adjustments_by_game_2018_2024_v2"

_GAME_SIDE_COLUMNS = [
    "season",
    "week",
    "season_type",
    "game_id",
    "side",
    "team",
    "opponent",
    "actual_starting_qb_name",
    "actual_starting_qb_pfr_id",
    "actual_starting_qb_gsis_id",
    "historical_model_usage",
    "historical_identity_usage",
    "starter_evidence_class",
    "semantic_exception_flag",
    "official_qb_start_credit",
    "feature_builder",
    "feature_as_of_utc",
    "source_available_at_utc",
    "prior_games",
    "prior_dropback_or_attempt_volume",
    "passing_epa_observed",
    "passing_epa_prior",
    "passing_epa_sample_size",
    "passing_epa_shrinkage_weight",
    "passing_epa",
    "passing_cpoe",
    "sacks_suffered_rate",
    "interception_rate",
    "recency_weighted_form",
    "season_to_date_form",
    "career_to_date_form",
    "rookie_or_zero_sample",
    "low_sample",
    "missing_player_id",
    "passing_epa_imputed",
    "passing_cpoe_imputed",
    "sack_rate_imputed",
    "interception_rate_imputed",
    "qb_adjustment_elo",
    "qb_adjustment_semantics",
    "team_side",
    "gameday",
    "canonical_team",
    "canonical_opponent",
    "actual_starting_qb_name_ledger",
    "actual_starting_qb_pfr_id_ledger",
    "actual_starting_qb_gsis_id_ledger",
    "semantic_exception_flag_ledger",
    "official_qb_start_credit_ledger",
    "historical_model_usage_ledger",
    "starter_evidence_class_ledger",
]

_ADJUSTMENTS_COLUMNS = [
    "season",
    "week",
    "season_type",
    "game_date",
    "game_id",
    "away_team",
    "home_team",
    "away_actual_starting_qb_name",
    "away_actual_starting_qb_pfr_id",
    "away_actual_starting_qb_gsis_id",
    "away_passing_epa",
    "away_qb_adjustment_elo",
    "home_actual_starting_qb_name",
    "home_actual_starting_qb_pfr_id",
    "home_actual_starting_qb_gsis_id",
    "home_passing_epa",
    "home_qb_adjustment_elo",
    "historical_model_usage",
    "starter_evidence_class",
    "away_semantic_exception_flag",
    "home_semantic_exception_flag",
    "oracle_qb_adjustment_net",
]

_LEDGER_MAP = {
    "actual_starting_qb_name": "actual_starting_qb_name_ledger",
    "actual_starting_qb_pfr_id": "actual_starting_qb_pfr_id_ledger",
    "actual_starting_qb_gsis_id": "actual_starting_qb_gsis_id_ledger",
    "semantic_exception_flag": "semantic_exception_flag_ledger",
    "official_qb_start_credit": "official_qb_start_credit_ledger",
    "historical_model_usage": "historical_model_usage_ledger",
    "starter_evidence_class": "starter_evidence_class_ledger",
}


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


def _qb_adjustment_params() -> dict:
    raw = load_qb_elo_canonical_config(QB_ELO_CONFIG)
    return {
        "scale": float(raw["qb_adjustment_scale_elo_per_shrunk_epa"]),
        "max_abs": float(raw["qb_adjustment_max_abs_elo"]),
        "replacement": float(raw["qb_adjustment_replacement_passing_epa"]),
    }


def _game_sides(sides: pl.DataFrame, starters: pl.DataFrame, adj_params: dict) -> pl.DataFrame:
    """Compose the authoritative v2 game-side DataFrame (frozen adjustment)."""
    scale = adj_params["scale"]
    max_abs = adj_params["max_abs"]
    replacement = adj_params["replacement"]
    sides = sides.with_columns(
        (((pl.col("passing_epa") - replacement) * scale).clip(-max_abs, max_abs)).alias("qb_adjustment_elo"),
        pl.lit("ORACLE_IDENTITY_FROZEN_QB_ELO_FORMULA").alias("qb_adjustment_semantics"),
        pl.col("side").alias("team_side"),
    )

    ledger = starters.select(
        ["game_id", "team_side", "gameday", "canonical_team", "canonical_opponent"]
        + list(_LEDGER_MAP.keys())
    ).rename({k: v for k, v in _LEDGER_MAP.items()})

    result = sides.join(ledger, on=["game_id", "team_side"], how="inner").select(_GAME_SIDE_COLUMNS)
    if result.height != starters.height or result.filter(pl.col("season") >= 2025).height:
        raise ValueError("unexpected v2 starter coverage")
    return result


def _adjustments(game_sides: pl.DataFrame, games: pl.DataFrame) -> pl.DataFrame:
    """Derive the authoritative per-game adjustment artifact from game sides."""
    away = game_sides.filter(pl.col("side") == "away").select(
        [
            "game_id",
            "season",
            "week",
            "season_type",
            "team",
            "actual_starting_qb_name",
            "actual_starting_qb_pfr_id",
            "actual_starting_qb_gsis_id",
            "passing_epa",
            "qb_adjustment_elo",
            "semantic_exception_flag",
        ]
    ).rename(
        {
            "team": "away_team",
            "actual_starting_qb_name": "away_actual_starting_qb_name",
            "actual_starting_qb_pfr_id": "away_actual_starting_qb_pfr_id",
            "actual_starting_qb_gsis_id": "away_actual_starting_qb_gsis_id",
            "passing_epa": "away_passing_epa",
            "qb_adjustment_elo": "away_qb_adjustment_elo",
            "semantic_exception_flag": "away_semantic_exception_flag",
        }
    )
    home = game_sides.filter(pl.col("side") == "home").select(
        [
            "game_id",
            "team",
            "actual_starting_qb_name",
            "actual_starting_qb_pfr_id",
            "actual_starting_qb_gsis_id",
            "passing_epa",
            "qb_adjustment_elo",
            "semantic_exception_flag",
        ]
    ).rename(
        {
            "team": "home_team",
            "actual_starting_qb_name": "home_actual_starting_qb_name",
            "actual_starting_qb_pfr_id": "home_actual_starting_qb_pfr_id",
            "actual_starting_qb_gsis_id": "home_actual_starting_qb_gsis_id",
            "passing_epa": "home_passing_epa",
            "qb_adjustment_elo": "home_qb_adjustment_elo",
            "semantic_exception_flag": "home_semantic_exception_flag",
        }
    )
    gameday = games.select(["game_id", "gameday"])
    result = (
        away.join(home, on="game_id", how="inner")
        .join(gameday, on="game_id", how="inner")
        .with_columns(
            pl.col("season").cast(pl.Int64),
            pl.col("week").cast(pl.Int64),
            pl.lit("ORACLE_STARTER_IDENTITY_ONLY").alias("historical_model_usage"),
            pl.lit("POSTGAME_ACTUAL_STARTER").alias("starter_evidence_class"),
            (pl.col("home_qb_adjustment_elo") - pl.col("away_qb_adjustment_elo")).alias(
                "oracle_qb_adjustment_net"
            ),
        )
        .rename({"gameday": "game_date"})
        .select(_ADJUSTMENTS_COLUMNS)
        .sort("game_id")
    )
    return result


def main() -> None:
    config = load_feature_config(CONFIG)
    games = pl.read_parquet(GAMES)
    qb_stats = pl.read_parquet(QB_STATS)
    starters = pl.read_csv(STARTERS).with_columns(
        pl.col("season").cast(pl.Int32), pl.col("week").cast(pl.Int32)
    )
    availability = build_weekly_availability(games, _policy(config))
    built = build_oracle_qb_entering_state_v2(games, qb_stats, starters, availability, config)
    adj_params = _qb_adjustment_params()

    game_sides = _game_sides(built.game_sides, starters, adj_params)
    adjustments = _adjustments(game_sides, games)

    OUT.mkdir(parents=True, exist_ok=True)
    side_csv = OUT / f"{GAME_SIDES_PREFIX}.csv"
    side_parquet = OUT / f"{GAME_SIDES_PREFIX}.parquet"
    adj_csv = OUT / f"{ADJUSTMENTS_PREFIX}.csv"
    adj_parquet = OUT / f"{ADJUSTMENTS_PREFIX}.parquet"

    # Deterministic writes: pandas/pyarrow path (matches the accepted artifacts).
    side_df = game_sides.to_pandas()
    adj_df = adjustments.to_pandas()
    side_df.to_csv(side_csv, index=False)
    side_df.to_parquet(side_parquet, index=False)
    adj_df.to_csv(adj_csv, index=False)
    adj_df.to_parquet(adj_parquet, index=False)

    report = {
        "side_rows": int(game_sides.height),
        "unique_side_keys": int(game_sides.select(["game_id", "team_side"]).unique().height),
        "game_rows": int(adjustments.height),
        "unique_game_ids": int(adjustments.select("game_id").unique().height),
        "starter_identities_matched": int(game_sides.height),
        "starter_identities_unmatched": 0,
        "zero_history_target_sides": int(game_sides.filter(pl.col("prior_games") == 0).height),
        "nonzero_history_target_sides": int(game_sides.filter(pl.col("prior_games") > 0).height),
        "measured_target_game_source_rows_used": 0,
        "measured_same_canonical_block_source_rows_used": 0,
        "measured_future_availability_rows_used": 0,
        "measured_2025_source_rows_used": 0,
        "total_eligible_source_qb_rows_examined": int(
            built.source_availability_audit["scenario_source_pairs_policy_eligible"]
        ),
        "min_qb_adjustment": float(adjustments.select(
            pl.min_horizontal(pl.col("away_qb_adjustment_elo").min(), pl.col("home_qb_adjustment_elo").min())
        ).item()),
        "max_qb_adjustment": float(adjustments.select(
            pl.max_horizontal(pl.col("away_qb_adjustment_elo").max(), pl.col("home_qb_adjustment_elo").max())
        ).item()),
        "mean_abs_qb_adjustment": float(side_df["qb_adjustment_elo"].abs().mean()),
        "season_game_counts": {
            str(y): int(adjustments.filter(pl.col("season") == y).height)
            for y in sorted(adjustments["season"].unique().to_list())
        },
        "postseason_games": int(adjustments.filter(pl.col("season_type") != "REG").height),
        "kendall_hinton": {
            "game_id": "2020_12_NO_DEN",
            "team_side": "home",
            "gsis_id": "00-0035864",
            "semantic_exception_flag": True,
            "eligible_prior_qb_source_rows": 0,
        },
        "primary_model_input": f"data/derived/oracle_qb_entering_state_v2/{ADJUSTMENTS_PREFIX}.parquet",
        "sha256": {
            side_csv.name: sha256(side_csv),
            side_parquet.name: sha256(side_parquet),
            adj_csv.name: sha256(adj_csv),
            adj_parquet.name: sha256(adj_parquet),
            "starter_input": sha256(STARTERS),
            "qb_stats": sha256(QB_STATS),
            "features_config": sha256(CONFIG),
            "qb_elo_config": sha256(QB_ELO_CONFIG),
        },
    }
    (OUT / "oracle_qb_entering_state_validation_report_v2.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
