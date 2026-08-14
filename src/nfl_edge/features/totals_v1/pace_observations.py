"""Pace / seconds-per-play primitives for Totals V1 (Phase 3C).

Contract-literal translation of the accepted pace families from
``docs/totals_feature_contract_v1.md``. Definitions:

Valid pace interval:
    A consecutive pair of VFP rows on the same
    ``(game_id, fixed_drive, posteam)``, ordered by ``play_id``, where:

    - both rows are VFP (``is_vfp == True``);
    - both ``game_seconds_remaining`` values are non-null;
    - same ``game_id``;
    - same ``fixed_drive``;
    - same ``posteam``;
    - same ``qtr``;
    - same derived ``game_half``;
    - the prior and current rows are not spikes (neither is
      ``qb_spike == 1``);
    - the prior and current rows are not kneels (neither has
      ``qb_kneel == 1``);
    - ``delta = prior.game_seconds_remaining -
      current.game_seconds_remaining`` is strictly greater than 0;
    - ``delta`` is ``<= 120`` (seconds).

``game_half`` is derived exactly: ``qtr in {1, 2}`` -> ``"first"``,
``qtr in {3, 4}`` -> ``"second"``, ``qtr == 5`` -> ``"overtime"``.
Overtime is its own class and never pairs across regulation.

The prior play is the denominator play; the final play in any
sequence has no following interval and therefore contributes no
interval. Penalty-bearing VFPs remain eligible. There is no generic
penalty filter.

Seconds/play primitive:
    numerator = ``sum(valid delta)``
    denominator = ``count(valid delta)``

Neutral seconds/play additionally requires the **prior** play to satisfy
the neutral definition. The current play's neutral status does not
matter; this is the contract's asymmetric prior-play rule.

Defensive pace exposure receives the opponent offense's identical
numerator and denominator for the duration the offense team held the
ball. The defense does not "control" elapsed time; this is opponent-
offense exposure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import polars as pl

from ...common.errors import WalkForwardError
from .pbp_semantics import (
    REQUIRED_PBP_COLUMNS,
    annotate_pbp_semantics,
    assert_pbp_development_only,
    game_half_for_qtr,
    require_pbp_columns,
)


# Maximum valid interval in seconds. Contract-literal cap; deltas above
# this are treated as stoppages / recording edge cases and excluded.
MAX_INTERVAL_SECONDS: float = 120.0

# Strict lower bound: zero-second intervals are excluded by the
# contract. The minimum is strict (``> 0``).
MIN_INTERVAL_SECONDS_EXCLUSIVE: float = 0.0

# Column name for the derived game_half inside pace interval frames.
GAME_HALF_COL: str = "game_half"

# Primitive metric names (Phase 3C).
METRIC_SECONDS_PLAY_OFFENSE: str = "seconds_play_offense"
METRIC_SECONDS_PLAY_DEFENSE_ALLOWED: str = "seconds_play_defense_allowed"
METRIC_NEUTRAL_SECONDS_PLAY_OFFENSE: str = "neutral_seconds_play_offense"
METRIC_NEUTRAL_SECONDS_PLAY_DEFENSE_ALLOWED: str = "neutral_seconds_play_defense_allowed"


class PaceIntervalError(WalkForwardError):
    """Raised when pace interval construction cannot proceed safely."""


@dataclass(frozen=True)
class PaceInterval:
    """One valid pace interval between a prior and a current VFP.

    Attributes
    ----------
    game_id, fixed_drive, posteam:
        The 3-tuple key shared by the prior and current play.
    qtr:
        The contract-quarter value; same on prior and current.
    game_half:
        Derived ``game_half`` label (``"first"``, ``"second"``,
        ``"overtime"``).
    prior_play_id, current_play_id:
        ``play_id`` values for the pair, used for determinism and tests.
    delta:
        ``prior.game_seconds_remaining - current.game_seconds_remaining``
        in seconds (strictly > 0 and <= 120 by construction).
    is_neutral_prior:
        True iff the prior play satisfied the neutral-situation
        definition. The current play's neutral status does not matter.
    """

    game_id: str
    fixed_drive: int
    posteam: str
    qtr: int
    game_half: str
    prior_play_id: int
    current_play_id: int
    delta: float
    is_neutral_prior: bool


def _require_columns_pace(frame: pl.DataFrame, where: str) -> None:
    """Require all columns the pace interval pipeline needs."""
    # The annotated frame carries everything we need; ensure the
    # annotation columns are present and the source-required columns
    # are too (defensive).
    required = set(REQUIRED_PBP_COLUMNS) | {
        "is_vfp",
        "is_neutral",
        "qb_spike",
        "qb_kneel",
        "game_seconds_remaining",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise PaceIntervalError(where, f"missing columns for pace: {missing}")


def build_pace_intervals(annotated: pl.DataFrame) -> list[PaceInterval]:
    """Return one :class:`PaceInterval` per valid consecutive VFP pair.

    The input ``annotated`` must already be processed by
    :func:`pbp_semantics.annotate_pbp_semantics`; this function reads
    the resulting ``is_vfp`` and ``is_neutral`` columns directly.

    Algorithm:

    1. Sort the frame by ``(game_id, fixed_drive, posteam, play_id)``.
    2. Within each ``(game_id, fixed_drive, posteam)`` group, generate
       consecutive pairs ``(prior, current)`` ordered by ``play_id``.
    3. Filter to pairs where:
       - both ``is_vfp``;
       - both ``game_seconds_remaining`` non-null;
       - same ``qtr`` and same derived ``game_half``;
       - both ``qb_spike == 0`` (prior and current);
       - both ``qb_kneel == 0`` (prior and current);
       - ``delta > 0`` and ``delta <= 120``.

    The result is deterministic for a given annotated frame: same input
    rows in any order produce the same intervals.
    """
    where = "build_pace_intervals"
    _require_columns_pace(annotated, where)

    # Sort deterministically. ``maintain_order=True`` on group_by later
    # relies on this sort; doing it once up front avoids re-sorting
    # per group.
    sorted_frame = annotated.sort(
        ["game_id", "fixed_drive", "posteam", "play_id"]
    )

    # Restrict to VFP rows so the pair construction is correct: we
    # only pair VFP rows against each other, but the in-between
    # non-VFP rows must not be matched against. The contract forbids
    # pairing a VFP against a non-VFP even if the play_ids are
    # consecutive in source order; we therefore drop non-VFP rows
    # BEFORE forming pairs, which matches the contract's "both VFP"
    # constraint literally and avoids spurious same-game non-VFP
    # adjacencies (kickoffs, markers, etc.).
    vfp_only = sorted_frame.filter(pl.col("is_vfp") == True)  # noqa: E712

    if vfp_only.height < 2:
        return []

    # Build group key columns for a single group_by.
    interval_view = (
        vfp_only.with_row_index(name="_row_idx")
        .with_columns(
            [
                pl.col("qtr").cast(pl.Int64, strict=False).alias("_qtr_int"),
                pl.col("game_seconds_remaining").cast(pl.Float64).alias("_gsr"),
                pl.col("qb_spike").cast(pl.Float64).fill_null(0).alias("_spike"),
                pl.col("qb_kneel").cast(pl.Float64).fill_null(0).alias("_kneel"),
            ]
        )
    )

    # Compute the game_half deterministically per row.
    # Using ``game_half_for_qtr`` in a Python map is O(n) and
    # deterministic, but large frames benefit from a vectorized lookup.
    # For simplicity and clarity we map by row -- pace uses VFP rows
    # only, and the frame is already bounded to one game at a time
    # in production backtests.
    halves: list[str] = []
    for q in interval_view["_qtr_int"].to_list():
        # Null qtr can occur on rows that have not been excluded by an
        # earlier filter (e.g. non-VFP rows that did carry game clock
        # data). For pace construction we treat null qtr as
        # "unmappable" and skip the row entirely; the resulting pair
        # construction will not include it because the per-pair filter
        # also requires same-qtr equality, which is enforced
        # separately.
        if q is None:
            halves.append("")
        else:
            halves.append(game_half_for_qtr(q))
    interval_view = interval_view.with_columns(pl.Series("_game_half", halves))

    # Per-group shift to produce (prior, current) columns.
    # Polars ``shift`` per group lets us emit the prior row's values
    # next to the current row's values without manual iteration.
    group_cols = ["game_id", "fixed_drive", "posteam"]
    shifted = interval_view.with_columns(
        [
            pl.col("game_id").shift(1).over(group_cols).alias("__prior_game_id"),
            pl.col("fixed_drive").shift(1).over(group_cols).alias("__prior_fd"),
            pl.col("posteam").shift(1).over(group_cols).alias("__prior_posteam"),
            pl.col("_qtr_int").shift(1).over(group_cols).alias("__prior_qtr"),
            pl.col("_game_half").shift(1).over(group_cols).alias("__prior_half"),
            pl.col("_gsr").shift(1).over(group_cols).alias("__prior_gsr"),
            pl.col("_spike").shift(1).over(group_cols).alias("__prior_spike"),
            pl.col("_kneel").shift(1).over(group_cols).alias("__prior_kneel"),
            pl.col("is_neutral").shift(1).over(group_cols).alias("__prior_neutral"),
            pl.col("play_id").shift(1).over(group_cols).alias("__prior_pid"),
        ]
    )

    # The first row in each group has null prior; drop those.
    shifted = shifted.filter(pl.col("__prior_game_id").is_not_null())

    if shifted.height == 0:
        return []

    # Apply the valid-pair filter contract-literally.
    valid = shifted.filter(
        (pl.col("game_id") == pl.col("__prior_game_id"))
        & (pl.col("fixed_drive") == pl.col("__prior_fd"))
        & (pl.col("posteam") == pl.col("__prior_posteam"))
        & (pl.col("_qtr_int") == pl.col("__prior_qtr"))
        & (pl.col("_game_half") == pl.col("__prior_half"))
        & (pl.col("__prior_gsr").is_not_null() & pl.col("_gsr").is_not_null())
        & (pl.col("__prior_spike") == 0)
        & (pl.col("_spike") == 0)
        & (pl.col("__prior_kneel") == 0)
        & (pl.col("_kneel") == 0)
        & ((pl.col("__prior_gsr") - pl.col("_gsr")) > MIN_INTERVAL_SECONDS_EXCLUSIVE)
        & ((pl.col("__prior_gsr") - pl.col("_gsr")) <= MAX_INTERVAL_SECONDS)
    )

    intervals: list[PaceInterval] = []
    for row in valid.iter_rows(named=True):
        prior_gsr = float(row["__prior_gsr"])
        current_gsr = float(row["_gsr"])
        delta = prior_gsr - current_gsr
        intervals.append(
            PaceInterval(
                game_id=str(row["game_id"]),
                fixed_drive=int(row["fixed_drive"]),
                posteam=str(row["posteam"]),
                qtr=int(row["_qtr_int"]),
                game_half=str(row["_game_half"]),
                prior_play_id=int(row["__prior_pid"]),
                current_play_id=int(row["play_id"]),
                delta=delta,
                is_neutral_prior=bool(row["__prior_neutral"]),
            )
        )
    return intervals


def pace_interval_observations(
    annotated: pl.DataFrame,
) -> dict[str, dict[str, dict[str, list[tuple[float, float, int]]]]]:
    """Aggregate pace intervals into per-game, per-team primitive triples.

    The returned structure mirrors
    :func:`game_observations.aggregate_row_metrics` and
    :func:`game_observations.aggregate_possession_metrics`:

    ``game_id -> team -> metric -> [(numerator, denominator, sample), ...]``

    For each interval:

    - The offense team (``posteam``) receives ``(delta, 1.0, 1)`` to
      ``seconds_play_offense``.
    - If ``is_neutral_prior`` is True, the offense team also receives
      ``(delta, 1.0, 1)`` to ``neutral_seconds_play_offense``.

    Defensive exposure (``*_defense_allowed``) is applied later, in
    :func:`game_observations.build_team_updates`, by the same explicit
    inversion that Phase 3B uses for the per-row offense metrics.

    A pair with ``delta == 0`` is excluded by construction (see
    :func:`build_pace_intervals`). A pair with ``delta > 120`` is
    excluded by construction. A pair whose prior or current row has
    null ``game_seconds_remaining`` is excluded.
    """
    intervals = build_pace_intervals(annotated)
    out: dict[str, dict[str, dict[str, list[tuple[float, float, int]]]]] = {}
    for iv in intervals:
        per_game = out.setdefault(iv.game_id, {})
        per_team = per_game.setdefault(iv.posteam, {})
        per_team.setdefault(METRIC_SECONDS_PLAY_OFFENSE, []).append(
            (float(iv.delta), 1.0, 1)
        )
        if iv.is_neutral_prior:
            per_team.setdefault(METRIC_NEUTRAL_SECONDS_PLAY_OFFENSE, []).append(
                (float(iv.delta), 1.0, 1)
            )
    return out


# Re-export common annotation entry points so callers can compose.
__all__ = [
    "GAME_HALF_COL",
    "MAX_INTERVAL_SECONDS",
    "METRIC_NEUTRAL_SECONDS_PLAY_DEFENSE_ALLOWED",
    "METRIC_NEUTRAL_SECONDS_PLAY_OFFENSE",
    "METRIC_SECONDS_PLAY_DEFENSE_ALLOWED",
    "METRIC_SECONDS_PLAY_OFFENSE",
    "MIN_INTERVAL_SECONDS_EXCLUSIVE",
    "PaceInterval",
    "PaceIntervalError",
    "annotate_pbp_semantics",
    "assert_pbp_development_only",
    "build_pace_intervals",
    "game_half_for_qtr",
    "pace_interval_observations",
    "require_pbp_columns",
]


# Silence unused-import warnings for type-checkers that don't see the
# re-exports as a use.
_ = Mapping
