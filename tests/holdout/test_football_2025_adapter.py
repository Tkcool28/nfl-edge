from __future__ import annotations

from datetime import datetime, timezone

import polars as pl
import pytest

from nfl_edge.holdout.football_2025 import (
    HoldoutFootballContractError,
    build_holdout_blocks,
    predict_oracle_qb_elo_block,
    reveal_and_update_qb_elo_block,
)
from nfl_edge.models.qb_elo import EloConfig, initial_state


class FakeOracleResolver:
    def __init__(self, game_ids: list[str]):
        self._game_ids = set(game_ids)

    def __call__(self, game_id: str) -> tuple[float, float]:
        if game_id not in self._game_ids:
            raise KeyError(game_id)
        return (12.0, -4.0)

    def assert_coverage(self, game_ids: list[str], *, where: str) -> None:
        assert where == "holdout_2025.oracle_qb.coverage"
        assert set(game_ids) == self._game_ids

    def manifest_identity(self):
        return {
            "mode": "ORACLE",
            "implementation": "tests.FakeOracleResolver",
            "oracle_artifact_path": "synthetic/oracle.parquet",
            "oracle_artifact_sha256": "a" * 64,
            "historical_model_usage": "ORACLE_STARTER_IDENTITY_ONLY",
            "starter_evidence_class": "POSTGAME_STARTER_IDENTITY_ALLOWED_FOR_HISTORICAL_WALKTHROUGH",
        }


def _current(*, revealed: bool = False) -> pl.DataFrame:
    margin = 7 if revealed else None
    return pl.DataFrame(
        {
            "game_id": ["2025_01_AAA_BBB"],
            "season": [2025],
            "season_type": ["REG"],
            "week": [1],
            "prediction_as_of_utc": [datetime(2025, 9, 1, 18, 0, tzinfo=timezone.utc)],
            "home_team": ["AAA"],
            "away_team": ["BBB"],
            "neutral_site": [False],
            "target_available": [revealed],
            "target_margin": [margin],
            "target_home_win": [True if revealed else None],
            "target_tie": [False],
        }
    )


def _history() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": ["2024_18_CCC_DDD"],
            "season": [2024],
            "season_type": ["REG"],
            "week": [18],
            "prediction_as_of_utc": [datetime(2024, 12, 30, 18, 0, tzinfo=timezone.utc)],
            "home_team": ["CCC"],
            "away_team": ["DDD"],
            "neutral_site": [False],
            "target_available": [True],
            "target_margin": [3],
            "target_home_win": [True],
            "target_tie": [False],
        }
    )


def test_build_holdout_blocks_is_2025_only_and_deterministic():
    frame = pl.concat([_current(), _current().with_columns(pl.lit("2025_01_EEE_FFF").alias("game_id"))])
    blocks = build_holdout_blocks(frame)
    assert len(blocks) == 1
    assert blocks[0].block_id == "2025_REG_W01"
    assert blocks[0].game_ids == ("2025_01_AAA_BBB", "2025_01_EEE_FFF")


def test_current_block_outcome_is_rejected_before_qb_prediction():
    block = build_holdout_blocks(_current())[0]
    cfg = EloConfig()
    state = initial_state(["AAA", "BBB"], cfg)
    with pytest.raises(HoldoutFootballContractError, match="outcome already marked available"):
        predict_oracle_qb_elo_block(
            history_games=_history(),
            current_games=_current(revealed=True),
            block=block,
            state=state,
            config=cfg,
            qb_adjustment_resolver=FakeOracleResolver(list(block.game_ids)),
            run_id="synthetic",
        )


def test_oracle_starter_identity_predicts_before_outcome_then_updates_after_reveal():
    current = _current()
    block = build_holdout_blocks(current)[0]
    cfg = EloConfig()
    state = initial_state(["AAA", "BBB", "CCC", "DDD"], cfg)
    frozen = predict_oracle_qb_elo_block(
        history_games=_history(),
        current_games=current,
        block=block,
        state=state,
        config=cfg,
        qb_adjustment_resolver=FakeOracleResolver(list(block.game_ids)),
        run_id="synthetic",
        created_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )
    assert frozen["outcomes_revealed"] is False
    assert len(frozen["predictions"]) == 1
    row = frozen["predictions"][0]
    assert row["qb_certainty_state"] == "CONFIRMED"
    assert row["home_qb_adjustment"] == 12.0
    assert row["away_qb_adjustment"] == -4.0
    assert row["target_available"] is False
    assert row["actual_margin"] is None
    assert 0.0 < row["predicted_home_win_probability"] < 1.0

    revealed = reveal_and_update_qb_elo_block(
        frozen_prediction=frozen,
        revealed_games=_current(revealed=True),
        config=cfg,
        run_id="synthetic",
    )
    assert revealed["outcomes_revealed"] is True
    assert len(revealed["state_updates"]) == 2
    assert revealed["next_update_order"] == 2
    assert revealed["new_state"].rating("AAA") > frozen["block_start_state"].rating("AAA")
    assert revealed["new_state"].rating("BBB") < frozen["block_start_state"].rating("BBB")


def test_prior_2025_unrevealed_history_is_rejected():
    current = _current().with_columns(pl.lit(2).alias("week"), pl.lit("2025_02_AAA_BBB").alias("game_id"))
    block = build_holdout_blocks(current)[0]
    prior_unrevealed = _current()
    cfg = EloConfig()
    state = initial_state(["AAA", "BBB"], cfg)
    with pytest.raises(HoldoutFootballContractError, match="prior 2025 history contains an unrevealed outcome"):
        predict_oracle_qb_elo_block(
            history_games=prior_unrevealed,
            current_games=current,
            block=block,
            state=state,
            config=cfg,
            qb_adjustment_resolver=FakeOracleResolver(list(block.game_ids)),
            run_id="synthetic",
        )
