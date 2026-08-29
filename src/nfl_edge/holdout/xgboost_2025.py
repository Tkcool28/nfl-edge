"""Holdout-only adapter for the frozen chronology-corrected XGBoost V1.

The accepted development engine stays hard-sealed at 2024. This adapter
reuses its frozen candidate, split, early-stop, refit, DMatrix and fingerprint
implementation while allowing an already-authorized caller to predict one
2025 block.

Categorical encoding is frozen from the accepted 2018-2024 development
reference. Previously revealed 2025 rows may become training rows, but neither
they nor the current/future holdout may expand or reorder the vocabulary. An
unseen 2025 category fails closed.
"""
from __future__ import annotations

from typing import Any

import polars as pl

from nfl_edge.backtest.xgboost_walk_forward import (
    CANDIDATES,
    SHARED_SETTINGS,
    BlockKey,
    WalkForwardEngine,
    compute_block_keys,
    construct_split,
    evaluate_warmup_reason,
    feature_order_hash,
    parameter_hash,
    reject_market_columns,
    shared_settings_hash,
)

from .football_2025 import (
    HOLDOUT_SEASON,
    HoldoutBlock,
    HoldoutFootballContractError,
    assert_current_block_unrevealed,
    assert_history_strictly_prior,
)

FROZEN_CANDIDATE_ID = "conservative"
FROZEN_FEATURE_COUNT = 132
FROZEN_FEATURE_ORDER_HASH = "e33c5154a7ba3e9b89b8da55bf41dd6b8358b49b09baee14f0d9106c1cf4a09c"
FROZEN_SHARED_SETTINGS_HASH = "b1bf9d17f0747f264f4d6dfec3323133e753106009890224d79c7527d034cf97"
FROZEN_SELECTED_PARAM_HASH = "a044ba76fd138bde1a52e364fd7fce5de042a2ddfdb6cdac22e592d4819ed58b"
_REQUIRED_META = {
    "game_id",
    "season",
    "season_type",
    "week",
    "scheduled_start_utc",
    "target_home_win",
}


def _block_key(block: HoldoutBlock) -> BlockKey:
    priority = {"PRE": 0, "REG": 1, "WC": 2, "DIV": 3, "CON": 4, "SB": 5}
    if block.season_type not in priority:
        raise HoldoutFootballContractError(f"unsupported XGBoost season_type {block.season_type!r}")
    return BlockKey(
        season=block.season,
        season_type_priority=priority[block.season_type],
        season_type=block.season_type,
        week=block.week,
    )


def _assert_feature_contract(feature_cols: list[str]) -> None:
    if len(feature_cols) != FROZEN_FEATURE_COUNT:
        raise HoldoutFootballContractError(
            f"XGBoost holdout requires {FROZEN_FEATURE_COUNT} features: got {len(feature_cols)}"
        )
    got = feature_order_hash(feature_cols)
    if got != FROZEN_FEATURE_ORDER_HASH:
        raise HoldoutFootballContractError(
            f"XGBoost feature order drift: {got} != {FROZEN_FEATURE_ORDER_HASH}"
        )
    if shared_settings_hash() != FROZEN_SHARED_SETTINGS_HASH:
        raise HoldoutFootballContractError("XGBoost shared settings drift")
    candidate = CANDIDATES[FROZEN_CANDIDATE_ID]
    authority_payload = {
        "colsample_bytree": candidate.colsample_bytree,
        "gamma": candidate.gamma,
        "learning_rate": candidate.learning_rate,
        "max_delta_step": candidate.max_delta_step,
        "max_depth": candidate.max_depth,
        "min_child_weight": candidate.min_child_weight,
        "reg_alpha": candidate.reg_alpha,
        "reg_lambda": candidate.reg_lambda,
        "subsample": candidate.subsample,
    }
    if parameter_hash(authority_payload) != FROZEN_SELECTED_PARAM_HASH:
        raise HoldoutFootballContractError("XGBoost conservative candidate parameter drift")


def _assert_frame_schema(frame: pl.DataFrame, feature_cols: list[str], *, where: str) -> None:
    missing = sorted((_REQUIRED_META | set(feature_cols)) - set(frame.columns))
    if missing:
        raise HoldoutFootballContractError(f"{where} missing XGBoost columns: {missing[:12]}")
    reject_market_columns(list(frame.columns))


def _assert_development_reference(frame: pl.DataFrame) -> None:
    if frame.height == 0:
        raise HoldoutFootballContractError("XGBoost development reference is empty")
    seasons = sorted({int(x) for x in frame["season"].unique().to_list()})
    if not seasons or min(seasons) < 2018 or max(seasons) > 2024:
        raise HoldoutFootballContractError(
            f"XGBoost vocabulary reference must be 2018-2024 only: {seasons}"
        )


def _assert_frozen_categories(engine: WalkForwardEngine, frame: pl.DataFrame, *, where: str) -> None:
    for col, vocab in engine._categorical_vocab.items():  # noqa: SLF001
        observed = set(frame[col].drop_nulls().unique().to_list())
        unseen = sorted(observed - set(vocab))
        if unseen:
            raise HoldoutFootballContractError(
                f"{where} contains unseen XGBoost category for {col}: {unseen}"
            )


def _filter_keys(frame: pl.DataFrame, keys: list[BlockKey]) -> pl.DataFrame:
    tuples = [(k.season, k.season_type, k.week) for k in keys]
    return WalkForwardEngine._filter_by_keys(frame, tuples)  # noqa: SLF001


def predict_xgboost_block(
    *,
    development_reference: pl.DataFrame,
    prior_history: pl.DataFrame,
    current_games: pl.DataFrame,
    block: HoldoutBlock,
    feature_cols: list[str],
) -> dict[str, Any]:
    """Fit from strictly-prior rows and predict one sealed 2025 block."""
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
            f"XGBoost block game identity mismatch: frame={ids} block={block.game_ids}"
        )
    if current["target_home_win"].null_count() != current.height:
        raise HoldoutFootballContractError("XGBoost current target_home_win must be null")

    encoder = WalkForwardEngine(
        development_reference,
        feature_cols,
        target_col="target_home_win",
    )
    _assert_frozen_categories(encoder, prior_history, where="prior_history")
    _assert_frozen_categories(encoder, current, where="current_games")

    current_key = _block_key(block)
    prior_keys = compute_block_keys(prior_history)
    split = construct_split(prior_keys, current_key)
    fit_df = _filter_keys(prior_history, split.fit_blocks)
    val_df = _filter_keys(prior_history, split.validation_blocks)
    warmup_reason = evaluate_warmup_reason(split, fit_df, val_df, SHARED_SETTINGS)
    if warmup_reason is not None:
        return {
            "block": block,
            "candidate_id": FROZEN_CANDIDATE_ID,
            "warmup": True,
            "warmup_reason": warmup_reason,
            "fit_rows": fit_df.height,
            "validation_rows": val_df.height,
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
