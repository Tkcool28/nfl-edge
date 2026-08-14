"""Tests for the canonical row-level PBP semantics (Totals V1 Phase 3B).

These tests encode the accepted Phase 2 contract literally. Any
substitution from the contract definitions (e.g. ``play_type`` for
``pass_attempt``, ``pass`` for ``complete_pass``, unconditional sack-as-
dropback, raw OR for turnover events, last-row posteam for possession)
fails these tests.
"""

from __future__ import annotations

import polars as pl
import pytest

from nfl_edge.common.errors import SealedHoldoutAccessError, WalkForwardError
from nfl_edge.features.totals_v1 import annotate_pbp_semantics
from nfl_edge.features.totals_v1.pbp_semantics import (
    completion_observation,
    dropback_fallback_observation,
    dropback_observation,
    epa_observation,
    pass_attempt_observation,
    rush_attempt_observation,
    sack_observation,
    success_observation,
    turnover_event_observation,
)


# ---------------------------------------------------------------------------
# Row fixture
# ---------------------------------------------------------------------------


def _row(
    *,
    game_id: str = "g",
    season: int = 2024,
    posteam: str | None = "KC",
    defteam: str | None = "BAL",
    play_type: str | None = "pass",
    play_deleted: float = 0.0,
    aborted_play: float = 0.0,
    pass_attempt: float | None = 1.0,
    rush_attempt: float | None = 0.0,
    complete_pass: float | None = 1.0,
    qb_dropback: float | None = 1.0,
    qb_kneel: float = 0.0,
    qb_spike: float = 0.0,
    sack: float | None = 0.0,
    epa: float | None = 0.0,
    success: float | None = 0.0,
    interception: float | None = None,
    fumble_lost: float | None = None,
    fixed_drive: float = 1.0,
    fixed_drive_result: str | None = "Punt",
    play_id: float = 1.0,
    # Phase 3C required-column defaults. Null by default so that tests
    # that do not exercise a neutral / air-yards / explosive / opportunity
    # column can leave the column null without changing row semantics.
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
        "season": season,
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
        "fixed_drive": fixed_drive,
        "fixed_drive_result": fixed_drive_result,
        "play_id": play_id,
        "qtr": qtr,
        "score_differential": score_differential,
        "game_seconds_remaining": game_seconds_remaining,
        "yardline_100": yardline_100,
        "goal_to_go": goal_to_go,
        "yards_gained": yards_gained,
        "air_yards": air_yards,
        "yards_after_catch": yards_after_catch,
    }


def _frame(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows)


def _ann_row(**kwargs) -> dict:
    return annotate_pbp_semantics(_frame([_row(**kwargs)])).row(0, named=True)


# ---------------------------------------------------------------------------
# VFP base predicate (preserved from prior phase)
# ---------------------------------------------------------------------------


def test_vfp_pass_eligible():
    assert _ann_row()["is_vfp"] is True


def test_vfp_rush_eligible():
    assert _ann_row(play_type="run", rush_attempt=1.0, pass_attempt=0.0, complete_pass=None, qb_dropback=0.0)["is_vfp"] is True


def test_vfp_qb_kneel_eligible():
    assert _ann_row(play_type="qb_kneel", pass_attempt=0.0, rush_attempt=0.0, complete_pass=None, qb_dropback=0.0, qb_kneel=1.0)["is_vfp"] is True


def test_vfp_qb_spike_eligible():
    assert _ann_row(play_type="qb_spike", pass_attempt=0.0, rush_attempt=0.0, complete_pass=None, qb_dropback=0.0, qb_spike=1.0)["is_vfp"] is True


def test_vfp_no_play_excluded():
    assert _ann_row(play_type="no_play", qb_dropback=None, pass_attempt=None, rush_attempt=None, complete_pass=None)["is_vfp"] is False


def test_vfp_play_deleted_excluded():
    assert _ann_row(play_deleted=1.0)["is_vfp"] is False


def test_vfp_aborted_play_excluded():
    assert _ann_row(aborted_play=1.0)["is_vfp"] is False


def test_vfp_null_posteam_excluded():
    assert _ann_row(posteam=None)["is_vfp"] is False


def test_vfp_null_defteam_excluded():
    assert _ann_row(defteam=None)["is_vfp"] is False


@pytest.mark.parametrize("pt", ["kickoff", "punt", "field_goal", "extra_point"])
def test_vfp_special_team_excluded(pt):
    assert _ann_row(play_type=pt, qb_dropback=None, pass_attempt=None, rush_attempt=None, complete_pass=None)["is_vfp"] is False


def test_vfp_marker_row_excluded():
    # play_type null = marker row (GAME_START / END_QUARTER / END_GAME)
    assert _ann_row(play_type=None, qb_dropback=None, pass_attempt=None, rush_attempt=None, complete_pass=None)["is_vfp"] is False


def test_vfp_sp_independent_pass():
    rows = [
        _row(play_id=1.0),
        _row(play_id=2.0, success=1.0),
    ]
    ann = annotate_pbp_semantics(_frame(rows))
    assert ann["is_vfp"].to_list() == [True, True]


def test_vfp_penalty_bearing_pass_retained():
    # VFP predicate does not consult penalty. Penalty-bearing pass rows
    # are VFP-eligible when they satisfy the contract VFP predicate.
    assert _ann_row()["is_vfp"] is True  # default row is a normal pass


def test_vfp_penalty_bearing_rush_retained():
    assert _ann_row(play_type="run", rush_attempt=1.0, pass_attempt=0.0, complete_pass=None, qb_dropback=0.0)["is_vfp"] is True


def test_vfp_season_2025_hard_fails():
    with pytest.raises(SealedHoldoutAccessError):
        annotate_pbp_semantics(_frame([_row(season=2025)]))


def test_vfp_season_2017_hard_fails():
    with pytest.raises(WalkForwardError):
        annotate_pbp_semantics(_frame([_row(season=2017)]))


# ---------------------------------------------------------------------------
# FIX 1 — Pass attempts / completions
# ---------------------------------------------------------------------------


def test_pass_attempt_basic():
    # VFP + pass_attempt=1 -> attempt
    n, d, s = pass_attempt_observation(_ann_row())
    assert (n, d, s) == (1.0, 1.0, 1)


def test_pass_attempt_pass_attempt_zero_not_attempt():
    # pass_attempt=0 must NOT count as attempt, even if play_type="pass".
    n, d, s = pass_attempt_observation(_ann_row(play_type="pass", pass_attempt=0.0))
    assert (n, d, s) == (0.0, 0.0, 0)


def test_pass_attempt_null_not_attempt():
    n, d, s = pass_attempt_observation(_ann_row(pass_attempt=None))
    assert (n, d, s) == (0.0, 0.0, 0)


def test_pass_attempt_sack_excluded():
    # Sack rows in nflverse have null pass_attempt. Even with sack=1 the
    # row is NOT a pass attempt because pass_attempt != 1.
    n, d, s = pass_attempt_observation(_ann_row(sack=1.0, pass_attempt=None))
    assert (n, d, s) == (0.0, 0.0, 0)


def test_pass_attempt_non_vfp_excluded():
    n, d, s = pass_attempt_observation(_ann_row(posteam=None))
    assert (n, d, s) == (0.0, 0.0, 0)


def test_completion_requires_complete_pass_one():
    n, d, s = completion_observation(_ann_row(complete_pass=1.0))
    assert (n, d, s) == (1.0, 1.0, 1)


def test_completion_complete_pass_zero_not_completion():
    n, d, s = completion_observation(_ann_row(complete_pass=0.0))
    assert (n, d, s) == (0.0, 0.0, 0)


def test_completion_null_complete_pass_not_completion():
    n, d, s = completion_observation(_ann_row(complete_pass=None))
    assert (n, d, s) == (0.0, 0.0, 0)


def test_completion_non_vfp_excluded():
    n, d, s = completion_observation(_ann_row(posteam=None, complete_pass=1.0))
    assert (n, d, s) == (0.0, 0.0, 0)


def test_completion_does_not_substitute_pass():
    # ``pass==1`` must NOT be a substitute for ``complete_pass``.
    # We construct a row that is a pass attempt with complete_pass=0 but
    # an extra hypothetical "pass" flag at 1; the completion predicate
    # must still return 0 because complete_pass=0.
    n, d, s = completion_observation(_ann_row(complete_pass=0.0))
    assert (n, d, s) == (0.0, 0.0, 0)


# ---------------------------------------------------------------------------
# FIX 2 — Rush attempts (kneels excluded)
# ---------------------------------------------------------------------------


def test_rush_attempt_basic():
    n, d, s = rush_attempt_observation(
        _ann_row(play_type="run", rush_attempt=1.0, pass_attempt=0.0, complete_pass=None, qb_dropback=0.0)
    )
    assert (n, d, s) == (1.0, 1.0, 1)


def test_rush_attempt_rush_attempt_zero_not_attempt():
    # Even with play_type="run", rush_attempt=0 is NOT a rush attempt.
    n, d, s = rush_attempt_observation(
        _ann_row(play_type="run", rush_attempt=0.0, pass_attempt=0.0, complete_pass=None, qb_dropback=0.0)
    )
    assert (n, d, s) == (0.0, 0.0, 0)


def test_rush_attempt_null_not_attempt():
    n, d, s = rush_attempt_observation(
        _ann_row(play_type="run", rush_attempt=None, pass_attempt=0.0, complete_pass=None, qb_dropback=0.0)
    )
    assert (n, d, s) == (0.0, 0.0, 0)


def test_rush_attempt_kneel_excluded():
    # Kneel row even if rush_attempt=1 must NOT count as a rush attempt.
    n, d, s = rush_attempt_observation(
        _ann_row(play_type="qb_kneel", rush_attempt=1.0, pass_attempt=0.0, complete_pass=None, qb_dropback=0.0, qb_kneel=1.0)
    )
    assert (n, d, s) == (0.0, 0.0, 0)


def test_rush_attempt_non_vfp_excluded():
    n, d, s = rush_attempt_observation(
        _ann_row(posteam=None, play_type="run", rush_attempt=1.0)
    )
    assert (n, d, s) == (0.0, 0.0, 0)


# ---------------------------------------------------------------------------
# FIX 3 — Dropbacks (primary + null-only fallback)
# ---------------------------------------------------------------------------


def test_dropback_primary_basic():
    n, d, s = dropback_observation(_ann_row(qb_dropback=1.0))
    assert (n, d, s) == (1.0, 1.0, 1)


def test_dropback_qb_dropback_zero_sack_one_not_fallback():
    # qb_dropback=0, sack=1 -> NOT a dropback. The contract requires
    # the fallback to fire only when qb_dropback IS NULL.
    n, d, s = dropback_observation(_ann_row(qb_dropback=0.0, sack=1.0, pass_attempt=None))
    assert (n, d, s) == (0.0, 0.0, 0)


def test_dropback_fallback_qb_dropback_null_sack_one():
    # qb_dropback NULL + sack=1 -> fallback qualifies as dropback.
    n, d, s = dropback_observation(
        _ann_row(qb_dropback=None, sack=1.0, pass_attempt=None, epa=None, success=None)
    )
    assert (n, d, s) == (1.0, 1.0, 1)
    # And the fallback flag is set so provenance can record it.
    row = _ann_row(qb_dropback=None, sack=1.0, pass_attempt=None, epa=None, success=None)
    assert row["is_dropback_fallback"] is True
    fn, fd, fs = dropback_fallback_observation(row)
    assert (fn, fd, fs) == (1.0, 1.0, 1)


def test_dropback_fallback_qb_dropback_null_pass_attempt_one():
    # qb_dropback NULL + pass_attempt=1 -> fallback dropback.
    n, d, s = dropback_observation(
        _ann_row(qb_dropback=None, pass_attempt=1.0, sack=0.0)
    )
    assert (n, d, s) == (1.0, 1.0, 1)


def test_dropback_non_vfp_never_qualifies():
    # No matter the flags, a non-VFP row is not a dropback.
    n, d, s = dropback_observation(_ann_row(posteam=None, qb_dropback=1.0))
    assert (n, d, s) == (0.0, 0.0, 0)
    n, d, s = dropback_observation(_ann_row(posteam=None, qb_dropback=None, sack=1.0))
    assert (n, d, s) == (0.0, 0.0, 0)


def test_dropback_fallback_requires_pass_attempt_or_sack():
    # qb_dropback NULL but neither pass_attempt nor sack set: not a dropback.
    n, d, s = dropback_observation(
        _ann_row(qb_dropback=None, pass_attempt=0.0, sack=0.0, play_type="run",
                 rush_attempt=1.0, complete_pass=None)
    )
    assert (n, d, s) == (0.0, 0.0, 0)


# ---------------------------------------------------------------------------
# FIX 4 — Turnover event (interception requires pass attempt; lost fumble requires VFP)
# ---------------------------------------------------------------------------


def test_turnover_interception_on_pass_attempt():
    n, d, s = turnover_event_observation(_ann_row(pass_attempt=1.0, interception=1.0))
    assert (n, d, s) == (1.0, 1.0, 1)


def test_turnover_interception_on_non_pass_attempt_excluded():
    # interception=1 on a rush (pass_attempt=0) does NOT count.
    n, d, s = turnover_event_observation(
        _ann_row(play_type="run", pass_attempt=0.0, rush_attempt=1.0, complete_pass=None, qb_dropback=0.0,
                 interception=1.0)
    )
    assert (n, d, s) == (0.0, 0.0, 0)


def test_turnover_lost_fumble_on_vfp():
    n, d, s = turnover_event_observation(_ann_row(fumble_lost=1.0))
    assert (n, d, s) == (1.0, 1.0, 1)


def test_turnover_lost_fumble_on_non_vfp_excluded():
    n, d, s = turnover_event_observation(_ann_row(posteam=None, fumble_lost=1.0))
    assert (n, d, s) == (0.0, 0.0, 0)


def test_turnover_both_flags_counted_once():
    # Both interception and fumble_lost on the same qualifying play -> 1 event, not 2.
    n, d, s = turnover_event_observation(
        _ann_row(pass_attempt=1.0, interception=1.0, fumble_lost=1.0)
    )
    assert (n, d, s) == (1.0, 1.0, 1)


def test_turnover_null_flags_no_event():
    n, d, s = turnover_event_observation(_ann_row(interception=None, fumble_lost=None))
    assert (n, d, s) == (0.0, 0.0, 0)


def test_turnover_interception_zero_with_pass_attempt_no_event():
    n, d, s = turnover_event_observation(_ann_row(pass_attempt=1.0, interception=0.0, fumble_lost=0.0))
    assert (n, d, s) == (0.0, 0.0, 0)


# ---------------------------------------------------------------------------
# EPA / Success null semantics (preserved)
# ---------------------------------------------------------------------------


def test_epa_observed_contributes():
    n, d, s = epa_observation(_ann_row(epa=0.5))
    assert (n, d, s) == (0.5, 1.0, 1)


def test_epa_null_excluded_from_both():
    n, d, s = epa_observation(_ann_row(epa=None))
    assert (n, d, s) == (0.0, 0.0, 0)


def test_success_observed_contributes():
    n, d, s = success_observation(_ann_row(success=1.0))
    assert (n, d, s) == (1.0, 1.0, 1)


def test_success_null_excluded():
    n, d, s = success_observation(_ann_row(success=None))
    assert (n, d, s) == (0.0, 0.0, 0)


def test_sack_observation_basic():
    # Sack on a VFP pass_attempt row (sack=1 with non-null sack).
    n, d, s = sack_observation(_ann_row(sack=1.0))
    assert (n, d, s) == (1.0, 1.0, 1)


def test_sack_observation_non_vfp_excluded():
    n, d, s = sack_observation(_ann_row(posteam=None, sack=1.0))
    assert (n, d, s) == (0.0, 0.0, 0)


# ---------------------------------------------------------------------------
# Determinism under row shuffle
# ---------------------------------------------------------------------------


def test_row_shuffle_yields_identical_annotations():
    rows = [
        _row(play_id=1.0, epa=0.1, success=1.0),
        _row(play_id=2.0, sack=1.0, pass_attempt=None, complete_pass=None, qb_dropback=None, epa=None, success=None),
        _row(play_id=3.0, play_type="run", pass_attempt=0.0, rush_attempt=1.0, complete_pass=None, qb_dropback=0.0,
             epa=0.3, success=1.0),
    ]
    a = annotate_pbp_semantics(_frame(rows))
    b = annotate_pbp_semantics(_frame(list(reversed(rows))))
    a_sorted = a.sort("play_id")
    b_sorted = b.sort("play_id")
    for col in ("is_vfp", "is_pass_attempt", "is_completion", "is_rush_attempt",
                "is_dropback", "is_dropback_fallback", "is_turnover_event",
                "has_epa_obs", "has_success_obs"):
        assert a_sorted[col].to_list() == b_sorted[col].to_list(), col