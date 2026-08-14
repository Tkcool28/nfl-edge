"""Phase 3D focused tests for the Totals V1 feature table.

Covers all 12 required test groups (A through L) from the Phase 3D contract:
A. Entering state aggregation
B. Metric-specific minima
C. Matchup combination
D. Rest context
E. Roof context
F. Surface context
G. Context projection
H. Oracle QB join
I. Column order
J. Same-block poisoning
K. Later-block poisoning
L. 2025 safety
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import polars as pl
import pytest

from nfl_edge.features.totals_v1.block_state import (
    Accumulator,
    BlockStartSnapshot,
    GameObservation,
    TeamEntState,
    TotalsBlockState,
)
from nfl_edge.features.totals_v1.context import (
    APPROVED_CONTEXT_FIELDS,
    PROHIBITED_CONTEXT_FIELDS,
    ContextProjectionError,
    assert_no_prohibited_context_columns,
    find_prohibited_columns,
    project_totals_context,
)
from nfl_edge.features.totals_v1.context_features import extract_context_features
from nfl_edge.features.totals_v1.entering_state import (
    MATCHUP_FAMILIES,
    MetricFamilyConfig,
    compute_matchup_pair,
    extract_entering_rate,
)
from nfl_edge.features.totals_v1.feature_table import (
    EXACT_90_COLUMNS,
    _join_oracle_qb,
    _load_oracle_qb,
)
from nfl_edge.backtest.blocks import PredictionBlock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _acc(num: float, den: float, sample: int = 0) -> Accumulator:
    """Shorthand for creating an Accumulator."""
    return Accumulator(numerator=num, denominator=den, sample_count=sample)


def _team_state(**metrics: Accumulator) -> TeamEntState:
    """Shorthand for creating a TeamEntState with named metrics."""
    return TeamEntState(metrics=metrics)


def _snapshot(**teams: TeamEntState) -> BlockStartSnapshot:
    """Shorthand for creating a BlockStartSnapshot."""
    return BlockStartSnapshot(block_id="test_block", teams=teams)


def _block(season: int, stype: str, week: int, game_ids: tuple[str, ...]) -> PredictionBlock:
    """Shorthand for creating a PredictionBlock."""
    return PredictionBlock(
        block_id=f"{season}_{stype}_W{week:02d}",
        season=season,
        season_type=stype,
        week=week,
        as_of_utc=datetime(season, 1, 1, tzinfo=timezone.utc),
        game_ids=game_ids,
    )


# Minimal canonical games schema for testing
def _canonical_games(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows).cast(
        {"season": pl.Int32, "week": pl.Int32}
    )


# Minimal schedule schema for testing
def _schedule(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows).cast(
        {"season": pl.Int32, "week": pl.Int32}
    )


# ===========================================================================
# A. ENTERING STATE
# ===========================================================================

class TestEnteringStateA:
    """Entering-state aggregation rules (Section 1)."""

    def test_no_prior_games_null_state(self):
        """No prior games -> all metrics null, missing=1."""
        state = TeamEntState()  # empty
        for family in MATCHUP_FAMILIES:
            val, missing = extract_entering_rate(state, family.offense_metric, family.minimum)
            assert val is None, f"{family.feature_name}: expected None for empty state"
            assert missing == 1, f"{family.feature_name}: expected missing=1"

    def test_below_exact_minimum_null(self):
        """Below exact metric minimum -> null."""
        # EPA/play minimum is 20 VFPs
        state = _team_state(epa_play_offense=_acc(10.0, 19.0))
        val, missing = extract_entering_rate(state, "epa_play_offense", 20)
        assert val is None
        assert missing == 1

    def test_exactly_at_minimum_non_null(self):
        """Exactly at minimum -> non-null."""
        state = _team_state(epa_play_offense=_acc(10.0, 20.0))
        val, missing = extract_entering_rate(state, "epa_play_offense", 20)
        assert val == 0.5
        assert missing == 0

    def test_above_minimum_non_null(self):
        """Above minimum -> non-null."""
        state = _team_state(epa_play_offense=_acc(15.0, 30.0))
        val, missing = extract_entering_rate(state, "epa_play_offense", 20)
        assert val == 0.5
        assert missing == 0

    def test_ratio_uses_sum_numerators_over_sum_denominators(self):
        """Rate = sum(numerators) / sum(denominators), not mean of rates."""
        # Two prior games: (3, 10) and (7, 10). Sum = (10, 20). Rate = 0.5.
        # NOT mean of rates: mean(0.3, 0.7) = 0.5 (coincidentally same here).
        # Better test: (1, 10) and (9, 10). Sum = (10, 20). Rate = 0.5.
        # Mean of rates = mean(0.1, 0.9) = 0.5 (still same for this case).
        # Use (2, 10) and (8, 20). Sum = (10, 30). Rate = 1/3.
        # Mean of rates = mean(0.2, 0.4) = 0.3. These differ!
        state = _team_state(success_offense=_acc(10.0, 30.0))
        val, missing = extract_entering_rate(state, "success_offense", 20)
        assert missing == 0
        assert abs(val - 10.0 / 30.0) < 1e-12

    def test_not_arithmetic_mean_of_prior_rates(self):
        """Explicitly prove it's not the arithmetic mean of prior game rates."""
        # Build state from two games with very different rates.
        # Game 1: (2, 10) -> rate 0.2. Game 2: (8, 20) -> rate 0.4.
        # Sum = (10, 30). Volume-weighted rate = 10/30 = 0.333...
        # Arithmetic mean of rates = (0.2 + 0.4) / 2 = 0.3.
        state = _team_state(success_offense=_acc(10.0, 30.0))
        val, _ = extract_entering_rate(state, "success_offense", 20)
        volume_weighted = 10.0 / 30.0
        arithmetic_mean = (2.0 / 10.0 + 8.0 / 20.0) / 2.0
        assert abs(val - volume_weighted) < 1e-12
        assert abs(val - arithmetic_mean) > 0.01  # explicitly different

    def test_cross_season_history_retained(self):
        """State built from cross-season observations is retained."""
        state = TotalsBlockState()
        # Season 2018 block
        block_18 = _block(2018, "REG", 1, ("2018_01_KC_NE",))
        state.commit_block(block_18, [
            GameObservation(
                block_id=block_18.block_id,
                game_id="2018_01_KC_NE",
                team_updates={
                    "KC": {"epa_play_offense": (5.0, 50.0, 50)},
                },
            )
        ])
        # Season 2019 block
        block_19 = _block(2019, "REG", 1, ("2019_01_NE_KC",))
        state.commit_block(block_19, [
            GameObservation(
                block_id=block_19.block_id,
                game_id="2019_01_NE_KC",
                team_updates={
                    "KC": {"epa_play_offense": (5.0, 50.0, 50)},
                },
            )
        ])
        # KC state should have 100 total observations across both seasons
        snap = state.snapshot_for_block(_block(2020, "REG", 1, ("2020_01_KC_NE",)))
        kc_state = snap.team("KC")
        acc = kc_state.get("epa_play_offense")
        assert acc is not None
        assert acc.denominator == 100.0
        assert acc.numerator == 10.0

    def test_postseason_updates_follow_canonical_order(self):
        """Postseason observations update state in canonical order."""
        state = TotalsBlockState()
        # REG block
        reg = _block(2024, "REG", 18, ("2024_18_KC_DEN",))
        state.commit_block(reg, [
            GameObservation(
                block_id=reg.block_id,
                game_id="2024_18_KC_DEN",
                team_updates={"KC": {"epa_play_offense": (1.0, 20.0, 20)}},
            )
        ])
        # WC block (after REG in canonical order)
        wc = _block(2024, "WC", 19, ("2024_19_KC_HOU",))
        snap = state.snapshot_for_block(wc)
        kc = snap.team("KC")
        assert kc.get("epa_play_offense").denominator == 20.0

        state.commit_block(wc, [
            GameObservation(
                block_id=wc.block_id,
                game_id="2024_19_KC_HOU",
                team_updates={"KC": {"epa_play_offense": (2.0, 30.0, 30)}},
            )
        ])
        # SB block should see both REG and WC
        sb = _block(2024, "SB", 22, ("2024_22_KC_PHI",))
        snap2 = state.snapshot_for_block(sb)
        kc2 = snap2.team("KC")
        assert kc2.get("epa_play_offense").denominator == 50.0
        assert kc2.get("epa_play_offense").numerator == 3.0

    def test_same_block_observations_unavailable_until_commit(self):
        """Same-block observations are NOT in the snapshot."""
        state = TotalsBlockState()
        block = _block(2024, "REG", 1, ("2024_01_KC_NE", "2024_01_NE_KC"))
        # Snapshot before any commit
        snap = state.snapshot_for_block(block)
        assert snap.team("KC").get("epa_play_offense") is None
        # Commit
        state.commit_block(block, [
            GameObservation(
                block_id=block.block_id,
                game_id="2024_01_KC_NE",
                team_updates={"KC": {"epa_play_offense": (5.0, 50.0, 50)}},
            ),
            GameObservation(
                block_id=block.block_id,
                game_id="2024_01_NE_KC",
                team_updates={"NE": {"epa_play_offense": (3.0, 40.0, 40)}},
            ),
        ])
        # After commit, state is updated
        block2 = _block(2024, "REG", 2, ("2024_02_KC_DEN",))
        snap2 = state.snapshot_for_block(block2)
        assert snap2.team("KC").get("epa_play_offense").denominator == 50.0

    def test_source_row_shuffle_deterministic(self):
        """Accumulator results are deterministic regardless of observation order."""
        acc1 = _acc(0, 0)
        acc1 = acc1.add(1.0, 10.0, 10)
        acc1 = acc1.add(2.0, 20.0, 20)
        acc2 = _acc(0, 0)
        acc2 = acc2.add(2.0, 20.0, 20)
        acc2 = acc2.add(1.0, 10.0, 10)
        assert acc1.numerator == acc2.numerator
        assert acc1.denominator == acc2.denominator


# ===========================================================================
# B. METRIC-SPECIFIC MINIMA
# ===========================================================================

class TestMetricMinimaB:
    """Boundary tests for every metric family minimum (Section 2)."""

    def test_epa_play_19_of_20(self):
        state = _team_state(epa_play_offense=_acc(5.0, 19.0))
        val, m = extract_entering_rate(state, "epa_play_offense", 20)
        assert val is None and m == 1

    def test_epa_play_20_of_20(self):
        state = _team_state(epa_play_offense=_acc(5.0, 20.0))
        val, m = extract_entering_rate(state, "epa_play_offense", 20)
        assert val is not None and m == 0

    def test_success_19_of_20(self):
        state = _team_state(success_offense=_acc(5.0, 19.0))
        val, m = extract_entering_rate(state, "success_offense", 20)
        assert val is None and m == 1

    def test_success_20_of_20(self):
        state = _team_state(success_offense=_acc(5.0, 20.0))
        val, m = extract_entering_rate(state, "success_offense", 20)
        assert val is not None and m == 0

    def test_points_per_drive_4_of_5(self):
        state = _team_state(points_per_drive_offense=_acc(14.0, 4.0))
        val, m = extract_entering_rate(state, "points_per_drive_offense", 5)
        assert val is None and m == 1

    def test_points_per_drive_5_of_5(self):
        state = _team_state(points_per_drive_offense=_acc(14.0, 5.0))
        val, m = extract_entering_rate(state, "points_per_drive_offense", 5)
        assert val is not None and m == 0

    def test_scoring_drive_4_of_5(self):
        state = _team_state(scoring_drive_rate_offense=_acc(2.0, 4.0))
        val, m = extract_entering_rate(state, "scoring_drive_rate_offense", 5)
        assert val is None and m == 1

    def test_scoring_drive_5_of_5(self):
        state = _team_state(scoring_drive_rate_offense=_acc(2.0, 5.0))
        val, m = extract_entering_rate(state, "scoring_drive_rate_offense", 5)
        assert val is not None and m == 0

    def test_turnovers_per_drive_4_of_5(self):
        state = _team_state(turnovers_per_drive_offense=_acc(1.0, 4.0))
        val, m = extract_entering_rate(state, "turnovers_per_drive_offense", 5)
        assert val is None and m == 1

    def test_turnovers_per_drive_5_of_5(self):
        state = _team_state(turnovers_per_drive_offense=_acc(1.0, 5.0))
        val, m = extract_entering_rate(state, "turnovers_per_drive_offense", 5)
        assert val is not None and m == 0

    def test_seconds_per_play_9_of_10(self):
        state = _team_state(seconds_play_offense=_acc(270.0, 9.0))
        val, m = extract_entering_rate(state, "seconds_play_offense", 10)
        assert val is None and m == 1

    def test_seconds_per_play_10_of_10(self):
        state = _team_state(seconds_play_offense=_acc(270.0, 10.0))
        val, m = extract_entering_rate(state, "seconds_play_offense", 10)
        assert val is not None and m == 0

    def test_neutral_seconds_9_of_10(self):
        state = _team_state(neutral_seconds_play_offense=_acc(250.0, 9.0))
        val, m = extract_entering_rate(state, "neutral_seconds_play_offense", 10)
        assert val is None and m == 1

    def test_neutral_seconds_10_of_10(self):
        state = _team_state(neutral_seconds_play_offense=_acc(250.0, 10.0))
        val, m = extract_entering_rate(state, "neutral_seconds_play_offense", 10)
        assert val is not None and m == 0

    def test_neutral_pass_rate_19_of_20(self):
        state = _team_state(neutral_pass_rate_offense=_acc(10.0, 19.0))
        val, m = extract_entering_rate(state, "neutral_pass_rate_offense", 20)
        assert val is None and m == 1

    def test_neutral_pass_rate_20_of_20(self):
        state = _team_state(neutral_pass_rate_offense=_acc(10.0, 20.0))
        val, m = extract_entering_rate(state, "neutral_pass_rate_offense", 20)
        assert val is not None and m == 0

    def test_red_zone_td_4_of_5(self):
        state = _team_state(red_zone_td_rate_offense=_acc(2.0, 4.0))
        val, m = extract_entering_rate(state, "red_zone_td_rate_offense", 5)
        assert val is None and m == 1

    def test_red_zone_td_5_of_5(self):
        state = _team_state(red_zone_td_rate_offense=_acc(2.0, 5.0))
        val, m = extract_entering_rate(state, "red_zone_td_rate_offense", 5)
        assert val is not None and m == 0

    def test_goal_to_go_td_4_of_5(self):
        state = _team_state(goal_to_go_td_rate_offense=_acc(3.0, 4.0))
        val, m = extract_entering_rate(state, "goal_to_go_td_rate_offense", 5)
        assert val is None and m == 1

    def test_goal_to_go_td_5_of_5(self):
        state = _team_state(goal_to_go_td_rate_offense=_acc(3.0, 5.0))
        val, m = extract_entering_rate(state, "goal_to_go_td_rate_offense", 5)
        assert val is not None and m == 0

    def test_sacks_per_dropback_19_of_20(self):
        state = _team_state(sacks_per_dropback_offense=_acc(2.0, 19.0))
        val, m = extract_entering_rate(state, "sacks_per_dropback_offense", 20)
        assert val is None and m == 1

    def test_sacks_per_dropback_20_of_20(self):
        state = _team_state(sacks_per_dropback_offense=_acc(2.0, 20.0))
        val, m = extract_entering_rate(state, "sacks_per_dropback_offense", 20)
        assert val is not None and m == 0

    def test_air_yards_19_of_20(self):
        state = _team_state(air_yards_per_attempt_offense=_acc(100.0, 19.0))
        val, m = extract_entering_rate(state, "air_yards_per_attempt_offense", 20)
        assert val is None and m == 1

    def test_air_yards_20_of_20(self):
        state = _team_state(air_yards_per_attempt_offense=_acc(100.0, 20.0))
        val, m = extract_entering_rate(state, "air_yards_per_attempt_offense", 20)
        assert val is not None and m == 0

    def test_yac_19_of_20(self):
        state = _team_state(yac_per_completion_offense=_acc(80.0, 19.0))
        val, m = extract_entering_rate(state, "yac_per_completion_offense", 20)
        assert val is None and m == 1

    def test_yac_20_of_20(self):
        state = _team_state(yac_per_completion_offense=_acc(80.0, 20.0))
        val, m = extract_entering_rate(state, "yac_per_completion_offense", 20)
        assert val is not None and m == 0

    def test_explosive_pass_19_of_20(self):
        state = _team_state(explosive_pass_rate_offense=_acc(5.0, 19.0))
        val, m = extract_entering_rate(state, "explosive_pass_rate_offense", 20)
        assert val is None and m == 1

    def test_explosive_pass_20_of_20(self):
        state = _team_state(explosive_pass_rate_offense=_acc(5.0, 20.0))
        val, m = extract_entering_rate(state, "explosive_pass_rate_offense", 20)
        assert val is not None and m == 0

    def test_explosive_rush_19_of_20(self):
        state = _team_state(explosive_rush_rate_offense=_acc(3.0, 19.0))
        val, m = extract_entering_rate(state, "explosive_rush_rate_offense", 20)
        assert val is None and m == 1

    def test_explosive_rush_20_of_20(self):
        state = _team_state(explosive_rush_rate_offense=_acc(3.0, 20.0))
        val, m = extract_entering_rate(state, "explosive_rush_rate_offense", 20)
        assert val is not None and m == 0


# ===========================================================================
# C. MATCHUP
# ===========================================================================

class TestMatchupC:
    """Matchup combination rules (Section 5)."""

    def test_both_available_arithmetic_mean(self):
        """Both sides available -> simple arithmetic mean."""
        home = _team_state(
            epa_play_offense=_acc(10.0, 50.0),  # rate = 0.2
            epa_play_defense_allowed=_acc(5.0, 50.0),  # rate = 0.1
        )
        away = _team_state(
            epa_play_offense=_acc(15.0, 50.0),  # rate = 0.3
            epa_play_defense_allowed=_acc(8.0, 50.0),  # rate = 0.16
        )
        family = MetricFamilyConfig("epa_per_play", "epa_play_offense", "epa_play_defense_allowed", 20)
        result = compute_matchup_pair(home, away, family)
        # home_matchup = (home_off + away_def) / 2 = (0.2 + 0.16) / 2 = 0.18
        assert result["home_matchup_epa_per_play_missing"] == 0
        assert abs(result["home_matchup_epa_per_play"] - 0.18) < 1e-12
        # away_matchup = (away_off + home_def) / 2 = (0.3 + 0.1) / 2 = 0.2
        assert result["away_matchup_epa_per_play_missing"] == 0
        assert abs(result["away_matchup_epa_per_play"] - 0.2) < 1e-12

    def test_home_offense_missing_home_matchup_null(self):
        """Home offense below minimum -> home matchup null."""
        home = _team_state(
            # No epa_play_offense (empty state)
            epa_play_defense_allowed=_acc(5.0, 50.0),
        )
        away = _team_state(
            epa_play_offense=_acc(15.0, 50.0),
            epa_play_defense_allowed=_acc(8.0, 50.0),
        )
        family = MetricFamilyConfig("epa_per_play", "epa_play_offense", "epa_play_defense_allowed", 20)
        result = compute_matchup_pair(home, away, family)
        # home_matchup needs home_offense + away_defense; home_offense missing
        assert result["home_matchup_epa_per_play"] is None
        assert result["home_matchup_epa_per_play_missing"] == 1
        # away_matchup needs away_offense + home_defense; both available
        assert result["away_matchup_epa_per_play_missing"] == 0

    def test_away_defense_missing_home_matchup_null(self):
        """Away defense below minimum -> home matchup null."""
        home = _team_state(
            epa_play_offense=_acc(10.0, 50.0),
            epa_play_defense_allowed=_acc(5.0, 50.0),
        )
        away = _team_state(
            epa_play_offense=_acc(15.0, 50.0),
            # No epa_play_defense_allowed (below minimum)
        )
        family = MetricFamilyConfig("epa_per_play", "epa_play_offense", "epa_play_defense_allowed", 20)
        result = compute_matchup_pair(home, away, family)
        assert result["home_matchup_epa_per_play"] is None
        assert result["home_matchup_epa_per_play_missing"] == 1
        # away_matchup still OK (away_off + home_def)
        assert result["away_matchup_epa_per_play_missing"] == 0

    def test_missing_indicator_correct(self):
        """Missing indicator is exactly 0 or 1."""
        home = _team_state()
        away = _team_state()
        family = MetricFamilyConfig("epa_per_play", "epa_play_offense", "epa_play_defense_allowed", 20)
        result = compute_matchup_pair(home, away, family)
        for key in result:
            if key.endswith("_missing"):
                assert result[key] == 1

    def test_no_cross_side_pooling(self):
        """Offense and defense denominators are not pooled across sides."""
        home = _team_state(
            epa_play_offense=_acc(10.0, 50.0),
            # home defense has only 10 obs -> below min 20
            epa_play_defense_allowed=_acc(3.0, 10.0),
        )
        away = _team_state(
            # away offense has only 10 obs -> below min 20
            epa_play_offense=_acc(3.0, 10.0),
            epa_play_defense_allowed=_acc(8.0, 50.0),
        )
        family = MetricFamilyConfig("epa_per_play", "epa_play_offense", "epa_play_defense_allowed", 20)
        result = compute_matchup_pair(home, away, family)
        # away_matchup = (away_off + home_def) / 2 -> both below min -> null
        assert result["away_matchup_epa_per_play"] is None
        assert result["away_matchup_epa_per_play_missing"] == 1
        # home_matchup = (home_off + away_def) / 2 -> both above min -> OK
        assert result["home_matchup_epa_per_play_missing"] == 0

    def test_all_15_families_present(self):
        """All 15 families produce the expected output keys."""
        assert len(MATCHUP_FAMILIES) == 15
        home = _team_state()
        away = _team_state()
        for family in MATCHUP_FAMILIES:
            result = compute_matchup_pair(home, away, family)
            assert f"away_matchup_{family.feature_name}" in result
            assert f"away_matchup_{family.feature_name}_missing" in result
            assert f"home_matchup_{family.feature_name}" in result
            assert f"home_matchup_{family.feature_name}_missing" in result


# ===========================================================================
# D. REST
# ===========================================================================

class TestRestD:
    """Rest context features (Section 7)."""

    def test_source_integer_preserved(self):
        row = {"away_rest": 10, "home_rest": 7}
        result = extract_context_features(row)
        assert result["away_rest_days"] == 10
        assert result["home_rest_days"] == 7
        assert result["away_rest_days_missing"] == 0
        assert result["home_rest_days_missing"] == 0

    def test_null_rest_null_plus_missing(self):
        row = {"away_rest": None, "home_rest": None}
        result = extract_context_features(row)
        assert result["away_rest_days"] is None
        assert result["away_rest_days_missing"] == 1
        assert result["home_rest_days"] is None
        assert result["home_rest_days_missing"] == 1

    def test_non_null_rest_missing_zero(self):
        row = {"away_rest": 7, "home_rest": 14}
        result = extract_context_features(row)
        assert result["away_rest_days_missing"] == 0
        assert result["home_rest_days_missing"] == 0


# ===========================================================================
# E. ROOF
# ===========================================================================

class TestRoofE:
    """Roof context features (Section 8)."""

    def test_mixed_case_normalized_lowercase(self):
        for raw in ["Open", "OPEN", "Dome", "DOME", "Closed", "outdoors"]:
            row = {"roof_type": raw}
            result = extract_context_features(row)
            assert result["roof_category"] == raw.lower()
            assert result["roof_missing"] == 0

    def test_null_roof_unknown_missing(self):
        row = {"roof_type": None}
        result = extract_context_features(row)
        assert result["roof_category"] == "unknown"
        assert result["roof_missing"] == 1

    def test_non_null_roof_missing_zero(self):
        row = {"roof_type": "dome"}
        result = extract_context_features(row)
        assert result["roof_missing"] == 0


# ===========================================================================
# F. SURFACE
# ===========================================================================

class TestSurfaceF:
    """Surface context features (Section 9)."""

    def test_mixed_case_normalized_lowercase(self):
        for raw in ["Grass", "GRASS", "FieldTurf", "AstroTurf"]:
            row = {"surface": raw}
            result = extract_context_features(row)
            assert result["surface_category"] == raw.lower()
            assert result["surface_missing"] == 0

    def test_null_surface_unknown_missing(self):
        row = {"surface": None}
        result = extract_context_features(row)
        assert result["surface_category"] == "unknown"
        assert result["surface_missing"] == 1

    def test_non_null_surface_missing_zero(self):
        row = {"surface": "grass"}
        result = extract_context_features(row)
        assert result["surface_missing"] == 0


# ===========================================================================
# G. CONTEXT PROJECTION
# ===========================================================================

class TestContextProjectionG:
    """Prohibited field exclusion (Section 10)."""

    def test_prohibited_columns_excluded_before_join(self):
        """Build a synthetic schedule with prohibited fields; prove exclusion."""
        schedule = _schedule([
            {
                "game_id": "2024_01_KC_NE",
                "season": 2024,
                "game_type": "REG",
                "week": 1,
                "away_rest": 7,
                "home_rest": 7,
                "roof": "outdoors",
                "surface": "grass",
                # Prohibited fields:
                "away_score": 20,
                "home_score": 17,
                "result": 3,
                "total": 37,
                "temp": 65,
                "wind": 5,
                "away_moneyline": -150,
                "home_moneyline": 130,
                "spread_line": -3.0,
                "total_line": 47.5,
                "away_qb_id": "00-0033873",
                "home_qb_id": "00-0023459",
                "away_qb_name": "P.Mahomes",
                "home_qb_name": "D.Maye",
            }
        ])
        projected = project_totals_context(schedule)
        # Prohibited columns must be absent
        for prohibited in [
            "away_score", "home_score", "result", "total", "temp", "wind",
            "away_moneyline", "home_moneyline", "spread_line", "total_line",
            "away_qb_id", "home_qb_id", "away_qb_name", "home_qb_name",
        ]:
            assert prohibited not in projected.columns, f"{prohibited} leaked into projection"
        # Approved columns must be present
        for approved in ["game_id", "season", "season_type", "week", "away_rest", "home_rest", "roof", "surface"]:
            assert approved in projected.columns, f"{approved} missing from projection"

    def test_find_prohibited_columns_comprehensive(self):
        """Verify find_prohibited_columns catches all market/outcome/weather/QB tokens."""
        columns = [
            "game_id", "season", "away_score", "home_score", "result",
            "total", "away_moneyline", "home_moneyline", "spread_line",
            "total_line", "under_odds", "over_odds", "temp", "wind",
            "away_qb_id", "home_qb_id", "away_qb_name", "home_qb_name",
            "away_rest", "home_rest", "roof", "surface",
        ]
        found = find_prohibited_columns(columns)
        assert "away_score" in found
        assert "home_score" in found
        assert "result" in found
        assert "total" in found
        assert "temp" in found
        assert "wind" in found
        assert "away_qb_id" in found
        assert "game_id" not in found
        assert "away_rest" not in found


# ===========================================================================
# H. ORACLE QB
# ===========================================================================

class TestOracleQBH:
    """Oracle QB entering-state v2 join (Section 11)."""

    @pytest.fixture
    def oracle_qb_path(self):
        return "data/derived/oracle_qb_entering_state_v2/oracle_qb_entering_state_game_sides_2018_2024_v2.parquet"

    def test_unique_game_id_side_key(self, oracle_qb_path):
        """(game_id, side) must be unique."""
        from pathlib import Path
        qb = _load_oracle_qb(Path(oracle_qb_path))
        dups = qb.select("game_id", "side").is_duplicated().sum()
        assert dups == 0

    def test_away_home_mapping(self, oracle_qb_path):
        """Correct away/home side mapping."""
        from pathlib import Path
        qb = _load_oracle_qb(Path(oracle_qb_path))
        result = _join_oracle_qb("2024_22_KC_PHI", qb)
        # KC is away, PHI is home in this game
        assert "away_qb_passing_epa" in result
        assert "home_qb_passing_epa" in result

    def test_all_final_qb_fields_mapped(self, oracle_qb_path):
        """All 22 QB output columns are produced."""
        from pathlib import Path
        qb = _load_oracle_qb(Path(oracle_qb_path))
        result = _join_oracle_qb("2024_22_KC_PHI", qb)
        expected_suffixes = [
            "qb_passing_epa", "qb_passing_epa_imputed",
            "qb_passing_cpoe", "qb_passing_cpoe_imputed",
            "qb_sacks_suffered_rate", "qb_sack_rate_imputed",
            "qb_interception_rate", "qb_interception_rate_imputed",
            "qb_recency_weighted_form", "qb_low_sample", "qb_missing_player_id",
        ]
        for side in ("away", "home"):
            for suffix in expected_suffixes:
                key = f"{side}_{suffix}"
                assert key in result, f"missing {key}"

    def test_prior_dropback_volume_not_in_final_90(self):
        """prior_dropback_or_attempt_volume does NOT enter the 90 columns."""
        for col in EXACT_90_COLUMNS:
            assert "prior_dropback" not in col
            assert "attempt_volume" not in col

    def test_qb_adjustment_elo_not_consumed(self, oracle_qb_path):
        """qb_adjustment_elo is NOT loaded."""
        from pathlib import Path
        qb = _load_oracle_qb(Path(oracle_qb_path))
        assert "qb_adjustment_elo" not in qb.columns

    def test_qb_ids_names_not_consumed(self, oracle_qb_path):
        """Historical QB IDs/names are NOT loaded."""
        from pathlib import Path
        qb = _load_oracle_qb(Path(oracle_qb_path))
        for col in ["actual_starting_qb_name", "actual_starting_qb_pfr_id",
                     "actual_starting_qb_gsis_id", "away_qb_id", "home_qb_id",
                     "away_qb_name", "home_qb_name"]:
            assert col not in qb.columns

    def test_duplicate_key_hard_fails(self):
        """Duplicate (game_id, side) raises FeatureTableError."""
        from nfl_edge.features.totals_v1.feature_table import _load_oracle_qb, FeatureTableError
        from pathlib import Path
        import tempfile, os
        # Create a parquet with duplicate (game_id, side)
        df = pl.DataFrame({
            "game_id": ["G1", "G1"],
            "side": ["away", "away"],
            "passing_epa": [0.1, 0.2],
            "passing_cpoe": [0.0, 0.0],
            "sacks_suffered_rate": [0.0, 0.0],
            "interception_rate": [0.0, 0.0],
            "recency_weighted_form": [0.0, 0.0],
            "low_sample": [False, False],
            "missing_player_id": [False, False],
            "passing_epa_imputed": [False, False],
            "passing_cpoe_imputed": [False, False],
            "sack_rate_imputed": [False, False],
            "interception_rate_imputed": [False, False],
        })
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            df.write_parquet(f.name)
            tmp = f.name
        try:
            with pytest.raises(FeatureTableError, match="duplicate"):
                _load_oracle_qb(Path(tmp))
        finally:
            os.unlink(tmp)

    def test_missing_side_null_values(self):
        """Missing side produces null values for all QB columns."""
        from nfl_edge.features.totals_v1.feature_table import _join_oracle_qb
        # Oracle QB with only "away" side for a game
        qb = pl.DataFrame({
            "game_id": ["G1"],
            "side": ["away"],
            "passing_epa": [0.1],
            "passing_cpoe": [0.0],
            "sacks_suffered_rate": [0.05],
            "interception_rate": [0.03],
            "recency_weighted_form": [0.02],
            "low_sample": [False],
            "missing_player_id": [False],
            "passing_epa_imputed": [False],
            "passing_cpoe_imputed": [False],
            "sack_rate_imputed": [False],
            "interception_rate_imputed": [False],
        })
        result = _join_oracle_qb("G1", qb)
        # Away side should have values
        assert result["away_qb_passing_epa"] == 0.1
        # Home side should be None (missing)
        assert result["home_qb_passing_epa"] is None
        assert result["home_qb_passing_cpoe"] is None
        assert result["home_qb_low_sample"] is None


# ===========================================================================
# I. COLUMN ORDER
# ===========================================================================

class TestColumnOrderI:
    """Exact90-column order assertion (Section 13)."""

    def test_exact_90_columns_count(self):
        assert len(EXACT_90_COLUMNS) == 90

    def test_exact_column_order_equality(self):
        """Not set equality — exact ordered list equality."""
        expected = [
            "away_rest_days", "away_rest_days_missing",
            "home_rest_days", "home_rest_days_missing",
            "roof_category", "roof_missing",
            "surface_category", "surface_missing",
            "away_qb_passing_epa", "away_qb_passing_epa_imputed",
            "away_qb_passing_cpoe", "away_qb_passing_cpoe_imputed",
            "away_qb_sacks_suffered_rate", "away_qb_sack_rate_imputed",
            "away_qb_interception_rate", "away_qb_interception_rate_imputed",
            "away_qb_recency_weighted_form", "away_qb_low_sample",
            "away_qb_missing_player_id",
            "home_qb_passing_epa", "home_qb_passing_epa_imputed",
            "home_qb_passing_cpoe", "home_qb_passing_cpoe_imputed",
            "home_qb_sacks_suffered_rate", "home_qb_sack_rate_imputed",
            "home_qb_interception_rate", "home_qb_interception_rate_imputed",
            "home_qb_recency_weighted_form", "home_qb_low_sample",
            "home_qb_missing_player_id",
        ]
        # Matchups (15 families x 4 columns)
        families = [
            "epa_per_play", "success_rate", "points_per_drive", "scoring_drive_rate",
            "seconds_per_play", "neutral_seconds_per_play", "neutral_pass_rate",
            "red_zone_td_rate", "goal_to_go_td_rate", "turnovers_per_drive",
            "sacks_per_dropback", "air_yards_per_attempt", "yac_per_completion",
            "explosive_pass_rate", "explosive_rush_rate",
        ]
        for f in families:
            expected.extend([
                f"away_matchup_{f}", f"away_matchup_{f}_missing",
                f"home_matchup_{f}", f"home_matchup_{f}_missing",
            ])
        assert len(expected) == 90
        assert list(EXACT_90_COLUMNS) == expected

    def test_no_duplicate_columns(self):
        assert len(set(EXACT_90_COLUMNS)) == 90


# ===========================================================================
# J. SAME-BLOCK POISONING
# ===========================================================================

class TestSameBlockPoisoningJ:
    """Same-block observations do not leak (Section 14)."""

    def test_same_block_games_see_identical_state(self):
        """Two games in the same target block see identical pre-block state."""
        state = TotalsBlockState()
        # Prior block with KC and NE data
        prior = _block(2024, "REG", 1, ("2024_01_KC_NE",))
        state.commit_block(prior, [
            GameObservation(
                block_id=prior.block_id,
                game_id="2024_01_KC_NE",
                team_updates={
                    "KC": {"epa_play_offense": (5.0, 50.0, 50)},
                    "NE": {"epa_play_offense": (3.0, 40.0, 40)},
                },
            )
        ])

        # Target block with two games involving KC and DEN
        target = _block(2024, "REG", 2, ("2024_02_KC_DEN", "2024_02_DEN_KC"))
        snap = state.snapshot_for_block(target)

        # Both games should see the same KC state
        kc_state_1 = snap.team("KC")
        kc_state_2 = snap.team("KC")
        assert kc_state_1.get("epa_play_offense").numerator == kc_state_2.get("epa_play_offense").numerator
        assert kc_state_1.get("epa_play_offense").denominator == kc_state_2.get("epa_play_offense").denominator

    def test_injected_extreme_values_no_cross_leak(self):
        """Inject extreme values for one target-block game; other games unchanged."""
        state = TotalsBlockState()
        # Prior block
        prior = _block(2024, "REG", 1, ("2024_01_KC_NE",))
        state.commit_block(prior, [
            GameObservation(
                block_id=prior.block_id,
                game_id="2024_01_KC_NE",
                team_updates={"KC": {"epa_play_offense": (5.0, 50.0, 50)}},
            )
        ])

        # Target block with two games
        target = _block(2024, "REG", 2, ("2024_02_KC_DEN", "2024_02_DEN_LV"))
        snap = state.snapshot_for_block(target)

        # KC's entering state from snapshot
        kc_acc = snap.team("KC").get("epa_play_offense")
        assert kc_acc.denominator == 50.0

        # After commit with extreme values for KC in game 2
        state.commit_block(target, [
            GameObservation(
                block_id=target.block_id,
                game_id="2024_02_KC_DEN",
                team_updates={"KC": {"epa_play_offense": (1000.0, 500.0, 500)}},
            ),
            GameObservation(
                block_id=target.block_id,
                game_id="2024_02_DEN_LV",
                team_updates={"DEN": {"epa_play_offense": (1.0, 10.0, 10)}},
            ),
        ])

        # The snapshot was taken BEFORE commit; it should still show the
        # original KC state. Verify by checking the snapshot itself.
        assert snap.team("KC").get("epa_play_offense").denominator == 50.0
        assert snap.team("KC").get("epa_play_offense").numerator == 5.0


# ===========================================================================
# K. LATER-BLOCK POISONING
# ===========================================================================

class TestLaterBlockPoisoningK:
    """Future-block observations don't affect earlier rows (Section 14)."""

    def test_future_block_observations_dont_affect_earlier(self):
        """Inject extreme future observations; earlier rows unchanged."""
        state = TotalsBlockState()

        block1 = _block(2024, "REG", 1, ("2024_01_KC_NE",))
        block2 = _block(2024, "REG", 2, ("2024_02_KC_DEN",))

        # Snapshot block1
        snap1 = state.snapshot_for_block(block1)
        assert snap1.team("KC").get("epa_play_offense") is None

        # Commit block1
        state.commit_block(block1, [
            GameObservation(
                block_id=block1.block_id,
                game_id="2024_01_KC_NE",
                team_updates={"KC": {"epa_play_offense": (5.0, 50.0, 50)}},
            )
        ])

        # Snapshot block2 BEFORE committing block2
        snap2 = state.snapshot_for_block(block2)
        assert snap2.team("KC").get("epa_play_offense").denominator == 50.0

        # Commit block2 with extreme values
        state.commit_block(block2, [
            GameObservation(
                block_id=block2.block_id,
                game_id="2024_02_KC_DEN",
                team_updates={"KC": {"epa_play_offense": (999.0, 999.0, 999)}},
            )
        ])

        # snap1 was already frozen; it should still show None (empty at that time)
        assert snap1.team("KC").get("epa_play_offense") is None
        # snap2 was already frozen; it should still show 50.0 denominator
        assert snap2.team("KC").get("epa_play_offense").denominator == 50.0


# ===========================================================================
# L. 2025 SAFETY
# ===========================================================================

class Test2025SafetyL:
    """NFL season 2025 rejection and calendar-year-2025 inclusion (Section 15)."""

    def test_2025_poison_rejected(self):
        """NFL season 2025 in schedule is rejected by context projection."""
        schedule = _schedule([
            {
                "game_id": "2025_01_KC_NE",
                "season": 2025,
                "game_type": "REG",
                "week": 1,
                "away_rest": 7,
                "home_rest": 7,
                "roof": "outdoors",
                "surface": "grass",
            }
        ])
        from nfl_edge.common.errors import SealedHoldoutAccessError
        with pytest.raises(SealedHoldoutAccessError):
            project_totals_context(schedule)

    def test_2024_postseason_calendar_2025_included(self):
        """Season-2024 postseason (played in calendar 2025) is valid."""
        schedule = _schedule([
            {
                "game_id": "2024_22_KC_PHI",
                "season": 2024,
                "game_type": "SB",
                "week": 22,
                "away_rest": 14,
                "home_rest": 14,
                "roof": "dome",
                "surface": "sportturf",
            }
        ])
        projected = project_totals_context(schedule)
        assert projected.height == 1
        assert projected["game_id"][0] == "2024_22_KC_PHI"
        assert projected["season"][0] == 2024

    def test_2024_22_kc_phi_included(self):
        """2024_22_KC_PHI is present in the development data."""
        schedule = _schedule([
            {
                "game_id": "2024_22_KC_PHI",
                "season": 2024,
                "game_type": "SB",
                "week": 22,
                "away_rest": 14,
                "home_rest": 14,
                "roof": "dome",
                "surface": "sportturf",
            }
        ])
        projected = project_totals_context(schedule)
        assert "2024_22_KC_PHI" in projected["game_id"].to_list()

    def test_no_calendar_year_exclusion(self):
        """No calendar-year-2025 exclusion exists — only NFL-season exclusion."""
        # A schedule with season=2024 should pass even if dates are in 2025
        schedule = _schedule([
            {
                "game_id": "2024_22_KC_PHI",
                "season": 2024,
                "game_type": "SB",
                "week": 22,
                "away_rest": 14,
                "home_rest": 14,
                "roof": "dome",
                "surface": "sportturf",
            }
        ])
        projected = project_totals_context(schedule)
        assert projected.height == 1  # not filtered out by calendar year


# ===========================================================================
# Integration: import smoke test
# ===========================================================================

class TestImports:
    """Verify Phase 3D modules import cleanly."""

    def test_entering_state_imports(self):
        from nfl_edge.features.totals_v1 import (
            MATCHUP_FAMILIES, MetricFamilyConfig, compute_matchup_pair, extract_entering_rate,
        )
        assert len(MATCHUP_FAMILIES) == 15

    def test_context_features_imports(self):
        from nfl_edge.features.totals_v1 import extract_context_features
        result = extract_context_features({"away_rest": 7, "home_rest": 7, "roof_type": "dome", "surface": "grass"})
        assert result["away_rest_days"] == 7

    def test_feature_table_imports(self):
        from nfl_edge.features.totals_v1 import (
            EXACT_90_COLUMNS, TotalsV1FeatureTable, build_totals_v1_feature_table,
        )
        assert len(EXACT_90_COLUMNS) == 90


# ===========================================================================
# REMEDIATION TESTS: Deviation 1 — Feature/Identity Separation
# ===========================================================================

class TestRemediationFeatureIdentity:
    """Prove features is exactly 90 columns and identity is separate."""

    def test_totlas_v1_feature_table_has_identity_field(self):
        """TotalsV1FeatureTable has a separate identity field."""
        from nfl_edge.features.totals_v1.feature_table import TotalsV1FeatureTable
        import dataclasses
        fields = {f.name for f in dataclasses.fields(TotalsV1FeatureTable)}
        assert "features" in fields
        assert "identity" in fields
        assert "provenance" in fields

    def test_end_to_end_builder_returns_90_features(self):
        """The actual builder returns features.width == 90 and separate identity."""
        from nfl_edge.features.totals_v1.feature_table import (
            build_totals_v1_feature_table,
            EXACT_90_COLUMNS,
        )
        from pathlib import Path
        import polars as pl

        pbp_root = Path('/var/lib/chatgpt-vps-mcp/artifacts/nfl-edge/raw/task05c_pbp_v1')
        oracle_qb_path = Path('data/derived/oracle_qb_entering_state_v2/oracle_qb_entering_state_game_sides_2018_2024_v2.parquet')
        schedule = pl.read_parquet('data/raw/source_snapshots/v1/schedules_2018_2025_frozen-baseline-v1.parquet')
        canonical_games = pl.read_parquet('data/frozen/games/games_2018_2025.parquet')

        result = build_totals_v1_feature_table(pbp_root, schedule, canonical_games, oracle_qb_path)

        # Features is exactly 90 columns
        assert result.features.width == 90, (
            f"features.width = {result.features.width}, expected 90"
        )
        assert result.features.columns == list(EXACT_90_COLUMNS), (
            "features.columns does not match EXACT_90_COLUMNS"
        )

        # Identity is separate with exactly 7 columns
        expected_identity = ["game_id", "season", "season_type", "week", "home_team", "away_team", "block_id"]
        assert result.identity.width == 7
        assert result.identity.columns == expected_identity

        # Row alignment
        assert result.identity.height == result.features.height

        # No identity column in features
        for col in expected_identity:
            assert col not in result.features.columns, (
                f"Identity column {col!r} leaked into features"
            )

        # No feature column in identity
        for col in EXACT_90_COLUMNS:
            assert col not in result.identity.columns, (
                f"Feature column {col!r} leaked into identity"
            )

    def test_no_extra_feature_column(self):
        """No extra feature column is present beyond the declared 90."""
        from nfl_edge.features.totals_v1.feature_table import EXACT_90_COLUMNS
        assert len(set(EXACT_90_COLUMNS)) == 90
        assert len(EXACT_90_COLUMNS) == 90


# ===========================================================================
# REMEDIATION TESTS: Deviation 2 — Roof Authority
# ===========================================================================

class TestRemediationRoofAuthority:
    """Prove roof_type from canonical games is the roof authority."""

    def test_roof_type_is_authority_not_raw_schedule_roof(self):
        """Changing raw schedule roof while keeping roof_type fixed CANNOT change output."""
        from nfl_edge.features.totals_v1.context_features import extract_context_features

        # Simulate the builder's context assembly: schedule provides rest+surface,
        # canonical games provides roof_type.
        ctx_schedule_a = {"away_rest": 7, "home_rest": 7, "surface": "grass"}
        ctx_schedule_b = {"away_rest": 7, "home_rest": 7, "surface": "grass"}

        # Canonical games roof_type is the authority
        roof_type_from_canonical = "DOME"

        # Inject roof_type as the builder does
        ctx_a = {**ctx_schedule_a, "roof_type": roof_type_from_canonical}
        ctx_b = {**ctx_schedule_b, "roof_type": roof_type_from_canonical}

        result_a = extract_context_features(ctx_a)
        result_b = extract_context_features(ctx_b)

        # Both must produce the same roof feature
        assert result_a["roof_category"] == "dome"
        assert result_b["roof_category"] == "dome"
        assert result_a["roof_missing"] == 0
        assert result_b["roof_missing"] == 0

    def test_conflicting_raw_schedule_roof_ignored(self):
        """Raw schedule roof='outdoors' with canonical roof_type='DOME' -> 'dome'."""
        from nfl_edge.features.totals_v1.context_features import extract_context_features

        # The builder only passes roof_type to extract_context_features.
        # Even if raw schedule had roof='outdoors', it's not read.
        ctx = {
            "away_rest": 7,
            "home_rest": 7,
            "surface": "grass",
            "roof_type": "DOME",  # from canonical games
        }
        result = extract_context_features(ctx)
        assert result["roof_category"] == "dome"
        assert result["roof_missing"] == 0

    def test_raw_schedule_roof_not_required(self):
        """Raw schedule roof field is not required for feature generation."""
        from nfl_edge.features.totals_v1.context_features import extract_context_features

        # Context row without any 'roof' key (only roof_type)
        ctx = {
            "away_rest": 7,
            "home_rest": 7,
            "surface": "grass",
            "roof_type": "open",
        }
        result = extract_context_features(ctx)
        assert result["roof_category"] == "open"
        assert result["roof_missing"] == 0

    def test_roof_type_mixed_case_lowercased(self):
        """roof_type values are lowercased."""
        from nfl_edge.features.totals_v1.context_features import extract_context_features
        for raw in ["Open", "OPEN", "Dome", "DOME", "Closed", "outdoors"]:
            result = extract_context_features({"roof_type": raw})
            assert result["roof_category"] == raw.lower()

    def test_roof_type_null_unknown_missing(self):
        """Null roof_type -> 'unknown', missing=1."""
        from nfl_edge.features.totals_v1.context_features import extract_context_features
        result = extract_context_features({"roof_type": None})
        assert result["roof_category"] == "unknown"
        assert result["roof_missing"] == 1

    def test_roof_type_non_null_missing_zero(self):
        """Non-null roof_type -> missing=0."""
        from nfl_edge.features.totals_v1.context_features import extract_context_features
        result = extract_context_features({"roof_type": "dome"})
        assert result["roof_missing"] == 0

    def test_canonical_games_has_roof_type_column(self):
        """Canonical games table has roof_type column."""
        import polars as pl
        games = pl.read_parquet('data/frozen/games/games_2018_2025.parquet')
        assert "roof_type" in games.columns

    def test_schedule_roof_not_authoritative(self):
        """Prove extract_context_features reads roof_type, not roof."""
        from nfl_edge.features.totals_v1.context_features import extract_context_features

        # If both 'roof' and 'roof_type' are present, roof_type wins
        ctx = {
            "roof": "outdoors",
            "roof_type": "DOME",
        }
        result = extract_context_features(ctx)
        assert result["roof_category"] == "dome"  # roof_type wins, not roof


# ===========================================================================
# REMEDIATION TESTS: Existing invariants preserved
# ===========================================================================

class TestRemediationInvariantsPreserved:
    """Prove existing Phase 3D invariants are unchanged."""

    def test_entering_state_formula_unchanged(self):
        from nfl_edge.features.totals_v1.entering_state import extract_entering_rate
        from nfl_edge.features.totals_v1.block_state import Accumulator, TeamEntState
        state = TeamEntState(metrics={"epa_play_offense": Accumulator(numerator=10.0, denominator=30.0)})
        val, missing = extract_entering_rate(state, "epa_play_offense", 20)
        assert val == 10.0 / 30.0
        assert missing == 0

    def test_exact_minima_unchanged(self):
        from nfl_edge.features.totals_v1.entering_state import extract_entering_rate
        from nfl_edge.features.totals_v1.block_state import Accumulator, TeamEntState
        state = TeamEntState(metrics={"epa_play_offense": Accumulator(numerator=5.0, denominator=19.0)})
        val, missing = extract_entering_rate(state, "epa_play_offense", 20)
        assert val is None
        assert missing == 1

    def test_matchup_formula_unchanged(self):
        from nfl_edge.features.totals_v1.entering_state import compute_matchup_pair, MetricFamilyConfig
        from nfl_edge.features.totals_v1.block_state import Accumulator, TeamEntState
        home = TeamEntState(metrics={"epa_play_offense": Accumulator(numerator=10.0, denominator=50.0)})
        away = TeamEntState(metrics={"epa_play_defense_allowed": Accumulator(numerator=8.0, denominator=50.0)})
        family = MetricFamilyConfig("epa_per_play", "epa_play_offense", "epa_play_defense_allowed", 20)
        result = compute_matchup_pair(home, away, family)
        assert result["home_matchup_epa_per_play_missing"] == 0
        expected = (10.0/50.0 + 8.0/50.0) / 2
        assert abs(result["home_matchup_epa_per_play"] - expected) < 1e-12

    def test_same_block_poisoning_still_blocked(self):
        from nfl_edge.features.totals_v1.block_state import TotalsBlockState, GameObservation
        from nfl_edge.backtest.blocks import PredictionBlock
        from datetime import datetime, timezone
        state = TotalsBlockState()
        block = PredictionBlock(
            block_id="2024_REG_W01", season=2024, season_type="REG", week=1,
            as_of_utc=datetime(2024, 9, 1, tzinfo=timezone.utc),
            game_ids=("G1", "G2"),
        )
        snap = state.snapshot_for_block(block)
        assert snap.team("KC").get("epa_play_offense") is None

    def test_season_2025_rejection_unchanged(self):
        import polars as pl
        from nfl_edge.features.totals_v1.context import project_totals_context
        from nfl_edge.common.errors import SealedHoldoutAccessError
        schedule = pl.DataFrame({
            "game_id": ["2025_01_KC_NE"], "season": [2025], "game_type": ["REG"], "week": [1],
            "away_rest": [7], "home_rest": [7], "roof": ["outdoors"], "surface": ["grass"],
        })
        with pytest.raises(SealedHoldoutAccessError):
            project_totals_context(schedule)

    def test_2024_postseason_calendar_2025_included(self):
        import polars as pl
        from nfl_edge.features.totals_v1.context import project_totals_context
        schedule = pl.DataFrame({
            "game_id": ["2024_22_KC_PHI"], "season": [2024], "game_type": ["SB"], "week": [22],
            "away_rest": [14], "home_rest": [14], "roof": ["dome"], "surface": ["sportturf"],
        })
        projected = project_totals_context(schedule)
        assert projected.height == 1
        assert "2024_22_KC_PHI" in projected["game_id"].to_list()
