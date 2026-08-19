"""Outcome-blind coverage report CLI for the canonical market dataset."""
import polars as pl
from nfl_edge.market_data.coverage import (
    book_market_coverage, intersections, books_per_game,
    complete_books_per_game, per_season_coverage,
)

BASE = "data/market_data/canonical"
g = pl.read_parquet(f"{BASE}/canonical_games.parquet")
bm = pl.read_parquet(f"{BASE}/canonical_book_market.parquet")

print("=== MATCH STATUS ===")
print(g.group_by("match_status").len().sort("match_status"))
print("\n=== PER SEASON ===")
print(per_season_coverage(g))
print("\n=== BOOK X MARKET COVERAGE (target games) ===")
print(book_market_coverage(bm))
print("\n=== INTERSECTIONS ===")
print(intersections(bm))
print("\n=== BOOKS PER GAME ===")
print(books_per_game(bm))
print("\n=== COMPLETE-MARKET BOOKS PER GAME ===")
print(complete_books_per_game(bm))
print("\n=== LEAD TIME (minutes) ===")
lead = g["lead_minutes"].drop_nulls()
print(f"n={lead.len()} min={lead.min():.2f} median={lead.median():.2f} max={lead.max():.2f}")
print("snapshot-not-pregame (lead<=0):", g.filter(
    (pl.col("lead_minutes").is_not_null()) & (pl.col("lead_minutes") <= 0)).height)
from collections import Counter
c = Counter()
for x in g["quality_flags"].to_list():
    if x:
        for f in str(x).split(","):
            c[f] += 1
print("\n=== QUALITY FLAGS ===")
for k, v in sorted(c.items()):
    print(f"{k}: {v}")
