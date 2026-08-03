"""Chronological development prediction block definitions.

A prediction block is the smallest unit of walk-forward progress: every
game in one ``(season, season_type, week)`` tuple. Blocks are produced
strictly in chronological order and are the only forward progress unit for
the engine. The block schedule is deterministic given the input games
frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterator

import polars as pl

from ..common.errors import (
    SealedHoldoutAccessError,
    WalkForwardError,
    assert_season_in_window,
)

# The development window is hard-locked so the engine cannot accidentally
# progress into 2025 (the sealed holdout) or 2026 (the forward-use season).
DEVELOPMENT_SEASON_MAX = 2024
FORWARD_USE_SEASON = 2026
SEALED_HOLDOUT_SEASON = 2025


@dataclass(frozen=True)
class PredictionBlock:
    """One chronological development prediction block.

    Blocks are immutable. The id is the natural primary key used by the
    prediction ledger and the state ledger so runs can be cross-referenced
    deterministically."""

    block_id: str
    season: int
    season_type: str
    week: int
    as_of_utc: datetime
    game_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        assert_season_in_window(
            season=self.season,
            allowed_max=DEVELOPMENT_SEASON_MAX,
            where="PredictionBlock",
            detail=f"block_id={self.block_id}",
        )
        if not self.game_ids:
            raise WalkForwardError("PredictionBlock", f"empty block {self.block_id}")
        if not self.as_of_utc.tzinfo:
            raise WalkForwardError("PredictionBlock", f"block {self.block_id} as_of_utc is naive")


def build_development_blocks(
    games: pl.DataFrame,
    *,
    allowed_max_season: int = DEVELOPMENT_SEASON_MAX,
) -> list[PredictionBlock]:
    """Return chronological prediction blocks for the development window.

    Required columns in ``games``:

    - ``game_id``
    - ``season``, ``season_type``, ``week``
    - ``prediction_as_of_utc`` (timezone-aware UTC)

    The games frame is filtered to ``season <= allowed_max_season``.
    For the tripwire test, use :func:`assert_development_seasons_only` to
    verify no 2025 rows are present before calling this function.
    """

    required = {"game_id", "season", "season_type", "week", "prediction_as_of_utc"}
    missing = sorted(required - set(games.columns))
    if missing:
        raise WalkForwardError("build_development_blocks", f"missing columns: {missing}")

    if games.height == 0:
        return []

    filtered = games.filter(pl.col("season") <= int(allowed_max_season))
    if filtered.height == 0:
        return []

    # Group by block key. Within each block, sort game_ids deterministically.
    rows = filtered.select(
        "game_id", "season", "season_type", "week", "prediction_as_of_utc"
    ).to_dicts()
    by_key: dict[tuple[int, str, int], list[dict]] = {}
    by_key_as_of: dict[tuple[int, str, int], datetime] = {}
    for row in rows:
        key = (int(row["season"]), str(row["season_type"]), int(row["week"]))
        by_key.setdefault(key, []).append(row)
        if key not in by_key_as_of:
            by_key_as_of[key] = row["prediction_as_of_utc"]
        else:
            # All games in a block share the same prediction_as_of_utc by
            # construction of the feature pipeline. Defensive check.
            if by_key_as_of[key] != row["prediction_as_of_utc"]:
                raise WalkForwardError(
                    "build_development_blocks",
                    f"heterogeneous as_of_utc inside block {key}",
                )

    # Order: season ASC, then season_type priority (REG, WC, DIV, CON, SB),
    # then week ASC. season_type priority aligns with the actual NFL
    # postseason bracket order.
    ST_PRIORITY = {"REG": 0, "WC": 1, "DIV": 2, "CON": 3, "SB": 4}
    blocks: list[PredictionBlock] = []
    for key in sorted(
        by_key.keys(),
        key=lambda k: (k[0], ST_PRIORITY.get(k[1], 99), k[2]),
    ):
        season, season_type, week = key
        game_ids = tuple(sorted(row["game_id"] for row in by_key[key]))
        block_id = f"{season}_{season_type}_W{week:02d}"
        blocks.append(
            PredictionBlock(
                block_id=block_id,
                season=season,
                season_type=season_type,
                week=week,
                as_of_utc=by_key_as_of[key],
                game_ids=game_ids,
            )
        )
    return blocks


def assert_development_seasons_only(
    games: pl.DataFrame,
    *,
    allowed_max_season: int = DEVELOPMENT_SEASON_MAX,
) -> None:
    """Hard-fail if the games frame contains any season > allowed_max_season.

    This function is the primary tripwire for the 2025 sealed holdout. It
    raises :class:`SealedHoldoutAccessError` on any development-path violation.
    Use it at the boundary of any function that should never see 2025 data.
    """
    if games.height == 0:
        return
    max_season = int(games["season"].max())
    if max_season > allowed_max_season:
        raise SealedHoldoutAccessError(
            max_season,
            "assert_development_seasons_only",
            "input contains season > development_max",
        )


def iter_blocks(blocks: list[PredictionBlock]) -> Iterator[PredictionBlock]:
    """Yield blocks in source order. Wraps the list so future engines can
    swap in lazy streaming without changing call sites."""

    yield from blocks
