"""Tests for per-game / per-team primitive observation construction (Phase 3B).

Covers:

- multi-metric same-team updates;
- both game sides produced with exact offense/defense inversion;
- empty-update game still representable;
- deterministic under shuffled source rows;
- feeds the accepted ``GameObservation`` shape from Phase 3A.

All assertions follow the accepted contract definitions (pass_attempt,
complete_pass, rush_attempt w/ kneel exclusion, dropback+fallback,
possession = (game_id, fixed_drive, posteam), fixed_drive_result authority,
scoring-drive = Touchdown or Field goal only, turnovers/drive sums events).
"""

from __future__ import annotations

import polars as pl
import pytest

from nfl_edge.features.totals_v1 import (
    METRIC_EPA_PLAY_DEFENSE_ALLOWED,
    METRIC_EPA_PLAY_OFFENSE,
    METRIC_PASS_ATTEMPTS_DEFENSE_ALLOWED,
    METRIC_PASS_ATTEMPTS_OFFENSE,
    METRIC_POINTS_PER_DRIVE_DEFENSE_ALLOWED,
    METRIC_POINTS_PER_DRIVE_OFFENSE,
    METRIC_RUSH_ATTEMPTS_DEFENSE_ALLOWED,
    METRIC_RUSH_ATTEMPTS_OFFENSE,
    METRIC_SACKS_DEFENSE_ALLOWED,
    METRIC_SACKS_OFFENSE,
    METRIC_SUCCESS_DEFENSE_ALLOWED,
    METRIC_SUCCESS_OFFENSE,
    METRIC_TURNOVERS_DEFENSE_ALLOWED,
    METRIC_TURNOVERS_OFFENSE,
    aggregate_possession_metrics,
    aggregate_row_metrics,
    annotate_pbp_semantics,
    build_game_observations,
    build_team_updates,
)
from nfl_edge.features.totals_v1.block_state import GameObservation


def _row(
    *,
    game_id: str,
    fixed_drive: float,
    play_id: float,
    posteam: str | None,
    defteam: str | None,
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


def _ann(*plays) -> pl.DataFrame:
    return annotate_pbp_semantics(pl.DataFrame(list(plays)))


# ---------------------------------------------------------------------------
# GameObservation shape and empty-update game
# ---------------------------------------------------------------------------


def test_empty_game_emits_empty_GameObservation():
    # A game with no real football plays still produces a GameObservation
    # with empty team_updates (Phase 3A complete-block invariant).
    empty = pl.DataFrame({
        "game_id": ["g1"], "season": [2024],
        "posteam": [None], "defteam": [None],
        "play_type": [None], "play_deleted": [0.0], "aborted_play": [0.0],
        "pass_attempt": [None], "rush_attempt": [None],
        "complete_pass": [None], "qb_dropback": [None],
        "qb_kneel": [0.0], "qb_spike": [0.0],
        "sack": [None], "epa": [None], "success": [None],
        "interception": [None], "fumble_lost": [None],
        "fixed_drive": [1.0],
        "fixed_drive_result": [None],
        "play_id": [1.0],
        "qtr": [None], "score_differential": [None],
        "game_seconds_remaining": [None], "yardline_100": [None],
        "goal_to_go": [None], "yards_gained": [None],
        "air_yards": [None], "yards_after_catch": [None],
    })
    obs = build_game_observations(block_id="blk", pbp_frames={"g1": empty})
    assert len(obs) == 1
    assert obs[0].block_id == "blk"
    assert obs[0].game_id == "g1"
    assert obs[0].team_updates == {}


def test_observation_carries_block_id():
    obs = build_game_observations(
        block_id="2024_REG_W01",
        pbp_frames={"g1": _ann(
            _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
                 posteam="KC", defteam="BAL", fixed_drive_result="Punt"),
            _row(game_id="g1", fixed_drive=2.0, play_id=2.0,
                 posteam="BAL", defteam="KC", fixed_drive_result="Punt"),
        )},
        game_to_teams={"g1": ("BAL", "KC")},
    )
    assert obs[0].block_id == "2024_REG_W01"


def test_observation_is_a_GameObservation_dataclass():
    plays = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             posteam="KC", defteam="BAL", epa=0.5, fixed_drive_result="Punt"),
        _row(game_id="g1", fixed_drive=2.0, play_id=2.0,
             posteam="BAL", defteam="KC", fixed_drive_result="Punt"),
    ]
    obs = build_game_observations(block_id="blk", pbp_frames={"g1": _ann(*plays)},
                                  game_to_teams={"g1": ("BAL", "KC")})
    assert isinstance(obs[0], GameObservation)
    assert obs[0].block_id == "blk"
    assert obs[0].game_id == "g1"
    assert isinstance(obs[0].team_updates, dict)


# ---------------------------------------------------------------------------
# Offense / defense inversion (exact equality of exposure)
# ---------------------------------------------------------------------------


def test_offense_defense_inversion_exact_equality():
    plays = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             posteam="KC", defteam="BAL", epa=0.5, success=1.0,
             fixed_drive_result="Punt"),
        _row(game_id="g1", fixed_drive=2.0, play_id=2.0,
             posteam="KC", defteam="BAL", epa=0.3, success=1.0,
             fixed_drive_result="Punt"),
        _row(game_id="g1", fixed_drive=3.0, play_id=3.0,
             posteam="BAL", defteam="KC", epa=-0.2, success=0.0,
             fixed_drive_result="Punt"),
        _row(game_id="g1", fixed_drive=4.0, play_id=4.0,
             posteam="BAL", defteam="KC", epa=-0.4, success=0.0,
             fixed_drive_result="Punt"),
    ]
    obs = build_game_observations(block_id="blk", pbp_frames={"g1": _ann(*plays)},
                                  game_to_teams={"g1": ("BAL", "KC")})
    upd = obs[0].team_updates
    # KC offense EPA == BAL defense-allowed EPA.
    assert upd["KC"][METRIC_EPA_PLAY_OFFENSE] == upd["BAL"][METRIC_EPA_PLAY_DEFENSE_ALLOWED]
    # BAL offense EPA == KC defense-allowed EPA.
    assert upd["BAL"][METRIC_EPA_PLAY_OFFENSE] == upd["KC"][METRIC_EPA_PLAY_DEFENSE_ALLOWED]
    assert upd["KC"][METRIC_SUCCESS_OFFENSE] == upd["BAL"][METRIC_SUCCESS_DEFENSE_ALLOWED]


def test_rush_attempt_uses_rush_attempt_flag_not_play_type():
    # play_type=="run" with rush_attempt=0 should NOT count as a rush attempt.
    plays = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             posteam="KC", defteam="BAL",
             play_type="run", rush_attempt=0.0, pass_attempt=0.0,
             complete_pass=None, qb_dropback=0.0,
             epa=0.5, success=1.0, fixed_drive_result="Punt"),
        _row(game_id="g1", fixed_drive=2.0, play_id=2.0,
             posteam="BAL", defteam="KC", fixed_drive_result="Punt"),
    ]
    obs = build_game_observations(block_id="blk", pbp_frames={"g1": _ann(*plays)},
                                  game_to_teams={"g1": ("BAL", "KC")})
    upd = obs[0].team_updates
    # KC rush_attempt_offense must be (0,0,0) because rush_attempt was 0.
    assert upd["KC"].get(METRIC_RUSH_ATTEMPTS_OFFENSE, (0.0, 0.0, 0)) == (0.0, 0.0, 0)


def test_pass_attempt_uses_pass_attempt_flag_not_play_type():
    # play_type=="pass" with pass_attempt=0 should NOT count as a pass attempt.
    plays = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             posteam="KC", defteam="BAL",
             play_type="pass", pass_attempt=0.0, complete_pass=None,
             qb_dropback=1.0, epa=0.5, success=1.0, fixed_drive_result="Punt"),
        _row(game_id="g1", fixed_drive=2.0, play_id=2.0,
             posteam="BAL", defteam="KC", fixed_drive_result="Punt"),
    ]
    obs = build_game_observations(block_id="blk", pbp_frames={"g1": _ann(*plays)},
                                  game_to_teams={"g1": ("BAL", "KC")})
    upd = obs[0].team_updates
    assert upd["KC"].get(METRIC_PASS_ATTEMPTS_OFFENSE, (0.0, 0.0, 0)) == (0.0, 0.0, 0)


def test_completion_requires_complete_pass():
    # pass_attempt=1 with complete_pass=0 must NOT contribute a completion.
    plays = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             posteam="KC", defteam="BAL",
             pass_attempt=1.0, complete_pass=0.0, epa=0.5, success=1.0,
             fixed_drive_result="Punt"),
        _row(game_id="g1", fixed_drive=2.0, play_id=2.0,
             posteam="BAL", defteam="KC", fixed_drive_result="Punt"),
    ]
    obs = build_game_observations(block_id="blk", pbp_frames={"g1": _ann(*plays)},
                                  game_to_teams={"g1": ("BAL", "KC")})
    upd = obs[0].team_updates
    # completions_offense must be (0,0,0).
    assert upd["KC"].get("completions_offense", (0.0, 0.0, 0)) == (0.0, 0.0, 0)


def test_kneel_excluded_from_rush_attempts():
    # qb_kneel row with rush_attempt=1 must NOT count as a rush attempt.
    plays = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             posteam="KC", defteam="BAL",
             play_type="qb_kneel", pass_attempt=0.0, rush_attempt=1.0,
             complete_pass=None, qb_dropback=0.0, qb_kneel=1.0,
             epa=0.0, success=1.0, fixed_drive_result="Punt"),
        _row(game_id="g1", fixed_drive=2.0, play_id=2.0,
             posteam="BAL", defteam="KC", fixed_drive_result="Punt"),
    ]
    obs = build_game_observations(block_id="blk", pbp_frames={"g1": _ann(*plays)},
                                  game_to_teams={"g1": ("BAL", "KC")})
    upd = obs[0].team_updates
    assert upd["KC"].get(METRIC_RUSH_ATTEMPTS_OFFENSE, (0.0, 0.0, 0)) == (0.0, 0.0, 0)


# ---------------------------------------------------------------------------
# Drive metrics + offense/defense inversion (touchdown drives)
# ---------------------------------------------------------------------------


def test_drive_metrics_appear_with_offense_defense_inversion():
    # KC has two possessions: one Touchdown (7 pts), one Punt (0 pts).
    plays = []
    for drive_id in (1, 2):
        outcome = "Touchdown" if drive_id == 1 else "Punt"
        for i in range(1, 4):
            plays.append(_row(
                game_id="g1", fixed_drive=float(drive_id),
                play_id=float(drive_id * 10 + i),
                posteam="KC", defteam="BAL",
                fixed_drive_result=outcome if i == 3 else None,
            ))
    # BAL gets a possession so the team pair resolves.
    plays.append(_row(
        game_id="g1", fixed_drive=3.0, play_id=30.0,
        posteam="BAL", defteam="KC", fixed_drive_result="Punt",
    ))
    obs = build_game_observations(block_id="blk", pbp_frames={"g1": _ann(*plays)},
                                  game_to_teams={"g1": ("BAL", "KC")})
    upd = obs[0].team_updates
    # KC offense: 7 + 0 = 7 / 2 possessions
    assert upd["KC"][METRIC_POINTS_PER_DRIVE_OFFENSE] == (7.0, 2.0, 2)
    # BAL sees the same 7 points / 2 drives allowed
    assert upd["BAL"][METRIC_POINTS_PER_DRIVE_DEFENSE_ALLOWED] == (7.0, 2.0, 2)


def test_safety_points_but_not_scoring_drive():
    # A Safety possession contributes 2 to points-per-drive but 0 to
    # scoring-drive rate.
    plays = []
    for drive_id in (1, 2):
        outcome = "Safety" if drive_id == 1 else "Touchdown"
        for i in range(1, 4):
            plays.append(_row(
                game_id="g1", fixed_drive=float(drive_id),
                play_id=float(drive_id * 10 + i),
                posteam="KC", defteam="BAL",
                fixed_drive_result=outcome if i == 3 else None,
            ))
    plays.append(_row(
        game_id="g1", fixed_drive=3.0, play_id=30.0,
        posteam="BAL", defteam="KC", fixed_drive_result="Punt",
    ))
    obs = build_game_observations(block_id="blk", pbp_frames={"g1": _ann(*plays)},
                                  game_to_teams={"g1": ("BAL", "KC")})
    upd = obs[0].team_updates
    # KC points/drive: 2 + 7 = 9 / 2 possessions.
    assert upd["KC"][METRIC_POINTS_PER_DRIVE_OFFENSE] == (9.0, 2.0, 2)
    # KC scoring drive rate: 1 (only the Touchdown) / 2.
    assert upd["KC"]["scoring_drive_rate_offense"] == (1.0, 2.0, 2)


def test_turnovers_per_drive_sums_events_not_boolean():
    # A KC possession with 2 turnover events (interception + lost fumble).
    plays = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             posteam="KC", defteam="BAL", pass_attempt=1.0, interception=1.0,
             fixed_drive_result="Turnover"),
        _row(game_id="g1", fixed_drive=1.0, play_id=2.0,
             posteam="KC", defteam="BAL", fumble_lost=1.0,
             play_type="run", rush_attempt=1.0, pass_attempt=0.0,
             complete_pass=None, qb_dropback=0.0,
             fixed_drive_result="Turnover"),
        # BAL possession for team-pair resolution.
        _row(game_id="g1", fixed_drive=2.0, play_id=3.0,
             posteam="BAL", defteam="KC", fixed_drive_result="Punt"),
    ]
    obs = build_game_observations(block_id="blk", pbp_frames={"g1": _ann(*plays)},
                                  game_to_teams={"g1": ("BAL", "KC")})
    upd = obs[0].team_updates
    # KC turnovers_offense: 2 events.
    assert upd["KC"][METRIC_TURNOVERS_OFFENSE] == (2.0, 2.0, 2)
    # KC turnovers_per_drive_offense: 2 events / 1 possession.
    assert upd["KC"]["turnovers_per_drive_offense"] == (2.0, 1.0, 1)
    # BAL defense-allowed mirrors.
    assert upd["BAL"][METRIC_TURNOVERS_DEFENSE_ALLOWED] == (2.0, 2.0, 2)
    assert upd["BAL"]["turnovers_per_drive_defense_allowed"] == (2.0, 1.0, 1)


def test_sack_defense_inversion():
    plays = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             posteam="KC", defteam="BAL",
             sack=1.0, pass_attempt=None, rush_attempt=None, complete_pass=None,
             qb_dropback=None, epa=None, success=None,
             fixed_drive_result="Punt"),
        _row(game_id="g1", fixed_drive=2.0, play_id=2.0,
             posteam="BAL", defteam="KC", fixed_drive_result="Punt"),
    ]
    obs = build_game_observations(block_id="blk", pbp_frames={"g1": _ann(*plays)},
                                  game_to_teams={"g1": ("BAL", "KC")})
    upd = obs[0].team_updates
    assert upd["KC"][METRIC_SACKS_OFFENSE] == (1.0, 1.0, 1)
    assert upd["BAL"][METRIC_SACKS_DEFENSE_ALLOWED] == (1.0, 1.0, 1)


# ---------------------------------------------------------------------------
# Determinism under row shuffle
# ---------------------------------------------------------------------------


def test_deterministic_under_source_row_shuffle():
    plays = []
    for drive_id in (1, 2, 3):
        for i in range(1, 4):
            plays.append(_row(
                game_id="g1", fixed_drive=float(drive_id),
                play_id=float(drive_id * 100 + i),
                posteam="KC" if drive_id in (1, 2) else "BAL",
                defteam="BAL" if drive_id in (1, 2) else "KC",
                fixed_drive_result="Touchdown" if drive_id == 1 else "Punt",
                epa=float(drive_id) * 0.1 + float(i) * 0.01,
                success=1.0,
            ))
    obs_a = build_game_observations(block_id="blk", pbp_frames={"g1": _ann(*plays)},
                                    game_to_teams={"g1": ("BAL", "KC")})
    obs_b = build_game_observations(block_id="blk", pbp_frames={"g1": _ann(*reversed(plays))},
                                    game_to_teams={"g1": ("BAL", "KC")})

    def flat(o):
        return sorted(
            (team, metric, val)
            for team, ms in sorted(o[0].team_updates.items())
            for metric, val in sorted(ms.items())
        )

    assert flat(obs_a) == flat(obs_b)


# ---------------------------------------------------------------------------
# Team-pair validation
# ---------------------------------------------------------------------------


def test_team_mismatch_raises():
    plays = _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
                 posteam="KC", defteam="BAL", fixed_drive_result="Punt")
    with pytest.raises(Exception):
        build_game_observations(block_id="blk", pbp_frames={"g1": _ann(plays)},
                                game_to_teams={"g1": ("NE", "ARI")})


# ---------------------------------------------------------------------------
# Direct aggregator tests
# ---------------------------------------------------------------------------


def test_aggregate_row_metrics_collects_per_row_triples():
    plays = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             posteam="KC", defteam="BAL", epa=0.5, success=1.0,
             fixed_drive_result="Punt"),
        _row(game_id="g1", fixed_drive=2.0, play_id=2.0,
             posteam="KC", defteam="BAL", epa=-0.2, success=0.0,
             fixed_drive_result="Punt"),
    ]
    agg = aggregate_row_metrics(_ann(*plays))
    assert "g1" in agg
    assert "KC" in agg["g1"]
    epa_triples = agg["g1"]["KC"][METRIC_EPA_PLAY_OFFENSE]
    assert len(epa_triples) == 2


def test_aggregate_possession_metrics_per_possession():
    from nfl_edge.features.totals_v1.drive_observations import PossessionObservation
    possessions = [
        PossessionObservation(game_id="g1", fixed_drive=1, posteam="KC",
                              points=7, is_scoring=True, turnover_events=0),
        PossessionObservation(game_id="g1", fixed_drive=2, posteam="KC",
                              points=0, is_scoring=False, turnover_events=2),
    ]
    agg = aggregate_possession_metrics(possessions)
    assert METRIC_POINTS_PER_DRIVE_OFFENSE in agg["g1"]["KC"]
    assert len(agg["g1"]["KC"][METRIC_POINTS_PER_DRIVE_OFFENSE]) == 2


def test_build_team_updates_uses_inferred_team_pair():
    plays = [
        _row(game_id="g1", fixed_drive=1.0, play_id=1.0,
             posteam="KC", defteam="BAL", epa=0.5, fixed_drive_result="Punt"),
        _row(game_id="g1", fixed_drive=2.0, play_id=2.0,
             posteam="BAL", defteam="KC", epa=0.3, fixed_drive_result="Punt"),
    ]
    agg_row = aggregate_row_metrics(_ann(*plays))
    upd = build_team_updates(game_id="g1", row_aggregates=agg_row,
                              possession_aggregates={}, home_team=None, away_team=None)
    assert METRIC_EPA_PLAY_OFFENSE in upd["KC"]
    assert METRIC_EPA_PLAY_DEFENSE_ALLOWED in upd["BAL"]