"""Holdout-only causal feature bridge for frozen Totals V1 exact-90 inputs.

This module deliberately does not read files and does not authorize 2025.
It reuses the accepted Totals V1 entering-state and feature-emission
primitives while keeping the development builder sealed at 2024.

The lifecycle is intentionally split:

1. bootstrap a TotalsBlockState from complete 2018-2024 observations;
2. snapshot that state and materialize the current 2025 block's exact 90
   predictors with no current outcome available;
3. freeze/predict the entire block;
4. only after outcomes are revealed, atomically commit the complete block's
   observations and return graded rows for strictly-prior future training.

No same-block observation can affect another game in the block because feature
materialization never mutates state and reveal/commit verifies that state still
matches the frozen block-start snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import polars as pl

from nfl_edge.backtest.blocks import PredictionBlock
from nfl_edge.features.totals_v1.block_state import (
    BlockStartSnapshot,
    GameObservation,
    TotalsBlockState,
)
from nfl_edge.features.totals_v1.feature_table import (
    EXACT_90_COLUMNS,
    _ORACLE_QB_CONSUMED_COLUMNS,
    _emit_feature_row,
)

from .football_2025 import (
    HOLDOUT_SEASON,
    HoldoutBlock,
    HoldoutFootballContractError,
    assert_current_block_unrevealed,
)

_DEVELOPMENT_SEASONS = tuple(range(2018, 2025))
_ST_PRIORITY = {"REG": 0, "WC": 1, "DIV": 2, "CON": 3, "SB": 4}
_IDENTITY_COLUMNS = (
    "game_id",
    "season",
    "season_type",
    "week",
    "home_team",
    "away_team",
    "block_id",
)
_CONTEXT_COLUMNS = ("away_rest", "home_rest", "surface", "roof_type")


@dataclass(frozen=True)
class FrozenTotalsFeatureBlock:
    """Immutable feature payload produced before a 2025 block is revealed."""

    block: HoldoutBlock
    block_start_snapshot: BlockStartSnapshot
    identity: pl.DataFrame
    features: pl.DataFrame
    model_frame: pl.DataFrame
    outcomes_revealed: bool = False


def _block_key(block: PredictionBlock) -> tuple[int, int, int]:
    season_type = str(block.season_type).upper()
    if season_type not in _ST_PRIORITY:
        raise HoldoutFootballContractError(
            f"unsupported development season_type for totals bootstrap: {season_type!r}"
        )
    return int(block.season), _ST_PRIORITY[season_type], int(block.week)


def bootstrap_totals_state(
    *,
    blocks: Sequence[PredictionBlock],
    observations_by_block: Mapping[str, Sequence[GameObservation]],
) -> TotalsBlockState:
    """Rebuild frozen entering state from complete 2018-2024 observations only.

    The caller is responsible for preparing observations through the accepted
    Totals V1 PBP observation machinery.  This function performs no I/O and
    accepts no 2025 block type.
    """
    if not blocks:
        raise HoldoutFootballContractError("Totals bootstrap requires development blocks")

    seasons = tuple(sorted({int(block.season) for block in blocks}))
    if seasons != _DEVELOPMENT_SEASONS:
        raise HoldoutFootballContractError(
            f"Totals bootstrap seasons must be exactly 2018-2024: got {seasons}"
        )

    ids = [str(block.block_id) for block in blocks]
    if len(ids) != len(set(ids)):
        raise HoldoutFootballContractError("Totals bootstrap block_id values must be unique")
    provided = set(str(key) for key in observations_by_block)
    expected = set(ids)
    if provided != expected:
        raise HoldoutFootballContractError(
            "Totals bootstrap observation blocks do not exactly match development blocks: "
            f"missing={sorted(expected - provided)} extra={sorted(provided - expected)}"
        )

    previous: tuple[int, int, int] | None = None
    state = TotalsBlockState()
    for block in blocks:
        key = _block_key(block)
        if previous is not None and key <= previous:
            raise HoldoutFootballContractError(
                f"Totals bootstrap blocks are not strictly chronological: {key} <= {previous}"
            )
        previous = key
        try:
            state.commit_block(block, list(observations_by_block[block.block_id]))
        except ValueError as exc:
            raise HoldoutFootballContractError(
                f"Totals bootstrap rejected incomplete/invalid block {block.block_id}: {exc}"
            ) from exc
    return state


def _current_block_frame(frame: pl.DataFrame, block: HoldoutBlock) -> pl.DataFrame:
    required = {
        "game_id",
        "season",
        "season_type",
        "week",
        "home_team",
        "away_team",
        *_CONTEXT_COLUMNS,
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise HoldoutFootballContractError(
            f"Totals feature current_games missing columns: {missing}"
        )
    selected = frame.filter(
        (pl.col("season") == block.season)
        & (pl.col("season_type").cast(pl.Utf8).str.to_uppercase() == block.season_type)
        & (pl.col("week") == block.week)
    ).sort("game_id")
    ids = tuple(str(value) for value in selected["game_id"].to_list())
    if ids != block.game_ids:
        raise HoldoutFootballContractError(
            f"Totals feature block game identity mismatch: frame={ids} block={block.game_ids}"
        )
    assert_current_block_unrevealed(selected)
    if "target_total_points" in selected.columns:
        if selected["target_total_points"].null_count() != selected.height:
            raise HoldoutFootballContractError(
                "Totals feature current target_total_points must be null before materialization"
            )
    return selected


def _oracle_for_block(oracle_qb: pl.DataFrame, block: HoldoutBlock) -> pl.DataFrame:
    required = {"game_id", "side", *_ORACLE_QB_CONSUMED_COLUMNS}
    missing = sorted(required - set(oracle_qb.columns))
    if missing:
        raise HoldoutFootballContractError(
            f"Totals feature Oracle QB frame missing consumed columns: {missing}"
        )
    selected = oracle_qb.filter(pl.col("game_id").cast(pl.Utf8).is_in(list(block.game_ids)))
    if selected.height:
        invalid_sides = sorted(
            {
                str(value)
                for value in selected["side"].drop_nulls().unique().to_list()
                if str(value) not in {"away", "home"}
            }
        )
        if invalid_sides:
            raise HoldoutFootballContractError(
                f"Totals feature Oracle QB frame has invalid sides: {invalid_sides}"
            )
        if selected.select("game_id", "side").is_duplicated().sum():
            raise HoldoutFootballContractError(
                "Totals feature Oracle QB frame has duplicate (game_id, side) rows"
            )
    # Select only the historically accepted consumed surface; any other columns
    # supplied by an authorized caller are intentionally not exposed downstream.
    return selected.select(["game_id", "side", *_ORACLE_QB_CONSUMED_COLUMNS])


def materialize_totals_feature_block(
    *,
    state: TotalsBlockState,
    current_games: pl.DataFrame,
    oracle_qb: pl.DataFrame,
    block: HoldoutBlock,
) -> FrozenTotalsFeatureBlock:
    """Freeze and emit the exact 90 R4 predictors for one unrevealed 2025 block."""
    current = _current_block_frame(current_games, block)
    oracle = _oracle_for_block(oracle_qb, block)
    snapshot = state.snapshot_for_block(block)

    feature_rows: list[dict[str, object]] = []
    identity_rows: list[dict[str, object]] = []
    for row in current.iter_rows(named=True):
        game_id = str(row["game_id"])
        emitted = _emit_feature_row(
            game_id=game_id,
            home_team=str(row["home_team"]),
            away_team=str(row["away_team"]),
            snapshot=snapshot,
            context_row={name: row.get(name) for name in _CONTEXT_COLUMNS},
            oracle_qb=oracle,
        )
        if set(emitted) != set(EXACT_90_COLUMNS):
            raise HoldoutFootballContractError(
                f"Totals feature emission drift for {game_id}: expected exact 90-column surface"
            )
        feature_rows.append(emitted)
        identity_rows.append(
            {
                "game_id": game_id,
                "season": int(row["season"]),
                "season_type": str(row["season_type"]).upper(),
                "week": int(row["week"]),
                "home_team": str(row["home_team"]),
                "away_team": str(row["away_team"]),
                "block_id": block.block_id,
            }
        )

    features = pl.DataFrame(feature_rows).select(list(EXACT_90_COLUMNS))
    identity = pl.DataFrame(identity_rows).select(list(_IDENTITY_COLUMNS))
    if features.width != 90 or features.columns != list(EXACT_90_COLUMNS):
        raise HoldoutFootballContractError("Totals feature matrix is not the frozen exact-90 contract")
    if features.height != identity.height or features.height != len(block.game_ids):
        raise HoldoutFootballContractError("Totals feature row count does not match block identity")

    model_frame = pl.concat([identity, features], how="horizontal").with_columns(
        pl.lit(False).alias("target_available"),
        pl.lit(None, dtype=pl.Float64).alias("target_total_points"),
    )
    return FrozenTotalsFeatureBlock(
        block=block,
        block_start_snapshot=snapshot,
        identity=identity,
        features=features,
        model_frame=model_frame,
        outcomes_revealed=False,
    )


def reveal_and_commit_totals_block(
    *,
    frozen: FrozenTotalsFeatureBlock,
    state: TotalsBlockState,
    revealed_games: pl.DataFrame,
    observations: Sequence[GameObservation],
) -> dict[str, object]:
    """Commit one complete block only after its frozen features receive outcomes."""
    if frozen.outcomes_revealed:
        raise HoldoutFootballContractError("Totals feature block outcomes already revealed")
    block = frozen.block
    if state.snapshot_for_block(block) != frozen.block_start_snapshot:
        raise HoldoutFootballContractError(
            "Totals entering state changed after feature freeze and before block commit"
        )

    required = {
        "game_id",
        "season",
        "season_type",
        "week",
        "target_available",
        "home_score",
        "away_score",
        "target_total_points",
    }
    missing = sorted(required - set(revealed_games.columns))
    if missing:
        raise HoldoutFootballContractError(f"Totals revealed block missing columns: {missing}")
    revealed = revealed_games.filter(
        (pl.col("season") == block.season)
        & (pl.col("season_type").cast(pl.Utf8).str.to_uppercase() == block.season_type)
        & (pl.col("week") == block.week)
    ).sort("game_id")
    ids = tuple(str(value) for value in revealed["game_id"].to_list())
    if ids != block.game_ids:
        raise HoldoutFootballContractError(
            f"Totals revealed block game identity mismatch: frame={ids} block={block.game_ids}"
        )
    if not bool(revealed["target_available"].fill_null(False).all()):
        raise HoldoutFootballContractError("Totals revealed block contains unavailable outcomes")
    for column in ("home_score", "away_score", "target_total_points"):
        if revealed[column].null_count():
            raise HoldoutFootballContractError(f"Totals revealed block missing {column}")
    for row in revealed.select(
        "game_id", "home_score", "away_score", "target_total_points"
    ).iter_rows(named=True):
        expected = float(row["home_score"]) + float(row["away_score"])
        if float(row["target_total_points"]) != expected:
            raise HoldoutFootballContractError(
                f"Totals target_total_points mismatch for {row['game_id']}: "
                f"{row['target_total_points']} != {expected}"
            )

    try:
        state.commit_block(block, list(observations))
    except ValueError as exc:
        raise HoldoutFootballContractError(
            f"Totals complete-block observation commit failed: {exc}"
        ) from exc

    targets = revealed.select("game_id", pl.col("target_total_points").cast(pl.Float64))
    graded = (
        frozen.model_frame.drop("target_available", "target_total_points")
        .join(targets, on="game_id", how="left", validate="1:1")
        .with_columns(pl.lit(True).alias("target_available"))
        .sort("game_id")
    )
    if graded["target_total_points"].null_count():
        raise HoldoutFootballContractError("Totals graded frame lost a revealed target")
    return {
        "block": block,
        "graded_model_rows": graded,
        "new_block_start_snapshot": state.snapshot_for_block(block),
        "outcomes_revealed": True,
    }
