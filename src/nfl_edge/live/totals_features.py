"""Season-generic live exact-90 feature bridge for frozen Ridge Totals R4."""
from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from nfl_edge.features.totals_v1.block_state import BlockStartSnapshot, TotalsBlockState
from nfl_edge.features.totals_v1.feature_table import (
    EXACT_90_COLUMNS,
    _ORACLE_QB_CONSUMED_COLUMNS,
    _emit_feature_row,
)
from nfl_edge.live.model_adapters import LiveBlock, LiveFootballContractError, assert_current_block_unrevealed

_CONTEXT_COLUMNS = ("away_rest", "home_rest", "surface", "roof_type")
_IDENTITY_COLUMNS = (
    "game_id", "season", "season_type", "week", "home_team", "away_team", "block_id",
)


@dataclass(frozen=True)
class FrozenLiveTotalsFeatureBlock:
    block: LiveBlock
    block_start_snapshot: BlockStartSnapshot
    identity: pl.DataFrame
    features: pl.DataFrame
    model_frame: pl.DataFrame
    outcomes_revealed: bool = False


def materialize_live_totals_feature_block(
    *,
    state: TotalsBlockState,
    current_games: pl.DataFrame,
    qb_surface: pl.DataFrame,
    block: LiveBlock,
) -> FrozenLiveTotalsFeatureBlock:
    """Freeze one live block and emit the historically accepted exact 90 predictors."""
    required = {"game_id", "home_team", "away_team", *_CONTEXT_COLUMNS}
    missing = sorted(required - set(current_games.columns))
    if missing:
        raise LiveFootballContractError(f"Totals live current_games missing columns: {missing}")
    current = assert_current_block_unrevealed(current_games, block)
    qb_required = {"game_id", "side", *_ORACLE_QB_CONSUMED_COLUMNS}
    qb_missing = sorted(qb_required - set(qb_surface.columns))
    if qb_missing:
        raise LiveFootballContractError(f"Totals live QB surface missing columns: {qb_missing}")
    oracle = qb_surface.filter(pl.col("game_id").cast(pl.Utf8).is_in(list(block.game_ids))).select(
        ["game_id", "side", *_ORACLE_QB_CONSUMED_COLUMNS]
    )
    if oracle.height != len(block.game_ids) * 2 or oracle.select("game_id", "side").is_duplicated().sum():
        raise LiveFootballContractError("Totals live QB surface must contain exactly two unique sides per game")

    snapshot = state.snapshot_for_block(block)
    feature_rows: list[dict[str, object]] = []
    identity_rows: list[dict[str, object]] = []
    for row in current.sort("game_id").iter_rows(named=True):
        gid = str(row["game_id"])
        emitted = _emit_feature_row(
            game_id=gid,
            home_team=str(row["home_team"]),
            away_team=str(row["away_team"]),
            snapshot=snapshot,
            context_row={name: row.get(name) for name in _CONTEXT_COLUMNS},
            oracle_qb=oracle,
        )
        if set(emitted) != set(EXACT_90_COLUMNS):
            raise LiveFootballContractError(f"Totals exact-90 emission drift for {gid}")
        feature_rows.append(emitted)
        identity_rows.append(
            {
                "game_id": gid,
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
        raise LiveFootballContractError("Totals live feature matrix is not the frozen exact-90 contract")
    model_frame = pl.concat([identity, features], how="horizontal").with_columns(
        pl.lit(False).alias("target_available"),
        pl.lit(None, dtype=pl.Float64).alias("target_total_points"),
    )
    return FrozenLiveTotalsFeatureBlock(
        block=block,
        block_start_snapshot=snapshot,
        identity=identity,
        features=features,
        model_frame=model_frame,
        outcomes_revealed=False,
    )
