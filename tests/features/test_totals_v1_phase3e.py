"""Phase 3E full validation + adversarial leakage + provenance + reproducibility.

Additive validation over the accepted, already-built Totals V1 pipeline.
Does NOT change formulas, minima, source authority, or semantics. Where the
frozen contract required a validation-only guard (conflicting
``fixed_drive_result`` hard-fail), the smallest correction was made and is
regression-tested here.

Real-data audits (drive-result conflicts, team normalization, provenance
truthfulness, reproducibility, row-order determinism, exact-90 real build)
are covered by dedicated runner/audit scripts referenced in the Phase 3E
report; this file holds the unit/adversarial checks that need only synthetic
frames.
"""

from __future__ import annotations

from datetime import datetime, timezone

import polars as pl
import pytest

from nfl_edge.backtest.blocks import PredictionBlock
from nfl_edge.common.errors import SealedHoldoutAccessError, WalkForwardError
from nfl_edge.features.totals_v1.block_state import (
    Accumulator,
    GameObservation,
    TeamEntState,
    TotalsBlockState,
)
from nfl_edge.features.totals_v1.chronology import (
    build_totals_blocks,
    is_strictly_earlier,
)
from nfl_edge.features.totals_v1.context import (
    APPROVED_CONTEXT_FIELDS,
    find_prohibited_columns,
    project_totals_context,
)
from nfl_edge.features.totals_v1.context_features import extract_context_features
from nfl_edge.features.totals_v1.drive_observations import (
    DrivePointsError,
    build_possessions,
    goal_to_go_opportunity_observations,
    red_zone_opportunity_observations,
)
from nfl_edge.features.totals_v1.entering_state import (
    MATCHUP_FAMILIES,
    compute_matchup_pair,
    extract_entering_rate,
)
from nfl_edge.features.totals_v1.feature_table import (
    EXACT_90_COLUMNS,
    TeamNormalizationError,
    _load_oracle_qb,
    _normalize_pbp_teams_to_canonical,
)
from nfl_edge.features.totals_v1.game_observations import build_team_updates
from nfl_edge.features.totals_v1.mapping import map_pbp_to_canonical
from nfl_edge.features.totals_v1.pace_observations import (
    build_pace_intervals,
    pace_interval_observations,
)
from nfl_edge.features.totals_v1.pbp_semantics import (
    annotate_pbp_semantics,
    epa_observation,
    success_observation,
)
from nfl_edge.features.totals_v1.provenance import ProvenanceCounters
from nfl_edge.features.totals_v1.season import (
    SEASON_TYPE_PRIORITY,
    SEALED_HOLDOUT_SEASON,
    assert_frame_development_only,
)


def utc(dt):
    return dt.replace(tzinfo=timezone.utc)


def block(block_id, season=2020, st="REG", week=1, game_ids=("G1",), asof=None):
    asof = asof or utc(datetime(2020, 9, 15, 12, 0, 0))
    return PredictionBlock(
        block_id=block_id,
        season=season,
        season_type=st,
        week=week,
        as_of_utc=asof,
        game_ids=tuple(game_ids),
    )


# ---------------------------------------------------------------------------
# Synthetic annotated PBP frame builder
# ---------------------------------------------------------------------------

REQUIRED = [
    "game_id", "season", "posteam", "defteam", "play_type", "play_deleted",
    "aborted_play", "pass_attempt", "rush_attempt", "complete_pass",
    "qb_dropback", "qb_kneel", "qb_spike", "sack", "epa", "success",
    "interception", "fumble_lost", "fixed_drive", "fixed_drive_result",
    "play_id", "qtr", "score_differential", "game_seconds_remaining",
    "yardline_100", "goal_to_go", "yards_gained", "air_yards",
    "yards_after_catch",
]


def frame(rows, season=2020, game_id="2020_01_KC_PHI"):
    defaults = {
        "game_id": game_id, "season": season, "posteam": "KC", "defteam": "PHI",
        "play_type": "pass", "play_deleted": 0, "aborted_play": 0,
        "pass_attempt": 1, "rush_attempt": 0, "complete_pass": 1,
        "qb_dropback": 1, "qb_kneel": 0, "qb_spike": 0, "sack": 0,
        "epa": 0.5, "success": 1, "interception": 0, "fumble_lost": 0,
        "fixed_drive": 1, "fixed_drive_result": "Punt", "play_id": 0,
        "qtr": 1, "score_differential": 0, "game_seconds_remaining": 3600,
        "yardline_100": 50, "goal_to_go": 0, "yards_gained": 4,
        "air_yards": 6, "yards_after_catch": 3,
        "week": 1, "home_team": "KC", "away_team": "PHI",
    }
    out = []
    for i, ov in enumerate(rows):
        row = {**defaults, **ov}
        row["play_id"] = ov.get("play_id", i + 1)
        out.append(row)
    return pl.DataFrame(out)


def annotated(rows, season=2020, game_id="2020_01_KC_PHI"):
    return annotate_pbp_semantics(frame(rows, season=season, game_id=game_id))


# ===========================================================================
# 1. PBP SEMANTIC ADVERSARIAL
# ===========================================================================


class TestVfpAdversarial:
    def test_ordinary_scrimmage_vfp_regardless_of_sp0(self):
        f = annotated([{"play_type": "pass", "sp": 0}, {"play_type": "run", "rush_attempt": 1, "pass_attempt": 0, "complete_pass": 0, "qb_dropback": 0, "sp": 0}])
        assert f["is_vfp"].to_list() == [True, True]

    def test_scoring_vfp_regardless_of_sp1(self):
        f = annotated([{"play_type": "pass", "sp": 1}, {"play_type": "run", "rush_attempt": 1, "pass_attempt": 0, "complete_pass": 0, "qb_dropback": 0, "sp": 1}])
        assert f["is_vfp"].to_list() == [True, True]

    def test_sp_only_change_does_not_alter_vfp(self):
        a = annotated([{"play_type": "pass", "sp": 0}])
        b = annotated([{"play_type": "pass", "sp": 1}])
        c = annotated([{"play_type": "run", "rush_attempt": 1, "pass_attempt": 0, "complete_pass": 0, "qb_dropback": 0, "sp": 0}])
        d = annotated([{"play_type": "run", "rush_attempt": 1, "pass_attempt": 0, "complete_pass": 0, "qb_dropback": 0, "sp": 1}])
        assert a["is_vfp"].to_list() == b["is_vfp"].to_list() == [True]
        assert c["is_vfp"].to_list() == d["is_vfp"].to_list() == [True]

    @pytest.mark.parametrize("bad", [
        {"play_deleted": 1},
        {"aborted_play": 1},
        {"play_type": "no_play"},
        {"play_type": "kickoff"},
        {"play_type": "punt"},
        {"play_type": "field_goal"},
        {"play_type": "extra_point"},
        {"play_type": "two_point_attempt"},
        {"play_type": "timeout"},
        {"play_type": "missing"},
    ])
    def test_excluded_classes_never_vfp(self, bad):
        f = annotated([bad])
        assert f["is_vfp"].to_list() == [False]

    def test_null_posteam_or_defteam_not_vfp(self):
        f = annotated([{"posteam": None}, {"defteam": None}])
        assert f["is_vfp"].to_list() == [False, False]

    def test_penalty_bearing_qualifying_vfp_stays_eligible(self):
        # VFP predicate carries no penalty term; a penalty-bearing pass/run
        # that otherwise qualifies remains VFP and contributes EPA/success.
        f = annotated([{"play_type": "pass", "penalty": 1, "penalty_team": "KC"}])
        assert f["is_vfp"].to_list() == [True]
        assert f["has_epa_obs"].to_list() == [True]


# ===========================================================================
# 2. NULL SEMANTICS (no silent null->0 conversion)
# ===========================================================================


class TestNullSemantics:
    def test_epa_null_excluded_zero_observed(self):
        f = annotated([{"epa": None}, {"epa": 0.0}, {"epa": 1.5}])
        rows = f.iter_rows(named=True)
        triples = [epa_observation(r) for r in rows]
        # null -> (0,0,0); 0.0 -> (0.0,1,1); 1.5 -> (1.5,1,1)
        assert triples == [(0.0, 0.0, 0), (0.0, 1.0, 1), (1.5, 1.0, 1)]

    def test_success_null_excluded_zero_observed(self):
        f = annotated([{"success": None}, {"success": 0}, {"success": 1}])
        rows = list(f.iter_rows(named=True))
        assert [success_observation(r) for r in rows] == [
            (0.0, 0.0, 0), (0.0, 1.0, 1), (1.0, 1.0, 1),
        ]

    def test_pace_clock_null_no_interval(self):
        # Two VFPs where one has null clock -> no interval from that pair.
        f = annotated([
            {"play_id": 1, "game_seconds_remaining": 3600},
            {"play_id": 2, "game_seconds_remaining": None},
        ])
        assert build_pace_intervals(f) == []

    def test_drive_result_null_excluded_from_denominators(self):
        f = annotated([
            {"play_id": 1, "fixed_drive_result": None},
            {"play_id": 2, "fixed_drive": 2, "fixed_drive_result": "Punt"},
        ])
        poss = build_possessions(f)
        # Only drive 2 (non-null result) is included.
        assert poss["fixed_drive"].to_list() == [2]

    def test_null_event_flags_create_no_turnover_or_sack(self):
        f = annotated([
            {"play_type": "pass", "interception": None, "fumble_lost": None, "sack": None},
        ])
        # A null event flag must not TRUTHY-create a turnover/sack event.
        # (Polars three-valued logic may leave the column null; that never
        # counts as an event at the observation layer.)
        assert not bool(f["is_turnover_event"][0])
        # Sack observation: null sack -> (0,0,0), no sack counted.
        from nfl_edge.features.totals_v1.pbp_semantics import sack_observation
        assert sack_observation(next(iter(f.iter_rows(named=True)))) == (0.0, 0.0, 0)

    def test_no_blanket_fill_null_zero_in_metric_paths(self):
        # Guard against a regression that zero-fills observable nulls.
        from nfl_edge.features import totals_v1 as tv
        import pathlib
        root = pathlib.Path(tv.__file__).parent
        hits = []
        for p in root.rglob("*.py"):
            text = p.read_text()
            if "fill_null(0)" in text:
                # Only the two predicate-only pace spike/kneel sentinels are
                # allowed; everything else is a violation.
                hits.append(str(p))
        allow = {
            str(root / "pace_observations.py"),
        }
        actual = [h for h in hits if h not in allow]
        assert actual == [], f"blanket fill_null(0) outside allowed predicate-only: {actual}"


# ===========================================================================
# 3. CANONICAL PBP MAPPING ATTACKS
# ===========================================================================


def canonical_df(rows):
    return pl.DataFrame(rows)


class TestCanonicalMapping:
    def test_reg_maps_to_reg(self):
        g = canonical_df([{"game_id": "2020_01_KC_PHI", "season": 2020, "season_type": "REG", "week": 1, "away_team": "PHI", "home_team": "KC"}])
        p = frame([{}], season=2020).with_columns(pl.lit("REG").alias("season_type"))
        m = map_pbp_to_canonical(p, g)
        assert m["season_type_canonical"].to_list() == ["REG"]

    @pytest.mark.parametrize("canon,exptype", [
        ("WC", "WC"), ("DIV", "DIV"), ("CON", "CON"), ("SB", "SB"),
    ])
    def test_post_maps_to_canonical_round(self, canon, exptype):
        g = canonical_df([{"game_id": "2020_22_KC_PHI", "season": 2020, "season_type": canon, "week": 22, "away_team": "PHI", "home_team": "KC"}])
        p = frame([{}], game_id="2020_22_KC_PHI", season=2020).with_columns(pl.lit("POST").alias("season_type"))
        m = map_pbp_to_canonical(p, g)
        assert m["season_type_canonical"].to_list() == [exptype]
        assert m["pbp_season_type"].to_list() == ["POST"]

    def test_duplicate_canonical_game_id_hard_fails(self):
        g = canonical_df([
            {"game_id": "2020_01_KC_PHI", "season": 2020, "season_type": "REG", "week": 1, "away_team": "PHI", "home_team": "KC"},
            {"game_id": "2020_01_KC_PHI", "season": 2020, "season_type": "REG", "week": 1, "away_team": "PHI", "home_team": "KC"},
        ])
        p = frame([{}], season=2020).with_columns(pl.lit("REG").alias("season_type"))
        with pytest.raises(WalkForwardError):
            map_pbp_to_canonical(p, g)

    def test_unmatched_required_pbp_game_id_hard_fails(self):
        g = canonical_df([{"game_id": "2020_01_KC_PHI", "season": 2020, "season_type": "REG", "week": 1, "away_team": "PHI", "home_team": "KC"}])
        p = frame([{}], game_id="2020_99_NE_BUF", season=2020).with_columns(pl.lit("REG").alias("season_type"))
        with pytest.raises(WalkForwardError):
            map_pbp_to_canonical(p, g)

    def test_conflicting_nfl_season_hard_fails(self):
        g = canonical_df([{"game_id": "2020_01_KC_PHI", "season": 2020, "season_type": "REG", "week": 1, "away_team": "PHI", "home_team": "KC"}])
        p = frame([{}], game_id="2020_01_KC_PHI", season=2021).with_columns(pl.lit("REG").alias("season_type"))
        with pytest.raises(WalkForwardError):
            map_pbp_to_canonical(p, g)

    def test_broad_post_never_becomes_reg_or_calendar_inferred(self):
        # POST -> canonical REG is invalid; round must come from game_id, not date.
        g = canonical_df([{"game_id": "2020_10_KC_PHI", "season": 2020, "season_type": "REG", "week": 10, "away_team": "PHI", "home_team": "KC"}])
        p = frame([{}], game_id="2020_10_KC_PHI", season=2020).with_columns(pl.lit("POST").alias("season_type"))

        with pytest.raises(WalkForwardError):
            map_pbp_to_canonical(p, g)


# ===========================================================================
# 4. HISTORICAL TEAM-ABBREVIATION NORMALIZATION
# ===========================================================================


class TestTeamNormalization:
    """Deterministic PER-GAME team normalization (contract-conformance).

    Normalization authority is each game's own two-team mapping
    (raw home/away -> canonical home/away). There is NO global alias
    dictionary: unknown/ambiguous values HARD-FAIL; cross-game identity
    never leaks.
    """

    @staticmethod
    def _norm(records):
        """Build a synthetic mapped-PBP frame and normalize it."""
        return _normalize_pbp_teams_to_canonical(pl.DataFrame(records))

    def test_oak_to_lv_via_canonical_identity(self):
        m = self._norm([{
            "game_id": "2020_01_OAK_KC", "home_team": "OAK", "away_team": "KC",
            "home_team_canonical": "LV", "away_team_canonical": "KC",
            "posteam": "OAK", "defteam": "KC",
        }])
        assert m["posteam"].to_list() == ["LV"]
        assert m["defteam"].to_list() == ["KC"]

    def test_la_to_lar_via_canonical_identity(self):
        m = self._norm([{
            "game_id": "2020_09_LA_SF", "home_team": "LA", "away_team": "SF",
            "home_team_canonical": "LAR", "away_team_canonical": "SF",
            "posteam": "LA", "defteam": "SF",
        }])
        assert m["posteam"].to_list() == ["LAR"]
        assert m["defteam"].to_list() == ["SF"]

    def test_defteam_normalizes_consistently(self):
        m = self._norm([{
            "game_id": "2020_01_OAK_KC", "home_team": "KC", "away_team": "OAK",
            "home_team_canonical": "KC", "away_team_canonical": "LV",
            "posteam": "KC", "defteam": "OAK",
        }])
        assert m["posteam"].to_list() == ["KC"]
        assert m["defteam"].to_list() == ["LV"]

    def test_already_canonical_unchanged(self):
        m = self._norm([{
            "game_id": "2020_01_KC_PHI", "home_team": "KC", "away_team": "PHI",
            "home_team_canonical": "KC", "away_team_canonical": "PHI",
            "posteam": "KC", "defteam": "PHI",
        }])
        assert m["posteam"].to_list() == ["KC"]
        assert m["defteam"].to_list() == ["PHI"]

    def test_game_id_invariance(self):
        m = self._norm([{
            "game_id": "2020_01_OAK_KC", "home_team": "OAK", "away_team": "KC",
            "home_team_canonical": "LV", "away_team_canonical": "KC",
            "posteam": "OAK", "defteam": "KC",
        }])
        assert m["game_id"].to_list() == ["2020_01_OAK_KC"]

    def test_unknown_posteam_hard_fails(self):
        with pytest.raises(TeamNormalizationError):
            self._norm([{
                "game_id": "2020_01_KC_PHI", "home_team": "KC", "away_team": "PHI",
                "home_team_canonical": "KC", "away_team_canonical": "PHI",
                "posteam": "XYZ", "defteam": "PHI",
            }])

    def test_unknown_defteam_hard_fails(self):
        with pytest.raises(TeamNormalizationError):
            self._norm([{
                "game_id": "2020_01_KC_PHI", "home_team": "KC", "away_team": "PHI",
                "home_team_canonical": "KC", "away_team_canonical": "PHI",
                "posteam": "KC", "defteam": "XYZ",
            }])

    def test_conflicting_raw_to_canonical_hard_fails(self):
        # Same game: raw home appears as both "LA" and "LAR" (two raw homes).
        with pytest.raises(TeamNormalizationError):
            self._norm([
                {"game_id": "g1", "home_team": "LA", "away_team": "SF",
                 "home_team_canonical": "LAR", "away_team_canonical": "SF",
                 "posteam": "LA", "defteam": "SF", "play_id": 1},
                {"game_id": "g1", "home_team": "LAR", "away_team": "SF",
                 "home_team_canonical": "LAR", "away_team_canonical": "SF",
                 "posteam": "LAR", "defteam": "SF", "play_id": 2},
            ])

    def test_ambiguous_canonical_identity_hard_fails(self):
        # Same game: two distinct canonical home identities.
        with pytest.raises(TeamNormalizationError):
            self._norm([
                {"game_id": "g1", "home_team": "LA", "away_team": "SF",
                 "home_team_canonical": "LAR", "away_team_canonical": "SF",
                 "posteam": "LA", "defteam": "SF", "play_id": 1},
                {"game_id": "g1", "home_team": "LA", "away_team": "SF",
                 "home_team_canonical": "XYZ_CANONICAL", "away_team_canonical": "SF",
                 "posteam": "LA", "defteam": "SF", "play_id": 2},
            ])

    def test_cross_game_contamination_absent(self):
        # Same raw abbreviation "LA" in two DIFFERENT games, with DIFFERENT
        # canonical identities. Each game must use ONLY its own mapping -- the
        # proof that no global alias map exists.
        frame = pl.DataFrame([
            {"game_id": "gameA", "home_team": "LA", "away_team": "SF",
             "home_team_canonical": "LAR", "away_team_canonical": "SF",
             "posteam": "LA", "defteam": "SF", "play_id": 1},
            {"game_id": "gameB", "home_team": "LA", "away_team": "NYG",
             "home_team_canonical": "XYZ_CANONICAL", "away_team_canonical": "NYG",
             "posteam": "LA", "defteam": "NYG", "play_id": 1},
            {"game_id": "gameB", "home_team": "LA", "away_team": "NYG",
             "home_team_canonical": "XYZ_CANONICAL", "away_team_canonical": "NYG",
             "posteam": "NYG", "defteam": "LA", "play_id": 2},
        ])
        out = _normalize_pbp_teams_to_canonical(frame).sort("play_id")
        # gameA "LA" -> LAR
        # gameB "LA" -> XYZ_CANONICAL (NOT LAR), and gameB defteam "LA" -> XYZ_CANONICAL
        assert out.filter(pl.col("game_id") == "gameA")["posteam"].to_list() == ["LAR"]
        b = out.filter(pl.col("game_id") == "gameB").sort("play_id")
        assert b["posteam"].to_list() == ["XYZ_CANONICAL", "NYG"]
        assert b["defteam"].to_list() == ["NYG", "XYZ_CANONICAL"]

    def test_shuffled_rows_identical_result(self):
        recs = [
            {"game_id": "g1", "home_team": "OAK", "away_team": "KC",
             "home_team_canonical": "LV", "away_team_canonical": "KC",
             "posteam": "OAK", "defteam": "KC", "play_id": 1},
            {"game_id": "g1", "home_team": "OAK", "away_team": "KC",
             "home_team_canonical": "LV", "away_team_canonical": "KC",
             "posteam": "KC", "defteam": "OAK", "play_id": 2},
            {"game_id": "g2", "home_team": "LA", "away_team": "SF",
             "home_team_canonical": "LAR", "away_team_canonical": "SF",
             "posteam": "LA", "defteam": "SF", "play_id": 1},
        ]
        fwd = _normalize_pbp_teams_to_canonical(pl.DataFrame(recs)).sort(["game_id", "play_id"])
        rev = _normalize_pbp_teams_to_canonical(pl.DataFrame(list(reversed(recs)))).sort(["game_id", "play_id"])
        assert fwd["posteam"].to_list() == rev["posteam"].to_list()
        assert fwd["defteam"].to_list() == rev["defteam"].to_list()

    def test_null_posteam_defteam_remain_null(self):
        m = self._norm([{
            "game_id": "2020_03_KC_PHI", "home_team": "KC", "away_team": "PHI",
            "home_team_canonical": "KC", "away_team_canonical": "PHI",
            "posteam": None, "defteam": None,
        }])
        assert m["posteam"].to_list() == [None]
        assert m["defteam"].to_list() == [None]

    # ---------------------------------------------------------------
    # Identity COMPLETENESS guards (exactly one per slot; two distinct teams)
    # ---------------------------------------------------------------

    def test_missing_raw_home_hard_fails(self):
        with pytest.raises(TeamNormalizationError):
            self._norm([{
                "game_id": "g1", "home_team": None, "away_team": "KC",
                "home_team_canonical": "LV", "away_team_canonical": "KC",
                "posteam": "LV", "defteam": "KC",
            }])

    def test_missing_raw_away_hard_fails(self):
        with pytest.raises(TeamNormalizationError):
            self._norm([{
                "game_id": "g1", "home_team": "KC", "away_team": None,
                "home_team_canonical": "KC", "away_team_canonical": "LV",
                "posteam": "KC", "defteam": "LV",
            }])

    def test_missing_canonical_home_hard_fails(self):
        with pytest.raises(TeamNormalizationError):
            self._norm([{
                "game_id": "g1", "home_team": "OAK", "away_team": "KC",
                "home_team_canonical": None, "away_team_canonical": "KC",
                "posteam": "LV", "defteam": "KC",
            }])

    def test_missing_canonical_away_hard_fails(self):
        with pytest.raises(TeamNormalizationError):
            self._norm([{
                "game_id": "g1", "home_team": "KC", "away_team": "OAK",
                "home_team_canonical": "KC", "away_team_canonical": None,
                "posteam": "KC", "defteam": "LV",
            }])

    def test_raw_home_equals_raw_away_hard_fails(self):
        with pytest.raises(TeamNormalizationError):
            self._norm([{
                "game_id": "g1", "home_team": "KC", "away_team": "KC",
                "home_team_canonical": "KC", "away_team_canonical": "PHI",
                "posteam": "KC", "defteam": "PHI",
            }])

    def test_canonical_home_equals_canonical_away_hard_fails(self):
        with pytest.raises(TeamNormalizationError):
            self._norm([{
                "game_id": "g1", "home_team": "KC", "away_team": "PHI",
                "home_team_canonical": "LAR", "away_team_canonical": "LAR",
                "posteam": "KC", "defteam": "PHI",
            }])

    def test_normal_complete_two_team_identity_passes(self):
        m = self._norm([{
            "game_id": "g1", "home_team": "LA", "away_team": "SF",
            "home_team_canonical": "LAR", "away_team_canonical": "SF",
            "posteam": "LA", "defteam": "SF",
        }])
        assert m["posteam"].to_list() == ["LAR"]
        assert m["defteam"].to_list() == ["SF"]


# ===========================================================================
# 5. COMPLETE-BLOCK FREEZE ADVERSARIAL
# ===========================================================================


class TestBlockFreeze:
    def test_snapshot_is_frozen_after_construction(self):
        state = TotalsBlockState()
        state.commit_block(
            block("2020_01_REG",
                  game_ids=("G1", "G2")),
            [GameObservation("2020_01_REG", "G1", {"KC": {"epa_play_offense": (1.0, 2.0, 2)}}),
             GameObservation("2020_01_REG", "G2", {"PHI": {"epa_play_offense": (2.0, 3.0, 3)}})],
        )
        snap = state.snapshot_for_block(block("2020_02_REG", game_ids=("G3",)))
        # Poison state after snapshot -> snapshot unchanged.
        state.commit_block(
            block("2020_02_REG", game_ids=("G3",)),
            [GameObservation("2020_02_REG", "G3", {"KC": {"epa_play_offense": (999.0, 999.0, 999)}})],
        )
        kc = snap.team("KC").get("epa_play_offense")
        assert (kc.numerator, kc.denominator) == (1.0, 2.0)

    def test_partial_block_commit_rejected(self):
        state = TotalsBlockState()
        b = block("2020_01_REG", game_ids=("G1", "G2"))
        with pytest.raises(ValueError):
            state.commit_block(b, [GameObservation("2020_01_REG", "G1", {})])

    def test_foreign_game_observation_rejected(self):
        state = TotalsBlockState()
        b = block("2020_01_REG", game_ids=("G1",))
        with pytest.raises(ValueError):
            state.commit_block(b, [GameObservation("2020_01_REG", "G9", {})])

    def test_commit_after_all_rows_emitted(self):
        # Emitting a block's rows reads the frozen snapshot; the block's own
        # observations are only applied at commit (after all rows emitted).
        state = TotalsBlockState()
        snap_pre = state.snapshot_for_block(block("2020_01_REG", game_ids=("G1",)))
        # Emit rows from snap_pre (unchanged by anything)
        assert snap_pre.team("KC").get("epa_play_offense") is None
        # Then commit -> observable only on a *later* snapshot
        state.commit_block(
            block("2020_01_REG", game_ids=("G1",)),
            [GameObservation("2020_01_REG", "G1", {"KC": {"epa_play_offense": (5.0, 5.0, 5)}})],
        )
        snap_post = state.snapshot_for_block(block("2020_02_REG", game_ids=("G2",)))
        kc = snap_post.team("KC").get("epa_play_offense")
        assert (kc.numerator, kc.denominator) == (5.0, 5.0)


# ===========================================================================
# 6-8. SAME-GAME / SAME-BLOCK / FUTURE-BLOCK provenance
# ===========================================================================


class TestLeakageProvenance:
    def _build(self):
        # Clean build count: everything zero.
        return ProvenanceCounters().to_build_provenance(
            target_block_id="2020_05_REG",
            eligible_source_block_ids=("2020_01_REG", "2020_02_REG"),
        )

    def test_clean_development_all_zero(self):
        p = self._build()
        assert p.valid_development_build is True
        assert p.same_game_source_rows == 0
        assert p.same_block_source_rows == 0
        assert p.future_block_source_rows == 0
        assert p.season_2025_source_rows == 0
        assert p.canonical_mapping_failures == 0

    def test_eligible_sources_never_contain_target_or_future(self):
        # Build a small set of blocks and confirm eligibility excludes the
        # target and everything at/after it.
        blocks = [
            block("2020_01_REG", week=1, game_ids=("G1",), asof=utc(datetime(2020, 9, 15))),
            block("2020_02_REG", week=2, game_ids=("G2",), asof=utc(datetime(2020, 9, 22))),
            block("2020_03_REG", week=3, game_ids=("G3",), asof=utc(datetime(2020, 9, 29))),
        ]
        target = blocks[1]
        # eligible_source_blocks needs an availability table; verify pure
        # ordering predicate instead: target strictly later than earlier
        # block, never itself, never future.
        assert is_strictly_earlier(blocks[0], target)
        assert not is_strictly_earlier(target, target)
        assert not is_strictly_earlier(blocks[2], target)

    def test_future_block_not_eligible(self):
        assert not is_strictly_earlier(block("2020_03_REG", week=3), block("2020_02_REG", week=2))


# ===========================================================================
# 9. POSTSEASON FORWARD ORDER
# ===========================================================================


class TestPostseasonOrdering:
    def test_reg_wc_div_con_sb_order(self):
        keys = [("2020", "REG", 1), ("2020", "WC", 1), ("2020", "DIV", 1),
                ("2020", "CON", 1), ("2020", "SB", 1)]
        assert [SEASON_TYPE_PRIORITY[t] for _, t, _ in keys] == [0, 1, 2, 3, 4]

    def test_sb_cannot_affect_earlier(self):
        sb = (2020, "SB", 1)
        con = (2020, "CON", 1)
        # SB key > CON key; hence a CON block is strictly earlier, never
        # affected by SB.
        assert (2020, SEASON_TYPE_PRIORITY["CON"], 1) < (2020, SEASON_TYPE_PRIORITY["SB"], 1)


# ===========================================================================
# 10-11. CALENDAR-YEAR / NFL-SEASON SAFETY + 2025 POISON
# ===========================================================================


class TestSeasonBoundary:
    def test_season_2024_calendar2025_accepted(self):
        f = pl.DataFrame({"season": [2024]})
        assert_frame_development_only(f)  # no raise; calendar date irrelevant

    def test_season_2025_rejected(self):
        f = pl.DataFrame({"season": [2025]})
        with pytest.raises(SealedHoldoutAccessError):
            assert_frame_development_only(f)

    def test_season_2017_below_window_rejected(self):
        f = pl.DataFrame({"season": [2017]})
        with pytest.raises(WalkForwardError):
            assert_frame_development_only(f)


# ===========================================================================
# 12. CONTEXT LEAKAGE ATTACK
# ===========================================================================


class TestContextLeakage:
    def _schedule(self, **extra):
        base = {
            "game_id": "2020_01_KC_PHI", "season": 2020, "game_type": "REG",
            "week": 1, "away_rest": 7, "home_rest": 7, "roof": "dome",
            "surface": "grass",
        }
        prohibited = {
            "away_score": 99, "home_score": 0, "result": "X",
            "total": 55, "away_moneyline": -500, "home_moneyline": 400,
            "spread_line": -9.5, "total_line": 48, "over_odds": -110,
            "under_odds": -110, "away_qb_id": "QB1", "home_qb_id": "QB2",
            "away_qb_name": "Mahomes", "home_qb_name": "Hurts",
            "temp": 72, "wind": 14,
        }
        prohibited.update(extra)
        return pl.DataFrame({**base, **prohibited})

    def test_prohibited_fields_removed_after_projection(self):
        proj = project_totals_context(self._schedule())
        # Only approved fields remain.
        allowed = set(APPROVED_CONTEXT_FIELDS)
        assert set(proj.columns) <= allowed
        for bad in ["away_score", "result", "total", "spread_line", "over_odds",
                    "away_qb_id", "away_qb_name", "temp", "wind"]:
            assert bad not in proj.columns

    def test_token_detection_matches_alternate_names(self):
        # Alternate but token-shaped names must each be detected as prohibited.
        shaped = [
            "away_points_total",      # _total
            "home_spread_line",       # spread
            "projected_total_score",  # _score
            "qb_id_num",              # qb_id
            "qb_name_alt",            # qb_name
            "hourly_wind_mph",        # _wind
            "indoor_temp_c",          # _temp
            "final_result",           # result
        ]
        for name in shaped:
            assert find_prohibited_columns([name]) == [name], name
        # And a truly benign name is not flagged.
        assert find_prohibited_columns(["surface", "away_rest"]) == []


# ===========================================================================
# 13. ROOF SOURCE AUTHORITY REGRESSION
# ===========================================================================


class TestRoofAuthority:
    def test_canonical_roof_wins_over_raw_schedule_roof(self):
        # canonical roof_type="DOME" is the authority; raw schedule roof ignored.
        ctx = {"away_rest": 7, "home_rest": 7, "surface": "grass",
               "roof_type": "DOME", "roof": "outdoors"}
        out = extract_context_features(ctx)
        assert out["roof_category"] == "dome"
        assert out["roof_missing"] == 0

    def test_raw_schedule_roof_variation_cannot_change_output(self):
        base = {"away_rest": 7, "home_rest": 7, "surface": "grass",
                "roof_type": "DOME"}
        outs = []
        for raw_roof in ["outdoors", "retractable", None, "closed"]:
            ctx = {**base, "roof": raw_roof}
            outs.append(extract_context_features(ctx))
        cats = [o["roof_category"] for o in outs]
        assert cats == ["dome"] * 4  # canonical roof fixed


# ===========================================================================
# 14. ORACLE QB ADVERSARIAL VALIDATION
# ===========================================================================


CONSUMED = [
    "passing_epa", "passing_cpoe", "sacks_suffered_rate", "interception_rate",
    "recency_weighted_form", "low_sample", "missing_player_id",
    "passing_epa_imputed", "passing_cpoe_imputed", "sack_rate_imputed",
    "interception_rate_imputed",
]


def oracle_frame(tmp_path, **extra_cols):
    path = tmp_path / "oracle.parquet"
    rows = [{"game_id": "2020_01_KC_PHI", "side": "away", **{c: 0.5 for c in CONSUMED}},
            {"game_id": "2020_01_KC_PHI", "side": "home", **{c: 0.7 for c in CONSUMED}}]
    for row in rows:
        row.update(extra_cols)
    pl.DataFrame(rows).write_parquet(path)
    return path


class TestOracleQbAllowlist:
    def test_only_consumed_and_key_columns_selected(self, tmp_path):
        path = oracle_frame(tmp_path, qb_adjustment_elo=9999.0,
                            actual_starting_qb_name="PAT MAHOMES",
                            actual_starting_qb_pfr_id="MahoPa00")
        loaded = _load_oracle_qb(path)
        assert set(loaded.columns) == {"game_id", "side", *CONSUMED}

    def test_changing_prohibited_columns_does_not_change_output(self, tmp_path):
        a = _load_oracle_qb(oracle_frame(tmp_path, qb_adjustment_elo=1.0))
        b = _load_oracle_qb(oracle_frame(tmp_path, qb_adjustment_elo=999999.0))
        assert a.equals(b)
        assert b["passing_epa"].to_list() == [0.5, 0.7]

    def test_duplicate_game_id_side_hard_fails(self, tmp_path):
        path = tmp_path / "dup.parquet"
        rows = []
        for side in ("away", "home"):
            rows.append({"game_id": "2020_01_KC_PHI", "side": side, **{c: 1.0 for c in CONSUMED}})
        rows.append({"game_id": "2020_01_KC_PHI", "side": "away", **{c: 9.0 for c in CONSUMED}})
        pl.DataFrame(rows).write_parquet(path)
        with pytest.raises(WalkForwardError):
            _load_oracle_qb(path)


# ===========================================================================
# 15. METRIC-SPECIFIC MINIMA FULL MATRIX
# ===========================================================================


class TestMetricMinima:
    @pytest.mark.parametrize("feature,minimum", [
        (f.feature_name, f.minimum) for f in MATCHUP_FAMILIES
    ])
    def test_minimum_boundary_n_minus_1_and_n(self, feature, minimum):
        family = next(f for f in MATCHUP_FAMILIES if f.feature_name == feature)
        # Offense accumulator at min-1 -> missing; at min -> available.
        off_below = TeamEntState({"dummy": Accumulator(0.0, minimum - 1, minimum - 1)})
        off_at = TeamEntState({"dummy": Accumulator(5.0, minimum, minimum)})
        val_below, miss_below = extract_entering_rate(off_below, "dummy", minimum)
        val_at, miss_at = extract_entering_rate(off_at, "dummy", minimum)
        assert miss_below == 1 and val_below is None
        assert miss_at == 0 and val_at is not None

    def test_each_family_uses_its_own_denominator(self):
        mins = {f.feature_name: f.minimum for f in MATCHUP_FAMILIES}
        # Distinguish low-threshold drive families (5) from play families (20)
        # and pace (10).
        assert mins["points_per_drive"] == 5
        assert mins["red_zone_td_rate"] == 5
        assert mins["seconds_per_play"] == 10
        assert mins["epa_per_play"] == 20
        assert mins["success_rate"] == 20
        assert len(set(mins.values())) >= 3  # at least 3 distinct thresholds


# ===========================================================================
# 16. VOLUME-WEIGHTING ADVERSARIAL CHECK
# ===========================================================================


class TestVolumeWeighting:
    def _weighted(self, metric, a_triple, b_triple, minimum):
        a = TeamEntState({metric: Accumulator(*a_triple)})
        b = TeamEntState({metric: Accumulator(*b_triple)})
        merged = a.get(metric).merge(b.get(metric))
        val, miss = extract_entering_rate(TeamEntState({metric: merged}), metric, minimum)
        return val, merged

    def test_play_rate_volume_weighting(self):
        val, m = self._weighted("epa_play_offense", (2.0, 10, 10), (8.0, 20, 20), 20)
        assert m.numerator == 10.0 and m.denominator == 30.0
        assert abs(val - 10.0 / 30.0) < 1e-9
        assert not abs(val - (0.2 + 0.4) / 2) < 1e-9  # NOT mean

    def test_drive_rate_volume_weighting(self):
        val, m = self._weighted("points_per_drive_offense", (2.0, 4, 4), (8.0, 5, 5), 5)
        assert m.numerator == 10.0 and m.denominator == 9.0

    def test_opportunity_rate_volume_weighting(self):
        val, m = self._weighted("red_zone_td_rate_offense", (0.0, 2, 2), (1.0, 3, 3), 5)
        assert m.numerator == 1.0 and m.denominator == 5.0

    def test_pace_rate_volume_weighting(self):
        val, m = self._weighted("seconds_play_offense", (100.0, 4, 4), (200.0, 6, 6), 10)
        assert m.numerator == 300.0 and m.denominator == 10.0
        assert abs(val - 30.0) < 1e-9


# ===========================================================================
# 17. MATCHUP FORMULA ADVERSARIAL CHECK
# ===========================================================================


def state_with(metric, n, d):
    return TeamEntState({metric: Accumulator(n, d, int(d))})


def state_both(family, off_n, off_d, def_n, def_d):
    """State carrying BOTH the offense metric and its defense-allowed twin."""
    return TeamEntState({
        family.offense_metric: Accumulator(off_n, off_d, int(off_d)),
        family.defense_metric: Accumulator(def_n, def_d, int(def_d)),
    })


class TestMatchupFormula:
    def test_home_away_matchup_formula(self):
        family = MATCHUP_FAMILIES[0]  # epa_per_play, min 20
        # home offense 4/40=0.1 ; home defense_allowed 2/20=0.1
        # away offense 4/40=0.1 ; away defense_allowed 8/20=0.4
        home = state_both(family, 4.0, 40, 2.0, 20)
        away = state_both(family, 4.0, 40, 8.0, 20)
        out = compute_matchup_pair(home, away, family)
        # home_matchup = (home_off + away_def_allowed)/2 = (0.1+0.4)/2 = 0.25
        # away_matchup = (away_off + home_def_allowed)/2 = (0.1+0.1)/2 = 0.10
        assert abs(out["home_matchup_epa_per_play"] - 0.25) < 1e-9
        assert abs(out["away_matchup_epa_per_play"] - 0.10) < 1e-9
        assert out["home_matchup_epa_per_play_missing"] == 0
        assert out["away_matchup_epa_per_play_missing"] == 0

    def test_not_pooling_raw_numerators(self):
        # Pooling would sum home offense raw n/d with away defense raw n/d:
        # (4+8)/(40+20)=0.2 != 0.25. We must NOT pool.
        family = MATCHUP_FAMILIES[0]
        home = state_both(family, 4.0, 40, 2.0, 20)   # off .1, def .1
        away = state_both(family, 4.0, 40, 8.0, 20)   # off .1, def .4
        out = compute_matchup_pair(home, away, family)
        assert abs(out["home_matchup_epa_per_play"] - 0.25) < 1e-9
        # The explicit pooling alternative is genuinely different (0.2).
        pooled = (home.get(family.offense_metric).numerator
                  + away.get(family.defense_metric).numerator) / (
            home.get(family.offense_metric).denominator
            + away.get(family.defense_metric).denominator)
        assert abs(pooled - 0.2) < 1e-9
        assert out["home_matchup_epa_per_play"] == pytest.approx(0.25)
        assert not (out["home_matchup_epa_per_play"] == pytest.approx(pooled))


# ===========================================================================
# 18. OFFENSE / DEFENSE INVERSION
# ===========================================================================


class TestDefenseInversion:
    def test_offense_metric_mirrors_to_opponent_defense_allowed(self):
        row_aggs = {
            "2020_01_KC_PHI": {
                "KC": {"epa_play_offense": [(2.0, 2.0, 2)]},
                "PHI": {"success_offense": [(1.0, 2.0, 2)]},
            }
        }
        updates = build_team_updates(
            "2020_01_KC_PHI", row_aggs, {}, home_team="KC", away_team="PHI",
        )
        # KC offense EPA appears on KC AS OFFENSE and on PHI as defense_allowed.
        assert updates["KC"]["epa_play_offense"] == (2.0, 2.0, 2)
        assert updates["PHI"]["epa_play_defense_allowed"] == (2.0, 2.0, 2)
        # PHI offense success -> KC defense_allowed; and PHI offense itself.
        assert updates["PHI"]["success_offense"] == (1.0, 2.0, 2)
        assert updates["KC"]["success_defense_allowed"] == (1.0, 2.0, 2)

    def test_no_cross_team_misassignment(self):
        # Only team A has metrics; team B present with empty aggregates so the
        # two-team invariant holds. A's offense must NOT be classified as A's
        # own defense_allowed.
        row_aggs = {"g": {"A": {"epa_play_offense": [(5.0, 5.0, 5)]}, "B": {}}}
        updates = build_team_updates("g", row_aggs, {}, home_team="A", away_team="B")
        assert updates["A"].get("epa_play_defense_allowed") is None
        assert updates["A"]["epa_play_offense"] == (5.0, 5.0, 5)
        assert updates["B"]["epa_play_defense_allowed"] == (5.0, 5.0, 5)
        assert "success_offense" not in updates["B"]

    @pytest.mark.parametrize("metric", [
        "epa_play_offense", "success_offense", "points_per_drive_offense",
        "seconds_play_offense", "neutral_pass_rate_offense", "red_zone_td_rate_offense",
        "goal_to_go_td_rate_offense", "turnovers_per_drive_offense",
        "sacks_per_dropback_offense", "air_yards_per_attempt_offense",
        "yac_per_completion_offense", "explosive_pass_rate_offense",
        "explosive_rush_rate_offense",
    ])
    def test_family_inversion_presence(self, metric):
        row_aggs = {"g": {"A": {metric: [(1.0, 1.0, 1)]}, "B": {}}}
        updates = build_team_updates("g", row_aggs, {}, home_team="A", away_team="B")
        twin = metric.replace("_offense", "_defense_allowed")
        assert updates["A"].get(metric) == (1.0, 1.0, 1)
        assert updates["B"].get(twin) == (1.0, 1.0, 1)
        # A never receives its own defense_allowed twin for that metric.
        assert updates["A"].get(twin) is None


# ===========================================================================
# 19. DRIVE RESULT CONSISTENCY
# ===========================================================================


class TestDriveResultConflict:
    def test_single_distinct_result_ok(self):
        f = annotated([
            {"play_id": 1, "fixed_drive_result": "Touchdown"},
            {"play_id": 2, "fixed_drive": 2, "fixed_drive_result": "Punt"},
        ])
        poss = build_possessions(f)
        assert poss.height == 2

    def test_conflicting_results_hard_fail(self):
        f = annotated([
            {"play_id": 1, "fixed_drive": 1, "fixed_drive_result": "Touchdown"},
            {"play_id": 2, "fixed_drive": 1, "fixed_drive_result": "Turnover"},
        ])
        with pytest.raises(DrivePointsError):
            build_possessions(f)

    def test_opportunity_conflict_hard_fail(self):
        f = annotated([
            {"play_id": 1, "fixed_drive": 1, "yardline_100": 5, "fixed_drive_result": "Touchdown"},
            {"play_id": 2, "fixed_drive": 1, "yardline_100": 10, "fixed_drive_result": "Field goal"},
        ])
        with pytest.raises(WalkForwardError):
            red_zone_opportunity_observations(f)


# ===========================================================================
# 20. PACE ADVERSARIAL CHECK
# ===========================================================================


class TestPaceAdversarial:
    def test_valid_interval_and_rules(self):
        # Two consecutive VFPs same drive/qtr/half, delta 30 -> 1 interval.
        f = annotated([
            {"play_id": 1, "game_seconds_remaining": 3600},
            {"play_id": 2, "game_seconds_remaining": 3570},
        ])
        ivals = build_pace_intervals(f)
        assert len(ivals) == 1
        assert ivals[0].delta == 30.0

    @pytest.mark.parametrize("first,second,is_delta", [
        ({"game_seconds_remaining": 3600}, {"game_seconds_remaining": 3600}, None),  # delta 0 -> excluded
        ({"game_seconds_remaining": 3600}, {"game_seconds_remaining": 3400}, None),  # delta 200 >120 -> excluded
        ({"game_seconds_remaining": None}, {"game_seconds_remaining": 3500}, None),  # null prior clock -> excluded
    ])
    def test_pace_exclusions(self, first, second, is_delta):
        f = annotated([{"play_id": 1, **first}, {"play_id": 2, **second}])
        assert build_pace_intervals(f) == []

    def test_spike_pair_excluded(self):
        f = annotated([
            {"play_id": 1, "game_seconds_remaining": 3600, "qb_spike": 1},
            {"play_id": 2, "game_seconds_remaining": 3570, "qb_spike": 1},
        ])
        assert build_pace_intervals(f) == []

    def test_kneel_pair_excluded(self):
        f = annotated([
            {"play_id": 1, "game_seconds_remaining": 3600, "qb_kneel": 1, "rush_attempt": 0, "pass_attempt": 0, "qb_dropback": 0},
            {"play_id": 2, "game_seconds_remaining": 3570, "qb_kneel": 1, "rush_attempt": 0, "pass_attempt": 0, "qb_dropback": 0},
        ])
        assert build_pace_intervals(f) == []

    def test_quarter_and_half_boundary_excluded(self):
        # qtr differs -> same_half check fails (qtr 1 vs 2 differ by qtr and half
        # check: qtr 1->first, qtr 2->first, same half BUT qtr differs -> excluded)
        f = annotated([
            {"play_id": 1, "game_seconds_remaining": 3600, "qtr": 1},
            {"play_id": 2, "game_seconds_remaining": 3570, "qtr": 2},
        ])
        assert build_pace_intervals(f) == []

    def test_regulation_ot_boundary_excluded(self):
        f = annotated([
            {"play_id": 1, "game_seconds_remaining": 3600, "qtr": 4},
            {"play_id": 2, "game_seconds_remaining": 3570, "qtr": 5},
        ])
        assert build_pace_intervals(f) == []

    def test_prior_play_controls_neutral_qualification(self):
        # Prior VFP neutral, current not -> interval still counted as neutral_seconds.
        f = annotated([
            {"play_id": 1, "game_seconds_remaining": 3600, "score_differential": 0, "game_seconds_remaining_prior": None, "qtr": 1, "epa": 0.0},
            {"play_id": 2, "game_seconds_remaining": 3500, "score_differential": 20, "qtr": 1, "epa": 0.0},
        ])
        aggs = pace_interval_observations(f)
        team = aggs.get("2020_01_KC_PHI", {}).get("KC", {})
        assert "neutral_seconds_play_offense" in team  # prior neutral qualifies

    def test_shuffled_input_gives_identical_intervals(self):
        rows = [
            {"play_id": 1, "game_seconds_remaining": 3600,
             "score_differential": 0, "qtr": 1, "epa": 0.0},
            {"play_id": 2, "game_seconds_remaining": 3570,
             "score_differential": 0, "qtr": 1, "epa": 0.0},
            {"play_id": 3, "game_seconds_remaining": 3550,
             "score_differential": 0, "qtr": 1, "epa": 0.0},
            {"play_id": 4, "game_seconds_remaining": 3500,
             "score_differential": 0, "qtr": 1, "epa": 0.0},
        ]
        f1 = annotated(rows)
        a = [(i.prior_play_id, i.current_play_id, round(i.delta, 3))
             for i in build_pace_intervals(f1)]
        shuffled = annotated(list(reversed(rows)))
        b = [(i.prior_play_id, i.current_play_id, round(i.delta, 3))
             for i in build_pace_intervals(shuffled)]
        assert a == b and len(a) == 3


# ===========================================================================
# 21. UNIQUE OPPORTUNITY CHECK
# ===========================================================================


class TestUniqueOpportunity:
    def test_red_zone_one_per_possession(self):
        f = annotated([
            {"play_id": 1, "yardline_100": 5, "fixed_drive_result": "Touchdown"},
            {"play_id": 2, "yardline_100": 8, "fixed_drive_result": "Touchdown"},
            {"play_id": 3, "yardline_100": 3, "fixed_drive_result": "Touchdown"},
        ])
        opps = red_zone_opportunity_observations(f)
        # Many qualifying plays, exactly one opportunity for the drive.
        assert len(opps) == 1
        assert opps[0][2] == (1.0, 1.0, 1)  # is_td

    def test_goal_to_go_one_per_possession(self):
        f = annotated([
            {"play_id": 1, "goal_to_go": 1, "fixed_drive_result": "Touchdown"},
            {"play_id": 2, "goal_to_go": 1, "fixed_drive_result": "Touchdown"},
        ])
        opps = goal_to_go_opportunity_observations(f)
        assert len(opps) == 1


# ===========================================================================
# 22. EXACT FEATURE MATRIX (unit contract checks)
# ===========================================================================


class TestExact90Columns:
    def test_exact_90_column_count(self):
        assert len(EXACT_90_COLUMNS) == 90
        assert len(set(EXACT_90_COLUMNS)) == 90  # no duplicates

    def test_identity_columns_not_in_features(self):
        identity = ["game_id", "season", "season_type", "week", "home_team",
                    "away_team", "block_id"]
        for col in identity:
            assert col not in EXACT_90_COLUMNS
