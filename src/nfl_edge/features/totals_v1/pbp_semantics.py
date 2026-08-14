"""Canonical row-level PBP semantics for Totals V1 (Phase 3B + Phase 3C).

This module translates the accepted Phase 2 contract into deterministic
row-level predicates and per-row observation extractors. Every definition
below is taken verbatim from ``docs/totals_feature_contract_v1.md`` and
must not be reinterpreted, extended, or substituted.

Definitions (all taken from the accepted contract):

Valid Football Play (VFP):
    ``posteam`` non-null
    AND ``defteam`` non-null
    AND ``play_deleted == 0``
    AND ``aborted_play == 0``
    AND ``play_type`` IN ``{"pass", "run", "qb_kneel", "qb_spike"}``

``sp`` is scoring-play metadata only and never participates in any VFP or
metric-eligibility predicate. Penalty-bearing rows are not categorically
excluded; they remain only if they satisfy the exact VFP predicate and
the metric-specific rule below.

Pass attempt: VFP AND ``pass_attempt == 1``. The contract forbids using
``play_type`` as a substitute. Sacks are excluded because they do not
satisfy ``pass_attempt == 1``. A null ``pass_attempt`` does not qualify.

Completion: pass attempt AND ``complete_pass == 1``. The contract forbids
using ``pass == 1`` as a substitute.

Rush attempt: VFP AND ``rush_attempt == 1`` AND ``qb_kneel == 0``. Kneels
are excluded from all rush populations even if a source rush flag is
present.

Dropback:
    Primary: VFP AND ``qb_dropback == 1``.
    Fallback (allowed only when ``qb_dropback`` is null): VFP AND
    ``qb_dropback IS NULL AND (pass_attempt == 1 OR sack == 1)``.
    The fallback is NOT an unconditional ``sack == 1`` shortcut.
    The fallback is recorded in the provenance layer.

Turnover event:
    Interception: pass attempt AND ``interception == 1``.
    Lost fumble: VFP AND ``fumble_lost == 1``.
    A qualifying play contributes at most one turnover event even if both
    flags are set. Turnover-on-downs is excluded from turnover rates.

EPA observation: VFP AND ``epa`` non-null. Numerator = epa, denominator = 1.
Missing EPA is excluded from both numerator and denominator. Never silently
zero-imputed.

Success observation: VFP AND ``success`` non-null. Numerator = success,
denominator = 1. Missing success is excluded. Never silently zero-imputed
or coerced to a failure.

Neutral situation (Phase 3C):
    VFP AND ``qtr`` IN ``{1, 2, 3}`` AND ``abs(score_differential) <= 8``
    AND ``game_seconds_remaining >= 900``. Fourth quarter is always
    excluded. ``score_differential`` is the pre-play offensive score
    differential. Neutral state is never inferred from final score or any
    other proxy.

Air yards observation: VFP AND ``pass_attempt == 1`` AND ``air_yards``
non-null. Numerator = ``air_yards``, denominator = 1.

YAC observation: VFP AND ``pass_attempt == 1`` AND ``complete_pass == 1``
AND ``yards_after_catch`` non-null. Numerator = ``yards_after_catch``,
denominator = 1.

Explosive pass event: VFP AND ``pass_attempt == 1`` AND
``yards_gained >= 20`` with observed ``yards_gained``. Numerator = 1,
denominator = 1 per qualifying attempt.

Explosive rush event: VFP AND ``rush_attempt == 1`` AND ``qb_kneel == 0``
AND ``yards_gained >= 10`` with observed ``yards_gained``. Numerator = 1,
denominator = 1 per qualifying kneel-excluded rush attempt. Kneels are
excluded even if a source rush flag is present.

Red-zone opportunity membership: VFP AND ``yardline_100 <= 20``. Used
by ``drive_observations`` to identify the first qualifying VFP per drive.

Goal-to-go opportunity membership: VFP AND ``goal_to_go == 1``. Used by
``drive_observations`` to identify drives that contain at least one
qualifying VFP. Never inferred from yardline.
"""

from __future__ import annotations

import polars as pl

from ...common.errors import WalkForwardError
from .season import assert_frame_development_only


# Canonical VFP play_type whitelist. Exact contract names.
VFP_PLAY_TYPES: frozenset[str] = frozenset({"pass", "run", "qb_kneel", "qb_spike"})


class PbpSemanticsError(WalkForwardError):
    """Raised when the input PBP frame cannot be safely used for semantics."""


# Columns the predicates need. Sourced from the contract's PBP-column list.
REQUIRED_PBP_COLUMNS: tuple[str, ...] = (
    "game_id",
    "season",
    "posteam",
    "defteam",
    "play_type",
    "play_deleted",
    "aborted_play",
    "pass_attempt",
    "rush_attempt",
    "complete_pass",
    "qb_dropback",
    "qb_kneel",
    "qb_spike",
    "sack",
    "epa",
    "success",
    "interception",
    "fumble_lost",
    "fixed_drive",
    "fixed_drive_result",
    "play_id",
    # Phase 3C additions (contract-literal PBP column list).
    "qtr",
    "score_differential",
    "game_seconds_remaining",
    "yardline_100",
    "goal_to_go",
    "yards_gained",
    "air_yards",
    "yards_after_catch",
)


# Quarter / half classification constants used by neutral and pace logic.
# Contract-literal: qtr in {1, 2} is "first half", {3, 4} is "second half".
# Overtime (qtr == 5) is its own class and never pairs across regulation.
NEUTRAL_QTRS: frozenset[int] = frozenset({1, 2, 3})
FIRST_HALF_QTRS: frozenset[int] = frozenset({1, 2})
SECOND_HALF_QTRS: frozenset[int] = frozenset({3, 4})
OVERTIME_QTR: int = 5


def game_half_for_qtr(qtr: int) -> str:
    """Return the deterministic ``game_half`` label for a single ``qtr`` value.

    Contract-literal mapping:

    - ``qtr in {1, 2}``        -> ``"first"``
    - ``qtr in {3, 4}``        -> ``"second"``
    - ``qtr == 5`` (OT)        -> ``"overtime"``
    - any other value          -> ``WalkForwardError`` (hard-fail; the
      contract forbids mapping overtime into regulation halves).

    The mapping is deterministic: same input, same label, no null fallback.
    """
    q = int(qtr)
    if q in FIRST_HALF_QTRS:
        return "first"
    if q in SECOND_HALF_QTRS:
        return "second"
    if q == OVERTIME_QTR:
        return "overtime"
    raise WalkForwardError(
        "game_half_for_qtr",
        f"unrecognized qtr {q}; contract permits only qtr in "
        f"{{1, 2}} -> first, {{3, 4}} -> second, 5 -> overtime",
    )


def require_pbp_columns(frame: pl.DataFrame, *, where: str) -> None:
    """Hard-fail if the input frame is missing any required predicate column."""
    missing = sorted(set(REQUIRED_PBP_COLUMNS) - set(frame.columns))
    if missing:
        raise PbpSemanticsError(where, f"missing PBP columns: {missing}")


def assert_pbp_development_only(
    frame: pl.DataFrame,
    *,
    season_col: str = "season",
    where: str = "pbp_semantics",
) -> None:
    """Hard-fail on any out-of-development-window NFL season in the frame."""
    assert_frame_development_only(frame, season_col=season_col, where=where)


# ---------------------------------------------------------------------------
# Predicates (Polars expressions)
# ---------------------------------------------------------------------------


def vfp_expr() -> pl.Expr:
    """The canonical VFP boolean expression.

    ``posteam`` non-null AND ``defteam`` non-null AND ``play_deleted == 0``
    AND ``aborted_play == 0`` AND ``play_type`` in the VFP whitelist.
    ``fill_null(False)`` keeps downstream aggregation unambiguous under
    Polars' three-valued logic.
    """
    return (
        pl.col("posteam").is_not_null()
        & pl.col("defteam").is_not_null()
        & (pl.col("play_deleted") == 0)
        & (pl.col("aborted_play") == 0)
        & pl.col("play_type").is_in(sorted(VFP_PLAY_TYPES))
    ).fill_null(False)


def pass_attempt_expr() -> pl.Expr:
    """VFP AND ``pass_attempt == 1`` (contract-literal)."""
    return vfp_expr() & (pl.col("pass_attempt") == 1)


def completion_expr() -> pl.Expr:
    """Pass attempt AND ``complete_pass == 1`` (contract-literal)."""
    return pass_attempt_expr() & (pl.col("complete_pass") == 1)


def rush_attempt_expr() -> pl.Expr:
    """VFP AND ``rush_attempt == 1`` AND ``qb_kneel == 0``.

    Kneels are excluded from rush populations even if the source rush
    flag is present (per contract: "kneels are excluded from all rush and
    explosive-rush rates even if a source flag is present").
    """
    return vfp_expr() & (pl.col("rush_attempt") == 1) & (pl.col("qb_kneel") == 0)


def dropback_primary_expr() -> pl.Expr:
    """VFP AND ``qb_dropback == 1``."""
    return vfp_expr() & (pl.col("qb_dropback") == 1)


def dropback_fallback_expr() -> pl.Expr:
    """VFP AND ``qb_dropback IS NULL AND (pass_attempt == 1 OR sack == 1)``.

    Fallback is allowed only when ``qb_dropback`` is null. The fallback
    is NOT an unconditional ``sack == 1`` shortcut. Provenance records
    fallback usage.
    """
    return (
        vfp_expr()
        & pl.col("qb_dropback").is_null()
        & ((pl.col("pass_attempt") == 1) | (pl.col("sack") == 1))
    )


def dropback_expr() -> pl.Expr:
    """Dropback OR dropback-fallback (primary first, fallback only when
    ``qb_dropback`` is null)."""
    return dropback_primary_expr() | dropback_fallback_expr()


def interception_event_expr() -> pl.Expr:
    """Pass attempt AND ``interception == 1`` (contract-literal)."""
    return pass_attempt_expr() & (pl.col("interception") == 1)


def lost_fumble_event_expr() -> pl.Expr:
    """VFP AND ``fumble_lost == 1`` (contract-literal)."""
    return vfp_expr() & (pl.col("fumble_lost") == 1)


def turnover_event_expr() -> pl.Expr:
    """Qualifying turnover event: interception OR lost fumble.

    A qualifying play contributes at most once even if both flags are
    set (logical OR, not sum).
    """
    return interception_event_expr() | lost_fumble_event_expr()


def epa_observed_expr() -> pl.Expr:
    """VFP AND ``epa`` non-null."""
    return vfp_expr() & pl.col("epa").is_not_null()


def success_observed_expr() -> pl.Expr:
    """VFP AND ``success`` non-null."""
    return vfp_expr() & pl.col("success").is_not_null()


def neutral_expr() -> pl.Expr:
    """Contract-literal neutral-situation predicate.

    Exactly: VFP AND ``qtr`` IN ``{1, 2, 3}`` AND
    ``abs(score_differential) <= 8`` AND ``game_seconds_remaining >= 900``.

    Fourth quarter is always excluded. ``score_differential`` is the
    pre-play offensive score differential. ``game_seconds_remaining`` is
    the pre-play clock. Null required fields do not qualify: a null
    ``score_differential`` or ``game_seconds_remaining`` is replaced by
    a sentinel value that fails the comparison, so the predicate returns
    ``False`` for those rows (matching the contract's null rule).
    """
    # Mask null required fields with sentinels that fail the comparison.
    # The contract forbids zero-imputing observable values; the sentinels
    # here are purely internal to the predicate evaluation and never enter
    # any aggregate. They exist only so that ``abs(null)`` and the
    # subsequent comparison evaluate to a deterministic False instead of
    # raising or returning null.
    score_safe = pl.col("score_differential").fill_null(9999)
    clock_safe = pl.col("game_seconds_remaining").fill_null(-1)
    return (
        vfp_expr()
        & pl.col("qtr").is_in(sorted(NEUTRAL_QTRS))
        & (score_safe.abs() <= 8)
        & (clock_safe >= 900)
    ).fill_null(False)


def air_yards_observed_expr() -> pl.Expr:
    """VFP AND ``pass_attempt == 1`` AND ``air_yards`` non-null."""
    return pass_attempt_expr() & pl.col("air_yards").is_not_null()


def yac_observed_expr() -> pl.Expr:
    """VFP AND ``pass_attempt == 1`` AND ``complete_pass == 1`` AND
    ``yards_after_catch`` non-null."""
    return completion_expr() & pl.col("yards_after_catch").is_not_null()


def yards_gained_observed_expr() -> pl.Expr:
    """VFP AND ``yards_gained`` non-null. Shared predicate used by both
    explosive-pass and explosive-rush populations to filter null yards."""
    return vfp_expr() & pl.col("yards_gained").is_not_null()


def explosive_pass_event_expr() -> pl.Expr:
    """VFP AND ``pass_attempt == 1`` AND observed ``yards_gained >= 20``.

    Population for the explosive-pass rate denominator = air_yards
    pass attempts with observed ``yards_gained`` (a stricter population
    than air_yards itself: the explosive denominator requires
    ``yards_gained`` non-null, not just ``air_yards``).
    """
    return pass_attempt_expr() & (pl.col("yards_gained") >= 20)


def explosive_rush_event_expr() -> pl.Expr:
    """VFP AND ``rush_attempt == 1`` AND ``qb_kneel == 0`` AND observed
    ``yards_gained >= 10``."""
    return rush_attempt_expr() & (pl.col("yards_gained") >= 10)


def red_zone_opportunity_membership_expr() -> pl.Expr:
    """VFP AND ``yardline_100 <= 20``.

    This is the membership test for "is this VFP in the red zone"; the
    drive-level opportunity identity (one per drive at the first such
    VFP) lives in :mod:`drive_observations`.
    """
    return vfp_expr() & (pl.col("yardline_100") <= 20)


def goal_to_go_opportunity_membership_expr() -> pl.Expr:
    """VFP AND ``goal_to_go == 1``.

    Never inferred from yardline. The drive-level opportunity identity
    (one per drive when at least one VFP carries the flag) lives in
    :mod:`drive_observations`.
    """
    return vfp_expr() & (pl.col("goal_to_go") == 1)


# ---------------------------------------------------------------------------
# Annotation entry point
# ---------------------------------------------------------------------------


def annotate_pbp_semantics(
    frame: pl.DataFrame,
    *,
    where: str = "annotate_pbp_semantics",
) -> pl.DataFrame:
    """Return the frame annotated with explicit Boolean semantics columns.

    Added columns:
      - ``is_vfp``: Valid Football Play.
      - ``is_pass_attempt``: VFP AND pass_attempt == 1.
      - ``is_completion``: pass attempt AND complete_pass == 1.
      - ``is_rush_attempt``: VFP AND rush_attempt == 1 AND qb_kneel == 0.
      - ``is_dropback``: dropback primary OR dropback fallback.
      - ``is_dropback_fallback``: True exactly when this row qualifies via
        the dropback fallback (qb_dropback IS NULL). Provenance consumers
        use this to count fallback usage.
      - ``is_turnover_event``: qualifying interception OR lost fumble.
      - ``has_epa_obs``: VFP AND epa non-null.
      - ``has_success_obs``: VFP AND success non-null.

    The frame is season-window-validated (NFL seasons 2018..2024 only;
    season 2025 hard-fails) and required-column-validated up front.
    """
    require_pbp_columns(frame, where=where)
    assert_pbp_development_only(frame, where=where)
    return frame.with_columns(
        [
            vfp_expr().alias("is_vfp"),
            pass_attempt_expr().alias("is_pass_attempt"),
            completion_expr().alias("is_completion"),
            rush_attempt_expr().alias("is_rush_attempt"),
            dropback_expr().alias("is_dropback"),
            dropback_fallback_expr().alias("is_dropback_fallback"),
            turnover_event_expr().alias("is_turnover_event"),
            epa_observed_expr().alias("has_epa_obs"),
            success_observed_expr().alias("has_success_obs"),
            # Phase 3C annotation additions. Each is a deterministic
            # Boolean expression re-derivable from the source columns.
            neutral_expr().alias("is_neutral"),
            air_yards_observed_expr().alias("has_air_yards_obs"),
            yac_observed_expr().alias("has_yac_obs"),
            yards_gained_observed_expr().alias("has_yards_gained_obs"),
            explosive_pass_event_expr().alias("is_explosive_pass"),
            explosive_rush_event_expr().alias("is_explosive_rush"),
            red_zone_opportunity_membership_expr().alias("is_red_zone"),
            goal_to_go_opportunity_membership_expr().alias("is_goal_to_go"),
        ]
    )


# ---------------------------------------------------------------------------
# Per-row observation extractors
# ---------------------------------------------------------------------------
# Each function returns (numerator, denominator, sample_count) for one row.
# A row that does not contribute returns (0.0, 0.0, 0) so missing
# observations never silently become zero in either numerator or
# denominator. This is the contract's non-negotiable null rule.


def epa_observation(row: dict) -> tuple[float, float, int]:
    """VFP-with-observed-EPA observation triple for one row."""
    if not row.get("is_vfp"):
        return (0.0, 0.0, 0)
    epa = row.get("epa")
    if epa is None:
        return (0.0, 0.0, 0)
    return (float(epa), 1.0, 1)


def success_observation(row: dict) -> tuple[float, float, int]:
    """VFP-with-observed-success observation triple for one row."""
    if not row.get("is_vfp"):
        return (0.0, 0.0, 0)
    success = row.get("success")
    if success is None:
        return (0.0, 0.0, 0)
    return (float(success), 1.0, 1)


def pass_attempt_observation(row: dict) -> tuple[float, float, int]:
    """Pass-attempt observation triple (count: 1/1/1 per attempt row)."""
    if not row.get("is_pass_attempt"):
        return (0.0, 0.0, 0)
    return (1.0, 1.0, 1)


def completion_observation(row: dict) -> tuple[float, float, int]:
    """Completion observation triple."""
    if not row.get("is_completion"):
        return (0.0, 0.0, 0)
    return (1.0, 1.0, 1)


def rush_attempt_observation(row: dict) -> tuple[float, float, int]:
    """Rush-attempt observation triple."""
    if not row.get("is_rush_attempt"):
        return (0.0, 0.0, 0)
    return (1.0, 1.0, 1)


def dropback_observation(row: dict) -> tuple[float, float, int]:
    """Dropback observation triple (primary or fallback)."""
    if not row.get("is_dropback"):
        return (0.0, 0.0, 0)
    return (1.0, 1.0, 1)


def sack_observation(row: dict) -> tuple[float, float, int]:
    """Sack observation triple. VFP AND sack == 1."""
    if not row.get("is_vfp"):
        return (0.0, 0.0, 0)
    if row.get("sack") != 1:
        return (0.0, 0.0, 0)
    return (1.0, 1.0, 1)


def turnover_event_observation(row: dict) -> tuple[float, float, int]:
    """Turnover-event observation triple (counted at most once per row)."""
    if not row.get("is_turnover_event"):
        return (0.0, 0.0, 0)
    return (1.0, 1.0, 1)


# Provenance counter for dropback fallback usage. Phase 3A's provenance
# layer exposes this as a deterministic counter that builders bump when
# a row qualifies via the fallback (qb_dropback IS NULL).


def dropback_fallback_observation(row: dict) -> tuple[float, float, int]:
    """Dropback-fallback observation triple. Counted once per fallback row.

    This is the provenance-side counter for fallback usage; the regular
    dropback_observation counts the same row as a dropback. The two are
    separate aggregates by design: one for the rate denominator, one for
    the fallback-usage counter.
    """
    if not row.get("is_dropback_fallback"):
        return (0.0, 0.0, 0)
    return (1.0, 1.0, 1)


# ---------------------------------------------------------------------------
# Phase 3C per-row observation extractors
# ---------------------------------------------------------------------------
# Each function returns (numerator, denominator, sample) for one row.
# A row that does not qualify contributes (0, 0, 0) so missing observations
# never silently become zero. Real observed zero values are still emitted
# (e.g. ``air_yards=0`` contributes 0 to the numerator but 1 to the
# denominator); only nulls are excluded.


def sack_within_dropback_observation(row: dict) -> tuple[float, float, int]:
    """Sacks/dropback numerator-and-denominator triple for one row.

    Returns ``(sack_flag, 1, 1)`` iff the row is a qualifying dropback
    (``is_dropback == True``). The sack flag is ``1.0`` exactly when
    ``sack == 1``; otherwise ``0.0``. Real ``sack == 0`` rows still
    contribute ``(0.0, 1.0, 1)`` because the contract counts them in the
    denominator. A null ``sack`` predicate does NOT qualify (handled by
    the dropback predicate upstream).
    """
    if not row.get("is_dropback"):
        return (0.0, 0.0, 0)
    sack = row.get("sack")
    if sack is None:
        return (0.0, 0.0, 0)
    if sack == 1:
        return (1.0, 1.0, 1)
    return (0.0, 1.0, 1)


def air_yards_observation(row: dict) -> tuple[float, float, int]:
    """Air-yards/attempt numerator-and-denominator triple.

    Population: VFP AND ``pass_attempt == 1`` AND observed ``air_yards``.
    Numerator = observed ``air_yards`` (which may be negative).
    Denominator = 1 per qualifying row. Null ``air_yards`` contributes
    nothing -- it is not silently coerced to zero.
    """
    if not row.get("is_pass_attempt"):
        return (0.0, 0.0, 0)
    air = row.get("air_yards")
    if air is None:
        return (0.0, 0.0, 0)
    return (float(air), 1.0, 1)


def yac_observation(row: dict) -> tuple[float, float, int]:
    """YAC/completion numerator-and-denominator triple.

    Population: VFP AND ``pass_attempt == 1`` AND ``complete_pass == 1``
    AND observed ``yards_after_catch``. Numerator = observed
    ``yards_after_catch``. Denominator = 1 per qualifying completion.
    Null ``yards_after_catch`` contributes nothing.
    """
    if not row.get("is_completion"):
        return (0.0, 0.0, 0)
    yac = row.get("yards_after_catch")
    if yac is None:
        return (0.0, 0.0, 0)
    return (float(yac), 1.0, 1)


def explosive_pass_observation(row: dict) -> tuple[float, float, int]:
    """Explosive-pass rate observation triple.

    Population: VFP AND ``pass_attempt == 1`` AND observed
    ``yards_gained``. Event: ``yards_gained >= 20``. Numerator = 1 on an
    explosive event, 0 otherwise; denominator = 1 per qualifying
    attempt. Null ``yards_gained`` contributes nothing.
    """
    if not row.get("is_pass_attempt"):
        return (0.0, 0.0, 0)
    yards = row.get("yards_gained")
    if yards is None:
        return (0.0, 0.0, 0)
    if float(yards) >= 20:
        return (1.0, 1.0, 1)
    return (0.0, 1.0, 1)


def explosive_rush_observation(row: dict) -> tuple[float, float, int]:
    """Explosive-rush rate observation triple.

    Population: VFP AND ``rush_attempt == 1`` AND ``qb_kneel == 0`` AND
    observed ``yards_gained``. Event: ``yards_gained >= 10``. Numerator
    = 1 on an explosive event, 0 otherwise; denominator = 1 per
    qualifying kneel-excluded rush. Null ``yards_gained`` contributes
    nothing. Kneels are excluded even if ``rush_attempt == 1``.
    """
    if not row.get("is_rush_attempt"):
        return (0.0, 0.0, 0)
    yards = row.get("yards_gained")
    if yards is None:
        return (0.0, 0.0, 0)
    if float(yards) >= 10:
        return (1.0, 1.0, 1)
    return (0.0, 1.0, 1)


def neutral_pass_attempt_observation(row: dict) -> tuple[float, float, int]:
    """Neutral-pass numerator-and-denominator triple.

    Returns ``(1, 1, 1)`` iff VFP AND ``pass_attempt == 1`` AND
    ``is_neutral == True``. Otherwise ``(0, 0, 0)``. There is no observed
    zero for a neutral pass attempt: a non-qualifying row does not
    contribute at all.
    """
    if not row.get("is_pass_attempt"):
        return (0.0, 0.0, 0)
    if not row.get("is_neutral"):
        return (0.0, 0.0, 0)
    return (1.0, 1.0, 1)


def neutral_rush_attempt_observation(row: dict) -> tuple[float, float, int]:
    """Neutral-rush numerator-and-denominator triple.

    Returns ``(1, 1, 1)`` iff VFP AND ``rush_attempt == 1`` AND
    ``qb_kneel == 0`` AND ``is_neutral == True``. Otherwise
    ``(0, 0, 0)``. Kneels remain excluded even with the source rush flag.
    """
    if not row.get("is_rush_attempt"):
        return (0.0, 0.0, 0)
    if not row.get("is_neutral"):
        return (0.0, 0.0, 0)
    return (1.0, 1.0, 1)