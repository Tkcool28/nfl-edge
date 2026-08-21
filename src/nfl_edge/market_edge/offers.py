"""Deterministic reconstruction of actionable spread offers for Task 05E.

Historical background (do not regress):
  The repaired outcome-blind census encoded *price-first* shopping in its
  ``SPREAD.act_line/act_price`` columns (see repair_census.py §4, which picked
  the ACTIONABLE book with the best decimal *price* first, ignoring the line).
  The frozen 05E config is authoritative and requires *number-first* shopping:
    "SPREAD: normalize to selected side; choose the NUMERICALLY GREATEST
     selected-side spread (e.g. +3.5 > +3 ; -2.5 > -3). If identical line
     choose the better price. If still identical use a deterministic fixed
     book tie-break."  (config/market_edge_validation_v1.yaml, actionable_price)

  Therefore grading must NEVER reuse census ``act_line/act_price`` for spread.
  Instead the actual per-book spread offers are reconstructed from the
  authoritative canonical book_market layer and fed through the canonical
  ``shopping.shop_spread()``. Pinnacle is benchmark-only and never actionable.

This module builds a deterministic index: ``{(game_id, selected_side) -->
list[Offer]}`` from the canonical book_market spread observations (DK + FD
both present -> indexed; missing either book for the side -> that side has an
incomplete reconstruction, which callers treat as FAIL-CLOSED non-actionable).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import polars as pl

from . import shopping
from ..market_data.matching import _NAME_TO_ABBR  # shared canonical team->abbr map

GAME_ID = "game_id"
SIDE = "side"  # resolved home / away


def normalize_book_market_frame(bm: pl.DataFrame) -> pl.DataFrame:
    """Resolve each spread offer's outcome name to a HOME/AWAY side and return a
    minimal (game_id, bookmaker_key, side, point, american_price) frame.

    Uses the canonical team-name map from market_data.matching (the same map the
    canonical builder used), matching each offer against the game's
    ``home_abbr`` / ``away_abbr``.
    """
    f = bm.filter(pl.col("market_key") == "spreads")
    f = f.with_columns(
        pl.col("outcome_name")
        .map_elements(
            lambda nm: (_NAME_TO_ABBR.get(str(nm).strip()) or "").upper(),
            return_dtype=pl.Utf8,
        )
        .alias("_abbr")
    )
    side = pl.when(pl.col("_abbr") == pl.col("home_abbr")).then(pl.lit("home"))
    side = side.when(pl.col("_abbr") == pl.col("away_abbr")).then(pl.lit("away")).otherwise(pl.lit(None))
    f = f.with_columns(side.alias(SIDE))
    f = f.filter(pl.col(SIDE).is_not_null())
    return f.select([GAME_ID, "bookmaker_key", SIDE, "point", "american_price"])


def build_spread_offer_index(bm: pl.DataFrame) -> dict[tuple[str, str], list["shopping.Offer"]]:
    """Return {(game_id, 'home'|'away'): [shopping.Offer, ...]} for DK/FD spread
    offers, with both sides of every indexed game present from the canonical
    book_market table. Only the two frozen actionable books (DK/FD) contribute.

    If more than one offer for the same (game, book, side) exists (should not in
    a well-formed canonical table), the most-favorable (max american price) is
    kept so the index is deterministic.
    """
    f = normalize_book_market_frame(bm).filter(pl.col("bookmaker_key").is_in(shopping.FIXED_BOOK_ORDER))
    mapping: dict[tuple[str, str], dict[str, shopping.Offer]] = defaultdict(dict)
    for row in f.select([GAME_ID, "bookmaker_key", SIDE, "point", "american_price"]).iter_rows(named=True):
        if row["point"] is None or row["american_price"] is None:
            continue
        key = (row[GAME_ID], row[SIDE])
        offer = shopping.Offer(
            book=row["bookmaker_key"],
            line=float(row["point"]),
            price_american=int(row["american_price"]),
        )
        cur = mapping[key].get(row["bookmaker_key"])
        if offer.price_american > (cur.price_american if cur else -10_000):
            mapping[key][row["bookmaker_key"]] = offer
    return {k: list(v.values()) for k, v in mapping.items()}


def load_spread_offer_index(path: str | Path) -> dict[tuple[str, str], list["shopping.Offer"]]:
    """Direct loader for a canonical book_market parquet path."""
    assert path.exists(), f"canonical book_market not found: {path}"
    return build_spread_offer_index(pl.read_parquet(path))


def iter_offers_for_key(index, game_id: str, side: str):
    """Return reconstructable list of the applicable offers (may be empty -> fail-closed)."""
    return index.get((game_id, side), [])