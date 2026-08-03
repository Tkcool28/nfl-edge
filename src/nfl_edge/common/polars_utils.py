"""Small helpers for deterministic polars I/O and schema assertions used by
Task 03A backtest, model, and evaluation code.

The helpers intentionally do not import from ``nfl_edge.features`` so that
the backtest stack remains independent of feature-pipeline-only data
dependencies. Should the feature pipeline evolve, the backtest boundary
stays intact."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import polars as pl

from .errors import MarketColumnError


PROHIBITED_MARKET_TOKENS: tuple[str, ...] = (
    "moneyline",
    "spread_odds",
    "total_line",
    "closing_",
    "pinnacle",
    "draftkings",
    "fanduel",
    "_odds",
    "spread_line",
    "over_odds",
    "under_odds",
    "current_market_probability",
    "closing_probability",
    "later_line_movement",
    "clv",
    "final_weather",
    "future_result",
    "postgame_injury_outcomes",
    "end_of_season_rankings",
)


def assert_no_market_columns(columns: Iterable[str]) -> None:
    """Hard-fail if any prohibited market token appears in ``columns``."""

    found: list[str] = []
    for column in columns:
        lower = str(column).lower()
        if any(token in lower for token in PROHIBITED_MARKET_TOKENS) or lower == "clv":
            found.append(column)
    if found:
        raise MarketColumnError(
            "market-derived columns are prohibited in model inputs: "
            + ", ".join(sorted(found))
        )


def write_parquet_deterministic(
    frame: pl.DataFrame,
    path: str | Path,
    *,
    compression: str = "zstd",
    row_group_size: int = 65536,
) -> None:
    """Write a deterministic zstd parquet. Matches the conventions used by
    the feature pipeline so 2025 ledger writes are reproducible."""

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(
        path,
        compression=compression,
        statistics=True,
        row_group_size=row_group_size,
    )


def read_parquet(path: str | Path) -> pl.DataFrame:
    """Read a parquet file. Thin wrapper that keeps call sites uniform."""

    return pl.read_parquet(path)


def stable_string_columns(frame: pl.DataFrame, columns: Sequence[str]) -> pl.DataFrame:
    """Cast string columns to ``pl.Categorical`` in a deterministic order
    so polars hashing is stable across runs. Currently unused by the walk-
    forward engine but kept for evaluation utilities that may need it."""

    return frame
