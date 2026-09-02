"""Post-V5 XGBoost validation-tail successor policy.

The frozen V1 engine reserves exactly two prior chronological blocks for
validation.  That is leakage-safe but creates artificial Week 1/Week 2 cold
starts when the two immediately-prior blocks are tiny postseason rounds.

V2 preserves every frozen candidate parameter and training gate.  The only
change is validation-tail construction: walk backward through strictly-prior
blocks until the existing minimum validation row/block gates are satisfied,
while preserving the existing minimum fit row/block gates.

No current/future block is ever eligible for fit or validation, and no outcome
performance is consulted when choosing the tail.
"""
from __future__ import annotations

from typing import Any

import polars as pl

from nfl_edge.backtest.xgboost_walk_forward import (
    SHARED_SETTINGS,
    BlockKey,
    BlockSplit,
    compute_block_keys,
)

SPLIT_POLICY_VERSION = "ADAPTIVE_STRICT_PRIOR_VALIDATION_TAIL_V2"


def _key_tuple(key: BlockKey) -> tuple[int, str, int]:
    return (int(key.season), str(key.season_type), int(key.week))


def _row_counts(frame: pl.DataFrame) -> dict[tuple[int, str, int], int]:
    if frame.height == 0:
        return {}
    grouped = frame.group_by(["season", "season_type", "week"]).len()
    return {
        (int(row["season"]), str(row["season_type"]), int(row["week"])): int(row["len"])
        for row in grouped.iter_rows(named=True)
    }


def construct_adaptive_split(
    prior_history: pl.DataFrame,
    current_block: BlockKey,
    settings: dict[str, Any] | None = None,
) -> BlockSplit:
    """Build the smallest recent validation tail that satisfies frozen gates.

    The tail is contiguous in block chronology and contains only blocks
    strictly earlier than ``current_block``.  We expand backward until both
    validation gates are satisfied, but only while leaving enough strictly-
    prior rows/blocks for the frozen fit gates.

    If history is genuinely insufficient, the function returns the most recent
    deterministic reservation available and the unchanged V1 warm-up evaluator
    remains responsible for failing closed.
    """
    cfg = SHARED_SETTINGS if settings is None else settings
    min_val_blocks = int(cfg["min_validation_blocks"])
    min_val_rows = int(cfg["min_validation_rows"])
    min_fit_blocks = int(cfg["min_training_blocks"])
    min_fit_rows = int(cfg["min_training_rows"])

    all_keys = compute_block_keys(prior_history)
    prior_keys = [key for key in all_keys if key < current_block]
    counts = _row_counts(prior_history)

    if not prior_keys:
        return BlockSplit(fit_blocks=[], validation_blocks=[], current_block=current_block)

    validation: list[BlockKey] = []
    best_validation: list[BlockKey] = []

    for key in reversed(prior_keys):
        proposed = [key, *validation]
        remaining = prior_keys[: len(prior_keys) - len(proposed)]
        remaining_rows = sum(counts.get(_key_tuple(k), 0) for k in remaining)

        # Never consume history that is required by the unchanged fit gates.
        if len(remaining) < min_fit_blocks or remaining_rows < min_fit_rows:
            break

        validation = proposed
        best_validation = list(validation)
        validation_rows = sum(counts.get(_key_tuple(k), 0) for k in validation)
        if len(validation) >= min_val_blocks and validation_rows >= min_val_rows:
            return BlockSplit(
                fit_blocks=remaining,
                validation_blocks=validation,
                current_block=current_block,
            )

    # Genuine early-history insufficiency: return a deterministic split and let
    # the existing warm-up reason logic identify the failed gate.
    if best_validation:
        validation = best_validation
    else:
        validation = prior_keys[-min(min_val_blocks, len(prior_keys)) :]

    fit_blocks = prior_keys[: len(prior_keys) - len(validation)]
    return BlockSplit(
        fit_blocks=fit_blocks,
        validation_blocks=validation,
        current_block=current_block,
    )


__all__ = ["SPLIT_POLICY_VERSION", "construct_adaptive_split"]
