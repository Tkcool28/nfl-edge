"""Tests for the dropback-fallback provenance wiring (Phase 3B).

The dropback fallback predicate is:
    VFP AND qb_dropback IS NULL AND (pass_attempt == 1 OR sack == 1)
and is exposed via the ``is_dropback_fallback`` annotation column. The
provenance layer tracks the count of qualifying rows as the
informational ``dropback_fallback_rows`` counter. This counter is NOT
a violation: ``valid_development_build`` and
``assert_clean_development`` ignore it.

These tests exercise the wiring added in
:func:`nfl_edge.features.totals_v1.game_observations.build_game_observations_with_provenance`,
which is the smallest path that already had annotated PBP rows and the
provenance counters available.
"""

from __future__ import annotations

import polars as pl
import pytest

from nfl_edge.features.totals_v1 import (
    annotate_pbp_semantics,
    build_game_observations_with_provenance,
)
from nfl_edge.features.totals_v1.provenance import (
    BuildProvenance,
    ProvenanceCounters,
)


# ---------------------------------------------------------------------------
# Row fixture
# ---------------------------------------------------------------------------


def _row(
    *,
    game_id: str = "g",
    posteam: str | None = "KC",
    defteam: str | None = "BAL",
    play_type: str | None = "pass",
    pass_attempt: float | None = 1.0,
    qb_dropback: float | None = 1.0,
    sack: float | None = 0.0,
    fixed_drive: float = 1.0,
    fixed_drive_result: str | None = "Punt",
    play_id: float = 1.0,
    season: int = 2024,
    play_deleted: float = 0.0,
    aborted_play: float = 0.0,
    rush_attempt: float | None = 0.0,
    complete_pass: float | None = 1.0,
    qb_kneel: float = 0.0,
    qb_spike: float = 0.0,
    epa: float | None = 0.0,
    success: float | None = 0.0,
    interception: float | None = None,
    fumble_lost: float | None = None,
    # Phase 3C required-column defaults (null when not under test).
    qtr: float | None = None,
    score_differential: float | None = None,
    game_seconds_remaining: float | None = None,
    yardline_100: float | None = None,
    goal_to_go: float | None = None,
    yards_gained: float | None = None,
    air_yards: float | None = None,
    yards_after_catch: float | None = None,
) -> dict:
    return {
        "game_id": game_id,
        "fixed_drive": fixed_drive,
        "play_id": play_id,
        "posteam": posteam,
        "defteam": defteam,
        "play_type": play_type,
        "play_deleted": play_deleted,
        "aborted_play": aborted_play,
        "pass_attempt": pass_attempt,
        "rush_attempt": rush_attempt,
        "complete_pass": complete_pass,
        "qb_dropback": qb_dropback,
        "qb_kneel": qb_kneel,
        "qb_spike": qb_spike,
        "sack": sack,
        "epa": epa,
        "success": success,
        "interception": interception,
        "fumble_lost": fumble_lost,
        "fixed_drive_result": fixed_drive_result,
        "season": season,
        "qtr": qtr,
        "score_differential": score_differential,
        "game_seconds_remaining": game_seconds_remaining,
        "yardline_100": yardline_100,
        "goal_to_go": goal_to_go,
        "yards_gained": yards_gained,
        "air_yards": air_yards,
        "yards_after_catch": yards_after_catch,
    }


def _game_frame(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows)


def _build(rows):
    """Build observations + counters with the canonical two-team frame."""
    obs, counters = build_game_observations_with_provenance(
        block_id="blk",
        pbp_frames={"g1": _game_frame(rows)},
        game_to_teams={"g1": ("BAL", "KC")},
    )
    return obs, counters


# ---------------------------------------------------------------------------
# Zero fallback
# ---------------------------------------------------------------------------


def test_zero_fallback_rows_produces_zero_counter():
    # Two ordinary VFP rows: neither uses the fallback path.
    rows = [
        _row(play_id=1.0, posteam="KC", defteam="BAL", qb_dropback=1.0),
        _row(play_id=2.0, posteam="BAL", defteam="KC", qb_dropback=1.0, fixed_drive=2.0),
    ]
    _, counters = _build(rows)
    assert counters.dropback_fallback_rows == 0
    bp = counters.to_build_provenance()
    assert bp.dropback_fallback_rows == 0
    assert bp.to_dict()["dropback_fallback_rows"] == 0


# ---------------------------------------------------------------------------
# One fallback
# ---------------------------------------------------------------------------


def test_one_fallback_qb_dropback_null_pass_attempt_one():
    rows = [
        # VFP + qb_dropback=NULL + pass_attempt=1 -> fallback qualifies.
        _row(play_id=1.0, posteam="KC", defteam="BAL",
             qb_dropback=None, pass_attempt=1.0),
        # Second-team play for team-pair resolution.
        _row(play_id=2.0, posteam="BAL", defteam="KC",
             qb_dropback=1.0, fixed_drive=2.0),
    ]
    _, counters = _build(rows)
    assert counters.dropback_fallback_rows == 1
    bp = counters.to_build_provenance()
    assert bp.dropback_fallback_rows == 1


def test_one_fallback_qb_dropback_null_sack_one():
    rows = [
        _row(play_id=1.0, posteam="KC", defteam="BAL",
             qb_dropback=None, pass_attempt=None, sack=1.0,
             complete_pass=None, epa=None, success=None),
        _row(play_id=2.0, posteam="BAL", defteam="KC",
             qb_dropback=1.0, fixed_drive=2.0),
    ]
    _, counters = _build(rows)
    assert counters.dropback_fallback_rows == 1


# ---------------------------------------------------------------------------
# Multiple fallback rows
# ---------------------------------------------------------------------------


def test_multiple_fallback_rows_sum_exactly():
    rows = [
        _row(play_id=1.0, posteam="KC", defteam="BAL",
             qb_dropback=None, pass_attempt=1.0),
        _row(play_id=2.0, posteam="KC", defteam="BAL",
             qb_dropback=None, pass_attempt=1.0, fixed_drive=2.0),
        _row(play_id=3.0, posteam="KC", defteam="BAL",
             qb_dropback=None, pass_attempt=None, sack=1.0,
             complete_pass=None, epa=None, success=None,
             fixed_drive=3.0),
        # Non-fallback second-team row for team-pair resolution.
        _row(play_id=4.0, posteam="BAL", defteam="KC",
             qb_dropback=1.0, fixed_drive=4.0),
    ]
    _, counters = _build(rows)
    assert counters.dropback_fallback_rows == 3


# ---------------------------------------------------------------------------
# Non-fallback cases excluded
# ---------------------------------------------------------------------------


def test_qb_dropback_one_is_not_fallback():
    rows = [
        _row(play_id=1.0, posteam="KC", defteam="BAL", qb_dropback=1.0),
        _row(play_id=2.0, posteam="BAL", defteam="KC", qb_dropback=1.0, fixed_drive=2.0),
    ]
    _, counters = _build(rows)
    assert counters.dropback_fallback_rows == 0


def test_qb_dropback_zero_with_sack_one_is_not_fallback():
    rows = [
        _row(play_id=1.0, posteam="KC", defteam="BAL",
             qb_dropback=0.0, sack=1.0, pass_attempt=None,
             complete_pass=None, epa=None, success=None),
        _row(play_id=2.0, posteam="BAL", defteam="KC",
             qb_dropback=1.0, fixed_drive=2.0),
    ]
    _, counters = _build(rows)
    assert counters.dropback_fallback_rows == 0


def test_non_vFP_row_is_not_fallback_even_with_null_qb_dropback():
    rows = [
        # Marker row: posteam=null -> not VFP, qb_dropback=null -> would
        # otherwise look like a fallback. Must NOT count.
        _row(play_id=1.0, posteam=None, defteam=None, play_type=None,
             qb_dropback=None, pass_attempt=None, complete_pass=None,
             rush_attempt=None, epa=None, success=None),
        _row(play_id=2.0, posteam="BAL", defteam="KC",
             qb_dropback=1.0, fixed_drive=2.0),
    ]
    _, counters = _build(rows)
    assert counters.dropback_fallback_rows == 0


def test_null_qb_dropback_without_pass_attempt_or_sack_is_not_fallback():
    rows = [
        # VFP + qb_dropback=null but neither pass_attempt nor sack set.
        _row(play_id=1.0, posteam="KC", defteam="BAL",
             qb_dropback=None, pass_attempt=0.0, sack=0.0,
             play_type="run", rush_attempt=1.0),
        _row(play_id=2.0, posteam="BAL", defteam="KC",
             qb_dropback=1.0, fixed_drive=2.0),
    ]
    _, counters = _build(rows)
    assert counters.dropback_fallback_rows == 0


def test_deleted_or_aborted_rows_excluded_from_fallback():
    rows = [
        _row(play_id=1.0, posteam="KC", defteam="BAL",
             qb_dropback=None, pass_attempt=1.0, play_deleted=1.0),
        _row(play_id=2.0, posteam="BAL", defteam="KC",
             qb_dropback=1.0, fixed_drive=2.0),
    ]
    _, counters = _build(rows)
    assert counters.dropback_fallback_rows == 0


# ---------------------------------------------------------------------------
# Counter is informational (NOT a violation)
# ---------------------------------------------------------------------------


def test_dropback_fallback_rows_does_not_affect_valid_development_build():
    rows = [
        _row(play_id=1.0, posteam="KC", defteam="BAL",
             qb_dropback=None, pass_attempt=1.0),
        _row(play_id=2.0, posteam="BAL", defteam="KC",
             qb_dropback=1.0, fixed_drive=2.0),
    ]
    _, counters = _build(rows)
    bp = counters.to_build_provenance()
    assert bp.dropback_fallback_rows == 1
    # The fallback counter must NOT prevent a build from being valid.
    assert bp.valid_development_build is True
    bp.assert_clean_development()  # must not raise


def test_dropback_fallback_counter_not_in_violations_dict():
    rows = [
        _row(play_id=1.0, posteam="KC", defteam="BAL",
             qb_dropback=None, pass_attempt=1.0),
        _row(play_id=2.0, posteam="BAL", defteam="KC",
             qb_dropback=1.0, fixed_drive=2.0),
    ]
    _, counters = _build(rows)
    bp = counters.to_build_provenance()
    assert "dropback_fallback_rows" not in bp.to_dict()["violations"]


def test_zero_counters_has_zero_fallback():
    c = ProvenanceCounters()
    assert c.dropback_fallback_rows == 0
    bp = c.to_build_provenance()
    assert isinstance(bp, BuildProvenance)
    assert bp.dropback_fallback_rows == 0


def test_add_dropback_fallback_rows_returns_incremented_counter():
    c = ProvenanceCounters()
    c2 = c.add_dropback_fallback_rows(5)
    assert c.dropback_fallback_rows == 0
    assert c2.dropback_fallback_rows == 5
    c3 = c2.add_dropback_fallback_rows(3)
    assert c3.dropback_fallback_rows == 8


# ---------------------------------------------------------------------------
# Source-of-truth cross-check against the annotation column
# ---------------------------------------------------------------------------


def test_counter_matches_is_dropback_fallback_column_sum():
    rows = [
        _row(play_id=1.0, posteam="KC", defteam="BAL",
             qb_dropback=None, pass_attempt=1.0),
        _row(play_id=2.0, posteam="KC", defteam="BAL",
             qb_dropback=1.0, fixed_drive=2.0),
        _row(play_id=3.0, posteam="KC", defteam="BAL",
             qb_dropback=0.0, sack=1.0, pass_attempt=None,
             complete_pass=None, epa=None, success=None, fixed_drive=3.0),
        _row(play_id=4.0, posteam="BAL", defteam="KC",
             qb_dropback=1.0, fixed_drive=4.0),
    ]
    _, counters = _build(rows)
    # Manually compute the source-of-truth count from the annotation column.
    expected = int(
        annotate_pbp_semantics(_game_frame(rows))["is_dropback_fallback"].sum()
    )
    assert counters.dropback_fallback_rows == expected == 1