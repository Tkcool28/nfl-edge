"""Focused in-memory contract tests for Totals V1 walk-forward preparation."""

from __future__ import annotations

from datetime import datetime, timezone

import polars as pl
import pytest

from nfl_edge.backtest.totals_walk_forward import (
    IDENTITY_COLUMNS,
    TARGET_COLUMNS,
    run_totals_walk_forward,
)
from nfl_edge.common.errors import SealedHoldoutAccessError, WalkForwardError
from nfl_edge.features.totals_v1.feature_table import EXACT_90_COLUMNS
from nfl_edge.features.totals_v1.season import DEVELOPMENT_SEASON_MAX

UTC = timezone.utc


def _at(day: int) -> datetime:
    return datetime(2024, 1, day, 12, tzinfo=UTC)


def _modeling_table(blocks: list[tuple[str, int, datetime, tuple[str, ...]]]) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for season_type, week, _, game_ids in blocks:
        for ordinal, game_id in enumerate(game_ids):
            row: dict[str, object] = {
                "game_id": game_id,
                "season": DEVELOPMENT_SEASON_MAX,
                "season_type": season_type,
                "week": week,
                "home_team": f"H{ordinal}",
                "away_team": f"A{ordinal}",
                "block_id": f"{DEVELOPMENT_SEASON_MAX}_{season_type}_W{week:02d}",
            }
            row.update({column: float(ordinal) for column in EXACT_90_COLUMNS})
            row.update(
                {
                    "home_score": 20 + ordinal,
                    "away_score": 17 + ordinal,
                    "target_total_points": 37 + ordinal,
                }
            )
            rows.append(row)
    return pl.DataFrame(rows)


def _availability(
    blocks: list[tuple[str, int, datetime, tuple[str, ...]]],
    eligible_days: dict[tuple[str, int], int],
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "season": [DEVELOPMENT_SEASON_MAX] * len(blocks),
            "season_type": [season_type for season_type, _, _, _ in blocks],
            "week": [week for _, week, _, _ in blocks],
            "prediction_as_of_utc": [as_of for _, _, as_of, _ in blocks],
            "eligible_for_features_at_utc": [
                _at(eligible_days[(season_type, week)]) for season_type, week, _, _ in blocks
            ],
        }
    )


def _block(run, season_type: str, week: int):
    return next(
        block
        for block in run.blocks
        if (block.target_block.season_type, block.target_block.week) == (season_type, week)
    )


def test_same_block_outcomes_are_excluded() -> None:
    blocks = [("REG", 1, _at(2), ("r1",)), ("REG", 2, _at(3), ("r2",))]
    run = run_totals_walk_forward(_modeling_table(blocks), _availability(blocks, {("REG", 1): 1, ("REG", 2): 1}))

    assert _block(run, "REG", 2).training_game_ids == ("r1",)


def test_future_blocks_are_excluded() -> None:
    blocks = [
        ("REG", 1, _at(2), ("r1",)),
        ("REG", 2, _at(3), ("r2",)),
        ("WC", 19, _at(4), ("wc",)),
    ]
    run = run_totals_walk_forward(
        _modeling_table(blocks),
        _availability(blocks, {("REG", 1): 1, ("REG", 2): 1, ("WC", 19): 1}),
    )

    assert _block(run, "REG", 2).training_game_ids == ("r1",)


def test_earlier_not_yet_matured_blocks_are_excluded() -> None:
    blocks = [("REG", 1, _at(2), ("r1",)), ("REG", 2, _at(3), ("r2",))]
    run = run_totals_walk_forward(_modeling_table(blocks), _availability(blocks, {("REG", 1): 4, ("REG", 2): 1}))

    assert _block(run, "REG", 2).training_game_ids == ()


def test_availability_equality_boundary_is_included() -> None:
    blocks = [("REG", 1, _at(2), ("r1",)), ("REG", 2, _at(3), ("r2",))]
    run = run_totals_walk_forward(_modeling_table(blocks), _availability(blocks, {("REG", 1): 3, ("REG", 2): 1}))

    assert _block(run, "REG", 2).training_game_ids == ("r1",)


def test_postseason_targets_use_canonical_reg_to_super_bowl_order() -> None:
    blocks = [
        ("SB", 22, _at(6), ("sb",)),
        ("CON", 21, _at(5), ("con",)),
        ("DIV", 20, _at(4), ("div",)),
        ("WC", 19, _at(3), ("wc",)),
        ("REG", 18, _at(2), ("reg18",)),
        ("REG", 17, _at(1), ("reg17",)),
    ]
    availability = _availability(
        blocks,
        {(season_type, week): 1 for season_type, week, _, _ in blocks},
    )

    run = run_totals_walk_forward(_modeling_table(blocks), availability)

    assert [(block.target_block.season_type, block.target_block.week) for block in run.blocks] == [
        ("REG", 17),
        ("REG", 18),
        ("WC", 19),
        ("DIV", 20),
        ("CON", 21),
        ("SB", 22),
    ]


def test_training_game_ids_are_deterministic() -> None:
    blocks = [
        ("REG", 1, _at(2), ("r1b", "r1a")),
        ("REG", 2, _at(3), ("r2b", "r2a")),
        ("WC", 19, _at(4), ("wc",)),
    ]
    availability = _availability(
        blocks,
        {(season_type, week): 1 for season_type, week, _, _ in blocks},
    )
    modeling_table = _modeling_table(blocks)

    first = run_totals_walk_forward(modeling_table, availability)
    second = run_totals_walk_forward(modeling_table.sample(fraction=1.0, shuffle=True, seed=7), availability)

    assert _block(first, "WC", 19).training_game_ids == ("r1a", "r1b", "r2a", "r2b")
    assert _block(second, "WC", 19).training_game_ids == _block(first, "WC", 19).training_game_ids


def test_training_rows_are_deterministic_under_shuffled_modeling_input() -> None:
    blocks = [("REG", 1, _at(2), ("r1b", "r1a")), ("REG", 2, _at(3), ("r2",))]
    availability = _availability(blocks, {("REG", 1): 1, ("REG", 2): 1})
    modeling_table = _modeling_table(blocks)

    first = run_totals_walk_forward(modeling_table, availability)
    second = run_totals_walk_forward(modeling_table.reverse(), availability)

    assert _block(first, "REG", 2).training_rows.equals(_block(second, "REG", 2).training_rows)


def test_prediction_rows_have_deterministic_game_id_ordering() -> None:
    blocks = [("REG", 1, _at(2), ("r1",)), ("REG", 2, _at(3), ("r2b", "r2a"))]
    run = run_totals_walk_forward(
        _modeling_table(blocks).reverse(),
        _availability(blocks, {("REG", 1): 1, ("REG", 2): 1}),
    )

    assert _block(run, "REG", 2).prediction_rows["game_id"].to_list() == ["r2a", "r2b"]


def test_prediction_surface_is_exactly_identity_plus_exact_features_without_targets() -> None:
    blocks = [("REG", 1, _at(2), ("r1",))]
    run = run_totals_walk_forward(_modeling_table(blocks), _availability(blocks, {("REG", 1): 1}))
    prediction_rows = _block(run, "REG", 1).prediction_rows

    assert prediction_rows.columns == [*IDENTITY_COLUMNS, *EXACT_90_COLUMNS]
    assert not set(TARGET_COLUMNS).intersection(prediction_rows.columns)


def test_outcome_surface_is_separate_identity_plus_target_only() -> None:
    blocks = [("REG", 1, _at(2), ("r1",))]
    run = run_totals_walk_forward(_modeling_table(blocks), _availability(blocks, {("REG", 1): 1}))
    outcome_rows = _block(run, "REG", 1).outcome_rows

    assert outcome_rows is not None
    assert outcome_rows.columns == [*IDENTITY_COLUMNS, "target_total_points"]


def test_training_surface_retains_target_total_points() -> None:
    blocks = [("REG", 1, _at(2), ("r1",))]
    run = run_totals_walk_forward(_modeling_table(blocks), _availability(blocks, {("REG", 1): 1}))

    assert "target_total_points" in _block(run, "REG", 1).training_rows.columns


def test_sealed_holdout_modeling_table_is_rejected() -> None:
    blocks = [("REG", 1, _at(2), ("r1",))]
    modeling_table = _modeling_table(blocks).with_columns(pl.lit(DEVELOPMENT_SEASON_MAX + 1).alias("season"))

    with pytest.raises(SealedHoldoutAccessError):
        run_totals_walk_forward(modeling_table, _availability(blocks, {("REG", 1): 1}))


def test_sealed_holdout_availability_table_is_rejected() -> None:
    blocks = [("REG", 1, _at(2), ("r1",))]
    availability = _availability(blocks, {("REG", 1): 1}).with_columns(
        pl.lit(DEVELOPMENT_SEASON_MAX + 1).alias("season")
    )

    with pytest.raises(SealedHoldoutAccessError):
        run_totals_walk_forward(_modeling_table(blocks), availability)


def test_missing_prediction_as_of_utc_is_a_hard_failure() -> None:
    blocks = [("REG", 1, _at(2), ("r1",))]
    availability = _availability(blocks, {("REG", 1): 1}).drop("prediction_as_of_utc")

    with pytest.raises(WalkForwardError, match="prediction_as_of_utc"):
        run_totals_walk_forward(_modeling_table(blocks), availability)


def test_duplicate_availability_block_is_a_hard_failure() -> None:
    blocks = [("REG", 1, _at(2), ("r1",))]
    availability = _availability(blocks, {("REG", 1): 1})

    with pytest.raises(WalkForwardError, match="exactly one row"):
        run_totals_walk_forward(_modeling_table(blocks), pl.concat([availability, availability]))
