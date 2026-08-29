from __future__ import annotations

from datetime import datetime, timezone

import polars as pl
import pytest

from nfl_edge.holdout.expected_margin_2025 import predict_expected_margin_block
from nfl_edge.holdout.football_2025 import (
    HoldoutFootballContractError,
    build_holdout_blocks,
)
from nfl_edge.models.expected_margin import (
    ExpectedMarginCandidateConfig,
    ExpectedMarginSharedConfig,
)


def _candidate(candidate_id: str = "stable") -> ExpectedMarginCandidateConfig:
    return ExpectedMarginCandidateConfig(
        id=candidate_id,
        offense_ridge=4.0,
        defense_ridge=4.0,
        home_field_ridge=4.0,
        recency_half_life_games=16.0,
        mapping_intercept_l2_weight=4.0,
        mapping_slope_l2_weight=4.0,
    )


def _shared() -> ExpectedMarginSharedConfig:
    return ExpectedMarginSharedConfig(
        league_baseline_prior=22.5,
        probability_min=0.01,
        probability_max=0.99,
        mapping_intercept_l2_prior=0.0,
        mapping_slope_l2_prior=0.0,
        mapping_solver_tolerance=1e-9,
        mapping_solver_max_iterations=100,
        tie_policy="exclude",
        minimum_training_games=2,
        minimum_mapping_rows=99,
        apply_probability_clipping=True,
        reject_nonpositive_slope=True,
        maximum_development_season=2024,
    )


def _history() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": ["2024_15_AAA_BBB", "2024_16_CCC_DDD", "2024_17_AAA_CCC", "2024_18_BBB_DDD"],
            "season": [2024, 2024, 2024, 2024],
            "season_type": ["REG", "REG", "REG", "REG"],
            "week": [15, 16, 17, 18],
            "prediction_as_of_utc": [
                datetime(2024, 12, 9, 18, tzinfo=timezone.utc),
                datetime(2024, 12, 16, 18, tzinfo=timezone.utc),
                datetime(2024, 12, 23, 18, tzinfo=timezone.utc),
                datetime(2024, 12, 30, 18, tzinfo=timezone.utc),
            ],
            "home_team": ["AAA", "CCC", "AAA", "BBB"],
            "away_team": ["BBB", "DDD", "CCC", "DDD"],
            "neutral_site": [False, False, False, False],
            "target_available": [True, True, True, True],
            "home_score": [27, 17, 24, 20],
            "away_score": [20, 21, 17, 23],
            "target_margin": [7, -4, 7, -3],
            "target_home_win": [True, False, True, False],
            "target_tie": [False, False, False, False],
        }
    )


def _current(*, revealed: bool = False) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": ["2025_01_AAA_DDD"],
            "season": [2025],
            "season_type": ["REG"],
            "week": [1],
            "prediction_as_of_utc": [datetime(2025, 9, 1, 18, tzinfo=timezone.utc)],
            "home_team": ["AAA"],
            "away_team": ["DDD"],
            "neutral_site": [False],
            "target_available": [revealed],
            "home_score": [28 if revealed else None],
            "away_score": [21 if revealed else None],
            "target_margin": [7 if revealed else None],
            "target_home_win": [True if revealed else None],
            "target_tie": [False],
        }
    )


def test_expected_margin_uses_only_prior_completed_games_and_hides_current_outcome():
    current = _current()
    block = build_holdout_blocks(current)[0]
    result = predict_expected_margin_block(
        history_games=_history(),
        current_games=current,
        prior_oos_predictions=[],
        block=block,
        candidate=_candidate(),
        shared=_shared(),
        run_id="synthetic",
        created_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )
    assert result["candidate_id"] == "stable"
    assert result["prior_completed_game_ids"] == tuple(_history()["game_id"].to_list())
    assert result["mapping_prior_rows"] == 0
    assert result["outcomes_revealed"] is False
    assert len(result["predictions"]) == 1
    row = result["predictions"][0]
    assert row["expected_home_margin_available"] is True
    assert row["target_available"] is False
    assert row["actual_margin"] is None
    assert row["actual_home_win"] is None
    assert row["is_binary_scored"] is False
    assert row["probability_available"] is False  # mapping deliberately warm in this synthetic case


def test_expected_margin_rejects_revealed_current_block_before_fit():
    current = _current(revealed=True)
    block = build_holdout_blocks(_current())[0]
    with pytest.raises(HoldoutFootballContractError, match="outcome already marked available"):
        predict_expected_margin_block(
            history_games=_history(),
            current_games=current,
            prior_oos_predictions=[],
            block=block,
            candidate=_candidate(),
            shared=_shared(),
            run_id="synthetic",
        )


def test_expected_margin_requires_frozen_stable_candidate():
    current = _current()
    block = build_holdout_blocks(current)[0]
    with pytest.raises(HoldoutFootballContractError, match="must be 'stable'"):
        predict_expected_margin_block(
            history_games=_history(),
            current_games=current,
            prior_oos_predictions=[],
            block=block,
            candidate=_candidate("balanced"),
            shared=_shared(),
            run_id="synthetic",
        )


def test_expected_margin_requires_original_2024_development_ceiling():
    current = _current()
    block = build_holdout_blocks(current)[0]
    shared = _shared()
    changed = ExpectedMarginSharedConfig(**{**shared.__dict__, "maximum_development_season": 2025})
    with pytest.raises(HoldoutFootballContractError, match="development maximum changed"):
        predict_expected_margin_block(
            history_games=_history(),
            current_games=current,
            prior_oos_predictions=[],
            block=block,
            candidate=_candidate(),
            shared=changed,
            run_id="synthetic",
        )
