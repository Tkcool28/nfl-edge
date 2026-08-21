"""Deterministic aggregation + comparison for the Market Edge ledger."""

from __future__ import annotations

import polars as pl


def per_season(rows: pl.DataFrame) -> dict:
    """Per-season summary (season integer -> N / HR / profit / ROI)."""
    out = {}
    if rows.height == 0:
        return out
    for season in sorted(rows["season"].unique().to_list()):
        s = rows.filter(pl.col("season") == season)
        n = s.height
        wins = int((s["w"] == 1).sum())
        be = float(s["breakeven"].mean())
        profit = float(s["profit"].sum())
        out[int(season)] = {
            "N": n, "hit_rate": round(wins / n, 4), "profit": round(profit, 3),
            "roi": round(profit / n, 4), "hr_minus_be": round(wins / n - be, 4),
        }
    return out


def summarize(rows: pl.DataFrame) -> dict:
    """Aggregate a graded ledger frame into the frozen per-candidate metrics.

    N includes pushes; hit rate = wins / N; ROI = profit / N (flat 1-unit stakes).
    """
    n = rows.height
    if n == 0:
        return {"N": 0}
    wins = int((rows["w"] == 1).sum())
    pushes = int((rows["p_push"] == 1).sum())
    losses = n - wins - pushes
    profit = float(rows["profit"].sum())
    avg_amer = float(rows["price_american"].mean())
    avg_dec = float(rows["price_decimal"].mean())
    avg_be = float(rows["breakeven"].mean())
    weeks = int(rows.select(pl.struct("season", "season_week")).n_unique())
    hr = wins / n
    avg_edge = float(rows["edge_pp"].mean()) if rows["edge_pp"].is_not_null().any() else None
    return {
        "N": n, "wins": wins, "losses": losses, "pushes": pushes,
        "hit_rate": round(hr, 4), "avg_american": round(avg_amer, 2),
        "avg_decimal": round(avg_dec, 4), "avg_breakeven": round(avg_be, 4),
        "profit": round(profit, 3), "roi": round(profit / n, 4),
        "hr_minus_be": round(hr - avg_be, 4), "unique_weeks": weeks,
        "avg_edge_pp": round(avg_edge, 4) if avg_edge is not None else None,
    }


def family_table(ledger: pl.DataFrame) -> pl.DataFrame:
    """Group the authoritative ledger by (family, model, bucket)."""
    recs = []
    for (fam, model, bucket) in ledger.select(["family", "model", "bucket"]).unique().sort(["family", "model", "bucket"]).rows():
        sub = ledger.filter((pl.col("family") == fam) & (pl.col("model") == model) & (pl.col("bucket") == bucket))
        s = summarize(sub)
        recs.append({
            "family": fam, "model": model, "bucket": bucket, "N": s["N"], "wins": s["wins"],
            "losses": s["losses"], "pushes": s["pushes"], "hit_rate": s["hit_rate"],
            "avg_american": s["avg_american"], "avg_decimal": s["avg_decimal"],
            "avg_breakeven": s["avg_breakeven"], "avg_edge_pp": s["avg_edge_pp"],
            "unique_weeks": s["unique_weeks"], "profit": s["profit"], "roi": s["roi"],
            "hr_minus_be": s["hr_minus_be"],
        })
    return pl.DataFrame(recs, infer_schema_length=None)


def candidate_summary(ledger: pl.DataFrame, family: str, model: str, bucket: str) -> dict:
    """Summary for one (family, model, bucket) subset of the authoritative ledger."""
    f = ledger.filter((pl.col("family") == family) & (pl.col("model") == model)
                      & (pl.col("bucket") == bucket))
    return {**summarize(f), "per_season": per_season(f)}