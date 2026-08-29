"""Holdout-only Expected Margin V1 block adapter for the sealed 2025 walkthrough.

This module does not read 2025 files and does not authorize the holdout.  An
already-authorized caller must supply the current block plus strictly-prior
history.  The accepted Expected Margin V1 mathematics are reused directly;
the development loader and its 2024 firewall remain unchanged.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import polars as pl

from nfl_edge.backtest.expected_margin_walk_forward import (
    _build_exposure_for_block,
    _eligible_mapping_rows,
    _fit_block_model,
    _predict_block,
    _prior_completed_games,
    _prior_oos_for_mapping,
)
from nfl_edge.models.expected_margin import (
    ExpectedMarginCandidateConfig,
    ExpectedMarginSharedConfig,
    FittedExpectedMargin,
    FittedMapping,
    fit_mapping,
    is_warmup_state,
)

from .football_2025 import (
    HOLDOUT_SEASON,
    HoldoutBlock,
    HoldoutFootballContractError,
    assert_current_block_unrevealed,
    assert_history_strictly_prior,
)

FROZEN_CANDIDATE_ID = "stable"
FROZEN_DEVELOPMENT_MAX = 2024
_REQUIRED_SCORE_COLUMNS = {
    "game_id",
    "season",
    "season_type",
    "week",
    "prediction_as_of_utc",
    "home_team",
    "away_team",
    "neutral_site",
    "target_available",
    "home_score",
    "away_score",
    "target_margin",
    "target_home_win",
    "target_tie",
}


def _assert_expected_margin_contract(
    candidate: ExpectedMarginCandidateConfig,
    shared: ExpectedMarginSharedConfig,
) -> None:
    if candidate.id != FROZEN_CANDIDATE_ID:
        raise HoldoutFootballContractError(
            f"Expected Margin holdout candidate must be {FROZEN_CANDIDATE_ID!r}: {candidate.id!r}"
        )
    if int(shared.maximum_development_season) != FROZEN_DEVELOPMENT_MAX:
        raise HoldoutFootballContractError(
            "Expected Margin frozen development maximum changed; holdout adapter refuses to run"
        )


def _assert_score_schema(frame: pl.DataFrame, *, where: str) -> None:
    missing = sorted(_REQUIRED_SCORE_COLUMNS - set(frame.columns))
    if missing:
        raise HoldoutFootballContractError(f"{where} missing Expected Margin columns: {missing}")


def _block_frame(frame: pl.DataFrame, block: HoldoutBlock) -> pl.DataFrame:
    selected = frame.filter(
        (pl.col("season") == HOLDOUT_SEASON)
        & (pl.col("season_type").cast(pl.Utf8).str.to_uppercase() == block.season_type)
        & (pl.col("week") == block.week)
    ).sort("game_id")
    ids = tuple(sorted(str(x) for x in selected["game_id"].to_list()))
    if ids != block.game_ids:
        raise HoldoutFootballContractError(
            f"Expected Margin block game identity mismatch: frame={ids} block={block.game_ids}"
        )
    return selected


def predict_expected_margin_block(
    *,
    history_games: pl.DataFrame,
    current_games: pl.DataFrame,
    prior_oos_predictions: list[dict[str, Any]],
    block: HoldoutBlock,
    candidate: ExpectedMarginCandidateConfig,
    shared: ExpectedMarginSharedConfig,
    run_id: str,
    model_version: str = "v1.0.0",
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Predict one 2025 block with frozen Expected Margin V1 stable semantics.

    ``history_games`` may contain development history and previously revealed
    2025 blocks only.  ``current_games`` must contain no current outcome.  The
    probability mapping may use only prior OOS rows whose outcomes are already
    available in that strictly-prior history.
    """
    _assert_expected_margin_contract(candidate, shared)
    _assert_score_schema(history_games, where="history_games")
    _assert_score_schema(current_games, where="current_games")
    assert_history_strictly_prior(history_games, block)
    assert_current_block_unrevealed(current_games)
    block_games = _block_frame(current_games, block)

    combined = pl.concat([history_games, current_games], how="diagonal_relaxed")
    exposure = _build_exposure_for_block(block=block, games=combined)
    prior_completed = _prior_completed_games(combined, block)
    cutoff_iso = block.as_of_utc.isoformat().replace("+00:00", "Z")

    team_strength_warmup = is_warmup_state(
        training_rows_available=int(prior_completed.height),
        minimum_training_games=int(shared.minimum_training_games),
    )
    if team_strength_warmup:
        fitted = FittedExpectedMargin(
            train_rows=int(prior_completed.height),
            train_completed_rows=0,
            n_teams=0,
            team_index={},
            offense_effect=(),
            defense_effect=(),
            home_field_effect=0.0,
            fitted_at_cutoff_utc=cutoff_iso,
            league_baseline=float(shared.league_baseline_prior),
        )
    else:
        fitted = _fit_block_model(
            prior_completed=prior_completed,
            candidate=candidate,
            shared=shared,
            cutoff_iso=cutoff_iso,
        )

    prior_mapping_rows = _prior_oos_for_mapping(
        prior_oos_predictions=list(prior_oos_predictions),
        games=combined,
        block=block,
    )
    if team_strength_warmup:
        mapping = FittedMapping(
            row_count=0,
            intercept=float("nan"),
            slope=float("nan"),
            fit_status="warmup",
            convergence_status="skipped_due_to_team_strength_warmup",
            cutoff_utc=cutoff_iso,
        )
    else:
        eligible = _eligible_mapping_rows(prior_mapping_rows)
        margins = [float(row["expected_home_margin"]) for row in eligible]
        wins = [bool(row["actual_home_win"]) for row in eligible]
        if len(margins) < int(shared.minimum_mapping_rows):
            mapping = FittedMapping(
                row_count=len(margins),
                intercept=float("nan"),
                slope=float("nan"),
                fit_status="warmup",
                convergence_status="skipped_due_to_mapping_warmup",
                cutoff_utc=cutoff_iso,
            )
        else:
            mapping = fit_mapping(
                prior_oos_margins=margins,
                prior_oos_home_win=wins,
                intercept_l2_prior=shared.mapping_intercept_l2_prior,
                slope_l2_prior=shared.mapping_slope_l2_prior,
                intercept_l2_weight=candidate.mapping_intercept_l2_weight,
                slope_l2_weight=candidate.mapping_slope_l2_weight,
                tolerance=shared.mapping_solver_tolerance,
                max_iterations=shared.mapping_solver_max_iterations,
                cutoff_utc=cutoff_iso,
            )

    predictions = _predict_block(
        block=block,
        block_games=block_games,
        candidate=candidate,
        shared=shared,
        fitted=fitted,
        mapping=mapping,
        run_id=run_id,
        model_version=model_version,
        exposure=exposure,
        created_at=created_at or datetime.now(timezone.utc),
        team_strength_warmup=team_strength_warmup,
    )
    if any(bool(row.get("target_available")) for row in predictions):
        raise HoldoutFootballContractError(
            "Expected Margin predictor observed a current-block outcome"
        )
    if any(row.get("actual_margin") is not None for row in predictions):
        raise HoldoutFootballContractError(
            "Expected Margin predictor emitted current-block actual margin"
        )

    return {
        "block": block,
        "candidate_id": candidate.id,
        "predictions": predictions,
        "fitted": fitted,
        "mapping": mapping,
        "exposure": exposure,
        "prior_completed_game_ids": tuple(
            str(x) for x in prior_completed["game_id"].to_list()
        ),
        "mapping_prior_rows": len(prior_mapping_rows),
        "outcomes_revealed": False,
    }
