"""Totals V1 chronology layer.

Reuses the established repository block and availability semantics rather than
creating a competing backtest engine:

- canonical prediction blocks from :func:`nfl_edge.backtest.blocks.build_development_blocks`;
- weekly availability from :mod:`nfl_edge.features.availability`
  (``WEEK_COMPLETE_TUESDAY_1200_UTC_V1``).

Canonical order is ``season ASC -> REG -> WC -> DIV -> CON -> SB -> week ASC``.
A source block is eligible for a target block only when:

1. the source block is strictly earlier in canonical order than the target
   block; and
2. the source block's weekly availability ``eligible_for_features_at_utc``
   is at or before the target block's ``prediction_as_of_utc``.

Same-block and future-block rows are never eligible. Postseason progresses
forward only and never updates a prior regular-season block.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterator, Sequence

import polars as pl

from ...backtest.blocks import PredictionBlock, build_development_blocks
from ...common.errors import WalkForwardError
from ...features.availability import AvailabilityPolicy, build_weekly_availability
from .season import DEVELOPMENT_SEASON_MAX, SEASON_TYPE_PRIORITY

# Canonical block type ordering, matching src/nfl_edge/backtest/blocks.py.
CANONICAL_ORDER_PRIORITY = SEASON_TYPE_PRIORITY


def canonical_block_key(season: int, season_type: str, week: int) -> tuple[int, int, int]:
    """Return the deterministic canonical sort key for a block.

    ``(season, canonical_type_priority, week)`` where the type priority is
    ``REG=0, WC=1, DIV=2, CON=3, SB=4``.
    """
    season = int(season)
    week = int(week)
    season_type = str(season_type).strip().upper()
    if season_type not in CANONICAL_ORDER_PRIORITY:
        raise WalkForwardError(
            "canonical_block_key",
            f"unknown canonical season_type {season_type!r}; expected one of {sorted(CANONICAL_ORDER_PRIORITY)}",
        )
    return (season, CANONICAL_ORDER_PRIORITY[season_type], week)


def block_key_from_prediction_block(block: PredictionBlock) -> tuple[int, int, int]:
    """Return the canonical sort key for a :class:`PredictionBlock`."""
    return canonical_block_key(block.season, block.season_type, block.week)


def is_strictly_earlier(
    source: PredictionBlock,
    target: PredictionBlock,
) -> bool:
    """Return True iff ``source`` is strictly earlier in canonical order than ``target``.

    Uses the deterministic canonical key comparison. A block is never strictly
    earlier than itself (same block excluded).
    """
    return block_key_from_prediction_block(source) < block_key_from_prediction_block(target)


def build_availability_table(games: pl.DataFrame) -> pl.DataFrame:
    """Return the weekly availability table for the provided canonical games.

    Uses the accepted ``WEEK_COMPLETE_TUESDAY_1200_UTC_V1`` policy.
    """
    return build_weekly_availability(games, AvailabilityPolicy())


def _availability_lookup(
    availability: pl.DataFrame,
) -> dict[tuple[int, str, int], pl.Row]:
    lookup: dict[tuple[int, str, int], pl.Row] = {}
    for row in availability.iter_rows(named=True):
        key = (int(row["season"]), str(row["season_type"]).strip().upper(), int(row["week"]))
        lookup[key] = row
    return lookup


def block_is_available_by(
    block: PredictionBlock,
    availability: pl.DataFrame,
    *,
    cutoff: datetime,
) -> bool:
    """Return True iff ``block``'s source availability is eligible by ``cutoff``.

    A completed game is source-eligible iff its canonical weekly
    ``eligible_for_features_at_utc <= cutoff`` (equality is eligible).
    """
    lookup = _availability_lookup(availability)
    key = (block.season, block.season_type, block.week)
    if key not in lookup:
        raise WalkForwardError(
            "block_is_available_by",
            f"no availability row for block {block.season}_{block.season_type}_W{block.week:02d}",
        )
    eligible_at = lookup[key]["eligible_for_features_at_utc"]
    return eligible_at <= cutoff


def eligible_source_blocks(
    target: PredictionBlock,
    all_blocks: Sequence[PredictionBlock],
    availability: pl.DataFrame,
) -> list[PredictionBlock]:
    """Return source blocks eligible to update ``target``.

    A source block is eligible iff it is strictly earlier than ``target`` in
    canonical order AND its weekly source availability is eligible by the
    target's ``prediction_as_of_utc``. Same-block and future-block rows are
    excluded. Deterministically ordered by canonical key.
    """
    target_key = block_key_from_prediction_block(target)
    cutoff = target.as_of_utc
    eligible: list[PredictionBlock] = []
    for candidate in all_blocks:
        if candidate.block_id == target.block_id:
            continue
        if block_key_from_prediction_block(candidate) >= target_key:
            continue
        # Availability must also permit use by the target cutoff.
        if not block_is_available_by(candidate, availability, cutoff=cutoff):
            continue
        eligible.append(candidate)
    eligible.sort(key=block_key_from_prediction_block)
    return eligible


def eligible_source_game_ids(
    target: PredictionBlock,
    all_blocks: Sequence[PredictionBlock],
    availability: pl.DataFrame,
) -> list[str]:
    """Return the eligible source game_ids for ``target``, sorted deterministically."""
    game_ids: list[str] = []
    for source in eligible_source_blocks(target, all_blocks, availability):
        game_ids.extend(source.game_ids)
    return sorted(game_ids)


def iter_blocks(blocks: Sequence[PredictionBlock]) -> Iterator[PredictionBlock]:
    """Yield blocks in canonical order (deterministic)."""
    yield from sorted(blocks, key=block_key_from_prediction_block)


def iter_eligible_sources_per_block(
    blocks: Sequence[PredictionBlock],
    availability: pl.DataFrame,
) -> Iterator[tuple[PredictionBlock, list[PredictionBlock]]]:
    """Yield ``(target_block, eligible_sources)`` in canonical target order."""
    ordered = list(iter_blocks(blocks))
    for target in ordered:
        yield target, eligible_source_blocks(target, ordered, availability)


def build_totals_blocks(
    games: pl.DataFrame,
    *,
    allowed_max_season: int = DEVELOPMENT_SEASON_MAX,
) -> list[PredictionBlock]:
    """Return deterministically-ordered Totals prediction blocks for the dev window."""
    return build_development_blocks(games, allowed_max_season=allowed_max_season)
