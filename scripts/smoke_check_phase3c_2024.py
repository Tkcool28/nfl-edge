"""Bounded 2024 real-data smoke check for Phase 3C primitives.

Loads the already-promoted 2024 PBP artifact at
``data/raw/task05c_pbp_v1/play_by_play_2024.parquet``, runs the full
``build_game_observations`` pipeline over all of its games, and reports
per-family non-null counts plus pace/opportunity totals.

This is a code-path/data-pipeline smoke check on REAL nflverse 2024 PBP
rows (no downloads). It exists ONLY to confirm that the Phase 3C
implementation, the offense/defense inversion, and the integrated
neutral-helper fix all run on the accepted source shape without
raising. It does not change the contract.

Exit code is non-zero only on unexpected exception.
"""

from __future__ import annotations

import sys
from pathlib import Path

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
    REQUIRED_PBP_COLUMNS,
    annotate_pbp_semantics,
    build_game_observations,
)
from nfl_edge.features.totals_v1.drive_observations import (
    goal_to_go_opportunity_observations,
    red_zone_opportunity_observations,
)
from nfl_edge.features.totals_v1.pace_observations import build_pace_intervals


# The CANONICAL promoted 2024 PBP artifact, per the Task 05C promotion.
# This is the host-promoted location (read-only) under
# /var/lib/chatgpt-vps-mcp/artifacts/nfl-edge/raw/task05c_pbp_v1/.
# This script does NOT copy the file into the worktree and does NOT
# fall back to any other location; if the canonical artifact is
# missing or its checksum/size does not match the expected values, the
# script aborts with a hard error before reading any rows.
PBP_DIR = Path("/var/lib/chatgpt-vps-mcp/artifacts/nfl-edge/raw/task05c_pbp_v1")
PBP_FILENAME = "play_by_play_2024.parquet"
PBP_PATH = PBP_DIR / PBP_FILENAME

EXPECTED_BYTE_SIZE: int = 20576368
EXPECTED_SHA256: str = "6d432dd4308329bfddaef633309ea119f9ca46d52cbb3c09f47172a2e8efcd01"


class CanonicalArtifactError(RuntimeError):
    """Raised when the canonical promoted 2024 artifact cannot be trusted."""


def _verify_canonical_artifact(path: Path) -> None:
    """Hard-verify existence, size, and SHA-256 of the canonical artifact.

    Reads the file in 1 MiB chunks; compares byte size and SHA-256
    against the expected values. Any mismatch raises CanonicalArtifactError
    so the smoke check exits without consuming an untrusted source.
    """
    if not path.exists():
        raise CanonicalArtifactError(
            f"canonical 2024 PBP artifact missing at {path!s}"
        )
    actual_size = path.stat().st_size
    if actual_size != EXPECTED_BYTE_SIZE:
        raise CanonicalArtifactError(
            f"canonical 2024 PBP byte size mismatch at {path!s}: "
            f"expected {EXPECTED_BYTE_SIZE}, got {actual_size}"
        )
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    actual_sha = h.hexdigest()
    if actual_sha != EXPECTED_SHA256:
        raise CanonicalArtifactError(
            f"canonical 2024 PBP SHA-256 mismatch at {path!s}: "
            f"expected {EXPECTED_SHA256}, got {actual_sha}"
        )
    print(f"verified_canonical_artifact: path={path!s}")
    print(f"verified_canonical_artifact: byte_size={actual_size}")
    print(f"verified_canonical_artifact: sha256={actual_sha}")


def main() -> int:
    _verify_canonical_artifact(PBP_PATH)
    df = pl.read_parquet(PBP_PATH, columns=sorted(REQUIRED_PBP_COLUMNS))

    # Per-game frames. ``group_by`` yields (key_tuple, DataFrame); the
    # key is a single-element tuple for a single grouping column.
    pbp_frames: dict[str, pl.DataFrame] = {
        key[0]: sub for key, sub in df.group_by("game_id", maintain_order=True)
    }
    games_count = len(pbp_frames)

    observations = build_game_observations(
        block_id="2024_REAL_SMOKE",
        pbp_frames=pbp_frames,
    )

    # Per-family non-null totals = sum of denominators across all teams.
    totals: dict[str, int] = {
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
    rz_total = 0
    gtg_total = 0

    # Per-frame pace and opportunity counts (using same annotated frame).
    for game_id, frame in pbp_frames.items():
        annotated = annotate_pbp_semantics(frame)
        intervals = build_pace_intervals(annotated)
        pace_total += len(intervals)
        neutral_pace_total += sum(1 for iv in intervals if iv.is_neutral_prior)
        rz_total += len(red_zone_opportunity_observations(annotated))
        gtg_total += len(goal_to_go_opportunity_observations(annotated))

    # Sum denominators from team_updates triples.
    for obs in observations:
        for team_metrics in obs.team_updates.values():
            for metric, triple in team_metrics.items():
                if metric in totals:
                    totals[metric] += int(triple[1])

    # Confirm internal neutral-pass helpers never appear.
    helper_leaks: list[str] = []
    for obs in observations:
        for team_metrics in obs.team_updates.values():
            for metric in team_metrics:
                if metric in ("neutral_pass_attempts_offense", "neutral_rush_attempts_offense"):
                    helper_leaks.append(metric)

    # Sanity: offense denominator == defense denominator per metric.
    mismatches: list[tuple[str, int, int]] = []
    for o_key, o_val in totals.items():
        if not o_key.endswith("_offense"):
            continue
        d_key = o_key.replace("_offense", "_defense_allowed")
        d_val = totals.get(d_key, -1)
        if d_val != o_val:
            mismatches.append((o_key, o_val, d_val))

    print("games_processed:", games_count)
    print("game_observations_built:", len(observations))
    print("pace_intervals:", pace_total)
    print("neutral_pace_intervals:", neutral_pace_total)
    print("red_zone_opportunities:", rz_total)
    print("goal_to_go_opportunities:", gtg_total)
    print("non_null_metric_denominators:")
    for metric, count in totals.items():
        print(f"  {metric}: {count}")
    print("internal_helper_leaks:", helper_leaks or "[]")
    print("offense_defense_inversion_mismatches:", mismatches or "[]")

    if helper_leaks or mismatches:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())