"""Expected-Margin v1 walk-forward engine.

A separate development walk-forward path for Base Model C
(docs/model_contract.md). The engine does NOT touch the QB-Elo
walk-forward in ``src/nfl_edge/backtest/walk_forward.py``; it
reuses ONLY the shared block scheduling primitives exported from
``src/nfl_edge/backtest/blocks.py`` (i.e. ``build_development_blocks``
and the canonical holdout guard ``assert_development_seasons_only``).

For each block (chronological ``(season, season_type, week)``):

1. The current block's games are completely held out. The engine
   trains the team-effects ridge regression using only completed
   games whose block ordering places them strictly before the
   current block. No completed game's outcome can influence the
   prediction of any game in the current block.
2. The fitted model is **frozen** for the entire current block.
   No parameter mutation is permitted during this pass.
3. The mapping layer is fit on prior OOS expected-margin
   predictions whose actual outcomes became available strictly
   before the current block cutoff. The current block is
   excluded from the mapping fit. The mapping is the sole
   probability layer; no second calibration is applied.
4. Warm-up states are explicitly recorded:

   - Team-strength warm-up: when fewer than
     ``shared.minimum_training_games`` completed games are
     available before the block cutoff, the engine records an
     explicit ``warmup_state = "prior_games_warmup"`` and emits
     no numeric expected margin.
   - Mapping warm-up: when fewer than
     ``shared.minimum_mapping_rows`` eligible prior OOS rows are
     available, the engine records ``mapping_warmup = true`` and
     the official home-win probability is unavailable.

The engine never produces a fallback probability. If the team
strengths are warm-up, the official probability is null. If the
team strengths are fit but the mapping is warm-up, the official
probability is null. If the mapping fit rejects a non-positive
slope, the official probability is null and the row is excluded
from the scorecard's probability scoring.

The engine never reads market data, never writes the QB-Elo
artifacts, and never accesses the 2025 sealed holdout or the
2026 forward-use season. Both seasons are rejected at the boundary.

Chronological ordering:

The recency weight depends on the chronological ordering of the
prior completed games. The order is established by the caller's
block ordering and the within-block ``prediction_as_of_utc`` (UTC
timezone-aware). ``game_id`` is used only as a final tie-breaker
within a single block. The age of each prior completed game is the
count of completed games that finished strictly before it in the
chronological order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from ..common.errors import (
    SealedHoldoutAccessError,
    WalkForwardError,
)
from ..common.polars_utils import assert_no_market_columns
from ..models.expected_margin import (
    ExpectedMarginCandidateConfig,
    ExpectedMarginSharedConfig,
    FittedExpectedMargin,
    FittedMapping,
    fit_expected_margin,
    fit_mapping,
    is_mapping_available,
    is_warmup_state,
    predict_home_win_probability,
)
from .blocks import (
    DEVELOPMENT_SEASON_MAX,
    FORWARD_USE_SEASON,
    SEALED_HOLDOUT_SEASON,
    PredictionBlock,
    assert_development_seasons_only,
    build_development_blocks,
)

# Required columns of the input game features parquet. The
# Expected-Margin model requires the actual home and away points
# (separately, not just the margin) plus the same block-contract
# fields used by the QB-Elo baseline.
_REQUIRED_GAME_COLUMNS: tuple[str, ...] = (
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
)


@dataclass(frozen=True)
class ExpectedMarginPrediction:
    """One prediction row for the Expected-Margin candidate."""

    prediction_id: str
    candidate_id: str
    run_id: str
    game_id: str
    season: int
    season_type: str
    week: int
    as_of_utc: str
    prediction_block_id: str
    home_team: str
    away_team: str
    neutral_site: bool
    home_offs_strength: float
    away_offs_strength: float
    home_def_strength: float
    away_def_strength: float
    home_field_effect: float
    league_baseline: float
    expected_home_points: float
    expected_away_points: float
    expected_home_margin: float
    expected_home_margin_available: bool
    warmup_state: str  # "ready" | "prior_games_warmup"
    training_rows_available_before_block: int
    training_completed_rows_before_block: int
    training_block_count: int
    prior_completed_games_count: int
    mapping_row_count: int
    mapping_intercept: float
    mapping_slope: float
    # "converged" | "warmup" | "rejected_nonpositive_slope" |
    # "singular" | "max_iterations_reached"
    mapping_fit_status: str
    mapping_convergence_status: str
    mapping_cutoff_utc: str
    mapping_warmup: bool
    mapping_rejected_nonpositive_slope: bool
    predicted_home_win_probability: float | None
    probability_available: bool
    target_available: bool
    actual_margin: float | None
    actual_home_win: bool | None
    actual_tie: bool
    is_binary_scored: bool
    created_at_utc: str


# ---------------------------------------------------------------------------
# Chronological ordering helpers
# ---------------------------------------------------------------------------


_ST_PRIORITY: dict[str, int] = {"REG": 0, "WC": 1, "DIV": 2, "CON": 3, "SB": 4}


def _season_type_priority(season_type: str) -> int:
    return _ST_PRIORITY.get(str(season_type).upper(), 99)


def _block_order_key(season: int, season_type: str, week: int) -> tuple[int, int, int]:
    """Block-ordering key: (season, season_type_priority, week)."""
    return (int(season), _season_type_priority(season_type), int(week))


def _chronological_age_per_row(
    prior_completed: pl.DataFrame,
) -> list[float]:
    """Return per-row chronological age in completed games.

    The age of each prior completed game is the count of completed
    games that finished strictly before it in the deterministic
    chronological order. The order is:

    1. ``prediction_as_of_utc`` (UTC timezone-aware primary key)
    2. ``game_id`` (lexicographic tie-breaker)

    The frame is sorted by these two keys. The age of row ``i`` in
    the sorted frame is exactly ``i`` because rows 0..i-1 are
    strictly older.

    The age is NEVER computed from game_id order alone and NEVER
    from numeric ``season, week`` alone — both are insufficient
    because games within the same block can be chronologically
    out of order relative to a lexical game_id sort.
    """
    if prior_completed.height == 0:
        return []
    # Sort by prediction_as_of_utc (UTC) then by game_id as a
    # deterministic tie-breaker.
    sorted_frame = prior_completed.sort(
        ["prediction_as_of_utc", "game_id"]
    )
    return [float(i) for i in range(sorted_frame.height)]


def _load_games(path: str | Path) -> pl.DataFrame:
    """Load and validate the game features parquet.

    Filters to the development window (``season <= 2024``) and
    performs an explicit assert_development_seasons_only guard so a
    2025 or 2026 row that slipped past the filter will trip the
    tripwire.
    """
    p = Path(path)
    frame = pl.read_parquet(p)
    if frame.height == 0:
        raise WalkForwardError("expected_margin_walk_forward", "empty games file")
    missing = sorted(set(_REQUIRED_GAME_COLUMNS) - set(frame.columns))
    if missing:
        raise WalkForwardError(
            "expected_margin_walk_forward",
            f"missing required columns: {missing}",
        )
    # Market-guard: the input frame must not contain any market column.
    assert_no_market_columns(frame)
    # Hard reject any row whose season is greater than the development
    # maximum. We reject 2025 and 2026 explicitly here, before any
    # block scheduling.
    if int(frame["season"].max()) > DEVELOPMENT_SEASON_MAX:
        bad = frame.filter(pl.col("season") > DEVELOPMENT_SEASON_MAX)
        bad_seasons = sorted(set(int(s) for s in bad["season"].unique().to_list()))
        for s in bad_seasons:
            if s == SEALED_HOLDOUT_SEASON:
                raise SealedHoldoutAccessError(
                    s,
                    "expected_margin_walk_forward._load_games",
                    "input frame contains 2025 sealed holdout rows",
                )
            if s == FORWARD_USE_SEASON:
                raise WalkForwardError(
                    "expected_margin_walk_forward._load_games",
                    "input frame contains 2026 forward-use rows",
                )
            raise WalkForwardError(
                "expected_margin_walk_forward._load_games",
                f"input frame contains unsupported season {s} > {DEVELOPMENT_SEASON_MAX}",
            )
    assert_development_seasons_only(frame)
    return frame


def _build_exposure_for_block(
    *, block: PredictionBlock, games: pl.DataFrame
) -> dict[str, int]:
    """Return truthful prior-state-exposure metadata for the block."""
    current_key = _block_order_key(block.season, block.season_type, block.week)
    games_sorted = games.with_columns(
        [
            pl.col("season_type")
            .map_elements(_season_type_priority)
            .alias("_st_priority")
        ]
    )
    prior = games_sorted.filter(
        (pl.col("season") < current_key[0])
        | (
            (pl.col("season") == current_key[0])
            & (pl.col("_st_priority") < current_key[1])
        )
        | (
            (pl.col("season") == current_key[0])
            & (pl.col("_st_priority") == current_key[1])
            & (pl.col("week") < current_key[2])
        )
    )
    n_rows = int(prior.height)
    n_completed = int(prior.filter(pl.col("target_available") == True).height)  # noqa: E712
    n_blocks = (
        int(
            prior.select(
                (pl.col("season").cast(pl.Utf8) + pl.lit("|")
                 + pl.col("season_type") + pl.lit("|")
                 + pl.col("week").cast(pl.Utf8))
                .n_unique()
            ).item()
        )
        if n_rows > 0
        else 0
    )
    return {
        "training_rows_available_before_block": n_rows,
        "training_completed_rows_before_block": n_completed,
        "training_block_count": n_blocks,
        "prior_completed_games_count": n_completed,
    }


def _prior_completed_games(
    games: pl.DataFrame, block: PredictionBlock
) -> pl.DataFrame:
    """Strictly prior completed games, sorted deterministically.

    A row is "prior completed" if ``target_available`` is true and
    its block ordering places it strictly before ``block``. The
    returned frame is sorted by the canonical chronological order
    (prediction_as_of_utc, game_id) so the model receives a fully
    deterministic chronological sequence.
    """
    current_key = _block_order_key(block.season, block.season_type, block.week)
    games_sorted = games.with_columns(
        [
            pl.col("season_type")
            .map_elements(_season_type_priority)
            .alias("_st_priority")
        ]
    )
    prior = games_sorted.filter(
        (pl.col("target_available") == True)  # noqa: E712
        & (
            (pl.col("season") < current_key[0])
            | (
                (pl.col("season") == current_key[0])
                & (pl.col("_st_priority") < current_key[1])
            )
            | (
                (pl.col("season") == current_key[0])
                & (pl.col("_st_priority") == current_key[1])
                & (pl.col("week") < current_key[2])
            )
        )
    ).sort(["prediction_as_of_utc", "game_id"])
    return prior


def _prior_oos_for_mapping(
    *,
    prior_oos_predictions: list[dict[str, Any]],
    games: pl.DataFrame,
    block: PredictionBlock,
) -> list[dict[str, Any]]:
    """Filter the prior OOS ledger to rows whose outcome was available
    strictly before the current block.
    """
    current_key = _block_order_key(block.season, block.season_type, block.week)
    available: list[dict[str, Any]] = []
    for row in prior_oos_predictions:
        game_id = str(row["game_id"])
        if int(row["season"]) > current_key[0]:
            continue
        if int(row["season"]) == current_key[0]:
            st = _season_type_priority(str(row["season_type"]))
            if st > current_key[1]:
                continue
            if st == current_key[1] and int(row["week"]) >= current_key[2]:
                continue
        outcome = games.filter(pl.col("game_id") == game_id)
        if outcome.height == 0:
            continue
        if not bool(outcome["target_available"].item()):
            continue
        available.append(row)
    return available


def _fit_block_model(
    *,
    prior_completed: pl.DataFrame,
    candidate: ExpectedMarginCandidateConfig,
    shared: ExpectedMarginSharedConfig,
    cutoff_iso: str,
) -> FittedExpectedMargin:
    """Fit the team-effects ridge regression on the prior slice.

    The recency weight is computed by ``_chronological_age_per_row``
    against the canonical chronological order; the input frame is
    sorted by ``prediction_as_of_utc`` then ``game_id`` so the
    indices returned by ``_chronological_age_per_row`` align row-
    for-row with the frame.
    """
    home_teams = [str(t) for t in prior_completed["home_team"].to_list()]
    away_teams = [str(t) for t in prior_completed["away_team"].to_list()]
    home_points = [float(p) for p in prior_completed["home_score"].to_list()]
    away_points = [float(p) for p in prior_completed["away_score"].to_list()]
    neutrals = [bool(n) for n in prior_completed["neutral_site"].to_list()]
    ages = _chronological_age_per_row(prior_completed)
    prior_training_games = [{} for _ in range(len(home_teams))]
    return fit_expected_margin(
        prior_training_games=prior_training_games,
        home_points=home_points,
        away_points=away_points,
        neutral_site=neutrals,
        home_team_codes=home_teams,
        away_team_codes=away_teams,
        chronological_age_in_completed_games=ages,
        candidate=candidate,
        shared=shared,
        fitted_at_cutoff_utc=cutoff_iso,
    )


def _predict_block(
    *,
    block: PredictionBlock,
    block_games: pl.DataFrame,
    candidate: ExpectedMarginCandidateConfig,
    shared: ExpectedMarginSharedConfig,
    fitted: FittedExpectedMargin,
    mapping: FittedMapping,
    run_id: str,
    model_version: str,
    exposure: dict[str, int],
    created_at: datetime,
    team_strength_warmup: bool,
) -> list[dict[str, Any]]:
    """Predict every game in the block from the frozen model.

    The block is sorted deterministically by ``game_id`` for the
    within-block ordering so the prediction_id is deterministic.
    The model and mapping are frozen for the entire block.

    A duplicate ``game_id`` within the block is rejected before any
    prediction row is written. This guards the ``prediction_id``
    uniqueness invariant that the prediction ledger requires.
    """
    block_dicts = sorted(block_games.to_dicts(), key=lambda r: str(r["game_id"]))
    seen_game_ids: set[str] = set()
    duplicate_game_ids: list[str] = []
    for row in block_dicts:
        gid = str(row["game_id"])
        if gid in seen_game_ids:
            duplicate_game_ids.append(gid)
        seen_game_ids.add(gid)
    if duplicate_game_ids:
        raise WalkForwardError(
            "expected_margin_walk_forward._predict_block",
            "duplicate game_id in block "
            f"{block.block_id}: {sorted(duplicate_game_ids)[:5]}",
        )
    predictions: list[dict[str, Any]] = []
    for row in block_dicts:
        game_id = str(row["game_id"])
        home_team = str(row["home_team"])
        away_team = str(row["away_team"])
        neutral_site = bool(row.get("neutral_site", False))
        season = int(row["season"])
        season_type = str(row["season_type"])
        week = int(row["week"])
        target_margin_val = row.get("target_margin")
        target_available = target_margin_val is not None
        if target_available:
            actual_margin: float | None = float(target_margin_val)
            if actual_margin == 0:
                actual_home_win: bool | None = None
                actual_tie = True
            else:
                actual_home_win = bool(actual_margin > 0)
                actual_tie = False
        else:
            actual_margin = None
            actual_home_win = None
            actual_tie = False
        is_binary_scored = bool(target_available and not actual_tie)

        home_off = float(fitted._offense(home_team))  # noqa: SLF001
        home_def = float(fitted._defense(home_team))  # noqa: SLF001
        away_off = float(fitted._offense(away_team))  # noqa: SLF001
        away_def = float(fitted._defense(away_team))  # noqa: SLF001

        if team_strength_warmup:
            expected_home_points = float("nan")
            expected_away_points = float("nan")
            expected_home_margin = float("nan")
            expected_margin_available = False
        else:
            expected_home_points = fitted.expected_home_points(
                home_team, away_team, neutral_site
            )
            expected_away_points = fitted.expected_away_points(
                home_team, away_team, neutral_site
            )
            expected_home_margin = expected_home_points - expected_away_points
            expected_margin_available = True

        # Mapping application.
        mapping_warmup = (
            not is_mapping_available(mapping)
            or mapping.fit_status == "warmup"
        )
        mapping_rejected = mapping.fit_status == "rejected_nonpositive_slope"
        if mapping_warmup or mapping_rejected or team_strength_warmup:
            predicted_probability: float | None = None
            probability_available = False
        else:
            predicted_probability = predict_home_win_probability(
                mapping,
                expected_home_margin,
                probability_min=shared.probability_min,
                probability_max=shared.probability_max,
                apply_clipping=shared.apply_probability_clipping,
            )
            probability_available = True

        predictions.append(
            {
                "prediction_id": f"{run_id}:{candidate.id}:{game_id}",
                "candidate_id": candidate.id,
                "run_id": run_id,
                "game_id": game_id,
                "season": season,
                "season_type": season_type,
                "week": week,
                "as_of_utc": block.as_of_utc.isoformat().replace("+00:00", "Z"),
                "prediction_block_id": block.block_id,
                "home_team": home_team,
                "away_team": away_team,
                "neutral_site": neutral_site,
                "home_offs_strength": home_off,
                "away_offs_strength": away_off,
                "home_def_strength": home_def,
                "away_def_strength": away_def,
                "home_field_effect": float(fitted.home_field_effect),
                "league_baseline": float(fitted.league_baseline),
                "expected_home_points": expected_home_points,
                "expected_away_points": expected_away_points,
                "expected_home_margin": expected_home_margin,
                "expected_home_margin_available": expected_margin_available,
                "warmup_state": "prior_games_warmup" if team_strength_warmup else "ready",
                "training_rows_available_before_block": exposure[
                    "training_rows_available_before_block"
                ],
                "training_completed_rows_before_block": exposure[
                    "training_completed_rows_before_block"
                ],
                "training_block_count": exposure["training_block_count"],
                "prior_completed_games_count": exposure["prior_completed_games_count"],
                "mapping_row_count": int(mapping.row_count),
                "mapping_intercept": float(mapping.intercept),
                "mapping_slope": float(mapping.slope),
                "mapping_fit_status": str(mapping.fit_status),
                "mapping_convergence_status": str(mapping.convergence_status),
                "mapping_cutoff_utc": str(mapping.cutoff_utc),
                "mapping_warmup": mapping_warmup,
                "mapping_rejected_nonpositive_slope": mapping_rejected,
                "predicted_home_win_probability": predicted_probability,
                "probability_available": probability_available,
                "target_available": target_available,
                "actual_margin": actual_margin,
                "actual_home_win": actual_home_win,
                "actual_tie": actual_tie,
                "is_binary_scored": is_binary_scored,
                "created_at_utc": created_at.isoformat().replace("+00:00", "Z"),
            }
        )
    return predictions


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_expected_margin_candidate(
    *,
    games_path: str | Path,
    candidate: ExpectedMarginCandidateConfig,
    shared: ExpectedMarginSharedConfig,
    run_id: str,
    model_version: str,
    as_of_season_max: int = DEVELOPMENT_SEASON_MAX,
) -> dict[str, Any]:
    """Run the expected-margin development walk-forward for **one** candidate.

    Returns a dictionary with the candidate's prediction rows and a
    block index. The function performs NO permanent I/O. The Caller
    is responsible for the ledger write. The function is pure (no
    global state) and side-effect free aside from reading the input
    parquet.

    The block schedule is built once and frozen. The fitted model
    and the mapping are both frozen for the duration of each block.
    The current block's games are excluded from the mapping fit.
    Future games are excluded by construction (the OOS ledger is
    append-only in chronological order).
    """
    games = _load_games(games_path)
    bad_seasons = sorted(
        set(
            int(s)
            for s in games["season"].unique().to_list()
            if int(s) > as_of_season_max
        )
    )
    if bad_seasons:
        for s in bad_seasons:
            if s == SEALED_HOLDOUT_SEASON:
                raise SealedHoldoutAccessError(
                    s,
                    "run_expected_margin_candidate",
                    "input contains 2025 sealed holdout rows",
                )
            if s == FORWARD_USE_SEASON:
                raise WalkForwardError(
                    "run_expected_margin_candidate",
                    "input contains 2026 forward-use rows",
                )
            raise WalkForwardError(
                "run_expected_margin_candidate",
                f"input contains unsupported season {s}",
            )

    blocks = build_development_blocks(games)
    if not blocks:
        raise WalkForwardError(
            "run_expected_margin_candidate", "no development blocks found"
        )

    created_at = datetime(2026, 8, 5, 0, 0, 0)

    all_predictions: list[dict[str, Any]] = []
    prior_oos: list[dict[str, Any]] = []

    for block in blocks:
        exposure = _build_exposure_for_block(block=block, games=games)
        prior_completed = _prior_completed_games(games, block)
        n_completed = int(prior_completed.height)
        cutoff_iso = block.as_of_utc.isoformat().replace("+00:00", "Z")

        team_strength_warmup = is_warmup_state(
            training_rows_available=n_completed,
            minimum_training_games=int(shared.minimum_training_games),
        )

        if team_strength_warmup:
            fitted = FittedExpectedMargin(
                train_rows=int(prior_completed.height),
                train_completed_rows=0,
                n_teams=0,
                team_index={},
                # StatePersistence: identify by candidate+block+cutoff only.,
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

        prior_oos_for_mapping = _prior_oos_for_mapping(
            prior_oos_predictions=prior_oos,
            games=games,
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
            margins = [
                float(r["expected_home_margin"])
                for r in prior_oos_for_mapping
                if bool(r.get("expected_home_margin_available", False))
            ]
            wins = [
                bool(r["actual_home_win"])
                for r in prior_oos_for_mapping
                if bool(r.get("expected_home_margin_available", False))
            ]
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

        block_games = games.filter(
            (pl.col("season") == block.season)
            & (pl.col("season_type") == block.season_type)
            & (pl.col("week") == block.week)
        ).sort("game_id")

        preds = _predict_block(
            block=block,
            block_games=block_games,
            candidate=candidate,
            shared=shared,
            fitted=fitted,
            mapping=mapping,
            run_id=run_id,
            model_version=model_version,
            exposure=exposure,
            created_at=created_at,
            team_strength_warmup=team_strength_warmup,
        )
        all_predictions.extend(preds)
        prior_oos.extend(preds)

    return {
        "run_id": run_id,
        "candidate_id": candidate.id,
        "model_version": model_version,
        "predictions": all_predictions,
    }
