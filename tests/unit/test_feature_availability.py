"""Unit tests for conservative weekly availability."""

from datetime import datetime, timezone

import polars as pl
import pytest

from nfl_edge.features.availability import (
    AvailabilityPolicy,
    build_weekly_availability,
    prediction_boundary_before,
    publication_boundary_after,
    record_is_eligible,
)

POLICY = AvailabilityPolicy(
    weekday=1,
    hour=12,
    minute=0,
    timezone_name="UTC",
)


def test_standard_and_postseason_week_boundaries_are_conservative_utc() -> None:
    games = pl.DataFrame(
        {
            "game_id": ["reg-thu", "reg-mon", "wc-sat", "wc-mon"],
            "season": [2024, 2024, 2024, 2024],
            "season_type": ["REG", "REG", "WC", "WC"],
            "week": [1, 1, 19, 19],
            "gameday": ["2024-09-05", "2024-09-09", "2025-01-11", "2025-01-13"],
        }
    )
    result = build_weekly_availability(games, POLICY).sort(["season", "week"])
    reg, postseason = result.to_dicts()
    assert reg["prediction_as_of_utc"] == datetime(2024, 9, 3, 12, tzinfo=timezone.utc)
    assert reg["eligible_for_features_at_utc"] == datetime(2024, 9, 10, 12, tzinfo=timezone.utc)
    assert postseason["prediction_as_of_utc"] == datetime(2025, 1, 7, 12, tzinfo=timezone.utc)
    assert postseason["eligible_for_features_at_utc"] == datetime(2025, 1, 14, 12, tzinfo=timezone.utc)
    assert "POSTSEASON" in postseason["availability_quality"]
    assert result.schema["eligible_for_features_at_utc"] == pl.Datetime("us", "UTC")


def test_tuesday_game_advances_publication_to_following_tuesday() -> None:
    assert publication_boundary_after("2024-12-24", POLICY) == datetime(
        2024, 12, 31, 12, tzinfo=timezone.utc
    )
    assert prediction_boundary_before("2024-12-24", POLICY) == datetime(
        2024, 12, 17, 12, tzinfo=timezone.utc
    )


def test_one_second_cutoff_rule() -> None:
    cutoff = datetime(2024, 9, 10, 12, tzinfo=timezone.utc)
    assert record_is_eligible(datetime(2024, 9, 10, 11, 59, 59, tzinfo=timezone.utc), cutoff)
    assert record_is_eligible(cutoff, cutoff)
    assert not record_is_eligible(datetime(2024, 9, 10, 12, 0, 1, tzinfo=timezone.utc), cutoff)


def test_availability_rejects_naive_timestamps_and_duplicate_games() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        record_is_eligible(datetime(2024, 9, 10, 12), datetime(2024, 9, 10, 12, tzinfo=timezone.utc))
    duplicate = pl.DataFrame(
        {
            "game_id": ["x", "x"],
            "season": [2024, 2024],
            "season_type": ["REG", "REG"],
            "week": [1, 1],
            "gameday": ["2024-09-05", "2024-09-05"],
        }
    )
    with pytest.raises(ValueError, match="duplicate game"):
        build_weekly_availability(duplicate, POLICY)
