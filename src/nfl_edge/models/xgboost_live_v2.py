"""Season-agnostic live XGBoost V2 prediction path.

This is the launch-facing successor to the frozen 2025 holdout adapter. It
preserves the accepted conservative XGBoost V1 model/feature contract and uses
the adaptive strictly-prior validation tail from ``xgboost_walk_forward_v2``.

The categorical vocabulary remains frozen from the accepted 2018-2024
reference. Prior settled seasons (including 2025 after the holdout is exposed)
may be training history, but current/future rows may never enter fit or
validation.
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
    _filter_keys,
)

_SEASON_TYPE_PRIORITY = {"PRE": 0, "REG": 1, "WC": 2, "DIV": 3, "CON": 4, "SB": 5}
_OUTCOME_COLUMNS = ("target_margin", "target_home_win", "home_score", "away_score")


class XGBoostLiveContractError(RuntimeError):
    """Raised before prediction when the live V2 chronology contract is violated."""


def _block_key(season: int, season_type: str, week: int) -> BlockKey:
    st = str(season_type).upper()
    if st not in _SEASON_TYPE_PRIORITY:
        raise XGBoostLiveContractError(f"unsupported XGBoost season_type {season_type!r}")
    return BlockKey(
        season=int(season),
        season_type_priority=_SEASON_TYPE_PRIORITY[st],
        season_type=st,
        week=int(week),
    )


def _assert_current_unrevealed(current: pl.DataFrame, current_key: BlockKey) -> None:
    if current.height == 0:
        raise XGBoostLiveContractError("current XGBoost block is empty")
    keys = compute_block_keys(current)
    if keys != [current_key]:
        raise XGBoostLiveContractError(
            f"current frame must contain exactly one requested block: {keys} != {[current_key]}"
        )
    if current["game_id"].null_count() or current["game_id"].n_unique() != current.height:
        raise XGBoostLiveContractError("current XGBoost game_id must be non-null and unique")
    if current["target_home_win"].null_count() != current.height:
        raise XGBoostLiveContractError("current XGBoost target_home_win must be null")
    for col in _OUTCOME_COLUMNS:
        if col in current.columns and current[col].null_count() != current.height:
            raise XGBoostLiveContractError(
                f"current XGBoost outcome field is non-null before prediction: {col}"
            )


def _assert_history_prior(prior_history: pl.DataFrame, current_key: BlockKey) -> None:
    future_or_current = [key for key in compute_block_keys(prior_history) if not key < current_key]
    if future_or_current:
        raise XGBoostLiveContractError(
            f"XGBoost prior history contains current/future blocks: {future_or_current[:5]}"
        )


def predict_xgboost_live_block_v2(
    *,
    development_reference: pl.DataFrame,
    prior_history: pl.DataFrame,
    current_games: pl.DataFrame,
    season: int,
    season_type: str,
    week: int,
    feature_cols: list[str],
) -> dict[str, Any]:
    """Predict one live block with the V2 adaptive strictly-prior split."""
    try:
        _assert_feature_contract(feature_cols)
        _assert_frame_schema(development_reference, feature_cols, where="development_reference")
        _assert_frame_schema(prior_history, feature_cols, where="prior_history")
        _assert_frame_schema(current_games, feature_cols, where="current_games")
        _assert_development_reference(development_reference)
    except RuntimeError as exc:
        raise XGBoostLiveContractError(str(exc)) from exc

    current_key = _block_key(season, season_type, week)
    current = current_games.filter(
        (pl.col("season") == int(season))
        & (pl.col("season_type") == str(season_type).upper())
        & (pl.col("week") == int(week))
    ).sort(["scheduled_start_utc", "game_id"])
    _assert_current_unrevealed(current, current_key)
    _assert_history_prior(prior_history, current_key)

    encoder = WalkForwardEngine(
        development_reference,
        feature_cols,
        target_col="target_home_win",
    )
    try:
        _assert_frozen_categories(encoder, prior_history, where="prior_history")
        _assert_frozen_categories(encoder, current, where="current_games")
    except RuntimeError as exc:
        raise XGBoostLiveContractError(str(exc)) from exc

    split = construct_adaptive_split(prior_history, current_key, SHARED_SETTINGS)
    fit_df = _filter_keys(prior_history, split.fit_blocks)
    val_df = _filter_keys(prior_history, split.validation_blocks)
    warmup_reason = evaluate_warmup_reason(split, fit_df, val_df, SHARED_SETTINGS)
    if warmup_reason is not None:
        return {
            "season": int(season),
            "season_type": str(season_type).upper(),
            "week": int(week),
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
        "season": int(season),
        "season_type": str(season_type).upper(),
        "week": int(week),
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


__all__ = ["SPLIT_POLICY_VERSION", "XGBoostLiveContractError", "predict_xgboost_live_block_v2"]
