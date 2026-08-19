"""Outcome-blind coverage / missingness report for the canonical market data.

Produces per-season and per-book/market coverage statistics from the CANONICAL
tables. No scores, results, or edge values are consulted.
"""

from __future__ import annotations

import polars as pl

from .canonical import BOOKS, MARKETS, PER_BOOK_ABBRV


def per_season_coverage(games: pl.DataFrame) -> pl.DataFrame:
    counts = (
        games.group_by("season")
        .agg(
            pl.col("game_id").count().alias("target_games"),
            (pl.col("match_status") == "MATCHED_EXACT").sum().alias("matched_exact"),
            (pl.col("match_status") == "UNMATCHED_NO_EVENT").sum().alias("unmatched"),
            (pl.col("match_status") == "AMBIGUOUS").sum().alias("ambiguous"),
            (pl.col("n_books") > 0).sum().alias("any_market_data"),
        )
        .sort("season")
    )
    return counts


def book_market_coverage(bm: pl.DataFrame) -> pl.DataFrame:
    """Per book x per market target-game coverage N and %."""
    out: list[dict] = []
    games_total = bm.select("game_id").n_unique()
    for b in BOOKS:
        bm_b = bm.filter(pl.col("bookmaker_key") == b)
        b_games = set(bm_b["game_id"].unique().to_list())
        row: dict = {"bookmaker": b}
        for m in ["h2h", "spreads", "totals"]:
            m_games = set(bm_b.filter(pl.col("market_key") == m)["game_id"].unique().to_list())
            row[f"{m}_n"] = len(m_games)
            row[f"{m}_pct"] = 100.0 * len(m_games) / games_total if games_total else 0.0
        complete = set()
        for gid in b_games:
            gms = set(bm_b.filter(pl.col("game_id") == gid)["market_key"].to_list())
            if gms >= {"h2h", "spreads", "totals"}:
                complete.add(gid)
        row["complete_n"] = len(complete)
        row["complete_pct"] = 100.0 * len(complete) / games_total if games_total else 0.0
        out.append(row)
    return pl.DataFrame(out, strict=False)


def intersections(bm: pl.DataFrame) -> pl.DataFrame:
    """Coverage intersections of the product-relevant book subsets."""
    games_total = bm.select("game_id").n_unique()
    def games_with(books: list[str]) -> set:
        bk = set(books)
        return {g for g in bm["game_id"].unique() if bk <= set(
            bm.filter(pl.col("game_id") == g)["bookmaker_key"].unique())}
    rows = []
    for label, books in [
        ("DK+FD", {"draftkings", "fanduel"}),
        ("DK+PIN", {"draftkings", "pinnacle"}),
        ("FD+PIN", {"fanduel", "pinnacle"}),
        ("DK+FD+PIN", {"draftkings", "fanduel", "pinnacle"}),
        ("DK+FD+PIN+BO", {"draftkings", "fanduel", "pinnacle", "betonlineag"}),
    ]:
        g = games_with(books)
        rows.append({"intersection": label, "games": len(g), "pct": 100.0 * len(g) / games_total})
    return pl.DataFrame(rows, strict=False)


def books_per_game(bm: pl.DataFrame) -> pl.DataFrame:
    counts = (
        bm.group_by("game_id")
        .agg(pl.col("bookmaker_key").n_unique().alias("n_books"))
        .with_columns(pl.col("n_books").cast(pl.Int32))
    )
    dist = counts.group_by("n_books").agg(pl.col("game_id").count().alias("n_games")).sort("n_books")
    return dist


def complete_books_per_game(bm: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for g in sorted(set(bm["game_id"].to_list())):
        gb = bm.filter(pl.col("game_id") == g)
        n = 0
        for b in gb["bookmaker_key"].unique():
            if set(gb.filter(pl.col("bookmaker_key") == b)["market_key"].to_list()) >= {"h2h", "spreads", "totals"}:
                n += 1
        rows.append({"game_id": g, "n_complete_books": n})
    c = pl.DataFrame(rows, strict=False)
    return c.group_by("n_complete_books").agg(pl.col("game_id").count().alias("n_games")).sort("n_complete_books")


def _games_with(bm: pl.DataFrame, books: set[str]) -> set:
    bk = {b for b in bm["bookmaker_key"]}
    return {g for g in bm["game_id"].unique()
            if books <= set(bm.filter(pl.col("game_id") == g)["bookmaker_key"].unique())}