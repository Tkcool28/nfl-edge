"""Pure walk-forward preparation for the frozen Totals V1 modeling table."""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from ..common.errors import WalkForwardError
from ..features.totals_v1.chronology import (
    build_totals_blocks,
    eligible_source_blocks,
    iter_blocks,
)
from ..features.totals_v1.feature_table import EXACT_90_COLUMNS
from ..features.totals_v1.season import assert_frame_development_only

IDENTITY_COLUMNS: tuple[str, ...] = (
    "game_id",
    "season",
    "season_type",
    "week",
    "home_team",
    "away_team",
    "block_id",
)
TARGET_COLUMNS: tuple[str, ...] = (
    "home_score",
    "away_score",
    "target_total_points",
)
_MODELING_TABLE_COLUMNS = IDENTITY_COLUMNS + EXACT_90_COLUMNS + TARGET_COLUMNS
_AVAILABILITY_KEY_COLUMNS: tuple[str, ...] = ("season", "season_type", "week")
_AVAILABILITY_COLUMNS = _AVAILABILITY_KEY_COLUMNS + (
    "prediction_as_of_utc",
    "eligible_for_features_at_utc",
)


@dataclass(frozen=True)
class TotalsWalkForwardBlock:
    """Prepared train/predict frames for one immutable target prediction block."""

    target_block: object
    training_game_ids: tuple[str, ...]
    training_rows: pl.DataFrame
    prediction_rows: pl.DataFrame
    outcome_rows: pl.DataFrame | None = None


@dataclass(frozen=True)
class TotalsWalkForwardRun:
    """The canonically ordered immutable collection of prepared target blocks."""

    blocks: tuple[TotalsWalkForwardBlock, ...]


def _require_exact_modeling_table(modeling_table: pl.DataFrame) -> None:
    actual = set(modeling_table.columns)
    expected = set(_MODELING_TABLE_COLUMNS)
    if actual != expected or len(modeling_table.columns) != len(_MODELING_TABLE_COLUMNS):
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise WalkForwardError(
            "run_totals_walk_forward",
            "modeling_table must contain exactly the frozen 100-column contract; "
            f"missing={missing}, unexpected={unexpected}",
        )

    assert_frame_development_only(
        modeling_table,
        where="run_totals_walk_forward modeling_table",
    )
    game_ids = modeling_table["game_id"].to_list()
    if any(game_id is None for game_id in game_ids):
        raise WalkForwardError("run_totals_walk_forward", "modeling_table has null game_id")
    if any(not isinstance(game_id, str) for game_id in game_ids):
        raise WalkForwardError("run_totals_walk_forward", "modeling_table game_id values must be strings")
    if len(set(game_ids)) != len(game_ids):
        raise WalkForwardError("run_totals_walk_forward", "modeling_table game_id values must be unique")


def _require_availability(availability: pl.DataFrame) -> None:
    missing = sorted(set(_AVAILABILITY_COLUMNS) - set(availability.columns))
    if missing:
        raise WalkForwardError(
            "run_totals_walk_forward",
            f"availability missing required columns: {missing}",
        )

    assert_frame_development_only(
        availability,
        where="run_totals_walk_forward availability",
    )
    nulls = availability.select(
        [pl.col(column).is_null().any().alias(column) for column in _AVAILABILITY_COLUMNS]
    ).row(0, named=True)
    null_columns = sorted(column for column, has_null in nulls.items() if has_null)
    if null_columns:
        raise WalkForwardError(
            "run_totals_walk_forward",
            f"availability has null required values: {null_columns}",
        )
    duplicate_keys = availability.select(list(_AVAILABILITY_KEY_COLUMNS)).is_duplicated().any()
    if duplicate_keys:
        raise WalkForwardError(
            "run_totals_walk_forward",
            "availability must have exactly one row per (season, season_type, week)",
        )


def _ordered_rows_for_game_ids(
    modeling_table: pl.DataFrame,
    game_ids: tuple[str, ...],
) -> pl.DataFrame:
    if not game_ids:
        return modeling_table.head(0)
    ordinal = pl.DataFrame(
        {"game_id": game_ids, "_walk_forward_ordinal": range(len(game_ids))}
    )
    return (
        ordinal.join(modeling_table, on="game_id", how="left")
        .sort("_walk_forward_ordinal")
        .drop("_walk_forward_ordinal")
    )


def run_totals_walk_forward(
    modeling_table: pl.DataFrame,
    availability: pl.DataFrame,
) -> TotalsWalkForwardRun:
    """Prepare deterministic expanding train/predict frames for every target block.

    Inputs are fully in-memory DataFrames. This function deliberately performs
    neither feature construction nor model fitting.
    """
    _require_exact_modeling_table(modeling_table)
    _require_availability(availability)

    block_input = modeling_table.select(
        ["game_id", "season", "season_type", "week"]
    ).join(
        availability.select([*_AVAILABILITY_KEY_COLUMNS, "prediction_as_of_utc"]),
        on=list(_AVAILABILITY_KEY_COLUMNS),
        how="left",
    )
    if block_input["prediction_as_of_utc"].null_count() != 0:
        raise WalkForwardError(
            "run_totals_walk_forward",
            "one or more modeled blocks lack joined prediction_as_of_utc",
        )

    all_blocks = tuple(iter_blocks(build_totals_blocks(block_input)))
    prepared_blocks: list[TotalsWalkForwardBlock] = []
    for target in all_blocks:
        source_blocks = eligible_source_blocks(target, all_blocks, availability)
        training_game_ids = tuple(
            game_id for source in source_blocks for game_id in source.game_ids
        )
        training_rows = _ordered_rows_for_game_ids(modeling_table, training_game_ids)
        prediction_rows = (
            _ordered_rows_for_game_ids(modeling_table, target.game_ids)
            .select([*IDENTITY_COLUMNS, *EXACT_90_COLUMNS])
        )
        outcome_rows = _ordered_rows_for_game_ids(modeling_table, target.game_ids).select(
            [*IDENTITY_COLUMNS, "target_total_points"]
        )
        prepared_blocks.append(
            TotalsWalkForwardBlock(
                target_block=target,
                training_game_ids=training_game_ids,
                training_rows=training_rows,
                prediction_rows=prediction_rows,
                outcome_rows=outcome_rows,
            )
        )

    return TotalsWalkForwardRun(blocks=tuple(prepared_blocks))
