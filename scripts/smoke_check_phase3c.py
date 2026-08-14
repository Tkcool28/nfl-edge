"""Bounded smoke check for Phase 3C primitives.

Runs the full ``build_game_observations`` pipeline over a deterministic
synthetic 2024-style PBP frame and reports per-family non-null counts
plus pace/opportunity totals. This is a CODE-PATH smoke check, not a
real-nflverse smoke check (no PBP data is downloaded per the task
constraint).

The frame is small enough to keep iteration budget low but structured
so that every selected Phase 3C primitive has at least one qualifying
observation.

Exit code is non-zero if any unexpected exception is raised.
"""

from __future__ import annotations

import random
import sys

import polars as pl

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
    build_game_observations,
)
from nfl_edge.features.totals_v1.pace_observations import (
    build_pace_intervals,
)


def _synth_frame(seed: int = 2024, num_games: int = 4) -> dict[str, pl.DataFrame]:
    """Generate a deterministic synthetic 2024-style PBP frame per game.

    The structure mirrors a small chunk of an NFL game: 6 drives, ~18
    VFPs per game, alternating offenses, mixed pass/rush, a few sacks,
    some red-zone visits, one goal-to-go, one explosive pass, one
    explosive rush, both neutral and non-neutral states, occasional
    nulls to exercise the null-exclusion rules.

    Returns ``{game_id: pbp_frame}``.
    """
    rng = random.Random(seed)
    teams_a = ["KC", "BUF", "PHI", "SF"]
    teams_b = ["BAL", "MIA", "DAL", "SEA"]
    out: dict[str, pl.DataFrame] = {}
    play_id_counter = 0
    for gi in range(num_games):
        game_id = f"g{gi + 1}"
        home, away = teams_a[gi], teams_b[gi]
        rows = []
        for drive_num in range(1, 7):
            posteam = home if drive_num % 2 else away
            defteam = away if posteam == home else home
            # Drive outcome: drives 1 and 4 are TDs, others are Punt/Field goal.
            outcomes = ["Touchdown", "Punt", "Field goal",
                        "Touchdown", "Punt", "Missed field goal"]
            outcome = outcomes[(drive_num - 1) % len(outcomes)]
            # Number of plays in this drive: 3 or 4.
            n_plays = 3 if drive_num % 2 else 4
            for pi in range(1, n_plays + 1):
                play_id_counter += 1
                # Pass attempt 60% of the time (excluding 2pt, kneel,
                # spike, etc.). Pick a qtr between 1-3 to keep most
                # plays neutral-eligible.
                is_pass = rng.random() < 0.6
                is_run = not is_pass
                # 1/8 chance of a spike to test exclusion.
                is_spike = not is_pass and rng.random() < 0.10
                is_kneel = not is_pass and not is_spike and rng.random() < 0.10
                # Initialize per-row flags to safe defaults.
                play_type = "pass"
                pass_attempt: float | None = 0.0
                rush_attempt: float | None = 0.0
                complete_pass: float | None = 0.0
                qb_dropback: float | None = 0.0
                qb_kneel = 0.0
                qb_spike = 0.0
                sack: float | None = 0.0
                air_yards: float | None = None
                yards_after_catch: float | None = None
                yards_gained: float | None = 0.0
                if is_kneel:
                    play_type = "qb_kneel"
                    rush_attempt = 1.0
                    complete_pass = None
                    qb_kneel = 1.0
                elif is_spike:
                    play_type = "qb_spike"
                    complete_pass = None
                    qb_spike = 1.0
                elif is_pass:
                    play_type = "pass"
                    pass_attempt = 1.0
                    complete_pass = 1.0 if rng.random() < 0.7 else 0.0
                    sack = 1.0 if rng.random() < (1 / 12) else 0.0
                    if sack == 1.0:
                        pass_attempt = 0.0
                        complete_pass = None
                        air_yards = None
                        yards_after_catch = None
                    else:
                        air_yards = float(rng.randint(0, 15))
                        yards_after_catch = float(rng.randint(0, 10))
                    qb_dropback = 1.0
                else:
                    play_type = "run"
                    rush_attempt = 1.0
                    complete_pass = None
                    yards_gained = float(rng.randint(-2, 12))

                # qtr 1-3 90% of time, qtr 4 10%.
                qtr = rng.choice([1, 2, 3, 3, 3, 4, 1, 2, 3, 4])
                # Neutral only in qtr 1-3 with score diff in [-8, +8]
                # and clock >= 900.
                if qtr == 4:
                    score_differential = rng.randint(-14, 14)
                    game_seconds_remaining = rng.randint(0, 899)
                else:
                    score_differential = rng.randint(-8, 8)
                    game_seconds_remaining = rng.randint(900, 3599)
                # 5% chance of null clock to test exclusion.
                if rng.random() < 0.05:
                    game_seconds_remaining = None
                # 5% chance of null score_differential.
                if rng.random() < 0.05:
                    score_differential = None

                # Yardline 1..99 with 10% chance of red zone.
                yardline_100 = float(rng.randint(1, 99))
                if rng.random() < 0.10:
                    yardline_100 = float(rng.randint(1, 20))
                goal_to_go = 1 if yardline_100 <= 2 else 0

                # Yards gained: pass ~ uniform [0, 25], sack ~ -2..-10,
                # rush ~ -2..12, else 0.
                if is_pass and not is_kneel and not is_spike and sack == 0.0:
                    yards_gained = float(rng.randint(0, 25))
                elif sack == 1.0:
                    yards_gained = -float(rng.randint(2, 10))

                # Last play of the drive carries the outcome.
                fdr = outcome if pi == n_plays else None

                rows.append({
                    "game_id": game_id,
                    "season": 2024,
                    "play_id": float(play_id_counter),
                    "fixed_drive": float(drive_num),
                    "posteam": posteam,
                    "defteam": defteam,
                    "play_type": play_type,
                    "play_deleted": 0.0,
                    "aborted_play": 0.0,
                    "pass_attempt": pass_attempt,
                    "rush_attempt": rush_attempt,
                    "complete_pass": complete_pass,
                    "qb_dropback": qb_dropback,
                    "qb_kneel": qb_kneel,
                    "qb_spike": qb_spike,
                    "sack": sack,
                    "epa": float(rng.uniform(-1.0, 1.0)),
                    "success": 1.0 if rng.random() < 0.5 else 0.0,
                    "interception": None,
                    "fumble_lost": None,
                    "fixed_drive_result": fdr,
                    "qtr": qtr,
                    "score_differential": score_differential,
                    "game_seconds_remaining": game_seconds_remaining,
                    "yardline_100": yardline_100,
                    "goal_to_go": float(goal_to_go),
                    "yards_gained": yards_gained,
                    "air_yards": air_yards,
                    "yards_after_catch": yards_after_catch,
                })

        out[game_id] = pl.DataFrame(rows)
    return out


def main() -> int:
    pbp = _synth_frame()
    observations = build_game_observations(
        block_id="2024_REG_W01",
        pbp_frames=pbp,
    )

    # Per-family totals.
    totals = {
        METRIC_SECONDS_PLAY_OFFENSE: 0,
        METRIC_NEUTRAL_SECONDS_PLAY_OFFENSE: 0,
        METRIC_NEUTRAL_PASS_RATE_OFFENSE: 0,
        METRIC_RED_ZONE_TD_RATE_OFFENSE: 0,
        METRIC_GOAL_TO_GO_TD_RATE_OFFENSE: 0,
        METRIC_SACKS_PER_DROPBACK_OFFENSE: 0,
        METRIC_AIR_YARDS_PER_ATTEMPT_OFFENSE: 0,
        METRIC_YAC_PER_COMPLETION_OFFENSE: 0,
        METRIC_EXPLOSIVE_PASS_RATE_OFFENSE: 0,
        METRIC_EXPLOSIVE_RUSH_RATE_OFFENSE: 0,
        METRIC_SECONDS_PLAY_DEFENSE_ALLOWED: 0,
        METRIC_NEUTRAL_SECONDS_PLAY_DEFENSE_ALLOWED: 0,
        METRIC_NEUTRAL_PASS_RATE_DEFENSE_ALLOWED: 0,
        METRIC_RED_ZONE_TD_RATE_DEFENSE_ALLOWED: 0,
        METRIC_GOAL_TO_GO_TD_RATE_DEFENSE_ALLOWED: 0,
        METRIC_SACKS_PER_DROPBACK_DEFENSE_ALLOWED: 0,
        METRIC_AIR_YARDS_PER_ATTEMPT_DEFENSE_ALLOWED: 0,
        METRIC_YAC_PER_COMPLETION_DEFENSE_ALLOWED: 0,
        METRIC_EXPLOSIVE_PASS_RATE_DEFENSE_ALLOWED: 0,
        METRIC_EXPLOSIVE_RUSH_RATE_DEFENSE_ALLOWED: 0,
    }

    pace_total = 0
    neutral_pace_total = 0
    for obs in observations:
        # Sum triple denominators across all teams.
        for team_metrics in obs.team_updates.values():
            for metric, triple in team_metrics.items():
                if metric in totals:
                    totals[metric] += int(triple[1])

    # Per-frame pace totals (counting intervals).
    for game_id, frame in pbp.items():
        from nfl_edge.features.totals_v1 import annotate_pbp_semantics
        annotated = annotate_pbp_semantics(frame)
        intervals = build_pace_intervals(annotated)
        pace_total += len(intervals)
        neutral_pace_total += sum(1 for iv in intervals if iv.is_neutral_prior)

    # Per-frame red-zone and goal-to-go opportunity counts.
    from nfl_edge.features.totals_v1 import annotate_pbp_semantics
    from nfl_edge.features.totals_v1.drive_observations import (
        red_zone_opportunity_observations,
        goal_to_go_opportunity_observations,
    )
    rz_total = 0
    gtg_total = 0
    for game_id, frame in pbp.items():
        annotated = annotate_pbp_semantics(frame)
        rz_total += len(red_zone_opportunity_observations(annotated))
        gtg_total += len(goal_to_go_opportunity_observations(annotated))

    print("games_processed", len(observations))
    print("pace_intervals", pace_total)
    print("neutral_pace_intervals", neutral_pace_total)
    print("red_zone_opportunities", rz_total)
    print("goal_to_go_opportunities", gtg_total)
    print("non_null_metric_totals:")
    for metric, count in totals.items():
        print(f"  {metric}: {count}")

    # Defense-allowed == offense totals (per spec, defense mirrors).
    offenders = {k: totals[k] for k in totals if k.endswith("_offense")}
    defenders = {k: totals[k] for k in totals if k.endswith("_defense_allowed")}
    # Sanity: each offense total == its defense twin.
    mismatch = []
    for o_key, o_val in offenders.items():
        d_key = o_key.replace("_offense", "_defense_allowed")
        if defenders.get(d_key, -1) != o_val:
            mismatch.append((o_key, o_val, d_key, defenders.get(d_key)))
    if mismatch:
        print("MISMATCH:", mismatch)
        return 1
    print("offense_defense_inversion_match: True")
    return 0


if __name__ == "__main__":
    sys.exit(main())
