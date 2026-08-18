"""Focused contract tests for Task05D's pre-bake-off totals wiring."""

from __future__ import annotations

import polars as pl
import pytest

from nfl_edge.backtest.totals_bake_off import (
    CANDIDATE_IDS,
    CANDIDATES,
    CATEGORICAL_PREDICTORS,
    MINIMUM_ELIGIBLE_PRIOR_ROWS,
    NUMERIC_PREDICTORS,
    SCORING_UNIVERSE,
    SERIAL_EXECUTION,
    CandidateMetricResult,
    build_candidate_model,
    configure_serial_execution,
    metric_selection_key,
    rank_candidates,
    run_candidate_on_prepared,
    scoring_blocks_from_prepared,
)
from nfl_edge.backtest.totals_walk_forward import TotalsWalkForwardBlock, TotalsWalkForwardRun
from nfl_edge.common.errors import ConfigurationError
from nfl_edge.features.totals_v1.feature_table import EXACT_90_COLUMNS


def _prepared_block(training_rows: int) -> TotalsWalkForwardBlock:
    return TotalsWalkForwardBlock(
        target_block=object(),
        training_game_ids=tuple(f"game-{index}" for index in range(training_rows)),
        training_rows=pl.DataFrame({"target_total_points": list(range(training_rows))}),
        prediction_rows=pl.DataFrame({"game_id": ["target"]}),
    )


def _result(candidate_id: str, **overrides: float) -> CandidateMetricResult:
    values = {
        "oob_rmse": 10.0,
        "mae": 8.0,
        "pearson": 0.5,
        "spearman": 0.4,
        "stability": 0.2,
    }
    values.update(overrides)
    return CandidateMetricResult(candidate_id=candidate_id, **values)


def _winner(candidate_id: str, **overrides: float) -> str:
    results = (_result(candidate_id, **overrides), *(_result(other_id) for other_id in CANDIDATE_IDS[1:]))
    return rank_candidates(results)[0].candidate_id


def test_scoring_universe_and_candidate_order_are_frozen() -> None:
    assert SCORING_UNIVERSE.scoring_blocks == 146
    assert SCORING_UNIVERSE.scoring_rows == 1864
    assert SCORING_UNIVERSE.warmup_rows == 78
    assert SCORING_UNIVERSE.earliest_block_id == "2018_REG_W06"
    assert SCORING_UNIVERSE.latest_block_id == "2024_SB_W22"
    assert CANDIDATE_IDS == ("R1", "R2", "R3", "R4")
    assert tuple(candidate.candidate_id for candidate in CANDIDATES) == CANDIDATE_IDS
    assert len(NUMERIC_PREDICTORS) == 88
    assert CATEGORICAL_PREDICTORS == ("roof_category", "surface_category")


def test_frozen_ridge_hyperparameters_and_serial_settings() -> None:
    candidates = {candidate.candidate_id: candidate.model_kwargs for candidate in CANDIDATES}
    assert [candidates[candidate_id]["alpha"] for candidate_id in CANDIDATE_IDS] == [0.1, 1, 10, 100]
    assert SERIAL_EXECUTION.multiprocessing_enabled is False
    environment = {key: "8" for key in SERIAL_EXECUTION.environment}
    configure_serial_execution(environment)
    assert environment == dict(SERIAL_EXECUTION.environment)

def test_row_floor_filters_only_prepared_walk_forward_blocks() -> None:
    run = TotalsWalkForwardRun(
        blocks=(_prepared_block(MINIMUM_ELIGIBLE_PRIOR_ROWS - 1), _prepared_block(MINIMUM_ELIGIBLE_PRIOR_ROWS))
    )

    eligible = scoring_blocks_from_prepared(run)

    assert eligible == (run.blocks[1],)
    with pytest.raises(TypeError, match="TotalsWalkForwardRun"):
        scoring_blocks_from_prepared(object())  # type: ignore[arg-type]


def test_metric_selection_and_full_tie_break_are_deterministic() -> None:
    results = tuple(_result(candidate_id) for candidate_id in reversed(CANDIDATE_IDS))
    ranked = rank_candidates(results)

    assert tuple(result.candidate_id for result in ranked) == CANDIDATE_IDS
    assert metric_selection_key(_result("R1")) < metric_selection_key(_result("R2"))
    assert _winner("R1", mae=7.9) == "R1"
    assert _winner("R1", pearson=0.6) == "R1"
    assert _winner("R1", spearman=0.5) == "R1"
    assert _winner("R1", stability=0.1) == "R1"


def test_metric_results_require_complete_known_finite_candidates() -> None:
    with pytest.raises(ConfigurationError, match="unknown"):
        _result("unknown")
    with pytest.raises(ConfigurationError, match="finite"):
        _result("R1", oob_rmse=float("nan"))
    with pytest.raises(ConfigurationError, match="exactly one"):
        rank_candidates((_result("R1"),) * len(CANDIDATE_IDS))


def _smoke_block() -> TotalsWalkForwardBlock:
    identities = {
        "game_id": [f"train-{index}" for index in range(MINIMUM_ELIGIBLE_PRIOR_ROWS)],
        "season": [2024] * MINIMUM_ELIGIBLE_PRIOR_ROWS,
        "season_type": ["REG"] * MINIMUM_ELIGIBLE_PRIOR_ROWS,
        "week": [1] * MINIMUM_ELIGIBLE_PRIOR_ROWS,
        "home_team": ["H"] * MINIMUM_ELIGIBLE_PRIOR_ROWS,
        "away_team": ["A"] * MINIMUM_ELIGIBLE_PRIOR_ROWS,
        "block_id": ["2024_REG_W01"] * MINIMUM_ELIGIBLE_PRIOR_ROWS,
    }
    features = {
        column: [float(index % 5) for index in range(MINIMUM_ELIGIBLE_PRIOR_ROWS)]
        for column in NUMERIC_PREDICTORS
    }
    features.update({column: ["unknown"] * MINIMUM_ELIGIBLE_PRIOR_ROWS for column in CATEGORICAL_PREDICTORS})
    identity_columns = ["game_id", "season", "season_type", "week", "home_team", "away_team", "block_id"]
    training_columns = [*identity_columns, *EXACT_90_COLUMNS, "home_score", "away_score", "target_total_points"]
    training = pl.DataFrame(
        {
            **identities,
            **features,
            "home_score": [20] * MINIMUM_ELIGIBLE_PRIOR_ROWS,
            "away_score": [17] * MINIMUM_ELIGIBLE_PRIOR_ROWS,
            "target_total_points": [37.0 + (index % 3) for index in range(MINIMUM_ELIGIBLE_PRIOR_ROWS)],
        }
    ).select(training_columns)
    prediction = training.head(1).select([*identity_columns, *EXACT_90_COLUMNS])
    outcomes = training.head(1).select([*identity_columns, "target_total_points"])
    return TotalsWalkForwardBlock(object(), tuple(identities["game_id"]), training, prediction, outcomes)


def test_factory_and_tiny_prepared_block_smoke_fit_for_ridge() -> None:
    run = TotalsWalkForwardRun((_smoke_block(),))

    assert build_candidate_model("R1").named_steps["model"].alpha == 0.1
    assert build_candidate_model("R4").named_steps["model"].alpha == 100
    for candidate_id in ("R1", "R4"):
        result = run_candidate_on_prepared(candidate_id, run)
        assert result.candidate_id == candidate_id
        assert len(result.records) == 1
        assert result.records[0].identity["game_id"] == "train-0"
        assert result.records[0].observed_target == 37.0
        assert result.records[0].predicted_total == pytest.approx(result.records[0].predicted_total)


def test_runner_fails_closed_without_outcome_surface() -> None:
    block = _smoke_block()
    missing_outcomes = TotalsWalkForwardBlock(
        block.target_block,
        block.training_game_ids,
        block.training_rows,
        block.prediction_rows,
    )
    run = TotalsWalkForwardRun((missing_outcomes,))

    with pytest.raises(ConfigurationError, match="outcome_rows"):
        run_candidate_on_prepared("R1", run)
