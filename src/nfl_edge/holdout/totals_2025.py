"""Holdout-only block predictor for the frozen Ridge Totals V1 R4 model.

This module does not read files and does not authorize the sealed 2025 holdout.
An already-authorized caller must supply the exact frozen 90-column predictor
surface for the current block plus strictly-prior training rows.  The accepted
Task05D model construction is reused directly: R4 is Ridge(alpha=100) behind
the frozen numeric/categorical preprocessing pipeline.

The development feature builder remains sealed at 2024.  In particular, this
adapter is not a substitute for the still-required causal 2025 Totals V1
feature materializer.
"""
from __future__ import annotations

from math import isfinite
from typing import Any

import polars as pl

from nfl_edge.backtest.totals_bake_off import (
    MINIMUM_ELIGIBLE_PRIOR_ROWS,
    _pandas_predictors,
    build_candidate_model,
    candidate_spec,
)
from nfl_edge.backtest.totals_walk_forward import IDENTITY_COLUMNS
from nfl_edge.features.totals_v1.feature_table import EXACT_90_COLUMNS

from .football_2025 import (
    HOLDOUT_SEASON,
    HoldoutBlock,
    HoldoutFootballContractError,
    assert_current_block_unrevealed,
    assert_history_strictly_prior,
)

FROZEN_CANDIDATE_ID = "R4"
FROZEN_ALPHA = 100
FROZEN_FEATURE_COUNT = 90
FROZEN_DEVELOPMENT_SEASONS = tuple(range(2018, 2025))
_TARGET_COLUMN = "target_total_points"


def _assert_frozen_model_contract() -> None:
    spec = candidate_spec(FROZEN_CANDIDATE_ID)
    if spec.family != "ridge" or tuple(spec.parameters) != (("alpha", FROZEN_ALPHA),):
        raise HoldoutFootballContractError(
            "Ridge Totals R4 frozen candidate drift: expected ridge alpha=100"
        )
    if len(EXACT_90_COLUMNS) != FROZEN_FEATURE_COUNT:
        raise HoldoutFootballContractError(
            f"Ridge Totals feature contract drift: {len(EXACT_90_COLUMNS)} != {FROZEN_FEATURE_COUNT}"
        )


def _require_columns(frame: pl.DataFrame, required: set[str], *, where: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise HoldoutFootballContractError(f"{where} missing totals columns: {missing[:12]}")


def _assert_training_history(history: pl.DataFrame, block: HoldoutBlock) -> None:
    _require_columns(
        history,
        set(IDENTITY_COLUMNS) | set(EXACT_90_COLUMNS) | {_TARGET_COLUMN},
        where="prior_history",
    )
    assert_history_strictly_prior(history, block)
    if history.height < MINIMUM_ELIGIBLE_PRIOR_ROWS:
        raise HoldoutFootballContractError(
            f"Ridge Totals R4 requires at least {MINIMUM_ELIGIBLE_PRIOR_ROWS} strictly-prior rows: "
            f"got {history.height}"
        )

    development = history.filter(pl.col("season") < HOLDOUT_SEASON)
    seasons = tuple(sorted({int(x) for x in development["season"].unique().to_list()}))
    if seasons != FROZEN_DEVELOPMENT_SEASONS:
        raise HoldoutFootballContractError(
            "Ridge Totals development history must contain exactly seasons 2018-2024: "
            f"got {seasons}"
        )

    target = history[_TARGET_COLUMN].cast(pl.Float64, strict=True)
    if target.null_count() or not all(isfinite(float(value)) for value in target.to_list()):
        raise HoldoutFootballContractError("Ridge Totals prior targets must be finite and fully revealed")

    holdout_history = history.filter(pl.col("season") == HOLDOUT_SEASON)
    if holdout_history.height and "target_available" in holdout_history.columns:
        if not bool(holdout_history["target_available"].fill_null(False).all()):
            raise HoldoutFootballContractError(
                "Ridge Totals prior 2025 history contains an unrevealed target"
            )


def _current_block(current_games: pl.DataFrame, block: HoldoutBlock) -> pl.DataFrame:
    _require_columns(
        current_games,
        set(IDENTITY_COLUMNS) | set(EXACT_90_COLUMNS),
        where="current_games",
    )
    current = current_games.filter(
        (pl.col("season") == block.season)
        & (pl.col("season_type").cast(pl.Utf8).str.to_uppercase() == block.season_type)
        & (pl.col("week") == block.week)
    ).sort("game_id")
    ids = tuple(sorted(str(value) for value in current["game_id"].to_list()))
    if ids != block.game_ids:
        raise HoldoutFootballContractError(
            f"Ridge Totals block game identity mismatch: frame={ids} block={block.game_ids}"
        )
    assert_current_block_unrevealed(current)
    if _TARGET_COLUMN in current.columns and current[_TARGET_COLUMN].null_count() != current.height:
        raise HoldoutFootballContractError(
            "Ridge Totals current target_total_points must be null before prediction"
        )
    return current


def predict_ridge_totals_block(
    *,
    prior_history: pl.DataFrame,
    current_games: pl.DataFrame,
    block: HoldoutBlock,
) -> dict[str, Any]:
    """Fit frozen R4 on strictly-prior rows and predict one unrevealed 2025 block.

    ``prior_history`` must include the complete 2018-2024 development surface
    and may additionally include already-revealed earlier 2025 blocks.  The
    current block is never added to training and its target is never read.
    """
    _assert_frozen_model_contract()
    _assert_training_history(prior_history, block)
    current = _current_block(current_games, block)

    training_x = _pandas_predictors(
        prior_history.select(list(EXACT_90_COLUMNS)),
        "ridge",
    )
    current_x = _pandas_predictors(
        current.select(list(EXACT_90_COLUMNS)),
        "ridge",
    )
    target = prior_history[_TARGET_COLUMN].cast(pl.Float64, strict=True).to_list()

    model = build_candidate_model(FROZEN_CANDIDATE_ID)
    model.fit(training_x, target)
    raw = model.predict(current_x)
    predictions = [float(value) for value in raw]
    if len(predictions) != current.height or not all(isfinite(value) for value in predictions):
        raise HoldoutFootballContractError("Ridge Totals R4 produced malformed predictions")

    return {
        "block": block,
        "candidate_id": FROZEN_CANDIDATE_ID,
        "alpha": FROZEN_ALPHA,
        "fit_rows": prior_history.height,
        "game_ids": [str(value) for value in current["game_id"].to_list()],
        "predicted_totals": predictions,
        "outcomes_revealed": False,
    }
