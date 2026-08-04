"""Exposure-metadata correctness tests.

Required exact tests:

- opening block: rows = 0, blocks = 0, completed = 0
- one prior block of 3 games: rows = 3, blocks = 1, completed = 3
- two prior blocks (3 and 4 games): rows = 7, blocks = 2, completed = 7
- unavailable target: rows increase, completed does not
- multiple games in one block count as one block
- REG and WC with same numeric week are distinct blocks
- postseason ordering follows the approved priority
- current block rows are excluded
- future block rows are excluded
- counts grow monotonically
- training_season_min and training_season_max remain truthful
"""

from __future__ import annotations

import polars as pl

from nfl_edge.backtest.walk_forward import _build_exposure_for_block


def _make_games(rows: list[dict]) -> pl.DataFrame:
    df = pl.DataFrame(rows)
    if "target_margin" in df.columns:
        has_margin = pl.col("target_margin").is_not_null()
    else:
        has_margin = pl.lit(False)
    return df.with_columns(has_margin.alias("target_available"))


def test_opening_block_exposure_is_zero() -> None:
    games = _make_games([
        {"season": 2018, "season_type": "REG", "week": 1, "target_margin": 3},
    ])
    e = _build_exposure_for_block(
        block_season=2018, block_season_type="REG", block_week=1, games=games
    )
    assert e == {
        "training_rows_available_before_block": 0,
        "training_season_min": None,
        "training_season_max": None,
        "training_block_count": 0,
        "prior_completed_games_count": 0,
    }


def test_one_prior_block_three_games() -> None:
    games = _make_games([
        {"season": 2018, "season_type": "REG", "week": 1, "target_margin": 3},
        {"season": 2018, "season_type": "REG", "week": 1, "target_margin": -7},
        {"season": 2018, "season_type": "REG", "week": 1, "target_margin": 14},
    ])
    e = _build_exposure_for_block(
        block_season=2018, block_season_type="REG", block_week=2, games=games
    )
    assert e["training_rows_available_before_block"] == 3
    assert e["training_block_count"] == 1
    assert e["prior_completed_games_count"] == 3
    assert e["training_season_min"] == 2018
    assert e["training_season_max"] == 2018


def test_two_prior_blocks_seven_games() -> None:
    games = _make_games([
        {"season": 2018, "season_type": "REG", "week": 1, "target_margin": 3},
        {"season": 2018, "season_type": "REG", "week": 1, "target_margin": -7},
        {"season": 2018, "season_type": "REG", "week": 1, "target_margin": 14},
        {"season": 2018, "season_type": "REG", "week": 2, "target_margin": 3},
        {"season": 2018, "season_type": "REG", "week": 2, "target_margin": -3},
        {"season": 2018, "season_type": "REG", "week": 2, "target_margin": 3},
        {"season": 2018, "season_type": "REG", "week": 2, "target_margin": -7},
    ])
    e = _build_exposure_for_block(
        block_season=2018, block_season_type="REG", block_week=3, games=games
    )
    assert e["training_rows_available_before_block"] == 7
    assert e["training_block_count"] == 2
    assert e["prior_completed_games_count"] == 7


def test_unavailable_target_increases_rows_not_completed() -> None:
    games = _make_games([
        {"season": 2018, "season_type": "REG", "week": 1, "target_margin": 3},
        {"season": 2018, "season_type": "REG", "week": 1, "target_margin": -7},
        {"season": 2018, "season_type": "REG", "week": 1, "target_margin": 14},
        {"season": 2018, "season_type": "REG", "week": 2, "target_margin": 3},
        {"season": 2018, "season_type": "REG", "week": 2, "target_margin": None},
    ])
    e = _build_exposure_for_block(
        block_season=2018, block_season_type="REG", block_week=3, games=games
    )
    # 5 prior rows: 3 from week 1, 2 from week 2 (including the
    # target-unavailable one).
    assert e["training_rows_available_before_block"] == 5
    # 4 completed (the 5th is target-unavailable).
    assert e["prior_completed_games_count"] == 4
    # 2 distinct prior blocks (week 1, week 2)
    assert e["training_block_count"] == 2


def test_unavailable_target_introduces_new_block_counts() -> None:
    games = _make_games([
        {"season": 2018, "season_type": "REG", "week": 1, "target_margin": 3},
        {"season": 2018, "season_type": "REG", "week": 2, "target_margin": None},
    ])
    e = _build_exposure_for_block(
        block_season=2018, block_season_type="REG", block_week=3, games=games
    )
    # 2 prior rows; week 1 and week 2 are distinct blocks.
    assert e["training_rows_available_before_block"] == 2
    assert e["training_block_count"] == 2
    assert e["prior_completed_games_count"] == 1


def test_multiple_games_in_one_block_count_as_one_block() -> None:
    games = _make_games([
        {"season": 2018, "season_type": "REG", "week": 1, "target_margin": 3},
        {"season": 2018, "season_type": "REG", "week": 1, "target_margin": -7},
        {"season": 2018, "season_type": "REG", "week": 1, "target_margin": 14},
    ])
    e = _build_exposure_for_block(
        block_season=2018, block_season_type="REG", block_week=2, games=games
    )
    assert e["training_rows_available_before_block"] == 3
    assert e["training_block_count"] == 1


def test_reg_and_wc_same_week_are_distinct_blocks() -> None:
    games = _make_games([
        {"season": 2018, "season_type": "REG", "week": 17, "target_margin": 3},
        {"season": 2018, "season_type": "WC", "week": 1, "target_margin": 3},
    ])
    e = _build_exposure_for_block(
        block_season=2018, block_season_type="SB", block_week=1, games=games
    )
    assert e["training_block_count"] == 2


def test_postseason_ordering_priority() -> None:
    # The block ordering is REG < WC < DIV < CON < SB
    games = _make_games([
        {"season": 2018, "season_type": "SB", "week": 1, "target_margin": 3},
        {"season": 2018, "season_type": "WC", "week": 1, "target_margin": 3},
    ])
    # Ask exposure for a SB block: prior must include WC (priority 1)
    # but not SB (priority 4, same season).
    e = _build_exposure_for_block(
        block_season=2018, block_season_type="SB", block_week=1, games=games
    )
    assert e["training_block_count"] == 1  # only the WC block


def test_current_block_rows_excluded() -> None:
    games = _make_games([
        {"season": 2018, "season_type": "REG", "week": 1, "target_margin": 3},
        {"season": 2018, "season_type": "REG", "week": 2, "target_margin": 3},
    ])
    e = _build_exposure_for_block(
        block_season=2018, block_season_type="REG", block_week=2, games=games
    )
    # Only the week-1 row is prior
    assert e["training_rows_available_before_block"] == 1
    assert e["training_block_count"] == 1


def test_future_block_rows_excluded() -> None:
    games = _make_games([
        {"season": 2018, "season_type": "REG", "week": 1, "target_margin": 3},
        {"season": 2019, "season_type": "REG", "week": 1, "target_margin": 3},
    ])
    e = _build_exposure_for_block(
        block_season=2018, block_season_type="REG", block_week=2, games=games
    )
    # 2019 is future; not included. Only the 2018 week-1 row is prior.
    assert e["training_rows_available_before_block"] == 1
    assert e["training_block_count"] == 1


def test_counts_grow_monotonically() -> None:
    games = _make_games([
        {"season": 2018, "season_type": "REG", "week": 1, "target_margin": 3},
        {"season": 2018, "season_type": "REG", "week": 2, "target_margin": -3},
        {"season": 2018, "season_type": "REG", "week": 3, "target_margin": 7},
        {"season": 2018, "season_type": "REG", "week": 4, "target_margin": 14},
    ])
    counts = []
    for w in range(1, 5):
        e = _build_exposure_for_block(
            block_season=2018, block_season_type="REG", block_week=w, games=games
        )
        counts.append(e["training_rows_available_before_block"])
    assert counts == [0, 1, 2, 3]
    blocks = []
    for w in range(1, 5):
        e = _build_exposure_for_block(
            block_season=2018, block_season_type="REG", block_week=w, games=games
        )
        blocks.append(e["training_block_count"])
    assert blocks == [0, 1, 2, 3]


def test_season_min_max_truthful() -> None:
    games = _make_games([
        {"season": 2018, "season_type": "REG", "week": 1, "target_margin": 3},
        {"season": 2019, "season_type": "REG", "week": 1, "target_margin": 3},
        {"season": 2020, "season_type": "REG", "week": 1, "target_margin": 3},
    ])
    e = _build_exposure_for_block(
        block_season=2021, block_season_type="REG", block_week=1, games=games
    )
    assert e["training_season_min"] == 2018
    assert e["training_season_max"] == 2020
