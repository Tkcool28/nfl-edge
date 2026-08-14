"""Narrow schedule-context projection for Totals V1.

The raw/frozen schedule source contains outcome, market, QB, and realized
weather fields that are prohibited in the Totals V1 intermediate context
frame. Before any context join, this module projects only the approved
identity/context fields and verifies that prohibited fields are absent
immediately after projection (not merely at the final model-column stage).

Prohibited (never in Totals context): final scores, ``result``, final
``total``, moneylines, spreads, spread odds, total lines, over/under odds,
historical QB IDs/names, realized ``temp``, realized ``wind``.
"""

from __future__ import annotations

from typing import Iterable

import polars as pl

from ...common.errors import WalkForwardError
from .season import assert_frame_development_only

# Approved identity/context fields allowed in the Totals V1 intermediate
# context frame.
APPROVED_CONTEXT_FIELDS: tuple[str, ...] = (
    "game_id",
    "season",
    "season_type",
    "week",
    "away_rest",
    "home_rest",
    "roof",
    "surface",
)

# Explicitly prohibited fields from the frozen schedule source.
PROHIBITED_CONTEXT_FIELDS: frozenset[str] = frozenset(
    {
        "away_score",
        "home_score",
        "result",
        "total",
        "away_moneyline",
        "home_moneyline",
        "spread_line",
        "away_spread_odds",
        "home_spread_odds",
        "total_line",
        "under_odds",
        "over_odds",
        "away_qb_id",
        "home_qb_id",
        "away_qb_name",
        "home_qb_name",
        "temp",
        "wind",
    }
)

# Token-based detection for any market/outcome/weather/QB-shaped column that
# may appear under a slightly different name.
_PROHIBITED_TOKENS: tuple[str, ...] = (
    "moneyline",
    "spread",
    "total_line",
    "_odds",
    "_score",
    "result",
    "_total",
    "qb_id",
    "qb_name",
    "away_qb",
    "home_qb",
    "_temp",
    "_wind",
)


class ContextProjectionError(WalkForwardError):
    """Raised when the Totals context frame violates the narrow projection."""


def find_prohibited_columns(columns: Iterable[str]) -> list[str]:
    """Return any prohibited column names present in an iterable of columns."""
    found: list[str] = []
    for column in columns:
        if column in PROHIBITED_CONTEXT_FIELDS:
            found.append(column)
            continue
        lower = column.lower()
        if any(token in lower for token in _PROHIBITED_TOKENS):
            found.append(column)
    return sorted(set(found))


def assert_no_prohibited_context_columns(frame: pl.DataFrame) -> None:
    """Hard-fail if the Totals context frame contains any prohibited column."""
    found = find_prohibited_columns(frame.columns)
    if found:
        raise ContextProjectionError(
            "assert_no_prohibited_context_columns",
            f"prohibited context columns present: {found}",
        )


def _require_column_safe(frame: pl.DataFrame, column: str, where: str) -> None:
    if column not in frame.columns:
        raise ContextProjectionError(where, f"missing required column {column!r}")


def project_totals_context(
    schedule: pl.DataFrame,
    *,
    season_col: str = "season",
    source_season_type_col: str = "game_type",
    where: str = "project_totals_context",
) -> pl.DataFrame:
    """Project the raw/frozen schedule to the approved Totals V1 context frame.

    Only the approved identity/context columns survive. The frozen baseline
    names the canonical block-type column ``game_type``; it is renamed to the
    approved ``season_type`` field during projection. Prohibited columns can
    never be selected in.

    The development boundary hard-fails rather than silently filtering: if
    any input NFL ``season`` falls outside 2018..2024 (in particular the 2025
    sealed holdout), the projection raises before that row can contribute.
    Calendar-year-2025 dates for NFL season 2024 remain valid; this check is
    purely on the NFL ``season`` column.
    """
    _require_column_safe(schedule, season_col, where)
    _require_column_safe(schedule, "game_id", where)

    # Approved context identity columns that must exist on the source.
    required_source = {
        "game_id",
        season_col,
        source_season_type_col,
        "week",
        "away_rest",
        "home_rest",
        "roof",
        "surface",
    }
    missing = sorted(required_source - set(schedule.columns))
    if missing:
        raise ContextProjectionError(
            where,
            f"source missing approved context columns: {missing}",
        )

    # Development boundary: the source frame may contain only NFL seasons
    # 2018..2024. Season 2025 (or any out-of-window season) hard-fails before
    # it can contribute; it is never silently dropped.
    assert_frame_development_only(schedule, season_col=season_col, where=where)

    # Narrow projection: select only approved fields and never anything more.
    projected = schedule.select(
        "game_id",
        season_col,
        source_season_type_col,
        "week",
        "away_rest",
        "home_rest",
        "roof",
        "surface",
    )
    projected = projected.rename({source_season_type_col: "season_type"})

    # Final safety: the projected frame must contain no prohibited columns.
    assert_no_prohibited_context_columns(projected)
    return projected
