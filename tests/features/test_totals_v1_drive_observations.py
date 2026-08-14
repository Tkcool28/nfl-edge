"""Tests for possession identity and drive primitives (Phase 3B, contract-literal).

Encoded rules from the accepted contract:

- Possession identity = non-null ``(game_id, fixed_drive, posteam)``
  group containing at least one VFP with non-null ``fixed_drive_result``.
- ``fixed_drive_result`` is the sole drive-result authority.
- Drive points = exact 9-value mapping. No aliases, no fallbacks.
- Scoring drive = Touchdown or Field goal only. Safety is NOT a scoring
  drive even though it scores points.
- Turnovers-per-drive numerator = sum of qualifying turnover events
  across all VFPs in the possession (not a Boolean per-drive flag).
- Unrecognized ``fixed_drive_result`` hard-fails.
"""

from __future__ import annotations

import polars as pl
import pytest

from nfl_edge.features.totals_v1 import annotate_pbp_semantics
from nfl_edge.features.totals_v1.drive_observations import (
    CONTRACT_DRIVE_POINTS,
    CONTRACT_SCORING_RESULTS,
    PossessionObservation,
    DrivePointsError,
    build_possessions,
    drive_points_from_result,
    is_scoring_result,
    points_per_drive_observation,
    possession_observations,
    scoring_drive_observation,
    turnovers_per_drive_observation,
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


def _ann(*plays) -> pl.DataFrame:
    return annotate_pbp_semantics(pl.DataFrame(list(plays)))


# ---------------------------------------------------------------------------
# FIX 6 — Drive points proxy (fixed_drive_result only)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "result,points",
    [
        ("Touchdown", 7),
        ("Field goal", 3),
        ("Safety", 2),
        ("Punt", 0),
        ("Turnover", 0),
        ("Turnover on downs", 0),
        ("Missed field goal", 0),
        ("End of half", 0),
        ("Opp touchdown", 0),
    ],
)
def test_drive_points_exact_mapping(result, points):
    assert drive_points_from_result(result) == points


def test_drive_points_hard_fail_on_unrecognized_result():
    with pytest.raises(DrivePointsError):
        drive_points_from_result("BLOCKED_PUNT")
    with pytest.raises(DrivePointsError):
        drive_points_from_result("END_GAME")
    with pytest.raises(DrivePointsError):
        drive_points_from_result("QB kneel")
    with pytest.raises(DrivePointsError):
        drive_points_from_result("Opp Touchdown")  # wrong case (contract is "Opp touchdown")
    with pytest.raises(DrivePointsError):
        drive_points_from_result("touchdown")  # wrong case
    with pytest.raises(DrivePointsError):
        drive_points_from_result("")


def test_contract_drive_points_set_is_exactly_nine_buckets():
    assert set(CONTRACT_DRIVE_POINTS.keys()) == {
        "Touchdown",
        "Field goal",
        "Safety",
        "Punt",
        "Turnover",
        "Turnover on downs",
        "Missed field goal",
        "End of half",
        "Opp touchdown",
    }


def test_no_alias_or_fallback_exists():
    # The CONTRACT_DRIVE_POINTS dict must be the only mapping. No
    # alias dict, no fallback dict.
    from nfl_edge.features.totals_v1 import drive_observations as m

    names = [n for n in dir(m) if not n.startswith("_")]
    forbidden = [
        "DRIVE_END_FALLBACK",
        "_NFLVERSE_SERIES_ALIAS",
        "NFLVERSE_SERIES_ALIAS",
        "build_drive_table",
        "drive_observations",
    ]
    for f in forbidden:
        assert f not in names, f"{f} must not exist (removed by contract)"


# ---------------------------------------------------------------------------
# FIX 7 — Scoring drive: Touchdown or Field goal only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "result,expected",
    [
        ("Touchdown", True),
        ("Field goal", True),
        ("Safety", False),
        ("Punt", False),
        ("Turnover", False),
        ("Turnover on downs", False),
        ("Missed field goal", False),
        ("End of half", False),
        ("Opp touchdown", False),
    ],
)
def test_scoring_drive_set_is_exactly_touchdown_and_field_goal(result, expected):
    assert is_scoring_result(result) is expected


def test_safety_scores_points_but_is_not_a_scoring_drive():
    # Safety -> 2 points (points-per-drive contribution), but is NOT a
    # scoring-drive contribution.
    assert drive_points_from_result("Safety") == 2
    assert is_scoring_result("Safety") is False


def test_scoring_drive_observation_safety_is_zero():
    # Even if a possession ended in Safety, the scoring-drive rate must
    # not count it.
    p = PossessionObservation(game_id="g", fixed_drive=1, posteam="KC",
                              points=2, is_scoring=False, turnover_events=0)
    n, d, s = scoring_drive_observation(p)
    assert (n, d, s) == (0.0, 1.0, 1)


def test_scoring_drive_observation_touchdown_is_one():
    p = PossessionObservation(game_id="g", fixed_drive=1, posteam="KC",
                              points=7, is_scoring=True, turnover_events=0)
    n, d, s = scoring_drive_observation(p)
    assert (n, d, s) == (1.0, 1.0, 1)


def test_scoring_drive_observation_field_goal_is_one():
    p = PossessionObservation(game_id="g", fixed_drive=1, posteam="KC",
                              points=3, is_scoring=True, turnover_events=0)
    n, d, s = scoring_drive_observation(p)
    assert (n, d, s) == (1.0, 1.0, 1)


# ---------------------------------------------------------------------------
# FIX 5 — Possession identity = (game_id, fixed_drive, posteam) 3-tuple
# ---------------------------------------------------------------------------


def test_possession_grouped_by_three_tuple_key():
    # Two drives: KC and BAL each run an offensive drive. Different
    # posteam on the same fixed_drive value but different game_id
    # doesn't share; different posteam on same game_id+fixed_drive must
    # produce separate possessions.
    rows = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             posteam="KC", defteam="BAL", fixed_drive_result="Touchdown"),
        _row(game_id="g1", fixed_drive=1.0, play_id=2.0,
             posteam="KC", defteam="BAL", fixed_drive_result="Touchdown"),
        # Same game_id and fixed_drive, different posteam -> separate possession.
        _row(game_id="g1", fixed_drive=2.0, play_id=3.0,
             posteam="BAL", defteam="KC", fixed_drive_result="Punt"),
    ]
    poss = build_possessions(_ann(*rows))
    assert poss.height == 2  # KC drive 1, BAL drive 2
    teams = sorted(poss["posteam"].to_list())
    assert teams == ["BAL", "KC"]


def test_possession_offense_is_posteam_of_key_not_last_row():
    # The possession key is the (game_id, fixed_drive, posteam) triple.
    # Here the same (game_id, fixed_drive) contains rows with two
    # different posteams; each posteam is its own possession.
    rows = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             posteam="KC", defteam="BAL", fixed_drive_result="Touchdown"),
        _row(game_id="g1", fixed_drive=1.0, play_id=2.0,
             posteam="KC", defteam="BAL", fixed_drive_result="Touchdown"),
        # Same (game_id, fixed_drive) but different posteam: separate possession.
        _row(game_id="g1", fixed_drive=1.0, play_id=3.0,
             posteam="BAL", defteam="KC", fixed_drive_result="Punt"),
    ]
    poss = build_possessions(_ann(*rows))
    by_team = {row["posteam"]: row for row in poss.iter_rows(named=True)}
    assert "KC" in by_team and "BAL" in by_team
    assert by_team["KC"]["points"] == 7
    assert by_team["BAL"]["points"] == 0


def test_possession_excluded_with_no_vFP():
    # Marker-only group with no VFP must not produce a possession.
    rows = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             posteam=None, defteam=None, play_type=None,
             qb_dropback=None, pass_attempt=None, rush_attempt=None,
             complete_pass=None, fixed_drive_result="Punt"),
    ]
    poss = build_possessions(_ann(*rows))
    assert poss.height == 0


def test_possession_excluded_with_null_fixed_drive_result():
    # Group has VFPs but fixed_drive_result is null: excluded.
    rows = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             fixed_drive_result=None),
    ]
    poss = build_possessions(_ann(*rows))
    assert poss.height == 0


def test_possession_uses_first_fixed_drive_result_value():
    # nflverse propagates the same fixed_drive_result to every row of
    # the drive; using ``first()`` is deterministic.
    rows = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             fixed_drive_result="Touchdown"),
        _row(game_id="g1", fixed_drive=1.0, play_id=2.0,
             fixed_drive_result="Touchdown"),
        _row(game_id="g1", fixed_drive=1.0, play_id=3.0,
             fixed_drive_result="Touchdown"),
    ]
    poss = build_possessions(_ann(*rows))
    assert poss.height == 1
    assert poss["points"].to_list() == [7]


def test_possession_unrecognized_fixed_drive_result_hard_fails():
    rows = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             fixed_drive_result="BLOCKED_PUNT"),  # not in contract mapping
    ]
    with pytest.raises(DrivePointsError, match="BLOCKED_PUNT"):
        build_possessions(_ann(*rows))


def test_possession_sort_order_is_deterministic():
    rows = [
        _row(game_id="g2", fixed_drive=1.0, play_id=1.0,
             fixed_drive_result="Touchdown"),
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             fixed_drive_result="Touchdown"),
        _row(game_id="g1", fixed_drive=2.0, play_id=2.0,
             posteam="BAL", defteam="KC", fixed_drive_result="Punt"),
    ]
    poss = build_possessions(_ann(*rows))
    keys = list(zip(poss["game_id"].to_list(), poss["fixed_drive"].to_list(),
                    poss["posteam"].to_list()))
    # Expected order: (g1, 1, KC), (g1, 2, BAL), (g2, 1, KC)
    assert keys == [("g1", 1.0, "KC"), ("g1", 2.0, "BAL"), ("g2", 1.0, "KC")]


# ---------------------------------------------------------------------------
# FIX 8 — Turnovers per drive (sum of events, not Boolean per drive)
# ---------------------------------------------------------------------------


def test_turnovers_per_drive_sums_events_within_possession():
    # A possession with 0 turnover events contributes (0, 1, 1).
    p = PossessionObservation(game_id="g", fixed_drive=1, posteam="KC",
                              points=0, is_scoring=False, turnover_events=0)
    n, d, s = turnovers_per_drive_observation(p)
    assert (n, d, s) == (0.0, 1.0, 1)


def test_turnovers_per_drive_with_one_event():
    p = PossessionObservation(game_id="g", fixed_drive=1, posteam="KC",
                              points=0, is_scoring=False, turnover_events=1)
    n, d, s = turnovers_per_drive_observation(p)
    assert (n, d, s) == (1.0, 1.0, 1)


def test_turnovers_per_drive_with_multiple_events():
    # A single possession may contain two qualifying turnover events
    # (e.g., fumble recovered by offense, then interception on next play).
    # Numerator must be 2; denominator still 1.
    p = PossessionObservation(game_id="g", fixed_drive=1, posteam="KC",
                              points=0, is_scoring=False, turnover_events=2)
    n, d, s = turnovers_per_drive_observation(p)
    assert (n, d, s) == (2.0, 1.0, 1)


def test_turnovers_per_drive_sums_across_vfps():
    rows = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             interception=1.0, fixed_drive_result="Touchdown"),
        _row(game_id="g1", fixed_drive=1.0, play_id=2.0,
             fumble_lost=1.0, fixed_drive_result="Touchdown"),
        _row(game_id="g1", fixed_drive=1.0, play_id=3.0,
             fixed_drive_result="Touchdown"),
    ]
    poss = build_possessions(_ann(*rows))
    assert poss.height == 1
    # turnover_events = 2 (one interception + one lost fumble).
    assert poss["turnover_events"].to_list() == [2]


def test_possession_observations_have_required_fields():
    rows = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             fixed_drive_result="Field goal"),
    ]
    poss = build_possessions(_ann(*rows))
    obs_list = possession_observations(poss)
    assert len(obs_list) == 1
    o = obs_list[0]
    assert isinstance(o, PossessionObservation)
    assert o.game_id == "g1"
    assert o.fixed_drive == 1
    assert o.posteam == "KC"
    assert o.points == 3
    assert o.is_scoring is True
    assert o.turnover_events == 0


# ---------------------------------------------------------------------------
# Determinism under row shuffle
# ---------------------------------------------------------------------------


def test_drive_table_deterministic_under_shuffle():
    rows = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0, fixed_drive_result="Touchdown"),
        _row(game_id="g1", fixed_drive=2.0, play_id=2.0, posteam="BAL", defteam="KC", fixed_drive_result="Punt"),
        _row(game_id="g2", fixed_drive=1.0, play_id=1.0, posteam="BUF", defteam="MIA", fixed_drive_result="Field goal"),
    ]
    poss_a = build_possessions(_ann(*rows))
    poss_b = build_possessions(_ann(*reversed(rows)))
    # Compare possession observation lists by (game, drive, posteam, points, scoring, to).
    def flat(p):
        return sorted(
            (r["game_id"], int(r["fixed_drive"]), r["posteam"],
             int(r["points"]), bool(r["is_scoring"]), int(r["turnover_events"]))
            for r in p.iter_rows(named=True)
        )
    assert flat(poss_a) == flat(poss_b)


# ---------------------------------------------------------------------------
# Points-per-drive observation primitive
# ---------------------------------------------------------------------------


def test_points_per_drive_observation_touchdown():
    p = PossessionObservation(game_id="g", fixed_drive=1, posteam="KC",
                              points=7, is_scoring=True, turnover_events=0)
    n, d, s = points_per_drive_observation(p)
    assert (n, d, s) == (7.0, 1.0, 1)


def test_points_per_drive_observation_safety():
    # Safety contributes 2 to points/drive but NOT to scoring drive.
    p = PossessionObservation(game_id="g", fixed_drive=1, posteam="KC",
                              points=2, is_scoring=False, turnover_events=0)
    n, d, s = points_per_drive_observation(p)
    assert (n, d, s) == (2.0, 1.0, 1)