"""Drive / possession primitives for Totals V1 (Phase 3B).

Translated verbatim from the accepted Phase 2 contract
(``docs/totals_feature_contract_v1.md``). This module is the sole
authority for possession identity, drive results, drive points, scoring
drives, and turnovers-per-drive.

Definitions (contract-literal):

Possession identity:
    One offensive possession per non-null ``(game_id, fixed_drive,
    posteam)`` group that:
      1. contains at least one VFP row, AND
      2. has non-null ``fixed_drive_result``.
    Exclude drive groups with no VFP, and exclude a group from all
    drive denominators if ``fixed_drive_result`` is null.
    Possession offense is the ``posteam`` of the 3-tuple key -- it is
    not inferred from the last row's ``posteam``. ``drive_end_transition``
    and ``series_result`` are not authoritative.

Drive-points proxy (``fixed_drive_result`` -> points):
    Touchdown          -> 7
    Field goal         -> 3
    Safety             -> 2
    Punt               -> 0
    Turnover           -> 0
    Turnover on downs  -> 0
    Missed field goal  -> 0
    End of half        -> 0
    Opp touchdown      -> 0
    No aliases, no fallback table, no remapping. If a non-null
    ``fixed_drive_result`` falls outside this exact mapping, raise
    ``DrivePointsError`` -- do not silently invent a point value.

Scoring-drive rate:
    Numerator = 1 iff ``fixed_drive_result`` is exactly ``Touchdown`` or
    ``Field goal``. Otherwise 0. ``Safety`` is NOT a scoring drive even
    though it scores points.

Turnovers-per-drive:
    Numerator = total qualifying turnover events across all VFPs in the
    possession (sum of qualifying rows where
    ``is_turnover_event == True``; each qualifying play counts at most
    once). Denominator = 1 per included possession.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from ...common.errors import WalkForwardError
from .pbp_semantics import turnover_event_expr


# Contract-literal drive-result buckets -> points. The set of keys is
# exactly the set of accepted fixed_drive_result strings. No aliases.
CONTRACT_DRIVE_POINTS: dict[str, int] = {
    "Touchdown": 7,
    "Field goal": 3,
    "Safety": 2,
    "Punt": 0,
    "Turnover": 0,
    "Turnover on downs": 0,
    "Missed field goal": 0,
    "End of half": 0,
    "Opp touchdown": 0,
}


# Contract-literal scoring-drive set: Touchdown or Field goal only.
# Safety scores 2 points but is NOT a scoring drive.
CONTRACT_SCORING_RESULTS: frozenset[str] = frozenset({"Touchdown", "Field goal"})


class DrivePointsError(WalkForwardError):
    """Raised when a ``fixed_drive_result`` is not in the contract mapping."""


@dataclass(frozen=True)
class PossessionObservation:
    """One included offensive possession (one row per 3-tuple key).

    Attributes
    ----------
    game_id, fixed_drive, posteam:
        The contract-possession 3-tuple key.
    points:
        Drive-points proxy from ``fixed_drive_result``.
    is_scoring:
        True iff ``fixed_drive_result`` is Touchdown or Field goal.
    turnover_events:
        Total qualifying turnover events across all VFPs in this
        possession (each qualifying play counts at most once).
    """

    game_id: str
    fixed_drive: int
    posteam: str
    points: int
    is_scoring: bool
    turnover_events: int


def drive_points_from_result(fixed_drive_result: str) -> int:
    """Return the contract drive-points for one ``fixed_drive_result``.

    Raises :class:`DrivePointsError` if the result is not in
    :data:`CONTRACT_DRIVE_POINTS`. No fallback, no alias.
    """
    if fixed_drive_result not in CONTRACT_DRIVE_POINTS:
        raise DrivePointsError(
            "drive_points_from_result",
            f"unrecognized fixed_drive_result={fixed_drive_result!r}; "
            "the contract forbids inventing a point value",
        )
    return CONTRACT_DRIVE_POINTS[fixed_drive_result]


def is_scoring_result(fixed_drive_result: str) -> bool:
    """Return True iff ``fixed_drive_result`` is Touchdown or Field goal."""
    return fixed_drive_result in CONTRACT_SCORING_RESULTS


def _require_column(frame: pl.DataFrame, column: str, where: str) -> None:
    if column not in frame.columns:
        raise WalkForwardError(where, f"missing required column {column!r}")


def build_possessions(
    annotated: pl.DataFrame,
    *,
    where: str = "build_possessions",
) -> pl.DataFrame:
    """Return one row per included offensive possession.

    Columns:
      - ``game_id``, ``fixed_drive``, ``posteam``: the 3-tuple key.
      - ``fixed_drive_result``: the FIRST non-null value across the
        group (nflverse propagates the same value to all rows in the
        drive; using ``first()`` keeps the result deterministic).
      - ``vfp_count``: number of VFP rows in this possession.
      - ``turnover_events``: sum of ``is_turnover_event`` over VFP rows
        in this possession (each row at most 1).
      - ``points``: drive-points proxy from ``fixed_drive_result``.
      - ``is_scoring``: True iff fixed_drive_result in scoring set.

    Inclusion rules (contract-literal):
      1. The 3-tuple ``(game_id, fixed_drive, posteam)`` is non-null.
      2. The group contains at least one VFP row.
      3. The group's ``fixed_drive_result`` is non-null.

    The output is sorted by ``game_id`` ASC, ``fixed_drive`` ASC,
    ``posteam`` ASC (deterministic). Possessions with no VFP, or with
    null ``fixed_drive_result``, are excluded from all drive
    denominators.
    """
    for c in ("game_id", "fixed_drive", "posteam", "is_vfp",
              "is_turnover_event", "fixed_drive_result", "play_id"):
        _require_column(annotated, c, where)

    # Sort by play_id ascending so the drive-result authority is
    # deterministic regardless of input row order (nflverse propagates
    # the same fixed_drive_result to every row of a drive; the contract
    # treats that field as the sole drive-result authority).
    sorted_annotated = annotated.sort("play_id")

    # Build the 3-tuple grouping on non-null posteam only (rows whose
    # posteam is null are kickoff marker rows that don't belong to any
    # offensive possession).
    grouped = (
        sorted_annotated.filter(pl.col("posteam").is_not_null())
        .group_by(["game_id", "fixed_drive", "posteam"], maintain_order=True)
        .agg(
            [
                pl.col("fixed_drive_result").first().alias("any_result_first"),
                pl.col("fixed_drive_result").drop_nulls().first().alias("fixed_drive_result"),
                pl.col("fixed_drive_result").drop_nulls().n_unique().alias("_distinct_results"),
                pl.col("is_vfp").sum().alias("vfp_count"),
                pl.col("is_turnover_event").sum().alias("turnover_events"),
            ]
        )
    )

    # Contract authority check (Phase 3E): ``fixed_drive_result`` is the sole
    # drive-result authority. A possession ``(game_id, fixed_drive, posteam)``
    # must have at most ONE distinct non-null ``fixed_drive_result``. If real
    # or synthetic data ever carries multiple conflicting non-null results
    # within one possession, HARD-FAIL instead of silently selecting
    # first/last. This is a validation-only guard; it does not change any
    # contract formula, min, or source authority.
    conflict = grouped.filter(pl.col("_distinct_results") > 1)
    if conflict.height:
        offenders = sorted(conflict.select(["game_id", "fixed_drive", "posteam"]).iter_rows())
        raise DrivePointsError(
            where,
            f"{conflict.height} possession(s) carry >1 distinct non-null "
            f"fixed_drive_result; the contract forbids silently choosing one. "
            f"First conflicts: {offenders[:10]}",
        )

    # Inclusion rules (contract-literal):
    #   1. The 3-tuple ``(game_id, fixed_drive, posteam)`` is non-null
    #      (guaranteed by the posteam filter above).
    #   2. The group contains at least one VFP row.
    #   3. The group has at least one row with non-null
    #      ``fixed_drive_result`` -- nflverse may set it on any row of
    #      the drive, not just the first; the contract treats
    #      ``fixed_drive_result`` as the sole drive-result authority.
    grouped = grouped.filter(
        (pl.col("vfp_count") >= 1) & pl.col("fixed_drive_result").is_not_null()
    )

    # Apply the contract-literal points/score mapping. Any non-null
    # fixed_drive_result outside CONTRACT_DRIVE_POINTS is a contract
    # violation: hard-fail with the actual offending value(s).
    unrecognized = grouped.filter(
        ~pl.col("fixed_drive_result").is_in(list(CONTRACT_DRIVE_POINTS.keys()))
        & pl.col("fixed_drive_result").is_not_null()
    )
    if unrecognized.height:
        offenders = sorted(unrecognized["fixed_drive_result"].unique().to_list())
        raise DrivePointsError(
            where,
            f"{unrecognized.height} possessions have fixed_drive_result "
            f"values outside the contract mapping: {offenders}; "
            "the contract forbids silently inventing a point value",
        )

    # Cast fixed_drive_result to String before mapping so the null
    # column type does not break replace_strict.
    safe = grouped.drop("any_result_first", "_distinct_results").with_columns(
        pl.col("fixed_drive_result").cast(pl.String)
    )
    points_expr = (
        pl.col("fixed_drive_result")
        .replace_strict(CONTRACT_DRIVE_POINTS, return_dtype=pl.Int64)
    )
    is_scoring_expr = pl.col("fixed_drive_result").is_in(list(CONTRACT_SCORING_RESULTS))

    return (
        safe.with_columns(
            [
                points_expr.alias("points"),
                is_scoring_expr.alias("is_scoring"),
            ]
        )
        .sort(["game_id", "fixed_drive", "posteam"])
    )


def possession_observations(
    possessions: pl.DataFrame,
) -> list[PossessionObservation]:
    """Convert the possession frame to a list of :class:`PossessionObservation`."""
    out: list[PossessionObservation] = []
    for row in possessions.iter_rows(named=True):
        out.append(
            PossessionObservation(
                game_id=str(row["game_id"]),
                fixed_drive=int(row["fixed_drive"]),
                posteam=str(row["posteam"]),
                points=int(row["points"]),
                is_scoring=bool(row["is_scoring"]),
                turnover_events=int(row["turnover_events"]),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Phase 3C: red-zone and goal-to-go opportunity observers
# ---------------------------------------------------------------------------
# Both red-zone and goal-to-go opportunities are scoped to a single
# possession: one opportunity per ``(game_id, fixed_drive, posteam)`` if
# the drive has at least one qualifying VFP, and only if the drive is
# included (>= 1 VFP and non-null ``fixed_drive_result``). The
# numerator is ``1`` iff the drive's ``fixed_drive_result`` is exactly
# ``"Touchdown"``. Denominator is ``1`` per included opportunity drive.
#
# A drive whose ``fixed_drive_result`` is null is excluded from the
# denominator entirely, matching the same inclusion rules that
# :class:`PossessionObservation` uses for points/drive and
# scoring-drive rate.


@dataclass(frozen=True)
class RedZoneOpportunity:
    """One included red-zone opportunity drive.

    Attributes
    ----------
    game_id, fixed_drive, posteam:
        The 3-tuple key that uniquely identifies the possession.
    is_td:
        True iff ``fixed_drive_result == "Touchdown"``. Any other result
        (Field goal, Punt, Turnover, etc.) is False.
    """

    game_id: str
    fixed_drive: int
    posteam: str
    is_td: bool


@dataclass(frozen=True)
class GoalToGoOpportunity:
    """One included goal-to-go opportunity drive.

    Attributes
    ----------
    game_id, fixed_drive, posteam:
        The 3-tuple key that uniquely identifies the possession.
    is_td:
        True iff ``fixed_drive_result == "Touchdown"``.
    """

    game_id: str
    fixed_drive: int
    posteam: str
    is_td: bool


def _require_drive_columns(annotated: pl.DataFrame, where: str) -> None:
    """Require all columns the red-zone / goal-to-go pipeline reads."""
    required = {
        "game_id",
        "fixed_drive",
        "posteam",
        "is_vfp",
        "is_red_zone",
        "is_goal_to_go",
        "fixed_drive_result",
        "play_id",
    }
    missing = sorted(required - set(annotated.columns))
    if missing:
        raise WalkForwardError(where, f"missing columns for opportunity build: {missing}")


def _build_opportunity_observations(
    annotated: pl.DataFrame,
    *,
    membership_col: str,
    metric_offense: str,
    where: str,
) -> list[tuple[str, str, tuple[float, float, int]]]:
    """Return ``[(game_id, posteam, triple), ...]`` for one opportunity family.

    Each triple is ``(numerator, denominator, sample)`` for one included
    drive that has at least one VFP with ``membership_col == True``.
    Numerator is ``1.0`` iff the drive's ``fixed_drive_result`` is
    exactly ``"Touchdown"``, else ``0.0``. Denominator is ``1.0`` per
    included opportunity drive. Drives whose ``fixed_drive_result`` is
    null contribute nothing (matching the PossessionObservation
    inclusion rule).
    """
    _require_drive_columns(annotated, where)

    # Sort by play_id so the first-qualifying-VFP identification and
    # the first non-null fixed_drive_result authority are deterministic.
    sorted_annotated = annotated.sort("play_id")

    # Group on the 3-tuple key, restrict to non-null posteam groups
    # (mirrors build_possessions). Aggregate:
    #   - vfp_count: number of VFP rows
    #   - has_membership: True iff at least one VFP row has membership
    #     flag True. This is the "drive has at least one qualifying VFP"
    #     gate; Phase 3C contract says "one opportunity per drive at
    #     that drive's first qualifying VFP" -- we collapse to "at least
    #     one" which is equivalent because the count of opportunities
    #     per drive is exactly one if any qualifying VFP exists.
    #   - first_result: first non-null fixed_drive_result in play_id
    #     order (nflverse propagates the same value to every row of a
    #     drive, so first is deterministic; using ``first`` after a
    #     play_id sort is the same as any-other ordering).
    grouped = (
        sorted_annotated.filter(pl.col("posteam").is_not_null())
        .group_by(["game_id", "fixed_drive", "posteam"], maintain_order=True)
        .agg(
            [
                pl.col("is_vfp").sum().alias("vfp_count"),
                (pl.col("is_vfp") & pl.col(membership_col)).sum().alias("membership_vfp_count"),
                pl.col("fixed_drive_result").drop_nulls().first().alias("fixed_drive_result"),
                pl.col("fixed_drive_result").drop_nulls().n_unique().alias("_distinct_results"),
            ]
        )
        .filter(
            (pl.col("vfp_count") >= 1)
            & (pl.col("membership_vfp_count") >= 1)
            & pl.col("fixed_drive_result").is_not_null()
        )
        .sort(["game_id", "fixed_drive", "posteam"])
    )

    # Phase 3E hard-fail on conflicting drive-result authority inside a
    # single possession (same rule as build_possessions). No silent first.
    conflict = grouped.filter(pl.col("_distinct_results") > 1)
    if conflict.height:
        raise WalkForwardError(
            where,
            f"{conflict.height} possession(s) carry >1 distinct non-null "
            f"fixed_drive_result; the contract forbids silently choosing one.",
        )
    grouped = grouped.drop("_distinct_results")

    out: list[tuple[str, str, tuple[float, float, int]]] = []
    for row in grouped.iter_rows(named=True):
        # The drive is included iff it has at least one VFP, has at
        # least one VFP with membership_col True, and has a non-null
        # fixed_drive_result. All three are enforced by the .filter()
        # above; the inner assertion is purely defensive.
        result = row["fixed_drive_result"]
        is_td = result == "Touchdown"
        out.append(
            (
                str(row["game_id"]),
                str(row["posteam"]),
                (1.0 if is_td else 0.0, 1.0, 1),
            )
        )
    return out


def red_zone_opportunity_observations(
    annotated: pl.DataFrame,
) -> list[tuple[str, str, tuple[float, float, int]]]:
    """Return per-drive red-zone opportunity triples.

    Each triple is ``(is_td, 1, 1)`` for one included drive that has
    at least one VFP with ``yardline_100 <= 20``. Numerator is ``1`` iff
    ``fixed_drive_result == "Touchdown"``.

    The drive is included iff:
    - it contains at least one VFP;
    - it contains at least one VFP with ``is_red_zone == True``;
    - its ``fixed_drive_result`` is non-null.

    Multiple qualifying red-zone plays in the same drive collapse to a
    single opportunity -- this function counts one per
    ``(game_id, fixed_drive, posteam)`` at the drive level.
    """
    return _build_opportunity_observations(
        annotated,
        membership_col="is_red_zone",
        metric_offense=METRIC_RED_ZONE_TD_RATE_OFFENSE,
        where="red_zone_opportunity_observations",
    )


def goal_to_go_opportunity_observations(
    annotated: pl.DataFrame,
) -> list[tuple[str, str, tuple[float, float, int]]]:
    """Return per-drive goal-to-go opportunity triples.

    Each triple is ``(is_td, 1, 1)`` for one included drive that has at
    least one VFP with ``goal_to_go == 1``. Numerator is ``1`` iff
    ``fixed_drive_result == "Touchdown"``. The drive is included iff it
    contains at least one VFP, at least one VFP with
    ``is_goal_to_go == True``, and has a non-null
    ``fixed_drive_result``.
    """
    return _build_opportunity_observations(
        annotated,
        membership_col="is_goal_to_go",
        metric_offense=METRIC_GOAL_TO_GO_TD_RATE_OFFENSE,
        where="goal_to_go_opportunity_observations",
    )


# Stable primitive metric names (Phase 3C may rename; these are the
# primitive observation names, NOT the final 90-column feature names).
METRIC_POINTS_PER_DRIVE = "points_per_drive"
METRIC_SCORING_DRIVE_RATE = "scoring_drive_rate"
METRIC_TURNOVERS_PER_DRIVE = "turnovers_per_drive"

# Phase 3C: drive-opportunity metric names (offense perspective; the
# defense-allowed twins are added in game_observations).
METRIC_RED_ZONE_TD_RATE_OFFENSE = "red_zone_td_rate_offense"
METRIC_RED_ZONE_TD_RATE_DEFENSE_ALLOWED = "red_zone_td_rate_defense_allowed"
METRIC_GOAL_TO_GO_TD_RATE_OFFENSE = "goal_to_go_td_rate_offense"
METRIC_GOAL_TO_GO_TD_RATE_DEFENSE_ALLOWED = "goal_to_go_td_rate_defense_allowed"


def points_per_drive_observation(p: PossessionObservation) -> tuple[float, float, int]:
    """One possession's points/drive contribution: numerator=points, denom=1."""
    return (float(p.points), 1.0, 1)


def scoring_drive_observation(p: PossessionObservation) -> tuple[float, float, int]:
    """One possession's scoring-drive contribution: 1 if Touchdown/FG, else 0."""
    return (1.0 if p.is_scoring else 0.0, 1.0, 1)


def turnovers_per_drive_observation(p: PossessionObservation) -> tuple[float, float, int]:
    """One possession's turnover contribution: numerator = total qualifying events."""
    return (float(p.turnover_events), 1.0, 1)


__all__ = [
    "CONTRACT_DRIVE_POINTS",
    "CONTRACT_SCORING_RESULTS",
    "PossessionObservation",
    "DrivePointsError",
    "GoalToGoOpportunity",
    "RedZoneOpportunity",
    "METRIC_POINTS_PER_DRIVE",
    "METRIC_SCORING_DRIVE_RATE",
    "METRIC_TURNOVERS_PER_DRIVE",
    "METRIC_RED_ZONE_TD_RATE_OFFENSE",
    "METRIC_RED_ZONE_TD_RATE_DEFENSE_ALLOWED",
    "METRIC_GOAL_TO_GO_TD_RATE_OFFENSE",
    "METRIC_GOAL_TO_GO_TD_RATE_DEFENSE_ALLOWED",
    "build_possessions",
    "drive_points_from_result",
    "goal_to_go_opportunity_observations",
    "is_scoring_result",
    "points_per_drive_observation",
    "possession_observations",
    "red_zone_opportunity_observations",
    "scoring_drive_observation",
    "turnovers_per_drive_observation",
]


# Re-export the turnover-row predicate for convenience.
turnover_row_expr = turnover_event_expr