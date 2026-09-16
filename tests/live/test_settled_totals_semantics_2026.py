from __future__ import annotations

import polars as pl
import pytest

from nfl_edge.common.errors import SealedHoldoutAccessError
from nfl_edge.features.totals_v1.game_observations import (
    build_game_observations,
    build_game_observations_with_provenance,
)
from nfl_edge.features.totals_v1.pbp_semantics import (
    PbpSemanticsError,
    annotate_live_settled_pbp_semantics,
    annotate_pbp_semantics,
)


def _row(
    *,
    game_id: str = "2026_01_BAL_BUF",
    season: int = 2026,
    posteam: str = "BUF",
    defteam: str = "BAL",
    fixed_drive: float = 1.0,
    play_id: float = 1.0,
) -> dict[str, object]:
    return {
        "game_id": game_id,
        "season": season,
        "posteam": posteam,
        "defteam": defteam,
        "play_type": "pass",
        "play_deleted": 0.0,
        "aborted_play": 0.0,
        "pass_attempt": 1.0,
        "rush_attempt": 0.0,
        "complete_pass": 1.0,
        "qb_dropback": 1.0,
        "qb_kneel": 0.0,
        "qb_spike": 0.0,
        "sack": 0.0,
        "epa": 0.25,
        "success": 1.0,
        "interception": 0.0,
        "fumble_lost": 0.0,
        "fixed_drive": fixed_drive,
        "fixed_drive_result": "Punt",
        "play_id": play_id,
        "qtr": 1.0,
        "score_differential": 0.0,
        "game_seconds_remaining": 3500.0 - play_id,
        "yardline_100": 75.0,
        "goal_to_go": 0.0,
        "yards_gained": 8.0,
        "air_yards": 6.0,
        "yards_after_catch": 2.0,
    }


def _frame(*rows: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame(list(rows))


def test_development_annotator_still_rejects_2026() -> None:
    with pytest.raises(SealedHoldoutAccessError):
        annotate_pbp_semantics(_frame(_row()))


def test_settled_live_annotator_accepts_only_2026() -> None:
    annotated = annotate_live_settled_pbp_semantics(_frame(_row()))
    assert annotated["is_vfp"].to_list() == [True]

    for season in (2024, 2025):
        with pytest.raises(PbpSemanticsError, match="only season 2026"):
            annotate_live_settled_pbp_semantics(_frame(_row(season=season)))


def test_game_observation_default_path_remains_development_only() -> None:
    frame = _frame(
        _row(posteam="BUF", defteam="BAL", fixed_drive=1.0, play_id=1.0),
        _row(posteam="BAL", defteam="BUF", fixed_drive=2.0, play_id=2.0),
    )
    with pytest.raises(SealedHoldoutAccessError):
        build_game_observations(
            block_id="2026_REG_W01",
            pbp_frames={"2026_01_BAL_BUF": frame},
            game_to_teams={"2026_01_BAL_BUF": ("BUF", "BAL")},
        )


def test_settled_live_game_observations_use_frozen_semantics_without_opening_holdout() -> None:
    frame = _frame(
        _row(posteam="BUF", defteam="BAL", fixed_drive=1.0, play_id=1.0),
        _row(posteam="BAL", defteam="BUF", fixed_drive=2.0, play_id=2.0),
    )
    observations, provenance = build_game_observations_with_provenance(
        block_id="2026_REG_W01",
        pbp_frames={"2026_01_BAL_BUF": frame},
        game_to_teams={"2026_01_BAL_BUF": ("BUF", "BAL")},
        annotation_fn=annotate_live_settled_pbp_semantics,
    )
    assert len(observations) == 1
    assert observations[0].game_id == "2026_01_BAL_BUF"
    assert set(observations[0].team_updates) == {"BAL", "BUF"}
    assert provenance.dropback_fallback_rows == 0
