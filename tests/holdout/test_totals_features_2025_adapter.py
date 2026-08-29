from __future__ import annotations

from datetime import datetime, timezone

import polars as pl
import pytest

from nfl_edge.backtest.blocks import PredictionBlock
from nfl_edge.features.totals_v1.block_state import GameObservation, TotalsBlockState
from nfl_edge.features.totals_v1.feature_table import (
    EXACT_90_COLUMNS,
    _ORACLE_QB_CONSUMED_COLUMNS,
)
from nfl_edge.holdout.football_2025 import (
    HoldoutFootballContractError,
    build_holdout_blocks,
)
from nfl_edge.holdout.totals_features_2025 import (
    bootstrap_totals_state,
    materialize_totals_feature_block,
    reveal_and_commit_totals_block,
)


def _current(*, target_total: float | None = None) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "game_id": "2025_01_AAA_BBB",
                "season": 2025,
                "season_type": "REG",
                "week": 1,
                "scheduled_start_utc": datetime(2025, 9, 4, 0, tzinfo=timezone.utc),
                "prediction_as_of_utc": datetime(2025, 9, 1, 18, tzinfo=timezone.utc),
                "home_team": "AAA",
                "away_team": "BBB",
                "neutral_site": False,
                "away_rest": 7,
                "home_rest": 8,
                "surface": "Grass",
                "roof_type": "Outdoors",
                "target_available": False,
                "target_total_points": target_total,
                "target_margin": None,
                "target_home_win": None,
                "home_score": None,
                "away_score": None,
            }
        ]
    )


def _oracle() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for side, offset in (("away", 0.0), ("home", 1.0)):
        row: dict[str, object] = {
            "game_id": "2025_01_AAA_BBB",
            "side": side,
        }
        for index, column in enumerate(_ORACLE_QB_CONSUMED_COLUMNS):
            row[column] = float(index) + offset
        rows.append(row)
    return pl.DataFrame(rows)


def _revealed(*, target_total: float = 44.0) -> pl.DataFrame:
    return _current().with_columns(
        pl.lit(True).alias("target_available"),
        pl.lit(24, dtype=pl.Int64).alias("home_score"),
        pl.lit(20, dtype=pl.Int64).alias("away_score"),
        pl.lit(target_total).alias("target_total_points"),
    )


def _observation(block_id: str, game_id: str = "2025_01_AAA_BBB") -> GameObservation:
    return GameObservation(
        block_id=block_id,
        game_id=game_id,
        team_updates={
            "AAA": {
                "epa_play_offense": (2.0, 4.0, 4),
                "epa_play_defense_allowed": (1.0, 4.0, 4),
            },
            "BBB": {
                "epa_play_offense": (1.0, 4.0, 4),
                "epa_play_defense_allowed": (2.0, 4.0, 4),
            },
        },
    )


def test_materialize_exact90_freezes_state_without_mutating_it():
    state = TotalsBlockState()
    current = _current()
    block = build_holdout_blocks(current)[0]
    before = state.snapshot_for_block(block)

    frozen = materialize_totals_feature_block(
        state=state,
        current_games=current,
        oracle_qb=_oracle(),
        block=block,
    )

    assert frozen.block_start_snapshot == before
    assert state.snapshot_for_block(block) == before
    assert frozen.features.width == 90
    assert frozen.features.columns == list(EXACT_90_COLUMNS)
    assert frozen.identity["game_id"].to_list() == ["2025_01_AAA_BBB"]
    assert frozen.model_frame["target_available"].to_list() == [False]
    assert frozen.model_frame["target_total_points"].null_count() == 1
    assert frozen.features.item(0, "away_rest_days") == 7
    assert frozen.features.item(0, "home_rest_days") == 8
    assert frozen.features.item(0, "roof_category") == "outdoors"
    assert frozen.features.item(0, "surface_category") == "grass"


def test_materialize_rejects_current_total_target():
    current = _current(target_total=44.0)
    block = build_holdout_blocks(_current())[0]

    with pytest.raises(HoldoutFootballContractError, match="must be null"):
        materialize_totals_feature_block(
            state=TotalsBlockState(),
            current_games=current,
            oracle_qb=_oracle(),
            block=block,
        )


def test_reveal_commits_complete_block_only_after_feature_freeze():
    state = TotalsBlockState()
    current = _current()
    block = build_holdout_blocks(current)[0]
    frozen = materialize_totals_feature_block(
        state=state,
        current_games=current,
        oracle_qb=_oracle(),
        block=block,
    )

    result = reveal_and_commit_totals_block(
        frozen=frozen,
        state=state,
        revealed_games=_revealed(),
        observations=[_observation(block.block_id)],
    )

    assert result["outcomes_revealed"] is True
    graded = result["graded_model_rows"]
    assert graded["target_available"].to_list() == [True]
    assert graded["target_total_points"].to_list() == [44.0]
    assert state.team_state("AAA").get("epa_play_offense") is not None


def test_reveal_rejects_target_score_mismatch_without_state_mutation():
    state = TotalsBlockState()
    current = _current()
    block = build_holdout_blocks(current)[0]
    frozen = materialize_totals_feature_block(
        state=state,
        current_games=current,
        oracle_qb=_oracle(),
        block=block,
    )
    before = state.snapshot_for_block(block)

    with pytest.raises(HoldoutFootballContractError, match="target_total_points mismatch"):
        reveal_and_commit_totals_block(
            frozen=frozen,
            state=state,
            revealed_games=_revealed(target_total=45.0),
            observations=[_observation(block.block_id)],
        )

    assert state.snapshot_for_block(block) == before


def test_reveal_rejects_state_changed_after_feature_freeze():
    state = TotalsBlockState()
    current = _current()
    block = build_holdout_blocks(current)[0]
    frozen = materialize_totals_feature_block(
        state=state,
        current_games=current,
        oracle_qb=_oracle(),
        block=block,
    )

    prior = PredictionBlock(
        block_id="2024_REG_W18",
        season=2024,
        season_type="REG",
        week=18,
        as_of_utc=datetime(2025, 1, 1, tzinfo=timezone.utc),
        game_ids=("2024_18_AAA_CCC",),
    )
    state.commit_block(
        prior,
        [
            GameObservation(
                block_id=prior.block_id,
                game_id=prior.game_ids[0],
                team_updates={"AAA": {"epa_play_offense": (1.0, 1.0, 1)}},
            )
        ],
    )

    with pytest.raises(HoldoutFootballContractError, match="state changed after feature freeze"):
        reveal_and_commit_totals_block(
            frozen=frozen,
            state=state,
            revealed_games=_revealed(),
            observations=[_observation(block.block_id)],
        )


def test_bootstrap_requires_exact_2018_2024_and_complete_observation_blocks():
    blocks: list[PredictionBlock] = []
    observations: dict[str, list[GameObservation]] = {}
    for season in range(2018, 2025):
        gid = f"{season}_01_AAA_BBB"
        block = PredictionBlock(
            block_id=f"{season}_REG_W01",
            season=season,
            season_type="REG",
            week=1,
            as_of_utc=datetime(season, 9, 1, tzinfo=timezone.utc),
            game_ids=(gid,),
        )
        blocks.append(block)
        observations[block.block_id] = [
            GameObservation(
                block_id=block.block_id,
                game_id=gid,
                team_updates={"AAA": {"epa_play_offense": (1.0, 2.0, 2)}},
            )
        ]

    state = bootstrap_totals_state(blocks=blocks, observations_by_block=observations)
    accumulator = state.team_state("AAA").get("epa_play_offense")
    assert accumulator is not None
    assert accumulator.numerator == 7.0
    assert accumulator.denominator == 14.0

    with pytest.raises(HoldoutFootballContractError, match="exactly 2018-2024"):
        bootstrap_totals_state(
            blocks=blocks[1:],
            observations_by_block={key: observations[key] for key in list(observations)[1:]},
        )

    incomplete = dict(observations)
    incomplete.pop(blocks[-1].block_id)
    with pytest.raises(HoldoutFootballContractError, match="do not exactly match"):
        bootstrap_totals_state(blocks=blocks, observations_by_block=incomplete)
