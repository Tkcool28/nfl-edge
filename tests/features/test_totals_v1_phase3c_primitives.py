"""Focused Phase 3C primitive tests for Totals V1 (Totals feature contract v1).

These tests are organized by the ten Phase 3C primitive families plus a
multi-family integration test. Each boundary the Phase 3C spec lists is
covered by at least one dedicated test.

The tests build minimal PBP frames that exercise one boundary at a time
and assert against the contract-literal formula. The integration test
combines all families in a single two-team game and checks that the
final ``GameObservation`` shape is what the contract promises.
"""

from __future__ import annotations

import polars as pl
import pytest

from nfl_edge.features.totals_v1 import (
    METRIC_AIR_YARDS_PER_ATTEMPT_DEFENSE_ALLOWED,
    METRIC_AIR_YARDS_PER_ATTEMPT_OFFENSE,
    METRIC_EXPLOSIVE_PASS_RATE_DEFENSE_ALLOWED,
    METRIC_EXPLOSIVE_PASS_RATE_OFFENSE,
    METRIC_EXPLOSIVE_RUSH_RATE_DEFENSE_ALLOWED,
    METRIC_EXPLOSIVE_RUSH_RATE_OFFENSE,
    METRIC_GOAL_TO_GO_TD_RATE_DEFENSE_ALLOWED,
    METRIC_GOAL_TO_GO_TD_RATE_OFFENSE,
    METRIC_NEUTRAL_PASS_RATE_DEFENSE_ALLOWED,
    METRIC_NEUTRAL_PASS_RATE_OFFENSE,
    METRIC_NEUTRAL_SECONDS_PLAY_DEFENSE_ALLOWED,
    METRIC_NEUTRAL_SECONDS_PLAY_OFFENSE,
    METRIC_RED_ZONE_TD_RATE_DEFENSE_ALLOWED,
    METRIC_RED_ZONE_TD_RATE_OFFENSE,
    METRIC_SACKS_PER_DROPBACK_DEFENSE_ALLOWED,
    METRIC_SACKS_PER_DROPBACK_OFFENSE,
    METRIC_SECONDS_PLAY_DEFENSE_ALLOWED,
    METRIC_SECONDS_PLAY_OFFENSE,
    METRIC_YAC_PER_COMPLETION_DEFENSE_ALLOWED,
    METRIC_YAC_PER_COMPLETION_OFFENSE,
    annotate_pbp_semantics,
    build_game_observations,
)
from nfl_edge.features.totals_v1.game_observations import (
    aggregate_row_metrics,
    build_team_updates,
)
from nfl_edge.features.totals_v1.pace_observations import (
    PaceInterval,
    build_pace_intervals,
    game_half_for_qtr,
)


# ---------------------------------------------------------------------------
# Shared row fixture helper (covers all Phase 3C required columns).
# ---------------------------------------------------------------------------


def _row(
    *,
    game_id: str = "g1",
    play_id: float = 1.0,
    fixed_drive: float = 1.0,
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
    fixed_drive_result: str | None = "Punt",
    season: int = 2024,
    qtr: float | None = 2,
    score_differential: float | None = 0,
    game_seconds_remaining: float | None = 1800,
    yardline_100: float | None = 75,
    goal_to_go: float | None = 0,
    yards_gained: float | None = 5,
    air_yards: float | None = 3,
    yards_after_catch: float | None = 2,
) -> dict:
    return {
        "game_id": game_id,
        "play_id": play_id,
        "fixed_drive": fixed_drive,
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


def _ann(*plays) -> pl.DataFrame:
    return annotate_pbp_semantics(pl.DataFrame(list(plays)))


# ===========================================================================
# A. Neutral predicate boundary tests
# ===========================================================================


class TestNeutralPredicate:
    def test_qtr1_eligible(self):
        assert _ann(_row(qtr=1, score_differential=0,
                         game_seconds_remaining=3000))["is_neutral"][0] is True

    def test_qtr2_eligible(self):
        assert _ann(_row(qtr=2, score_differential=0,
                         game_seconds_remaining=3000))["is_neutral"][0] is True

    def test_qtr3_eligible(self):
        assert _ann(_row(qtr=3, score_differential=0,
                         game_seconds_remaining=3000))["is_neutral"][0] is True

    def test_qtr4_excluded(self):
        assert _ann(_row(qtr=4, score_differential=0,
                         game_seconds_remaining=3000))["is_neutral"][0] is False

    @pytest.mark.parametrize("score", [-8, 0, 8])
    def test_score_differential_boundaries_eligible(self, score):
        assert _ann(_row(qtr=2, score_differential=score,
                         game_seconds_remaining=3000))["is_neutral"][0] is True

    @pytest.mark.parametrize("score", [-9, 9])
    def test_score_differential_outside_window_excluded(self, score):
        assert _ann(_row(qtr=2, score_differential=score,
                         game_seconds_remaining=3000))["is_neutral"][0] is False

    def test_clock_exactly_900_eligible(self):
        assert _ann(_row(qtr=2, score_differential=0,
                         game_seconds_remaining=900))["is_neutral"][0] is True

    def test_clock_below_900_excluded(self):
        assert _ann(_row(qtr=2, score_differential=0,
                         game_seconds_remaining=899))["is_neutral"][0] is False

    def test_non_vfp_excluded(self):
        # play_type outside the VFP whitelist -> not VFP, not neutral.
        assert _ann(_row(play_type="no_play", qb_dropback=None,
                         pass_attempt=None, rush_attempt=None,
                         complete_pass=None, qtr=2,
                         score_differential=0,
                         game_seconds_remaining=3000))["is_neutral"][0] is False

    def test_null_score_differential_excluded(self):
        assert _ann(_row(qtr=2, score_differential=None,
                         game_seconds_remaining=3000))["is_neutral"][0] is False

    def test_null_clock_excluded(self):
        assert _ann(_row(qtr=2, score_differential=0,
                         game_seconds_remaining=None))["is_neutral"][0] is False


# ===========================================================================
# B. Pace interval tests
# ===========================================================================


class TestPaceIntervals:
    def test_ordinary_valid_pair(self):
        ann = _ann(
            _row(play_id=1.0, qtr=2, game_seconds_remaining=2000),
            _row(play_id=2.0, qtr=2, game_seconds_remaining=1980,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        intervals = build_pace_intervals(ann)
        assert len(intervals) == 1
        iv = intervals[0]
        assert iv.delta == 20.0
        assert iv.game_half == "first"

    def test_final_play_has_no_interval(self):
        ann = _ann(
            _row(play_id=1.0, qtr=2, game_seconds_remaining=2000),
            _row(play_id=2.0, qtr=2, game_seconds_remaining=1990,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
            _row(play_id=3.0, qtr=2, game_seconds_remaining=1980,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        intervals = build_pace_intervals(ann)
        # Pairs: (1,2) and (2,3) -- final play (3) contributes no pair.
        assert len(intervals) == 2
        assert {iv.prior_play_id for iv in intervals} == {1, 2}

    def test_zero_second_delta_excluded(self):
        ann = _ann(
            _row(play_id=1.0, qtr=2, game_seconds_remaining=2000),
            _row(play_id=2.0, qtr=2, game_seconds_remaining=2000,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        assert build_pace_intervals(ann) == []

    def test_negative_delta_excluded(self):
        ann = _ann(
            _row(play_id=1.0, qtr=2, game_seconds_remaining=2000),
            _row(play_id=2.0, qtr=2, game_seconds_remaining=2020,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        # Prior clock 2000, current 2020 -> delta -20. Excluded.
        assert build_pace_intervals(ann) == []

    def test_exactly_120_included(self):
        ann = _ann(
            _row(play_id=1.0, qtr=2, game_seconds_remaining=2000),
            _row(play_id=2.0, qtr=2, game_seconds_remaining=1880,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        intervals = build_pace_intervals(ann)
        assert len(intervals) == 1
        assert intervals[0].delta == 120.0

    def test_121_excluded(self):
        ann = _ann(
            _row(play_id=1.0, qtr=2, game_seconds_remaining=2000),
            _row(play_id=2.0, qtr=2, game_seconds_remaining=1879,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        assert build_pace_intervals(ann) == []

    def test_null_prior_clock_excluded(self):
        ann = _ann(
            _row(play_id=1.0, qtr=2, game_seconds_remaining=None),
            _row(play_id=2.0, qtr=2, game_seconds_remaining=1980,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        assert build_pace_intervals(ann) == []

    def test_null_current_clock_excluded(self):
        ann = _ann(
            _row(play_id=1.0, qtr=2, game_seconds_remaining=2000),
            _row(play_id=2.0, qtr=2, game_seconds_remaining=None,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        assert build_pace_intervals(ann) == []

    def test_quarter_crossing_excluded(self):
        # Pair crosses qtr 2 -> 3 boundary.
        ann = _ann(
            _row(play_id=1.0, qtr=2, game_seconds_remaining=10),
            _row(play_id=2.0, qtr=3, game_seconds_remaining=3590,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        assert build_pace_intervals(ann) == []

    def test_half_crossing_excluded(self):
        # Pair crosses first half (qtr 2) -> second half (qtr 3). Already
        # excluded by the same-qtr test; verify the second-half label
        # differs and the pair is rejected.
        ann = _ann(
            _row(play_id=1.0, qtr=2, game_seconds_remaining=20),
            _row(play_id=2.0, qtr=3, game_seconds_remaining=3590,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        intervals = build_pace_intervals(ann)
        assert intervals == []

    def test_regulation_ot_crossing_excluded(self):
        # Pair crosses regulation qtr 4 -> OT (qtr 5).
        ann = _ann(
            _row(play_id=1.0, qtr=4, game_seconds_remaining=10),
            _row(play_id=2.0, qtr=5, game_seconds_remaining=600,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        intervals = build_pace_intervals(ann)
        assert intervals == []

    def test_different_fixed_drive_excluded(self):
        ann = _ann(
            _row(play_id=1.0, fixed_drive=1.0, qtr=2,
                 game_seconds_remaining=2000),
            _row(play_id=2.0, fixed_drive=2.0, qtr=2,
                 game_seconds_remaining=1980,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        assert build_pace_intervals(ann) == []

    def test_different_posteam_excluded(self):
        ann = _ann(
            _row(play_id=1.0, posteam="KC", defteam="BAL", qtr=2,
                 game_seconds_remaining=2000),
            _row(play_id=2.0, posteam="BAL", defteam="KC", qtr=2,
                 game_seconds_remaining=1980,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        assert build_pace_intervals(ann) == []

    def test_spike_prior_excluded(self):
        ann = _ann(
            _row(play_id=1.0, play_type="qb_spike", pass_attempt=0.0,
                 rush_attempt=0.0, complete_pass=None, qb_dropback=0.0,
                 qb_spike=1.0, qtr=2, game_seconds_remaining=2000,
                 air_yards=None, yards_after_catch=None),
            _row(play_id=2.0, qtr=2, game_seconds_remaining=1980,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        assert build_pace_intervals(ann) == []

    def test_spike_current_excluded(self):
        ann = _ann(
            _row(play_id=1.0, qtr=2, game_seconds_remaining=2000),
            _row(play_id=2.0, play_type="qb_spike", pass_attempt=0.0,
                 rush_attempt=0.0, complete_pass=None, qb_dropback=0.0,
                 qb_spike=1.0, qtr=2, game_seconds_remaining=1980,
                 air_yards=None, yards_after_catch=None),
        )
        assert build_pace_intervals(ann) == []

    def test_kneel_prior_excluded(self):
        ann = _ann(
            _row(play_id=1.0, play_type="qb_kneel", pass_attempt=0.0,
                 rush_attempt=0.0, complete_pass=None, qb_dropback=0.0,
                 qb_kneel=1.0, qtr=2, game_seconds_remaining=2000,
                 air_yards=None, yards_after_catch=None),
            _row(play_id=2.0, qtr=2, game_seconds_remaining=1980,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        assert build_pace_intervals(ann) == []

    def test_kneel_current_excluded(self):
        ann = _ann(
            _row(play_id=1.0, qtr=2, game_seconds_remaining=2000),
            _row(play_id=2.0, play_type="qb_kneel", pass_attempt=0.0,
                 rush_attempt=0.0, complete_pass=None, qb_dropback=0.0,
                 qb_kneel=1.0, qtr=2, game_seconds_remaining=1980,
                 air_yards=None, yards_after_catch=None),
        )
        assert build_pace_intervals(ann) == []

    def test_penalty_bearing_vfp_retained(self):
        # Penalty-bearing rows are not categorically excluded -- if they
        # satisfy the VFP predicate they remain in pace.
        # A penalty on a completed pass typically produces a no_play or
        # a pass row depending on the enforcement. Use a regular pass row
        # as the contract says penalty-bearing VFPs remain eligible.
        ann = _ann(
            _row(play_id=1.0, qtr=2, game_seconds_remaining=2000,
                 pass_attempt=1.0),
            _row(play_id=2.0, qtr=2, game_seconds_remaining=1980,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        intervals = build_pace_intervals(ann)
        assert len(intervals) == 1

    def test_shuffled_input_deterministic(self):
        rows = [
            _row(play_id=i + 1.0, qtr=2, game_seconds_remaining=2000 - i * 30,
                 play_type=("run" if i % 2 else "pass"),
                 rush_attempt=(1.0 if i % 2 else 0.0),
                 pass_attempt=(0.0 if i % 2 else 1.0),
                 complete_pass=None if i % 2 else 1.0,
                 qb_dropback=0.0 if i % 2 else 1.0,
                 air_yards=None if i % 2 else 3,
                 yards_after_catch=None if i % 2 else 2)
            for i in range(4)
        ]
        # Each pair must satisfy: same drive, same posteam, same qtr 2,
        # same half "first", same game, delta in (0, 120].
        a = build_pace_intervals(_ann(*rows))
        b = build_pace_intervals(_ann(*reversed(rows)))
        assert [(iv.prior_play_id, iv.current_play_id, iv.delta)
                for iv in a] == [(iv.prior_play_id, iv.current_play_id, iv.delta)
                                 for iv in b]

    def test_neutral_prior_non_neutral_current_may_qualify(self):
        # Prior neutral, current non-neutral -> neutral pace interval
        # may qualify.
        ann = _ann(
            _row(play_id=1.0, qtr=2, score_differential=0,
                 game_seconds_remaining=2000),
            _row(play_id=2.0, qtr=2, score_differential=12,
                 game_seconds_remaining=1980,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        intervals = build_pace_intervals(ann)
        assert len(intervals) == 1
        assert intervals[0].is_neutral_prior is True
        # The interval qualifies for neutral seconds/play even though
        # the current play is non-neutral.
        # Verify by checking the per-team neutral aggregation.
        from nfl_edge.features.totals_v1.pace_observations import (
            pace_interval_observations,
        )
        aggs = pace_interval_observations(ann)
        assert METRIC_NEUTRAL_SECONDS_PLAY_OFFENSE in aggs["g1"]["KC"]

    def test_non_neutral_prior_neutral_current_does_not_qualify(self):
        # Prior non-neutral, current neutral -> neutral interval must
        # NOT qualify (asymmetric rule).
        ann = _ann(
            _row(play_id=1.0, qtr=2, score_differential=12,
                 game_seconds_remaining=2000),
            _row(play_id=2.0, qtr=2, score_differential=0,
                 game_seconds_remaining=1980,
                 play_type="run", rush_attempt=1.0, pass_attempt=0.0,
                 complete_pass=None, qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        intervals = build_pace_intervals(ann)
        # Still a valid seconds/play interval; just not a neutral one.
        assert len(intervals) == 1
        assert intervals[0].is_neutral_prior is False

        from nfl_edge.features.totals_v1.pace_observations import (
            pace_interval_observations,
        )
        aggs = pace_interval_observations(ann)
        # Seconds/play offense: 1 interval counted.
        assert METRIC_SECONDS_PLAY_OFFENSE in aggs["g1"]["KC"]
        # Neutral seconds/play offense: must NOT be present (no neutral
        # prior on this interval).
        assert METRIC_NEUTRAL_SECONDS_PLAY_OFFENSE not in aggs["g1"]["KC"]


# ===========================================================================
# C. Neutral pass rate (combined) tests
# ===========================================================================


class TestNeutralPassRate:
    def test_neutral_pass_numerator_one_denominator_one(self):
        ann = _ann(_row(qtr=2, score_differential=0,
                        game_seconds_remaining=2000))
        aggs = aggregate_row_metrics(ann)
        triples = aggs["g1"]["KC"][METRIC_NEUTRAL_PASS_RATE_OFFENSE]
        assert triples == [(1.0, 1.0, 1)]

    def test_neutral_rush_numerator_zero_denominator_one(self):
        ann = _ann(_row(play_type="run", rush_attempt=1.0,
                        pass_attempt=0.0, complete_pass=None,
                        qb_dropback=0.0, qtr=2,
                        score_differential=0,
                        game_seconds_remaining=2000,
                        air_yards=None, yards_after_catch=None))
        aggs = aggregate_row_metrics(ann)
        triples = aggs["g1"]["KC"][METRIC_NEUTRAL_PASS_RATE_OFFENSE]
        assert triples == [(0.0, 1.0, 1)]

    def test_one_neutral_pass_plus_one_neutral_rush(self):
        ann = _ann(
            _row(play_id=1.0, qtr=2, score_differential=0,
                 game_seconds_remaining=2000),
            _row(play_id=2.0, play_type="run", rush_attempt=1.0,
                 pass_attempt=0.0, complete_pass=None, qb_dropback=0.0,
                 qtr=2, score_differential=0,
                 game_seconds_remaining=1980,
                 air_yards=None, yards_after_catch=None,
                 fixed_drive=1.0, fixed_drive_result="Punt",
                 defteam="BAL"),
        )
        aggs = aggregate_row_metrics(ann)
        triples = aggs["g1"]["KC"][METRIC_NEUTRAL_PASS_RATE_OFFENSE]
        # 1 pass + 1 rush -> combined numerator 1, denominator 2.
        assert triples == [(1.0, 2.0, 2)]

    def test_non_neutral_pass_excluded(self):
        ann = _ann(_row(qtr=2, score_differential=12,
                        game_seconds_remaining=2000))
        aggs = aggregate_row_metrics(ann)
        assert METRIC_NEUTRAL_PASS_RATE_OFFENSE not in aggs["g1"]["KC"]

    def test_non_neutral_rush_excluded(self):
        ann = _ann(_row(play_type="run", rush_attempt=1.0,
                        pass_attempt=0.0, complete_pass=None,
                        qb_dropback=0.0, qtr=2,
                        score_differential=12,
                        game_seconds_remaining=2000,
                        air_yards=None, yards_after_catch=None))
        aggs = aggregate_row_metrics(ann)
        assert METRIC_NEUTRAL_PASS_RATE_OFFENSE not in aggs["g1"]["KC"]

    def test_kneel_excluded_from_neutral_rush(self):
        ann = _ann(_row(play_type="qb_kneel", rush_attempt=1.0,
                        pass_attempt=0.0, complete_pass=None,
                        qb_dropback=0.0, qb_kneel=1.0,
                        qtr=2, score_differential=0,
                        game_seconds_remaining=2000,
                        air_yards=None, yards_after_catch=None))
        aggs = aggregate_row_metrics(ann)
        # Kneel has rush_attempt=1 but is excluded; neutral pass rate
        # must not be emitted.
        assert METRIC_NEUTRAL_PASS_RATE_OFFENSE not in aggs["g1"]["KC"]

    def test_play_type_pass_with_pass_attempt_zero_excluded(self):
        ann = _ann(_row(play_type="pass", pass_attempt=0.0,
                        complete_pass=None, qb_dropback=1.0,
                        qtr=2, score_differential=0,
                        game_seconds_remaining=2000))
        aggs = aggregate_row_metrics(ann)
        assert METRIC_NEUTRAL_PASS_RATE_OFFENSE not in aggs["g1"]["KC"]

    def test_play_type_run_with_rush_attempt_zero_excluded(self):
        ann = _ann(_row(play_type="run", rush_attempt=0.0,
                        pass_attempt=0.0, complete_pass=None,
                        qb_dropback=0.0,
                        qtr=2, score_differential=0,
                        game_seconds_remaining=2000,
                        air_yards=None, yards_after_catch=None))
        aggs = aggregate_row_metrics(ann)
        assert METRIC_NEUTRAL_PASS_RATE_OFFENSE not in aggs["g1"]["KC"]

    def test_null_required_attempt_flag_excluded(self):
        ann = _ann(_row(pass_attempt=None, rush_attempt=None,
                        complete_pass=None,
                        qtr=2, score_differential=0,
                        game_seconds_remaining=2000))
        aggs = aggregate_row_metrics(ann)
        assert METRIC_NEUTRAL_PASS_RATE_OFFENSE not in aggs["g1"]["KC"]

    def test_build_game_observations_neutral_pass_does_not_emit_components(self):
        # End-to-end: build_game_observations must not raise, must
        # emit neutral_pass_rate_offense and its defense twin, and must
        # NOT emit the internal component metrics.
        rows = [
            _row(play_id=1.0, qtr=2, score_differential=0,
                 game_seconds_remaining=2000),
            _row(play_id=2.0, play_type="run", rush_attempt=1.0,
                 pass_attempt=0.0, complete_pass=None, qb_dropback=0.0,
                 qtr=2, score_differential=0,
                 game_seconds_remaining=1980,
                 fixed_drive=1.0, fixed_drive_result="Punt",
                 air_yards=None, yards_after_catch=None),
            _row(play_id=3.0, posteam="BAL", defteam="KC",
                 play_type="run", rush_attempt=1.0,
                 pass_attempt=0.0, complete_pass=None, qb_dropback=0.0,
                 qtr=2, score_differential=0,
                 game_seconds_remaining=1900, fixed_drive=2.0,
                 fixed_drive_result="Punt",
                 air_yards=None, yards_after_catch=None),
        ]
        obs = build_game_observations(block_id="blk",
                                       pbp_frames={"g1": pl.DataFrame(rows)},
                                       game_to_teams={"g1": ("KC", "BAL")})
        upd = obs[0].team_updates
        # KC offense and BAL defense-allowed twins both present.
        assert METRIC_NEUTRAL_PASS_RATE_OFFENSE in upd["KC"]
        assert METRIC_NEUTRAL_PASS_RATE_DEFENSE_ALLOWED in upd["BAL"]
        # Internal component metrics are gone.
        assert "neutral_pass_attempts_offense" not in upd["KC"]
        assert "neutral_rush_attempts_offense" not in upd["KC"]


# ===========================================================================
# D. Red-zone opportunity tests
# ===========================================================================


class TestRedZoneOpportunity:
    def test_yardline_20_qualifies(self):
        ann = _ann(_row(yardline_100=20))
        from nfl_edge.features.totals_v1.drive_observations import (
            red_zone_opportunity_observations,
        )
        out = red_zone_opportunity_observations(ann)
        assert len(out) == 1
        # 1 drive -> 0/1 (Punt default), triple (0, 1, 1).
        assert out[0][2] == (0.0, 1.0, 1)

    def test_yardline_21_does_not_qualify(self):
        ann = _ann(_row(yardline_100=21))
        from nfl_edge.features.totals_v1.drive_observations import (
            red_zone_opportunity_observations,
        )
        out = red_zone_opportunity_observations(ann)
        assert out == []

    def test_multiple_red_zone_vfps_one_drive_count_once(self):
        # Two VFPs in same drive, both with yardline_100<=20. One
        # opportunity only.
        ann = _ann(
            _row(play_id=1.0, yardline_100=18),
            _row(play_id=2.0, yardline_100=12),
        )
        from nfl_edge.features.totals_v1.drive_observations import (
            red_zone_opportunity_observations,
        )
        out = red_zone_opportunity_observations(ann)
        assert len(out) == 1

    def test_null_fixed_drive_result_excludes_opportunity(self):
        ann = _ann(_row(yardline_100=15, fixed_drive_result=None))
        from nfl_edge.features.totals_v1.drive_observations import (
            red_zone_opportunity_observations,
        )
        out = red_zone_opportunity_observations(ann)
        # Drive has no fixed_drive_result -> not included in denominator.
        assert out == []

    def test_touchdown_numerator_one(self):
        ann = _ann(_row(yardline_100=10, fixed_drive_result="Touchdown"))
        from nfl_edge.features.totals_v1.drive_observations import (
            red_zone_opportunity_observations,
        )
        out = red_zone_opportunity_observations(ann)
        assert out[0][2] == (1.0, 1.0, 1)

    def test_field_goal_numerator_zero(self):
        ann = _ann(_row(yardline_100=10, fixed_drive_result="Field goal"))
        from nfl_edge.features.totals_v1.drive_observations import (
            red_zone_opportunity_observations,
        )
        out = red_zone_opportunity_observations(ann)
        assert out[0][2] == (0.0, 1.0, 1)

    def test_punt_numerator_zero(self):
        ann = _ann(_row(yardline_100=10, fixed_drive_result="Punt"))
        from nfl_edge.features.totals_v1.drive_observations import (
            red_zone_opportunity_observations,
        )
        out = red_zone_opportunity_observations(ann)
        assert out[0][2] == (0.0, 1.0, 1)

    def test_same_fixed_drive_different_posteam_distinct(self):
        # Two separate possessions on the same fixed_drive number but
        # with different posteam -> two opportunities, not one.
        ann = _ann(
            _row(game_id="g1", play_id=1.0, fixed_drive=1.0,
                 posteam="KC", defteam="BAL",
                 yardline_100=10, fixed_drive_result="Touchdown"),
            _row(game_id="g1", play_id=2.0, fixed_drive=1.0,
                 posteam="BAL", defteam="KC",
                 yardline_100=10, fixed_drive_result="Punt",
                 play_type="run", rush_attempt=1.0,
                 pass_attempt=0.0, complete_pass=None,
                 qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        )
        from nfl_edge.features.totals_v1.drive_observations import (
            red_zone_opportunity_observations,
        )
        out = red_zone_opportunity_observations(ann)
        assert len(out) == 2
        posteams = sorted(o[1] for o in out)
        assert posteams == ["BAL", "KC"]

    def test_shuffled_deterministic(self):
        rows = [
            _row(play_id=1.0, yardline_100=18,
                 fixed_drive_result="Touchdown"),
            _row(play_id=2.0, yardline_100=12, fixed_drive=2.0,
                 fixed_drive_result="Punt",
                 play_type="run", rush_attempt=1.0,
                 pass_attempt=0.0, complete_pass=None,
                 qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        ]
        from nfl_edge.features.totals_v1.drive_observations import (
            red_zone_opportunity_observations,
        )
        a = red_zone_opportunity_observations(_ann(*rows))
        b = red_zone_opportunity_observations(_ann(*reversed(rows)))
        assert sorted(a) == sorted(b)


# ===========================================================================
# E. Goal-to-go opportunity tests
# ===========================================================================


class TestGoalToGoOpportunity:
    def test_goal_to_go_one_qualifies(self):
        ann = _ann(_row(goal_to_go=1))
        from nfl_edge.features.totals_v1.drive_observations import (
            goal_to_go_opportunity_observations,
        )
        out = goal_to_go_opportunity_observations(ann)
        assert len(out) == 1

    def test_goal_to_go_zero_does_not_qualify(self):
        ann = _ann(_row(goal_to_go=0))
        from nfl_edge.features.totals_v1.drive_observations import (
            goal_to_go_opportunity_observations,
        )
        out = goal_to_go_opportunity_observations(ann)
        assert out == []

    def test_yardline_alone_does_not_create_opportunity(self):
        # yardline_100=2 but goal_to_go=0 -> NOT an opportunity.
        ann = _ann(_row(yardline_100=2, goal_to_go=0))
        from nfl_edge.features.totals_v1.drive_observations import (
            goal_to_go_opportunity_observations,
        )
        out = goal_to_go_opportunity_observations(ann)
        assert out == []

    def test_multiple_gtg_one_drive_count_once(self):
        ann = _ann(
            _row(play_id=1.0, goal_to_go=1),
            _row(play_id=2.0, goal_to_go=1),
        )
        from nfl_edge.features.totals_v1.drive_observations import (
            goal_to_go_opportunity_observations,
        )
        out = goal_to_go_opportunity_observations(ann)
        assert len(out) == 1

    def test_null_result_excludes_denominator(self):
        ann = _ann(_row(goal_to_go=1, fixed_drive_result=None))
        from nfl_edge.features.totals_v1.drive_observations import (
            goal_to_go_opportunity_observations,
        )
        out = goal_to_go_opportunity_observations(ann)
        assert out == []

    def test_touchdown_numerator_one(self):
        ann = _ann(_row(goal_to_go=1, fixed_drive_result="Touchdown"))
        from nfl_edge.features.totals_v1.drive_observations import (
            goal_to_go_opportunity_observations,
        )
        out = goal_to_go_opportunity_observations(ann)
        assert out[0][2] == (1.0, 1.0, 1)

    def test_non_touchdown_numerator_zero(self):
        ann = _ann(_row(goal_to_go=1, fixed_drive_result="Punt"))
        from nfl_edge.features.totals_v1.drive_observations import (
            goal_to_go_opportunity_observations,
        )
        out = goal_to_go_opportunity_observations(ann)
        assert out[0][2] == (0.0, 1.0, 1)

    def test_shuffled_deterministic(self):
        rows = [
            _row(play_id=1.0, goal_to_go=1,
                 fixed_drive_result="Touchdown"),
            _row(play_id=2.0, goal_to_go=1, fixed_drive=2.0,
                 fixed_drive_result="Punt",
                 play_type="run", rush_attempt=1.0,
                 pass_attempt=0.0, complete_pass=None,
                 qb_dropback=0.0,
                 air_yards=None, yards_after_catch=None),
        ]
        from nfl_edge.features.totals_v1.drive_observations import (
            goal_to_go_opportunity_observations,
        )
        a = goal_to_go_opportunity_observations(_ann(*rows))
        b = goal_to_go_opportunity_observations(_ann(*reversed(rows)))
        assert sorted(a) == sorted(b)


# ===========================================================================
# F. Sacks/dropback tests
# ===========================================================================


class TestSacksPerDropback:
    def test_primary_dropback_sack_one(self):
        ann = _ann(_row(qb_dropback=1.0, sack=1.0,
                        pass_attempt=0.0, complete_pass=None))
        aggs = aggregate_row_metrics(ann)
        triples = aggs["g1"]["KC"][METRIC_SACKS_PER_DROPBACK_OFFENSE]
        assert triples == [(1.0, 1.0, 1)]

    def test_primary_dropback_sack_zero(self):
        ann = _ann(_row(qb_dropback=1.0, sack=0.0))
        aggs = aggregate_row_metrics(ann)
        triples = aggs["g1"]["KC"][METRIC_SACKS_PER_DROPBACK_OFFENSE]
        assert triples == [(0.0, 1.0, 1)]

    def test_null_only_fallback_pass_attempt(self):
        # qb_dropback NULL, pass_attempt=1 -> fallback dropback, sack=0
        # -> 0/1.
        ann = _ann(_row(qb_dropback=None, sack=0.0,
                        pass_attempt=1.0, complete_pass=1.0))
        aggs = aggregate_row_metrics(ann)
        triples = aggs["g1"]["KC"][METRIC_SACKS_PER_DROPBACK_OFFENSE]
        assert triples == [(0.0, 1.0, 1)]

    def test_null_only_fallback_sack(self):
        # qb_dropback NULL, sack=1 -> fallback dropback, sack=1 -> 1/1.
        ann = _ann(_row(qb_dropback=None, sack=1.0,
                        pass_attempt=None, complete_pass=None,
                        rush_attempt=None))
        aggs = aggregate_row_metrics(ann)
        triples = aggs["g1"]["KC"][METRIC_SACKS_PER_DROPBACK_OFFENSE]
        assert triples == [(1.0, 1.0, 1)]

    def test_qb_dropback_zero_sack_one_not_fallback(self):
        # qb_dropback=0 + sack=1 must NOT count as dropback. Phase 3B
        # primary predicate is qb_dropback == 1, fallback requires
        # qb_dropback IS NULL.
        ann = _ann(_row(qb_dropback=0.0, sack=1.0,
                        pass_attempt=None, rush_attempt=None,
                        complete_pass=None))
        aggs = aggregate_row_metrics(ann)
        assert METRIC_SACKS_PER_DROPBACK_OFFENSE not in aggs["g1"]["KC"]

    def test_non_vfp_excluded(self):
        ann = _ann(_row(posteam=None, qb_dropback=1.0, sack=1.0))
        aggs = aggregate_row_metrics(ann)
        # No posteam -> no team bucket at all.
        assert METRIC_SACKS_PER_DROPBACK_OFFENSE not in aggs.get("g1", {}).get("KC", {})

    def test_offense_defense_inversion(self):
        # Build a 2-team game; KC offense sacks, BAL offense no sacks.
        rows = [
            _row(play_id=1.0, posteam="KC", defteam="BAL",
                 qb_dropback=1.0, sack=1.0,
                 pass_attempt=0.0, complete_pass=None),
            _row(play_id=2.0, posteam="BAL", defteam="KC",
                 play_type="run", rush_attempt=1.0,
                 pass_attempt=0.0, complete_pass=None,
                 qb_dropback=0.0, sack=0.0,
                 fixed_drive=2.0, fixed_drive_result="Punt",
                 air_yards=None, yards_after_catch=None),
        ]
        obs = build_game_observations(block_id="blk",
                                       pbp_frames={"g1": pl.DataFrame(rows)},
                                       game_to_teams={"g1": ("KC", "BAL")})
        upd = obs[0].team_updates
        # KC offense: 1/1.
        assert upd["KC"][METRIC_SACKS_PER_DROPBACK_OFFENSE] == (1.0, 1.0, 1)
        # BAL defense-allowed mirrors KC offense.
        assert upd["BAL"][METRIC_SACKS_PER_DROPBACK_DEFENSE_ALLOWED] == (1.0, 1.0, 1)


# ===========================================================================
# G. Air yards/attempt tests
# ===========================================================================


class TestAirYards:
    def test_positive_value(self):
        ann = _ann(_row(air_yards=8))
        aggs = aggregate_row_metrics(ann)
        triples = aggs["g1"]["KC"][METRIC_AIR_YARDS_PER_ATTEMPT_OFFENSE]
        assert triples == [(8.0, 1.0, 1)]

    def test_zero_value_retained(self):
        ann = _ann(_row(air_yards=0))
        aggs = aggregate_row_metrics(ann)
        triples = aggs["g1"]["KC"][METRIC_AIR_YARDS_PER_ATTEMPT_OFFENSE]
        # 0 is observed; contributes 0 to numerator and 1 to denominator.
        assert triples == [(0.0, 1.0, 1)]

    def test_negative_value_retained(self):
        ann = _ann(_row(air_yards=-3))
        aggs = aggregate_row_metrics(ann)
        triples = aggs["g1"]["KC"][METRIC_AIR_YARDS_PER_ATTEMPT_OFFENSE]
        assert triples == [(-3.0, 1.0, 1)]

    def test_null_excluded(self):
        ann = _ann(_row(air_yards=None))
        aggs = aggregate_row_metrics(ann)
        assert METRIC_AIR_YARDS_PER_ATTEMPT_OFFENSE not in aggs["g1"]["KC"]

    def test_non_pass_attempt_excluded(self):
        ann = _ann(_row(play_type="run", rush_attempt=1.0,
                        pass_attempt=0.0, complete_pass=None,
                        qb_dropback=0.0,
                        air_yards=-5, yards_after_catch=None))
        aggs = aggregate_row_metrics(ann)
        assert METRIC_AIR_YARDS_PER_ATTEMPT_OFFENSE not in aggs["g1"]["KC"]

    def test_offense_defense_inversion(self):
        rows = [
            _row(play_id=1.0, posteam="KC", defteam="BAL",
                 air_yards=10, fixed_drive_result="Punt"),
            _row(play_id=2.0, posteam="BAL", defteam="KC",
                 play_type="run", rush_attempt=1.0,
                 pass_attempt=0.0, complete_pass=None,
                 qb_dropback=0.0, fixed_drive=2.0,
                 fixed_drive_result="Punt",
                 air_yards=None, yards_after_catch=None),
        ]
        obs = build_game_observations(block_id="blk",
                                       pbp_frames={"g1": pl.DataFrame(rows)},
                                       game_to_teams={"g1": ("KC", "BAL")})
        upd = obs[0].team_updates
        assert upd["KC"][METRIC_AIR_YARDS_PER_ATTEMPT_OFFENSE] == (10.0, 1.0, 1)
        assert upd["BAL"][METRIC_AIR_YARDS_PER_ATTEMPT_DEFENSE_ALLOWED] == (10.0, 1.0, 1)


# ===========================================================================
# H. YAC per completion tests
# ===========================================================================


class TestYacPerCompletion:
    def test_positive_yac(self):
        ann = _row(complete_pass=1.0, yards_after_catch=7)
        aggs = aggregate_row_metrics(_ann(ann))
        triples = aggs["g1"]["KC"][METRIC_YAC_PER_COMPLETION_OFFENSE]
        assert triples == [(7.0, 1.0, 1)]

    def test_zero_yac_retained(self):
        ann = _row(complete_pass=1.0, yards_after_catch=0)
        aggs = aggregate_row_metrics(_ann(ann))
        triples = aggs["g1"]["KC"][METRIC_YAC_PER_COMPLETION_OFFENSE]
        assert triples == [(0.0, 1.0, 1)]

    def test_null_yac_excluded(self):
        ann = _row(complete_pass=1.0, yards_after_catch=None)
        aggs = aggregate_row_metrics(_ann(ann))
        assert METRIC_YAC_PER_COMPLETION_OFFENSE not in aggs["g1"]["KC"]

    def test_incomplete_pass_excluded(self):
        # pass_attempt=1 but complete_pass=0 -> not a completion.
        ann = _row(complete_pass=0.0, yards_after_catch=10)
        aggs = aggregate_row_metrics(_ann(ann))
        assert METRIC_YAC_PER_COMPLETION_OFFENSE not in aggs["g1"]["KC"]

    def test_complete_pass_one_without_pass_attempt_excluded(self):
        # complete_pass=1 but pass_attempt=0 -> not a pass attempt, not
        # a completion.
        ann = _row(play_type="run", rush_attempt=1.0,
                   pass_attempt=0.0, complete_pass=1.0,
                   qb_dropback=0.0, yards_after_catch=5,
                   air_yards=None)
        aggs = aggregate_row_metrics(_ann(ann))
        assert METRIC_YAC_PER_COMPLETION_OFFENSE not in aggs["g1"]["KC"]

    def test_offense_defense_inversion(self):
        rows = [
            _row(play_id=1.0, posteam="KC", defteam="BAL",
                 complete_pass=1.0, yards_after_catch=8),
            _row(play_id=2.0, posteam="BAL", defteam="KC",
                 play_type="run", rush_attempt=1.0,
                 pass_attempt=0.0, complete_pass=None,
                 qb_dropback=0.0, fixed_drive=2.0,
                 fixed_drive_result="Punt",
                 air_yards=None, yards_after_catch=None),
        ]
        obs = build_game_observations(block_id="blk",
                                       pbp_frames={"g1": pl.DataFrame(rows)},
                                       game_to_teams={"g1": ("KC", "BAL")})
        upd = obs[0].team_updates
        assert upd["KC"][METRIC_YAC_PER_COMPLETION_OFFENSE] == (8.0, 1.0, 1)
        assert upd["BAL"][METRIC_YAC_PER_COMPLETION_DEFENSE_ALLOWED] == (8.0, 1.0, 1)


# ===========================================================================
# I. Explosive pass rate tests
# ===========================================================================


class TestExplosivePassRate:
    def test_yards_19_no_event(self):
        aggs = aggregate_row_metrics(_ann(_row(yards_gained=19)))
        triples = aggs["g1"]["KC"][METRIC_EXPLOSIVE_PASS_RATE_OFFENSE]
        assert triples == [(0.0, 1.0, 1)]

    def test_yards_exactly_20_event(self):
        aggs = aggregate_row_metrics(_ann(_row(yards_gained=20)))
        triples = aggs["g1"]["KC"][METRIC_EXPLOSIVE_PASS_RATE_OFFENSE]
        assert triples == [(1.0, 1.0, 1)]

    def test_yards_21_event(self):
        aggs = aggregate_row_metrics(_ann(_row(yards_gained=21)))
        triples = aggs["g1"]["KC"][METRIC_EXPLOSIVE_PASS_RATE_OFFENSE]
        assert triples == [(1.0, 1.0, 1)]

    def test_null_yards_excluded(self):
        aggs = aggregate_row_metrics(_ann(_row(yards_gained=None)))
        assert METRIC_EXPLOSIVE_PASS_RATE_OFFENSE not in aggs["g1"]["KC"]

    def test_non_pass_attempt_excluded(self):
        aggs = aggregate_row_metrics(_ann(_row(play_type="run",
                                               rush_attempt=1.0,
                                               pass_attempt=0.0,
                                               complete_pass=None,
                                               qb_dropback=0.0,
                                               yards_gained=25,
                                               air_yards=None,
                                               yards_after_catch=None)))
        assert METRIC_EXPLOSIVE_PASS_RATE_OFFENSE not in aggs["g1"]["KC"]

    def test_offense_defense_inversion(self):
        rows = [
            _row(play_id=1.0, posteam="KC", defteam="BAL",
                 yards_gained=22, fixed_drive_result="Punt"),
            _row(play_id=2.0, posteam="BAL", defteam="KC",
                 play_type="run", rush_attempt=1.0,
                 pass_attempt=0.0, complete_pass=None,
                 qb_dropback=0.0, fixed_drive=2.0,
                 fixed_drive_result="Punt",
                 yards_gained=3, air_yards=None,
                 yards_after_catch=None),
        ]
        obs = build_game_observations(block_id="blk",
                                       pbp_frames={"g1": pl.DataFrame(rows)},
                                       game_to_teams={"g1": ("KC", "BAL")})
        upd = obs[0].team_updates
        assert upd["KC"][METRIC_EXPLOSIVE_PASS_RATE_OFFENSE] == (1.0, 1.0, 1)
        assert upd["BAL"][METRIC_EXPLOSIVE_PASS_RATE_DEFENSE_ALLOWED] == (1.0, 1.0, 1)


# ===========================================================================
# J. Explosive rush rate tests
# ===========================================================================


class TestExplosiveRushRate:
    def test_yards_9_no_event(self):
        aggs = aggregate_row_metrics(_ann(_row(play_type="run",
                                               rush_attempt=1.0,
                                               pass_attempt=0.0,
                                               complete_pass=None,
                                               qb_dropback=0.0,
                                               yards_gained=9,
                                               air_yards=None,
                                               yards_after_catch=None)))
        triples = aggs["g1"]["KC"][METRIC_EXPLOSIVE_RUSH_RATE_OFFENSE]
        assert triples == [(0.0, 1.0, 1)]

    def test_yards_exactly_10_event(self):
        aggs = aggregate_row_metrics(_ann(_row(play_type="run",
                                               rush_attempt=1.0,
                                               pass_attempt=0.0,
                                               complete_pass=None,
                                               qb_dropback=0.0,
                                               yards_gained=10,
                                               air_yards=None,
                                               yards_after_catch=None)))
        triples = aggs["g1"]["KC"][METRIC_EXPLOSIVE_RUSH_RATE_OFFENSE]
        assert triples == [(1.0, 1.0, 1)]

    def test_yards_11_event(self):
        aggs = aggregate_row_metrics(_ann(_row(play_type="run",
                                               rush_attempt=1.0,
                                               pass_attempt=0.0,
                                               complete_pass=None,
                                               qb_dropback=0.0,
                                               yards_gained=11,
                                               air_yards=None,
                                               yards_after_catch=None)))
        triples = aggs["g1"]["KC"][METRIC_EXPLOSIVE_RUSH_RATE_OFFENSE]
        assert triples == [(1.0, 1.0, 1)]

    def test_null_yards_excluded(self):
        aggs = aggregate_row_metrics(_ann(_row(play_type="run",
                                               rush_attempt=1.0,
                                               pass_attempt=0.0,
                                               complete_pass=None,
                                               qb_dropback=0.0,
                                               yards_gained=None,
                                               air_yards=None,
                                               yards_after_catch=None)))
        assert METRIC_EXPLOSIVE_RUSH_RATE_OFFENSE not in aggs["g1"]["KC"]

    def test_kneel_excluded_even_with_rush_attempt_one(self):
        aggs = aggregate_row_metrics(_ann(_row(play_type="qb_kneel",
                                               rush_attempt=1.0,
                                               pass_attempt=0.0,
                                               complete_pass=None,
                                               qb_dropback=0.0,
                                               qb_kneel=1.0,
                                               yards_gained=15,
                                               air_yards=None,
                                               yards_after_catch=None)))
        assert METRIC_EXPLOSIVE_RUSH_RATE_OFFENSE not in aggs["g1"]["KC"]

    def test_non_rush_excluded(self):
        aggs = aggregate_row_metrics(_ann(_row(yards_gained=25)))
        # Default fixture is a pass attempt, not a rush attempt.
        assert METRIC_EXPLOSIVE_RUSH_RATE_OFFENSE not in aggs["g1"]["KC"]

    def test_offense_defense_inversion(self):
        rows = [
            _row(play_id=1.0, posteam="KC", defteam="BAL",
                 play_type="run", rush_attempt=1.0,
                 pass_attempt=0.0, complete_pass=None,
                 qb_dropback=0.0, yards_gained=12,
                 air_yards=None, yards_after_catch=None,
                 fixed_drive_result="Punt"),
            _row(play_id=2.0, posteam="BAL", defteam="KC",
                 play_type="run", rush_attempt=1.0,
                 pass_attempt=0.0, complete_pass=None,
                 qb_dropback=0.0, yards_gained=2,
                 fixed_drive=2.0, fixed_drive_result="Punt",
                 air_yards=None, yards_after_catch=None),
        ]
        obs = build_game_observations(block_id="blk",
                                       pbp_frames={"g1": pl.DataFrame(rows)},
                                       game_to_teams={"g1": ("KC", "BAL")})
        upd = obs[0].team_updates
        assert upd["KC"][METRIC_EXPLOSIVE_RUSH_RATE_OFFENSE] == (1.0, 1.0, 1)
        assert upd["BAL"][METRIC_EXPLOSIVE_RUSH_RATE_DEFENSE_ALLOWED] == (1.0, 1.0, 1)


# ===========================================================================
# K. Multi-family integration test (two-team game with all 10 families)
# ===========================================================================


def _integration_game_rows():
    """Return rows for a two-team game exercising all 10 Phase 3C families.

    Game structure:
    - Drive 1 (KC): neutral pass (TD), then neutral rush; sacks/dropback
      on the third play; red-zone visit on drive 3; goal-to-go on
      drive 4.
    - Drive 2 (BAL): a few neutral attempts.
    - Pace intervals inside each drive.
    """
    rows = []
    # Drive 1: KC offense, three VFPs with pace intervals.
    rows.append(_row(
        game_id="g1", play_id=1.0, fixed_drive=1.0,
        posteam="KC", defteam="BAL",
        qtr=2, score_differential=0, game_seconds_remaining=3000,
        pass_attempt=1.0, complete_pass=1.0,
        air_yards=8, yards_after_catch=4, yards_gained=12,
        qb_dropback=1.0, sack=0.0,
        fixed_drive_result="Touchdown",
        yardline_100=10, goal_to_go=1,
    ))
    rows.append(_row(
        game_id="g1", play_id=2.0, fixed_drive=1.0,
        posteam="KC", defteam="BAL",
        qtr=2, score_differential=0, game_seconds_remaining=2970,
        play_type="run", rush_attempt=1.0,
        pass_attempt=0.0, complete_pass=None, qb_dropback=0.0,
        air_yards=None, yards_after_catch=None, yards_gained=5,
        sack=0.0,
        fixed_drive_result="Touchdown",
        yardline_100=15, goal_to_go=1,
    ))
    # Drive 2: BAL offense.
    rows.append(_row(
        game_id="g1", play_id=3.0, fixed_drive=2.0,
        posteam="BAL", defteam="KC",
        qtr=2, score_differential=-7, game_seconds_remaining=2500,
        play_type="run", rush_attempt=1.0,
        pass_attempt=0.0, complete_pass=None, qb_dropback=0.0,
        air_yards=None, yards_after_catch=None, yards_gained=3,
        sack=0.0,
        fixed_drive_result="Punt",
        yardline_100=70, goal_to_go=0,
    ))
    # Drive 3: KC offense with a sack (dropback).
    rows.append(_row(
        game_id="g1", play_id=4.0, fixed_drive=3.0,
        posteam="KC", defteam="BAL",
        qtr=3, score_differential=0, game_seconds_remaining=1500,
        qb_dropback=1.0, sack=1.0,
        pass_attempt=0.0, complete_pass=None,
        air_yards=None, yards_after_catch=None, yards_gained=-7,
        fixed_drive_result="Punt",
        yardline_100=50, goal_to_go=0,
    ))
    return rows


class TestMultiFamilyIntegration:
    def test_two_team_game_all_families(self):
        rows = _integration_game_rows()
        obs = build_game_observations(block_id="blk",
                                       pbp_frames={"g1": pl.DataFrame(rows)},
                                       game_to_teams={"g1": ("KC", "BAL")})
        upd = obs[0].team_updates

        # 10 Phase 3C primitives present on KC offense.
        assert METRIC_SECONDS_PLAY_OFFENSE in upd["KC"]
        assert METRIC_NEUTRAL_SECONDS_PLAY_OFFENSE in upd["KC"]
        assert METRIC_NEUTRAL_PASS_RATE_OFFENSE in upd["KC"]
        assert METRIC_RED_ZONE_TD_RATE_OFFENSE in upd["KC"]
        assert METRIC_GOAL_TO_GO_TD_RATE_OFFENSE in upd["KC"]
        assert METRIC_SACKS_PER_DROPBACK_OFFENSE in upd["KC"]
        assert METRIC_AIR_YARDS_PER_ATTEMPT_OFFENSE in upd["KC"]
        assert METRIC_YAC_PER_COMPLETION_OFFENSE in upd["KC"]
        assert METRIC_EXPLOSIVE_PASS_RATE_OFFENSE in upd["KC"]
        assert METRIC_EXPLOSIVE_RUSH_RATE_OFFENSE in upd["KC"]

        # Opponent defense-allowed inversion: every KC offense primitive
        # appears as BAL defense-allowed twin.
        assert METRIC_SECONDS_PLAY_DEFENSE_ALLOWED in upd["BAL"]
        assert METRIC_NEUTRAL_SECONDS_PLAY_DEFENSE_ALLOWED in upd["BAL"]
        assert METRIC_NEUTRAL_PASS_RATE_DEFENSE_ALLOWED in upd["BAL"]
        assert METRIC_RED_ZONE_TD_RATE_DEFENSE_ALLOWED in upd["BAL"]
        assert METRIC_GOAL_TO_GO_TD_RATE_DEFENSE_ALLOWED in upd["BAL"]
        assert METRIC_SACKS_PER_DROPBACK_DEFENSE_ALLOWED in upd["BAL"]
        assert METRIC_AIR_YARDS_PER_ATTEMPT_DEFENSE_ALLOWED in upd["BAL"]
        assert METRIC_YAC_PER_COMPLETION_DEFENSE_ALLOWED in upd["BAL"]
        assert METRIC_EXPLOSIVE_PASS_RATE_DEFENSE_ALLOWED in upd["BAL"]
        assert METRIC_EXPLOSIVE_RUSH_RATE_DEFENSE_ALLOWED in upd["BAL"]

        # Internal helper metrics are gone.
        assert "neutral_pass_attempts_offense" not in upd["KC"]
        assert "neutral_rush_attempts_offense" not in upd["KC"]

        # Phase 3B metrics still present and unchanged.
        assert "epa_play_offense" in upd["KC"]
        assert "success_offense" in upd["KC"]
        assert "pass_attempts_offense" in upd["KC"]
        assert "rush_attempts_offense" in upd["KC"]
        assert "points_per_drive_offense" in upd["KC"]
        assert "scoring_drive_rate_offense" in upd["KC"]

    def test_integration_deterministic_under_shuffle(self):
        rows = _integration_game_rows()
        obs_a = build_game_observations(block_id="blk",
                                         pbp_frames={"g1": pl.DataFrame(rows)},
                                         game_to_teams={"g1": ("KC", "BAL")})
        obs_b = build_game_observations(
            block_id="blk",
            pbp_frames={"g1": pl.DataFrame(list(reversed(rows)))},
            game_to_teams={"g1": ("KC", "BAL")},
        )

        def flat(observations):
            return sorted(
                (team, metric, val)
                for team, ms in sorted(observations[0].team_updates.items())
                for metric, val in sorted(ms.items())
            )

        assert flat(obs_a) == flat(obs_b)


# ===========================================================================
# L. game_half_for_qtr helper
# ===========================================================================


class TestGameHalfHelper:
    def test_qtrs_1_2_first(self):
        assert game_half_for_qtr(1) == "first"
        assert game_half_for_qtr(2) == "first"

    def test_qtrs_3_4_second(self):
        assert game_half_for_qtr(3) == "second"
        assert game_half_for_qtr(4) == "second"

    def test_qtr_5_overtime(self):
        assert game_half_for_qtr(5) == "overtime"
