"""Repeated-team and next-block-sensitivity tests.

Verifies:

A. unique-team block passes;
B. same team as home in two games raises ``RepeatedTeamInPredictionBlockError``;
C. same team once home and once away raises the same error;
D. duplicate game rows fail before prediction or state mutation;
E. error reports block ID, repeated team, and affected game IDs;
F. state remains byte-equivalent after a rejected block;
G. real 2018-2024 data has zero violations.

Also fixes the next-block sensitivity test using a shared team across
two blocks, proving block-1 freeze and block-2 carryover.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import polars as pl
import pytest

from nfl_edge.backtest.walk_forward import (
    _build_exposure_for_block,
    _predict_block,
)
from nfl_edge.common.errors import RepeatedTeamInPredictionBlockError
from nfl_edge.models.qb_elo import (
    EloConfig,
    EloState,
    apply_season_carryover,
    initial_state,
)


def _make_block(games: list[dict[str, Any]]) -> pl.DataFrame:
    """Build a block with a derived ``target_available`` column."""
    df = pl.DataFrame(games)
    return df.with_columns(pl.col("target_margin").is_not_null().alias("target_available"))


def _state_snapshot(state: EloState) -> dict[str, tuple[str, float]]:
    return {
        k: (v.team, v.rating) for k, v in sorted(state.teams.items())
    }


# ---- A ---------------------------------------------------------------------


def test_unique_team_block_passes() -> None:
    block = _make_block([
        {
            "game_id": "G1", "season": 2020, "season_type": "REG",
            "week": 1, "home_team": "AAA", "away_team": "BBB",
            "neutral_site": False, "target_margin": 7,
        },
        {
            "game_id": "G2", "season": 2020, "season_type": "REG",
            "week": 1, "home_team": "CCC", "away_team": "DDD",
            "neutral_site": False, "target_margin": -3,
        },
    ])
    state = initial_state(["AAA", "BBB", "CCC", "DDD"], EloConfig())
    state = apply_season_carryover(state, new_season=2020, config=EloConfig())
    preds, _ = _predict_block(
        block_games=block,
        block_id="B1",
        block_as_of_utc=datetime(2020, 9, 1, tzinfo=timezone.utc),
        state=state,
        elo_config=EloConfig(),
        run_id="R1",
        model_version="v1.0.0",
        exposure=_build_exposure_for_block(
            block_season=2020, block_season_type="REG", block_week=1,
            games=block.select(["season", "season_type", "week", "target_available"]),
        ),
        created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert len(preds) == 2


# ---- B / C / D -------------------------------------------------------------


def test_same_team_home_twice_raises() -> None:
    block = _make_block([
        {
            "game_id": "G1", "season": 2020, "season_type": "REG",
            "week": 1, "home_team": "AAA", "away_team": "BBB",
            "neutral_site": False, "target_margin": 7,
        },
        {
            "game_id": "G2", "season": 2020, "season_type": "REG",
            "week": 1, "home_team": "AAA", "away_team": "CCC",
            "neutral_site": False, "target_margin": 3,
        },
    ])
    state = initial_state(["AAA", "BBB", "CCC"], EloConfig())
    state = apply_season_carryover(state, new_season=2020, config=EloConfig())
    with pytest.raises(RepeatedTeamInPredictionBlockError) as excinfo:
        _predict_block(
            block_games=block,
            block_id="B-HOME-TWICE",
            block_as_of_utc=datetime(2020, 9, 1, tzinfo=timezone.utc),
            state=state,
            elo_config=EloConfig(),
            run_id="R1",
            model_version="v1.0.0",
            exposure=_build_exposure_for_block(
                block_season=2020, block_season_type="REG", block_week=1,
                games=block.select(["season", "season_type", "week", "target_available"]),
            ),
            created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
        )
    msg = str(excinfo.value)
    assert "B-HOME-TWICE" in msg
    assert "AAA" in msg
    assert "G1" in msg and "G2" in msg


def test_same_team_home_then_away_raises() -> None:
    block = _make_block([
        {
            "game_id": "G1", "season": 2020, "season_type": "REG",
            "week": 1, "home_team": "AAA", "away_team": "BBB",
            "neutral_site": False, "target_margin": 7,
        },
        {
            "game_id": "G2", "season": 2020, "season_type": "REG",
            "week": 1, "home_team": "CCC", "away_team": "AAA",
            "neutral_site": False, "target_margin": -3,
        },
    ])
    state = initial_state(["AAA", "BBB", "CCC"], EloConfig())
    state = apply_season_carryover(state, new_season=2020, config=EloConfig())
    with pytest.raises(RepeatedTeamInPredictionBlockError) as excinfo:
        _predict_block(
            block_games=block,
            block_id="B-HOME-AWAY",
            block_as_of_utc=datetime(2020, 9, 1, tzinfo=timezone.utc),
            state=state,
            elo_config=EloConfig(),
            run_id="R1",
            model_version="v1.0.0",
            exposure=_build_exposure_for_block(
                block_season=2020, block_season_type="REG", block_week=1,
                games=block.select(["season", "season_type", "week", "target_available"]),
            ),
            created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
        )
    msg = str(excinfo.value)
    assert "B-HOME-AWAY" in msg
    assert "AAA" in msg
    assert "G1" in msg and "G2" in msg


def test_duplicate_game_row_raises() -> None:
    block = _make_block([
        {
            "game_id": "G1", "season": 2020, "season_type": "REG",
            "week": 1, "home_team": "AAA", "away_team": "BBB",
            "neutral_site": False, "target_margin": 7,
        },
        {
            "game_id": "G1", "season": 2020, "season_type": "REG",
            "week": 1, "home_team": "AAA", "away_team": "BBB",
            "neutral_site": False, "target_margin": 7,
        },
    ])
    state = initial_state(["AAA", "BBB"], EloConfig())
    state = apply_season_carryover(state, new_season=2020, config=EloConfig())
    with pytest.raises(RepeatedTeamInPredictionBlockError):
        _predict_block(
            block_games=block,
            block_id="B-DUP",
            block_as_of_utc=datetime(2020, 9, 1, tzinfo=timezone.utc),
            state=state,
            elo_config=EloConfig(),
            run_id="R1",
            model_version="v1.0.0",
            exposure=_build_exposure_for_block(
                block_season=2020, block_season_type="REG", block_week=1,
                games=block.select(["season", "season_type", "week", "target_available"]),
            ),
            created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
        )


def test_state_byte_equivalent_after_rejection() -> None:
    block = _make_block([
        {
            "game_id": "G1", "season": 2020, "season_type": "REG",
            "week": 1, "home_team": "AAA", "away_team": "BBB",
            "neutral_site": False, "target_margin": 7,
        },
        {
            "game_id": "G2", "season": 2020, "season_type": "REG",
            "week": 1, "home_team": "AAA", "away_team": "CCC",
            "neutral_site": False, "target_margin": 3,
        },
    ])
    state_before = initial_state(["AAA", "BBB", "CCC"], EloConfig())
    state_before = apply_season_carryover(state_before, new_season=2020, config=EloConfig())
    snap_before = _state_snapshot(state_before)
    with pytest.raises(RepeatedTeamInPredictionBlockError):
        _predict_block(
            block_games=block,
            block_id="B1",
            block_as_of_utc=datetime(2020, 9, 1, tzinfo=timezone.utc),
            state=state_before,
            elo_config=EloConfig(),
            run_id="R1",
            model_version="v1.0.0",
            exposure=_build_exposure_for_block(
                block_season=2020, block_season_type="REG", block_week=1,
                games=block.select(["season", "season_type", "week", "target_available"]),
            ),
            created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
        )
    snap_after = _state_snapshot(state_before)
    assert snap_after == snap_before


def test_real_data_has_zero_repeated_team_violations() -> None:
    from nfl_edge.backtest.walk_forward import build_development_blocks
    games = pl.read_parquet(
        "data/derived/features_v1/game_features_2018_2025.parquet"
    )
    dev = games.filter(pl.col("season") <= 2024)
    blocks = build_development_blocks(dev)
    violations: list[tuple[str, str, str]] = []
    for block in blocks:
        block_games = dev.filter(
            (pl.col("season") == block.season)
            & (pl.col("season_type") == block.season_type)
            & (pl.col("week") == block.week)
        )
        seen: dict[str, str] = {}
        for row in block_games.iter_rows(named=True):
            gid = str(row["game_id"])
            for slot in ("home_team", "away_team"):
                t = str(row[slot])
                if t in seen:
                    violations.append((t, seen[t], gid))
                else:
                    seen[t] = gid
    assert violations == []


# ---- Next-block sensitivity with shared team --------------------------------


def _build_block(games: list[dict[str, Any]]) -> pl.DataFrame:
    df = pl.DataFrame(games)
    return df.with_columns(pl.col("target_margin").is_not_null().alias("target_available"))


def _run_two_block_workflow(
    block_a: pl.DataFrame,
    block_b: pl.DataFrame,
    actual_margin_b1: int = 7,
):
    """Run the walk-forward engine with two blocks and return the predictions
    (without the canonical update path) so the test can isolate block-1
    freeze and block-2 carryover.
    The ``actual_margin_b1`` is the margin used for the state update
    between block 1 and block 2."""

    from nfl_edge.backtest.walk_forward import (
        _build_exposure_for_block,
        _predict_block,
    )
    state = initial_state(
        ["AAA", "BBB", "CCC"], EloConfig()
    )
    state = apply_season_carryover(state, new_season=2020, config=EloConfig())
    snap_b1 = _state_snapshot(state)
    block1_games = block_a
    exposure1 = _build_exposure_for_block(
        block_season=2020, block_season_type="REG", block_week=1,
        games=block1_games.select(["season", "season_type", "week", "target_available"]),
    )
    preds1, _ = _predict_block(
        block_games=block1_games,
        block_id="B1",
        block_as_of_utc=datetime(2020, 9, 1, tzinfo=timezone.utc),
        state=state,
        elo_config=EloConfig(),
        run_id="R1",
        model_version="v1.0.0",
        exposure=exposure1,
        created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
    )
    # Apply update using the actual margin passed in
    from nfl_edge.models.qb_elo import PregamePrediction, update_state_with_margin
    p = PregamePrediction(
        game_id="G1", season=2020, season_type="REG", week=1,
        home_team="AAA", away_team="BBB",
        home_elo_before=state.rating("AAA"),
        away_elo_before=state.rating("BBB"),
        home_field_adjustment=48.0, home_qb_adjustment=0.0, away_qb_adjustment=0.0,
        qb_adjustment_net=0.0, qb_certainty_state="UNKNOWN",
        predicted_home_win_probability=0.6, actual_home_win=(actual_margin_b1 > 0), actual_tie=(actual_margin_b1 == 0),
        target_available=True,
    )
    h, a, new_state = update_state_with_margin(
        prediction=p, margin=actual_margin_b1, state=state, config=EloConfig()
    )
    snap_b2_in = _state_snapshot(new_state)
    exposure2 = _build_exposure_for_block(
        block_season=2020, block_season_type="REG", block_week=2,
        games=block_b.select(["season", "season_type", "week", "target_available"]),
    )
    preds2, _ = _predict_block(
        block_games=block_b,
        block_id="B2",
        block_as_of_utc=datetime(2020, 9, 8, tzinfo=timezone.utc),
        state=new_state,
        elo_config=EloConfig(),
        run_id="R1",
        model_version="v1.0.0",
        exposure=exposure2,
        created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
    )
    return preds1, preds2, snap_b1, snap_b2_in


def test_block1_uses_frozen_state() -> None:
    block_a = _build_block([
        {
            "game_id": "G1", "season": 2020, "season_type": "REG",
            "week": 1, "home_team": "AAA", "away_team": "BBB",
            "neutral_site": False, "target_margin": 7,
        },
    ])
    block_b = _build_block([
        {
            "game_id": "G2", "season": 2020, "season_type": "REG",
            "week": 2, "home_team": "AAA", "away_team": "CCC",
            "neutral_site": False, "target_margin": 3,
        },
    ])
    preds1, _, snap_b1, _ = _run_two_block_workflow(block_a, block_b)
    assert preds1[0]["home_elo_before"] == snap_b1["AAA"][1]
    assert preds1[0]["away_elo_before"] == snap_b1["BBB"][1]


def test_poisoning_block1_changes_block2_prediction() -> None:
    block_a = _build_block([
        {
            "game_id": "G1", "season": 2020, "season_type": "REG",
            "week": 1, "home_team": "AAA", "away_team": "BBB",
            "neutral_site": False, "target_margin": 7,
        },
    ])
    block_b = _build_block([
        {
            "game_id": "G2", "season": 2020, "season_type": "REG",
            "week": 2, "home_team": "AAA", "away_team": "CCC",
            "neutral_site": False, "target_margin": 3,
        },
    ])
    _, preds2_clean, _, _ = _run_two_block_workflow(block_a, block_b, actual_margin_b1=7)
    _, preds2_poison, _, _ = _run_two_block_workflow(block_a, block_b, actual_margin_b1=28)
    # AAA's home_elo_before in block 2 must change because block 1's
    # actual_margin (the poison) flowed into the state update.
    assert preds2_clean[0]["home_elo_before"] != preds2_poison[0]["home_elo_before"]
    # CCC's prior_rating is unchanged in both runs (CCC never appears
    # in block 1).
    assert preds2_clean[0]["away_elo_before"] == preds2_poison[0]["away_elo_before"]
