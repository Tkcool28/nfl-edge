from __future__ import annotations

import polars as pl
import pytest

from nfl_edge.holdout.xgboost_inputs_2025 import (
    XGBoostInputContractError,
    assemble_candidate1_xgboost_surface,
)
from nfl_edge.models.xgboost_contract import QB_FEATURE_COLUMNS


def _qb_row(game_id: str, side: str, rank: int = 1) -> dict[str, object]:
    row: dict[str, object] = {
        "game_id": game_id,
        "season": 2025,
        "side": side,
        "candidate_rank": rank,
    }
    for index, name in enumerate(QB_FEATURE_COLUMNS):
        if name in {"low_sample", "rookie_or_zero_sample", "missing_player_id"}:
            row[name] = bool(index % 2)
        else:
            row[name] = float(index + (0 if side == "home" else 100))
    return row


def test_exact_task03c_candidate_rank_one_join_prefixes_all_22_qb_features():
    games = pl.DataFrame(
        [
            {"game_id": "g1", "season": 2025, "week": 1, "team_metric": 1.0},
            {"game_id": "g2", "season": 2025, "week": 2, "team_metric": 2.0},
        ]
    )
    qb = pl.DataFrame(
        [
            _qb_row("g1", "home"),
            _qb_row("g1", "away"),
            _qb_row("g2", "home"),
            _qb_row("g2", "away"),
            _qb_row("g1", "home", rank=2),
        ]
    )
    out = assemble_candidate1_xgboost_surface(
        games,
        qb,
        season_min=2025,
        season_max=2025,
    )
    assert out.height == 2
    assert all(f"home_qb_{name}" in out.columns for name in QB_FEATURE_COLUMNS)
    assert all(f"away_qb_{name}" in out.columns for name in QB_FEATURE_COLUMNS)
    assert out.filter(pl.col("game_id") == "g1")["home_qb_passing_epa"].item() == 0.0
    assert out.filter(pl.col("game_id") == "g1")["away_qb_passing_epa"].item() == 100.0


def test_join_fails_closed_when_one_game_side_is_missing():
    games = pl.DataFrame(
        [
            {"game_id": "g1", "season": 2025, "week": 1},
            {"game_id": "g2", "season": 2025, "week": 2},
        ]
    )
    qb = pl.DataFrame(
        [
            _qb_row("g1", "home"),
            _qb_row("g1", "away"),
            _qb_row("g2", "home"),
        ]
    )
    with pytest.raises(XGBoostInputContractError, match="one home and one away row per game"):
        assemble_candidate1_xgboost_surface(
            games,
            qb,
            season_min=2025,
            season_max=2025,
        )


def test_join_fails_closed_on_duplicate_candidate_rank_one_side():
    games = pl.DataFrame([{"game_id": "g1", "season": 2025, "week": 1}])
    qb = pl.DataFrame([_qb_row("g1", "home"), _qb_row("g1", "home"), _qb_row("g1", "away")])
    with pytest.raises(XGBoostInputContractError, match="duplicate game_id/side"):
        assemble_candidate1_xgboost_surface(
            games,
            qb,
            season_min=2025,
            season_max=2025,
        )
