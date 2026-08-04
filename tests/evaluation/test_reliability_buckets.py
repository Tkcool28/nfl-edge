"""Reliability bucket coverage tests.

Verifies the complete, non-overlapping 10-bucket schema:

- every binary-scored row belongs to exactly one bucket;
- probability 1.0 belongs to the final bucket;
- empty bucket averages are null (not 0.0);
- sum of bucket counts equals binary_scored_games.

Boundary tests cover:

- 0.01
- 0.0999
- 0.10
- 0.50
- 0.8999
- 0.90
- 0.999
- 1.0
"""

from __future__ import annotations

import polars as pl
import pytest

from nfl_edge.evaluation.calibration import reliability_table


def _make_pred(prob: float, season: int = 2024) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "predicted_home_win_probability": [float(prob)],
            "actual_home_win": [True],
            "actual_tie": [False],
            "target_available": [True],
            "season": [season],
        }
    )


@pytest.mark.parametrize(
    "prob, expected_bucket_index",
    [
        (0.01, 0),
        (0.0999, 0),
        (0.10, 1),
        (0.50, 5),
        (0.8999, 8),
        (0.90, 9),
        (0.999, 9),
        (1.00, 9),
    ],
)
def test_boundary_probability_goes_to_expected_bucket(
    prob: float, expected_bucket_index: int
) -> None:
    df = _make_pred(prob)
    table = reliability_table(df)
    assert len(table) == 10
    nonzero = [r for r in table if r["count"] == 1]
    assert len(nonzero) == 1
    assert table[expected_bucket_index]["count"] == 1


def test_every_row_belongs_to_exactly_one_bucket() -> None:
    probs = [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95, 1.0]
    df = pl.DataFrame(
        {
            "predicted_home_win_probability": probs,
            "actual_home_win": [True] * len(probs),
            "actual_tie": [False] * len(probs),
            "target_available": [True] * len(probs),
            "season": [2024] * len(probs),
        }
    )
    table = reliability_table(df)
    total = sum(r["count"] for r in table)
    assert total == len(probs)


def test_no_row_assigned_twice() -> None:
    # Sample many rows and verify the sum of bucket counts equals the
    # total. There is no double-counting in the implementation.
    probs = [0.05 + 0.01 * i for i in range(50)]
    df = pl.DataFrame(
        {
            "predicted_home_win_probability": probs,
            "actual_home_win": [True] * len(probs),
            "actual_tie": [False] * len(probs),
            "target_available": [True] * len(probs),
            "season": [2024] * len(probs),
        }
    )
    table = reliability_table(df)
    total = sum(r["count"] for r in table)
    assert total == len(probs)


def test_probability_one_belongs_to_final_bucket() -> None:
    df = _make_pred(1.0)
    table = reliability_table(df)
    assert table[9]["count"] == 1
    assert table[8]["count"] == 0


def test_empty_bucket_averages_are_null() -> None:
    # Only one row -> 9 empty buckets
    df = _make_pred(0.5)
    table = reliability_table(df)
    for r in table:
        if r["count"] == 0:
            assert r["mean_predicted_probability"] is None
            assert r["actual_home_win_rate"] is None
        else:
            assert r["mean_predicted_probability"] is not None
            assert r["actual_home_win_rate"] is not None


def test_nonempty_bucket_averages_are_correct() -> None:
    df = pl.DataFrame(
        {
            "predicted_home_win_probability": [0.55, 0.55, 0.55],
            "actual_home_win": [True, True, False],
            "actual_tie": [False, False, False],
            "target_available": [True, True, True],
            "season": [2024, 2024, 2024],
        }
    )
    table = reliability_table(df)
    nonempty = [r for r in table if r["count"] > 0]
    assert len(nonempty) == 1
    bucket = nonempty[0]
    assert bucket["count"] == 3
    assert abs(bucket["mean_predicted_probability"] - 0.55) < 1e-9
    assert abs(bucket["actual_home_win_rate"] - 2 / 3) < 1e-9
