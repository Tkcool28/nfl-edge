"""Season-generic prospective adapters for the frozen football model stack.

These functions intentionally mirror the accepted 2025 forward adapters while
removing only their hard-coded ``season == 2025`` guard. Candidate selection,
feature contracts, chronological fit/validation/refit behavior, and model math
remain imported from the frozen development/holdout implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Callable

import polars as pl

from nfl_edge.backtest.expected_margin_walk_forward import (
    _build_exposure_for_block as _em_exposure,
    _eligible_mapping_rows,
    _fit_block_model,
    _predict_block as _em_predict,
    _prior_completed_games,
    _prior_oos_for_mapping,
)
from nfl_edge.backtest.totals_bake_off import (
    MINIMUM_ELIGIBLE_PRIOR_ROWS,
    _pandas_predictors,
    build_candidate_model,
)
from nfl_edge.backtest.totals_walk_forward import IDENTITY_COLUMNS
from nfl_edge.backtest.walk_forward import (
    _build_exposure_for_block as _elo_exposure,
    _predict_block as _elo_predict,
)
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
from nfl_edge.features.totals_v1.feature_table import EXACT_90_COLUMNS
from nfl_edge.holdout.expected_margin_2025 import (
    FROZEN_CANDIDATE_ID as EXPECTED_MARGIN_CANDIDATE_ID,
    _assert_expected_margin_contract,
    _assert_score_schema,
)
from nfl_edge.holdout.totals_2025 import (
    FROZEN_ALPHA,
    FROZEN_CANDIDATE_ID as RIDGE_TOTALS_CANDIDATE_ID,
    FROZEN_DEVELOPMENT_SEASONS,
    _assert_frozen_model_contract,
)
from nfl_edge.holdout.xgboost_2025 import (
    FROZEN_CANDIDATE_ID as XGBOOST_CANDIDATE_ID,
    _assert_development_reference,
    _assert_feature_contract,
    _assert_frame_schema,
    _assert_frozen_categories,
    _block_key,
    _filter_keys,
)
from nfl_edge.models.expected_margin import (
    ExpectedMarginCandidateConfig,
    ExpectedMarginSharedConfig,
    FittedExpectedMargin,
    FittedMapping,
    fit_mapping,
    is_warmup_state,
)
from nfl_edge.models.qb_elo import (
    EloConfig,
    EloState,
    apply_season_carryover,
    ensure_team,
)

_ST_PRIORITY = {"PRE": 0, "REG": 1, "WC": 2, "DIV": 3, "CON": 4, "SB": 5}
_OUTCOME_COLUMNS = (
    "target_margin", "target_home_win", "target_tie", "target_total_points",
    "home_score", "away_score",
)


class LiveFootballContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class LiveBlock:
    block_id: str
    season: int
    season_type: str
    week: int
    as_of_utc: datetime
    game_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if int(self.season) < 2026:
            raise LiveFootballContractError("live scoring blocks must be season >= 2026")
        if str(self.season_type).upper() not in _ST_PRIORITY:
            raise LiveFootballContractError(f"unsupported season_type {self.season_type!r}")
        if int(self.week) < 1 or not self.game_ids:
            raise LiveFootballContractError("live block must have a positive week and games")
        if self.as_of_utc.tzinfo is None or self.as_of_utc.utcoffset() is None:
            raise LiveFootballContractError("live block cutoff must be timezone-aware")
        if tuple(sorted(set(self.game_ids))) != self.game_ids:
            raise LiveFootballContractError("live block game_ids must be sorted and unique")

    @property
    def order_key(self) -> tuple[int, int, int]:
        return (int(self.season), _ST_PRIORITY[str(self.season_type).upper()], int(self.week))


def _order_key(season: int, season_type: str, week: int) -> tuple[int, int, int]:
    st = str(season_type).upper()
    if st not in _ST_PRIORITY:
        raise LiveFootballContractError(f"unsupported season_type {season_type!r}")
    return (int(season), _ST_PRIORITY[st], int(week))


def assert_current_block_unrevealed(frame: pl.DataFrame, block: LiveBlock) -> pl.DataFrame:
    if frame.height == 0:
        raise LiveFootballContractError("current live block is empty")
    current = frame.filter(
        (pl.col("season") == block.season)
        & (pl.col("season_type").cast(pl.Utf8).str.to_uppercase() == block.season_type)
        & (pl.col("week") == block.week)
    ).sort("game_id")
    ids = tuple(sorted(str(x) for x in current["game_id"].to_list()))
    if ids != block.game_ids:
        raise LiveFootballContractError(
            f"live block identity mismatch: frame={ids} block={block.game_ids}"
        )
    if "target_available" in current.columns and bool(
        current["target_available"].fill_null(False).any()
    ):
        raise LiveFootballContractError("current live block outcome is marked available")
    for col in _OUTCOME_COLUMNS:
        if col in current.columns and current[col].null_count() != current.height:
            raise LiveFootballContractError(f"current live outcome leaked through {col}")
    return current


def assert_history_strictly_prior(history: pl.DataFrame, block: LiveBlock) -> None:
    if history.height == 0:
        return
    required = {"season", "season_type", "week"}
    missing = sorted(required - set(history.columns))
    if missing:
        raise LiveFootballContractError(f"history missing chronology columns: {missing}")
    for row in history.select("season", "season_type", "week").iter_rows(named=True):
        key = _order_key(int(row["season"]), str(row["season_type"]), int(row["week"]))
        if key >= block.order_key:
            raise LiveFootballContractError(
                f"history contains current/future block {key} for {block.order_key}"
            )
    if "target_available" in history.columns:
        recent = history.filter(pl.col("season") >= 2025)
        if recent.height and not bool(recent["target_available"].fill_null(False).all()):
            raise LiveFootballContractError("recent prior history contains unrevealed outcomes")


def build_live_block(current_games: pl.DataFrame) -> LiveBlock:
    required = {"game_id", "season", "season_type", "week", "prediction_as_of_utc"}
    missing = sorted(required - set(current_games.columns))
    if missing or current_games.height == 0:
        raise LiveFootballContractError(f"cannot build live block; missing={missing}")
    seasons = {int(x) for x in current_games["season"].unique().to_list()}
    types = {str(x).upper() for x in current_games["season_type"].unique().to_list()}
    weeks = {int(x) for x in current_games["week"].unique().to_list()}
    cutoffs = current_games["prediction_as_of_utc"].unique().to_list()
    if len(seasons) != 1 or len(types) != 1 or len(weeks) != 1 or len(cutoffs) != 1:
        raise LiveFootballContractError("live block identity/cutoff must be homogeneous")
    raw_cutoff = cutoffs[0]
    cutoff = raw_cutoff if isinstance(raw_cutoff, datetime) else datetime.fromisoformat(
        str(raw_cutoff).replace("Z", "+00:00")
    )
    season, season_type, week = next(iter(seasons)), next(iter(types)), next(iter(weeks))
    return LiveBlock(
        block_id=f"{season}_{season_type}_W{week:02d}",
        season=season,
        season_type=season_type,
        week=week,
        as_of_utc=cutoff.astimezone(timezone.utc),
        game_ids=tuple(sorted(str(x) for x in current_games["game_id"].to_list())),
    )


def predict_qb_elo_block(
    *, history_games: pl.DataFrame, current_games: pl.DataFrame, block: LiveBlock,
    state: EloState, config: EloConfig,
    qb_adjustment_resolver: Callable[[str], tuple[float, float]],
    run_id: str, model_version: str = "v1.0.0", created_at: datetime | None = None,
) -> dict[str, Any]:
    assert_history_strictly_prior(history_games, block)
    current = assert_current_block_unrevealed(current_games, block)
    prepared = state
    if prepared.current_season is not None and prepared.current_season < block.season:
        prepared = apply_season_carryover(prepared, new_season=block.season, config=config)
    elif prepared.current_season is not None and prepared.current_season > block.season:
        raise LiveFootballContractError("QB-Elo state is beyond current live season")
    for team in sorted(set(current["home_team"].to_list()) | set(current["away_team"].to_list())):
        prepared = ensure_team(prepared, str(team), config)
    combined = pl.concat([history_games, current_games], how="diagonal_relaxed")
    exposure = _elo_exposure(
        block_season=block.season, block_season_type=block.season_type,
        block_week=block.week, games=combined,
    )
    predictions, pregame_inputs = _elo_predict(
        block_games=current,
        block_id=block.block_id,
        block_as_of_utc=block.as_of_utc,
        state=prepared,
        elo_config=config,
        run_id=run_id,
        model_version=model_version,
        exposure=exposure,
        created_at=created_at or datetime.now(timezone.utc),
        qb_adjustment_resolver=qb_adjustment_resolver,
    )
    if any(bool(row.get("target_available")) for row in predictions):
        raise LiveFootballContractError("QB-Elo observed a current outcome")
    return {
        "block": block, "predictions": predictions, "pregame_inputs": pregame_inputs,
        "block_start_state": prepared, "outcomes_revealed": False,
    }


def predict_xgboost_v2_block(
    *, development_reference: pl.DataFrame, prior_history: pl.DataFrame,
    current_games: pl.DataFrame, block: LiveBlock, feature_cols: list[str],
) -> dict[str, Any]:
    _assert_feature_contract(feature_cols)
    _assert_frame_schema(development_reference, feature_cols, where="development_reference")
    _assert_frame_schema(prior_history, feature_cols, where="prior_history")
    _assert_frame_schema(current_games, feature_cols, where="current_games")
    _assert_development_reference(development_reference)
    assert_history_strictly_prior(prior_history, block)
    current = assert_current_block_unrevealed(current_games, block).sort(
        ["scheduled_start_utc", "game_id"]
    )
    if current["target_home_win"].null_count() != current.height:
        raise LiveFootballContractError("XGBoost current target_home_win must be null")
    encoder = WalkForwardEngine(development_reference, feature_cols, target_col="target_home_win")
    _assert_frozen_categories(encoder, prior_history, where="prior_history")
    _assert_frozen_categories(encoder, current, where="current_games")
    split = construct_adaptive_split(prior_history, _block_key(block), SHARED_SETTINGS)
    fit_df = _filter_keys(prior_history, split.fit_blocks)
    val_df = _filter_keys(prior_history, split.validation_blocks)
    warmup_reason = evaluate_warmup_reason(split, fit_df, val_df, SHARED_SETTINGS)
    if warmup_reason is not None:
        return {
            "block": block, "candidate_id": XGBOOST_CANDIDATE_ID,
            "split_policy_version": SPLIT_POLICY_VERSION, "warmup": True,
            "warmup_reason": warmup_reason, "fit_rows": fit_df.height,
            "fit_blocks": len(split.fit_blocks), "validation_rows": val_df.height,
            "validation_blocks": len(split.validation_blocks), "probabilities": [],
            "game_ids": list(current["game_id"].to_list()), "outcomes_revealed": False,
        }
    binary_fit = fit_df.filter(
        (pl.col("target_home_win") == 1) | (pl.col("target_home_win") == 0)
    ).select(feature_cols + ["target_home_win"])
    binary_val = val_df.filter(
        (pl.col("target_home_win") == 1) | (pl.col("target_home_win") == 0)
    ).select(feature_cols + ["target_home_win"])
    candidate = CANDIDATES[XGBOOST_CANDIDATE_ID]
    fit_dm = encoder._to_dmatrix(binary_fit, feature_cols, "target_home_win")  # noqa: SLF001
    val_dm = encoder._to_dmatrix(binary_val, feature_cols, "target_home_win")  # noqa: SLF001
    _, best_iteration, early_status = encoder._train_with_early_stopping(  # noqa: SLF001
        candidate, fit_dm, val_dm
    )
    rounds = best_iteration + 1
    combined = pl.concat([binary_fit, binary_val], how="vertical")
    booster = encoder._refit_full(  # noqa: SLF001
        candidate, encoder._to_dmatrix(combined, feature_cols, "target_home_win"), rounds
    )
    raw = booster.predict(encoder._predict_dmatrix(current, feature_cols))  # noqa: SLF001
    eps = SHARED_SETTINGS["probability_epsilon"]
    probabilities = [max(eps, min(1.0 - eps, float(p))) for p in raw]
    return {
        "block": block, "candidate_id": XGBOOST_CANDIDATE_ID,
        "split_policy_version": SPLIT_POLICY_VERSION, "warmup": False,
        "warmup_reason": None, "fit_rows": binary_fit.height,
        "fit_blocks": len(split.fit_blocks), "validation_rows": binary_val.height,
        "validation_blocks": len(split.validation_blocks), "best_iteration": best_iteration,
        "final_refit_rounds": rounds, "early_stopping_status": early_status,
        "booster_fingerprint": encoder._booster_fingerprint(booster),  # noqa: SLF001
        "game_ids": list(current["game_id"].to_list()), "probabilities": probabilities,
        "categorical_vocabulary": {
            key: list(value) for key, value in encoder._categorical_vocab.items()  # noqa: SLF001
        },
        "outcomes_revealed": False,
    }


def predict_expected_margin_block(
    *, history_games: pl.DataFrame, current_games: pl.DataFrame,
    prior_oos_predictions: list[dict[str, Any]], block: LiveBlock,
    candidate: ExpectedMarginCandidateConfig, shared: ExpectedMarginSharedConfig,
    run_id: str, model_version: str = "v1.0.0", created_at: datetime | None = None,
) -> dict[str, Any]:
    _assert_expected_margin_contract(candidate, shared)
    _assert_score_schema(history_games, where="history_games")
    _assert_score_schema(current_games, where="current_games")
    assert_history_strictly_prior(history_games, block)
    current = assert_current_block_unrevealed(current_games, block)
    combined = pl.concat([history_games, current_games], how="diagonal_relaxed")
    exposure = _em_exposure(block=block, games=combined)
    prior_completed = _prior_completed_games(combined, block)
    cutoff_iso = block.as_of_utc.isoformat().replace("+00:00", "Z")
    warmup = is_warmup_state(
        training_rows_available=int(prior_completed.height),
        minimum_training_games=int(shared.minimum_training_games),
    )
    if warmup:
        fitted = FittedExpectedMargin(
            train_rows=int(prior_completed.height), train_completed_rows=0, n_teams=0,
            team_index={}, offense_effect=(), defense_effect=(), home_field_effect=0.0,
            fitted_at_cutoff_utc=cutoff_iso, league_baseline=float(shared.league_baseline_prior),
        )
    else:
        fitted = _fit_block_model(
            prior_completed=prior_completed, candidate=candidate, shared=shared,
            cutoff_iso=cutoff_iso,
        )
    mapping_rows = _prior_oos_for_mapping(
        prior_oos_predictions=list(prior_oos_predictions), games=combined, block=block,
    )
    if warmup:
        mapping = FittedMapping(
            row_count=0, intercept=float("nan"), slope=float("nan"), fit_status="warmup",
            convergence_status="skipped_due_to_team_strength_warmup", cutoff_utc=cutoff_iso,
        )
    else:
        eligible = _eligible_mapping_rows(mapping_rows)
        margins = [float(row["expected_home_margin"]) for row in eligible]
        wins = [bool(row["actual_home_win"]) for row in eligible]
        if len(margins) < int(shared.minimum_mapping_rows):
            mapping = FittedMapping(
                row_count=len(margins), intercept=float("nan"), slope=float("nan"),
                fit_status="warmup", convergence_status="skipped_due_to_mapping_warmup",
                cutoff_utc=cutoff_iso,
            )
        else:
            mapping = fit_mapping(
                prior_oos_margins=margins, prior_oos_home_win=wins,
                intercept_l2_prior=shared.mapping_intercept_l2_prior,
                slope_l2_prior=shared.mapping_slope_l2_prior,
                intercept_l2_weight=candidate.mapping_intercept_l2_weight,
                slope_l2_weight=candidate.mapping_slope_l2_weight,
                tolerance=shared.mapping_solver_tolerance,
                max_iterations=shared.mapping_solver_max_iterations,
                cutoff_utc=cutoff_iso,
            )
    predictions = _em_predict(
        block=block, block_games=current, candidate=candidate, shared=shared,
        fitted=fitted, mapping=mapping, run_id=run_id, model_version=model_version,
        exposure=exposure, created_at=created_at or datetime.now(timezone.utc),
        team_strength_warmup=warmup,
    )
    if any(bool(row.get("target_available")) for row in predictions):
        raise LiveFootballContractError("Expected Margin observed a current outcome")
    return {
        "block": block, "candidate_id": EXPECTED_MARGIN_CANDIDATE_ID,
        "predictions": predictions, "fitted": fitted, "mapping": mapping,
        "exposure": exposure, "prior_completed_game_ids": tuple(
            str(x) for x in prior_completed["game_id"].to_list()
        ),
        "mapping_prior_rows": len(mapping_rows), "outcomes_revealed": False,
    }


def predict_ridge_totals_r4_block(
    *, prior_history: pl.DataFrame, current_games: pl.DataFrame, block: LiveBlock,
) -> dict[str, Any]:
    _assert_frozen_model_contract()
    required = set(IDENTITY_COLUMNS) | set(EXACT_90_COLUMNS) | {"target_total_points"}
    missing = sorted(required - set(prior_history.columns))
    if missing:
        raise LiveFootballContractError(f"prior totals history missing columns: {missing[:12]}")
    assert_history_strictly_prior(prior_history, block)
    if prior_history.height < MINIMUM_ELIGIBLE_PRIOR_ROWS:
        raise LiveFootballContractError("Ridge Totals R4 lacks minimum strictly-prior rows")
    development = prior_history.filter(pl.col("season") <= 2024)
    seasons = tuple(sorted({int(x) for x in development["season"].unique().to_list()}))
    if seasons != FROZEN_DEVELOPMENT_SEASONS:
        raise LiveFootballContractError(
            f"Ridge Totals development seasons drift: {seasons}"
        )
    target = prior_history["target_total_points"].cast(pl.Float64, strict=True)
    if target.null_count() or not all(isfinite(float(x)) for x in target.to_list()):
        raise LiveFootballContractError("Ridge Totals prior targets must be fully revealed finite values")
    current_missing = sorted((set(IDENTITY_COLUMNS) | set(EXACT_90_COLUMNS)) - set(current_games.columns))
    if current_missing:
        raise LiveFootballContractError(f"current totals surface missing columns: {current_missing[:12]}")
    current = assert_current_block_unrevealed(current_games, block)
    if "target_total_points" in current.columns and current["target_total_points"].null_count() != current.height:
        raise LiveFootballContractError("Ridge Totals current target leaked")
    training_x = _pandas_predictors(prior_history.select(list(EXACT_90_COLUMNS)), "ridge")
    current_x = _pandas_predictors(current.select(list(EXACT_90_COLUMNS)), "ridge")
    model = build_candidate_model(RIDGE_TOTALS_CANDIDATE_ID)
    model.fit(training_x, target.to_list())
    predictions = [float(x) for x in model.predict(current_x)]
    if len(predictions) != current.height or not all(isfinite(x) for x in predictions):
        raise LiveFootballContractError("Ridge Totals R4 produced malformed predictions")
    return {
        "block": block, "candidate_id": RIDGE_TOTALS_CANDIDATE_ID, "alpha": FROZEN_ALPHA,
        "fit_rows": prior_history.height, "game_ids": [str(x) for x in current["game_id"].to_list()],
        "predicted_totals": predictions, "outcomes_revealed": False,
    }
