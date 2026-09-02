"""Post-V5 successor adapter for XGBoost with adaptive validation tail.

This preserves the frozen conservative XGBoost candidate, feature contract,
training gates, early stopping, refit semantics, categorical vocabulary and
strict-prior chronology from ``xgboost_2025``.  Only split construction changes:
validation expands backward through prior blocks until the existing minimum
row/block gates are satisfied.

The frozen ``xgboost_2025`` V1 adapter remains untouched for V5 provenance.
"""
from __future__ import annotations

from typing import Any

import polars as pl

from nfl_edge.backtest.xgboost_walk_forward import (
    CANDIDATES,
    SHARED_SETTINGS,
    WalkForwardEngine,
    evaluate_warmup_reason,
)
from nfl_edge.backtest.xgboost_walk_forward_v2 import (
    SPLIT_POLICY_VERSION,
    construct_adaptive_split,
)
from nfl_edge.holdout.xgboost_2025 import (
    FROZEN_CANDIDATE_ID,
    _assert_development_reference,
    _assert_feature_contract,
    _assert_frame_schema,
    _assert_frozen_categories,
    _block_key,
    _filter_keys,
)

from .football_2025 import (
    HOLDOUT_SEASON,
    HoldoutBlock,
    HoldoutFootballContractError,
    assert_current_block_unrevealed,
    assert_history_strictly_prior,
)


def predict_xgboost_block_v2(
    *,
    development_reference: pl.DataFrame,
    prior_history: pl.DataFrame,
    current_games: pl.DataFrame,
    block: HoldoutBlock,
    feature_cols: list[str],
) -> dict[str, Any]:
    """Predict one block using the V2 adaptive strictly-prior validation tail."""
    _assert_feature_contract(feature_cols)
    _assert_frame_schema(development_reference, feature_cols, where="development_reference")
    _assert_frame_schema(prior_history, feature_cols, where="prior_history")
    _assert_frame_schema(current_games, feature_cols, where="current_games")
    _assert_development_reference(development_reference)
    assert_history_strictly_prior(prior_history, block)
    assert_current_block_unrevealed(current_games)

    current = current_games.filter(
        (pl.col("season") == HOLDOUT_SEASON)
        & (pl.col("season_type") == block.season_type)
        & (pl.col("week") == block.week)
    ).sort(["scheduled_start_utc", "game_id"])
    ids = tuple(sorted(str(x) for x in current["game_id"].to_list()))
    if ids != block.game_ids:
        raise HoldoutFootballContractError(
            f"XGBoost V2 block game identity mismatch: frame={ids} block={block.game_ids}"
        )
    if current["target_home_win"].null_count() != current.height:
        raise HoldoutFootballContractError("XGBoost V2 current target_home_win must be null")

    encoder = WalkForwardEngine(
        development_reference,
        feature_cols,
        target_col="target_home_win",
    )
    _assert_frozen_categories(encoder, prior_history, where="prior_history")
    _assert_frozen_categories(encoder, current, where="current_games")

    current_key = _block_key(block)
    split = construct_adaptive_split(prior_history, current_key, SHARED_SETTINGS)
    fit_df = _filter_keys(prior_history, split.fit_blocks)
    val_df = _filter_keys(prior_history, split.validation_blocks)
    warmup_reason = evaluate_warmup_reason(split, fit_df, val_df, SHARED_SETTINGS)
    if warmup_reason is not None:
        return {
            "block": block,
            "candidate_id": FROZEN_CANDIDATE_ID,
            "split_policy_version": SPLIT_POLICY_VERSION,
            "warmup": True,
            "warmup_reason": warmup_reason,
            "fit_rows": fit_df.height,
            "fit_blocks": len(split.fit_blocks),
            "validation_rows": val_df.height,
            "validation_blocks": len(split.validation_blocks),
            "probabilities": [],
            "game_ids": list(current["game_id"].to_list()),
            "outcomes_revealed": False,
        }

    binary_fit = fit_df.filter(
        (pl.col("target_home_win") == 1) | (pl.col("target_home_win") == 0)
    ).select(feature_cols + ["target_home_win"])
    binary_val = val_df.filter(
        (pl.col("target_home_win") == 1) | (pl.col("target_home_win") == 0)
    ).select(feature_cols + ["target_home_win"])

    candidate = CANDIDATES[FROZEN_CANDIDATE_ID]
    fit_dm = encoder._to_dmatrix(binary_fit, feature_cols, "target_home_win")  # noqa: SLF001
    val_dm = encoder._to_dmatrix(binary_val, feature_cols, "target_home_win")  # noqa: SLF001
    _, best_iteration, early_status = encoder._train_with_early_stopping(  # noqa: SLF001
        candidate, fit_dm, val_dm
    )
    final_rounds = best_iteration + 1

    combined = pl.concat([binary_fit, binary_val], how="vertical")
    full_dm = encoder._to_dmatrix(combined, feature_cols, "target_home_win")  # noqa: SLF001
    booster = encoder._refit_full(candidate, full_dm, final_rounds)  # noqa: SLF001
    current_dm = encoder._predict_dmatrix(current, feature_cols)  # noqa: SLF001
    raw = booster.predict(current_dm)
    eps = SHARED_SETTINGS["probability_epsilon"]
    probabilities = [max(eps, min(1.0 - eps, float(p))) for p in raw]

    return {
        "block": block,
        "candidate_id": FROZEN_CANDIDATE_ID,
        "split_policy_version": SPLIT_POLICY_VERSION,
        "warmup": False,
        "warmup_reason": None,
        "fit_rows": binary_fit.height,
        "fit_blocks": len(split.fit_blocks),
        "validation_rows": binary_val.height,
        "validation_blocks": len(split.validation_blocks),
        "best_iteration": best_iteration,
        "final_refit_rounds": final_rounds,
        "early_stopping_status": early_status,
        "booster_fingerprint": encoder._booster_fingerprint(booster),  # noqa: SLF001
        "game_ids": list(current["game_id"].to_list()),
        "probabilities": probabilities,
        "categorical_vocabulary": {
            key: list(value) for key, value in encoder._categorical_vocab.items()  # noqa: SLF001
        },
        "outcomes_revealed": False,
    }


__all__ = ["predict_xgboost_block_v2"]
