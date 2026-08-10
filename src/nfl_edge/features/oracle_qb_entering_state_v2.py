"""Canonical-pipeline oracle QB entering-state reconstruction (v2).

Actual starters are historical identity labels only.  All numerical QB state is
constructed by :func:`build_qb_pregame_features` using the repository's
availability table and feature configuration; this module deliberately does
not import or execute QB-Elo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from .qb import build_qb_pregame_features
from .validation import assert_unique_keys

_REQUIRED_STARTER_COLUMNS = {
    "game_id",
    "season",
    "season_type",
    "week",
    "team_side",
    "canonical_team",
    "canonical_opponent",
    "actual_starting_qb_name",
    "actual_starting_qb_pfr_id",
    "actual_starting_qb_gsis_id",
    "historical_model_usage",
    "starter_evidence_class",
    "semantic_exception_flag",
    "official_qb_start_credit",
}


@dataclass(frozen=True)
class OracleQBEnteringStateV2:
    """Canonical QB features joined to postgame actual-starter identities."""

    game_sides: pl.DataFrame
    source_availability_audit: dict[str, Any]


def _oracle_scenarios(starters: pl.DataFrame) -> pl.DataFrame:
    missing = sorted(_REQUIRED_STARTER_COLUMNS - set(starters.columns))
    if missing:
        raise ValueError(f"oracle starters missing columns: {missing}")
    assert_unique_keys(starters, ["game_id", "team_side"], "oracle starter game side")
    invalid_side = starters.filter(~pl.col("team_side").is_in(["home", "away"]))
    if invalid_side.height:
        raise ValueError("oracle starter team_side must be home or away")
    return starters.select(
        pl.col("game_id"),
        pl.col("canonical_team").alias("team"),
        pl.col("canonical_opponent").alias("opponent"),
        pl.col("team_side").alias("side"),
        pl.lit(1).cast(pl.Int64).alias("candidate_rank"),
        pl.col("actual_starting_qb_gsis_id").alias("player_id"),
        pl.col("starter_evidence_class").alias("starter_certainty"),
        pl.col("season").cast(pl.Int32),
        pl.col("season_type"),
        pl.col("week").cast(pl.Int32),
    )


def _source_availability_audit(
    games: pl.DataFrame,
    qb_stats: pl.DataFrame,
    scenarios: pl.DataFrame,
    availability: pl.DataFrame,
    canonical_qb_features: pl.DataFrame,
) -> dict[str, Any]:
    """Measure policy eligibility and disclose record-level timestamp gaps."""

    game_columns = {"game_id", "season", "season_type", "week"}
    if missing := sorted(game_columns - set(games.columns)):
        raise ValueError(f"games missing source-audit columns: {missing}")
    availability_columns = {
        "season",
        "season_type",
        "week",
        "prediction_as_of_utc",
        "eligible_for_features_at_utc",
        "availability_rule",
    }
    if missing := sorted(availability_columns - set(availability.columns)):
        raise ValueError(f"availability missing source-audit columns: {missing}")

    # QB-stat ``season_type`` uses a broad POST label in this frozen source,
    # while the canonical games/availability path uses WC/DIV/CON/SB.  Join
    # availability through the canonical game's block identity, exactly as the
    # feature builder does when it resolves a stat's owning game.
    source = qb_stats.filter(pl.col("player_id").is_not_null()).join(
        games.select(
            "game_id",
            pl.col("season").alias("game_season"),
            pl.col("season_type").alias("game_season_type"),
            pl.col("week").alias("game_week"),
        ),
        on="game_id",
        how="inner",
    )
    source = source.join(
        availability.select(
            pl.col("season").alias("game_season"),
            pl.col("season_type").alias("game_season_type"),
            pl.col("week").alias("game_week"),
            "eligible_for_features_at_utc",
            "availability_rule",
        ),
        on=["game_season", "game_season_type", "game_week"],
        how="left",
    )
    if source["eligible_for_features_at_utc"].null_count():
        raise ValueError("source QB rows lack weekly availability")

    source_rows = source.to_dicts()
    scenario_rows = scenarios.to_dicts()
    policy_eligible = 0
    after_cutoff = 0
    same_game = 0
    future_season_used = 0
    for scenario in scenario_rows:
        for row in source_rows:
            if row["player_id"] != scenario["player_id"]:
                continue
            if row["game_id"] == scenario["game_id"]:
                same_game += 1
                continue
            as_of = availability.filter(
                (pl.col("season") == scenario["season"])
                & (pl.col("season_type") == scenario["season_type"])
                & (pl.col("week") == scenario["week"])
            )["prediction_as_of_utc"][0]
            if row["eligible_for_features_at_utc"] <= as_of:
                policy_eligible += 1
                if int(row["season"]) >= 2025:
                    future_season_used += 1
            else:
                after_cutoff += 1

    output_with_source = canonical_qb_features.filter(pl.col("source_available_at_utc").is_not_null())
    output_violations = output_with_source.filter(pl.col("source_available_at_utc") > pl.col("feature_as_of_utc"))
    observed_present = (
        int(source.filter(pl.col("observed_at_utc").is_not_null()).height)
        if "observed_at_utc" in source.columns
        else 0
    )
    return {
        "availability_basis": "CANONICAL_WEEKLY_AVAILABILITY_POLICY",
        "availability_rule": availability["availability_rule"][0],
        "record_level_source_availability_measured": observed_present == source.height,
        "source_rows_examined": int(source.height),
        "source_rows_record_observed_at_utc_present": observed_present,
        "source_rows_record_observed_at_utc_missing": int(source.height - observed_present),
        "scenario_source_pairs_policy_eligible": policy_eligible,
        "scenario_source_pairs_rejected_after_feature_as_of": after_cutoff,
        "scenario_source_pairs_same_game_excluded": same_game,
        "future_season_source_rows_used": future_season_used,
        "output_rows_with_prior_source": int(output_with_source.height),
        "output_source_availability_violations": int(output_violations.height),
    }


def build_oracle_qb_entering_state_v2(
    games: pl.DataFrame,
    qb_stats: pl.DataFrame,
    starters: pl.DataFrame,
    availability: pl.DataFrame,
    config: dict[str, Any],
) -> OracleQBEnteringStateV2:
    """Build actual-starter-labeled QB state with the canonical feature path."""

    scenarios = _oracle_scenarios(starters)
    canonical = build_qb_pregame_features(games, qb_stats, scenarios, availability, config)
    identities = starters.select(sorted(_REQUIRED_STARTER_COLUMNS)).rename({"team_side": "side"})
    result = canonical.join(identities, on=["game_id", "season", "season_type", "week", "side"], how="inner")
    result = result.with_columns(
        pl.lit("build_qb_pregame_features").alias("feature_builder"),
        pl.lit("POSTGAME_ACTUAL_STARTER_IDENTITY_ONLY").alias("historical_identity_usage"),
    ).select(
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
    ).sort(["season", "week", "game_id", "side"])
    assert_unique_keys(result, ["game_id", "side"], "oracle v2 game side")
    audit = _source_availability_audit(games, qb_stats, scenarios, availability, canonical)
    if audit["output_source_availability_violations"]:
        raise ValueError("canonical QB output contains a post-as-of source row")
    if audit["future_season_source_rows_used"]:
        raise ValueError("oracle v2 used a future-season QB source row")
    return OracleQBEnteringStateV2(game_sides=result, source_availability_audit=audit)
