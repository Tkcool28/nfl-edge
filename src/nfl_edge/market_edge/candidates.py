"""Build the authoritative, deterministic candidate row-ledger for Task 05E.

This is the SINGLE ledger used for all grading and reporting (correction 4).
It reads only the committed, outcome-blind census (`market_edge_census_v1.parquet`),
the frozen games outcome table, and the raw QB-Elo / XGBoost prediction tables
(for AVG constituent-presence), then:

1. ML families: QB_ELO / XGB / AVG positive-edge side rows, bucketed on the
   EXACT raw `edge_pp` (no rounded/report bins — correction 3).
2. AVG: exists ONLY when BOTH a QB-Elo and an XGBoost prediction exist for the
   game; otherwise the AVG row is dropped (no fallback — correction 1).
3. Corroborated: a game where QB-ELO and XGB select the SAME positive-edge side.
4. Dog-value zone (frozen): 0.40 <= p_model < 0.50 AND best DK/FD American
   price +111..+200 inclusive AND positive edge.
5. Spread: reconstructed from the canonical book_market via the frozen
   selected-side best-NUMBER-first shopping rule (shopping.shop_spread);
   graded against the actual reconstructed line/price/book — NEVER the stale
   census act_line/act_price (correction 2). Fail-closed when the DK/FD
   offers cannot be reconstructed.
6. Total R4: over/under per P vs O; bucketed on exact raw disagreement points.

The SAME build function is used for both periods (correction: same scorer for
both); the caller passes the split label. 2025 rows are hard-rejected BEFORE
any filtering or materialization.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from . import scoring, shopping
from . import offers as market_offers

DEFAULT_CANONICAL_BM = Path(__file__).resolve().parents[3] / "data/market_data/canonical/canonical_book_market.parquet"

# Frozen ML disagreement buckets (half-open, exact raw edge pp).
_ML_FAMILIES = {
    "QB_ELO": "ML_QBELO_DISAGREEMENT",
    "XGB": "ML_XGB_DISAGREEMENT",
    "AVG": "ML_AVG_DISAGREEMENT",
    "CORROB": "ML_CORROBORATED_DISAGREEMENT",
}

ML_BUCKETS = [(0, 2, "0-2"), (2, 4, "2-4"), (4, 8, "4-8"), (8, 12, "8-12"), (12, 1000, "12+")]
SPREAD_TOTAL_BUCKETS = [(0, 1, "0-1"), (1, 2, "1-2"), (2, 3, "2-3"), (3, 4, "3-4"), (4, 1000, "4+")]

DOG_ZONE = {"p_lo": 0.40, "p_hi": 0.50, "price_lo": 111, "price_hi": 200}
LONG_DOG_MIN_PRICE = 201


def _ml_bucket(edge_pp: float | None) -> str | None:
    if edge_pp is None:
        return None
    for lo, hi, label in ML_BUCKETS:
        if lo <= edge_pp < hi:
            return label
    return None


def _st_bucket(pts: float | None) -> str | None:
    if pts is None:
        return None
    for lo, hi, label in SPREAD_TOTAL_BUCKETS:
        if lo <= pts < hi:
            return label
    return None


def _in_dog_zone(p_model: float, price_american: int) -> bool:
    return (DOG_ZONE["p_lo"] <= p_model < DOG_ZONE["p_hi"]
            and DOG_ZONE["price_lo"] <= price_american <= DOG_ZONE["price_hi"])


def build_ledger(
    census: pl.DataFrame,
    games: pl.DataFrame,
    xgb_ids_with_prediction: set[str],
    split: str,
    spread_offers: dict[tuple[str, str], list["shopping.Offer"]] | None = None,
) -> pl.DataFrame:
    """Return the graded one-row authoritative ledger for one split period.

    ``split`` is one of "DISCOVERY" (2020-2022) or "CONFIRMATION" (2023-2024).
    The same function builds both periods.

    ``spread_offers``: optional prebuilt {(game_id, 'home'|'away'): [Offer]}
    index from offers.build_spread_offer_index(). When omitted it is rebuilt
    from the canonical book_market artifact at DEFAULT_CANONICAL_BM. Spread
    grading is ALWAYS done from reconstructed offers + shopping.shop_spread()
    — never from stale census act_line/act_price.
    """
    # ---- 2025 FIREWALL: reject BEFORE any filtering/materialization ---------
    if games.filter(pl.col("season") == 2025).height:
        raise RuntimeError(
            "2025 rows present in outcome table; 2025 is SEALED and must never be "
            "graded. Refusing to build a ledger while any 2025 outcome row is open."
        )
    # ---- hard boundary: only the observation universe may be graded ---------
    games = games.filter(pl.col("season").is_in([2020, 2021, 2022, 2023, 2024]))
    out_map = {g["game_id"]: g for g in games.to_dicts()}

    # Reconstructable spread offer index (corrected pass 2): rebuilt from the
    # canonical book_market unless the caller supplied a prebuilt index.
    if spread_offers is None:
        bm_path = DEFAULT_CANONICAL_BM
        if not bm_path.exists():
            raise RuntimeError(
                f"canonical book_market not found at {bm_path}; spread offers "
                f"cannot be reconstructed. Refusing to grade spread without them."
            )
        spread_index = market_offers.build_spread_offer_index(pl.read_parquet(bm_path))
    else:
        spread_index = spread_offers

    rows: list[dict] = []
    spread_recon: dict[str, tuple[float, str]] = {}

    def add(row: dict, family: str, model: str, bucket: str | None,
            side: str, price_american: int | None, edge_pp: float | None,
            p_model: float | None, impl_ev: float | None) -> None:
        g = out_map.get(row["game_id"])
        dec = scoring.american_to_decimal(price_american)
        if g is None or dec is None:
            return  # not graded (no outcome or not actionable)
        w, push, profit = scoring.moneyline_grading(side, g["home_score"], g["away_score"], dec)
        rows.append({
            "game_id": row["game_id"], "season": row["season"], "season_week": row.get("season_week"),
            "family": family, "model": model, "bucket": bucket, "selected_side": side,
            "price_american": price_american, "price_decimal": dec, "edge_pp": edge_pp,
            "p_model": p_model, "implied_ev": impl_ev, "w": w, "p_push": push,
            "profit": profit, "breakeven": scoring.breakeven_from_decimal(dec),
        })

    # ---- per-game, per-model positive-edge ML rows --------------------------
    pe = census.filter(pl.col("census_family") == "POSITIVE_EDGE_CANDIDATE")
    by_game: dict[tuple, dict] = {}
    for r in pe.iter_rows(named=True):
        if r["split_label"] != split:
            continue
        by_game.setdefault((r["game_id"], r["season"]), {})[r["model"]] = r

    for (gid, season), m in by_game.items():
        for model in ("QB_ELO", "XGB", "AVG"):
            r = m.get(model)
            if r is None or r["edge_pp"] is None or r["actionable_american"] is None:
                continue
            # Correction 1: AVG exists only when BOTH constituents have a prediction.
            if model == "AVG":
                if gid not in xgb_ids_with_prediction or "QB_ELO" not in m:
                    continue
            bucket = _ml_bucket(r["edge_pp"])
            add(r, _ML_FAMILIES[model], model, bucket, r["side"],
                r["actionable_american"], r["edge_pp"], r["p_model"], r.get("model_implied_ev"))
            # Dog-value zone (per model, frozen)
            if _in_dog_zone(r["p_model"], r["actionable_american"]):
                add(r, "ML_DOG_VALUE_ZONE", model, "ZONE", r["side"],
                    r["actionable_american"], r["edge_pp"], r["p_model"], r.get("model_implied_ev"))
            # Long-dog context (>= +201), separately reported high-risk population
            if r["actionable_american"] >= LONG_DOG_MIN_PRICE:
                add(r, "LONG_DOG_201+_CONTEXT", model, "LONG201+", r["side"],
                    r["actionable_american"], r["edge_pp"], r["p_model"], r.get("model_implied_ev"))

        # Corroborated: QB-ELO and XGB select the SAME positive-edge side. The
        # corroborated candidate is represented/scored with the AVG value, and AVG
        # exists ONLY when BOTH constituent predictions exist. FAIL CLOSED: if the
        # exact AVG cannot be constructed (the AVG row or either constituent's
        # prediction is missing), the corroborated candidate is SKIPPED — it is
        # NEVER emitted or scored from a QB-ELO-only fallback (correction 6b).
        q = m.get("QB_ELO"); x = m.get("XGB"); avg = m.get("AVG")
        if (q and x and avg and q["side"] == x["side"] and q["actionable_american"]
                and gid in xgb_ids_with_prediction):
            src = avg
            if src["actionable_american"]:
                bucket = _ml_bucket(src["edge_pp"])
                add(src, _ML_FAMILIES["CORROB"], "CORROB", bucket, src["side"],
                    src["actionable_american"], src["edge_pp"], src["p_model"], src.get("model_implied_ev"))
                if _in_dog_zone(src["p_model"], src["actionable_american"]):
                    add(src, "ML_DOG_VALUE_ZONE", "CORROB", "ZONE", src["side"],
                        src["actionable_american"], src["edge_pp"], src["p_model"], src.get("model_implied_ev"))

    # ---- spread (expected-margin) rows -------------------------------------
    # Corrected (pass 2): spread grading is ALWAYS from offers reconstructed from
    # the canonical book_market via the frozen selected-side best-NUMBER-first
    # rule (shopping.shop_spread). The stale census act_line/act_price (price-first)
    # are NEVER used. Fail-closed: a spread row whose DK+FD offers cannot both be
    # reconstructed is NOT graded (not actionable).
    spread_list = list(census.filter(pl.col("census_family") == "SPREAD").iter_rows(named=True))
    for r in spread_list:
        if r["split_label"] != split:
            continue
        g = out_map.get(r["game_id"])
        if g is None:
            continue
        offers = market_offers.iter_offers_for_key(spread_index, r["game_id"], r["selected_side"])
        if len(offers) < 2:  # fail-closed: both DK and FD must be reconstructable
            continue
        picked = shopping.shop_spread(offers)
        if picked is None:
            continue
        dec = scoring.american_to_decimal(picked.price_american)
        w, push, profit = scoring.spread_grading(r["selected_side"], g["home_score"], g["away_score"],
                                                 picked.line, dec)
        rows.append({
            "game_id": r["game_id"], "season": r["season"], "season_week": r.get("season_week"),
            "family": "SPREAD_DISAGREEMENT", "model": "EXPECTED_MARGIN", "bucket": _st_bucket(r["disagreement_pts"]),
            "selected_side": r["selected_side"], "price_american": picked.price_american, "price_decimal": dec,
            "edge_pp": r["disagreement_pts"], "p_model": None, "implied_ev": None, "w": w,
            "p_push": push, "profit": profit, "breakeven": scoring.breakeven_from_decimal(dec),
        })
        spread_recon.setdefault(r["game_id"], (picked.line, picked.book))

    for r in census.filter(pl.col("census_family") == "TOTAL_R4").iter_rows(named=True):
        if r["split_label"] != split:
            continue
        if r["act_line"] is None or r["act_price"] is None:
            continue
        g = out_map.get(r["game_id"]); dec = scoring.american_to_decimal(r["act_price"])
        if g is None or dec is None:
            continue
        w, push, profit = scoring.total_grading(r["selected_side"], g["home_score"], g["away_score"],
                                                r["act_line"], dec)
        rows.append({
            "game_id": r["game_id"], "season": r["season"], "season_week": r.get("season_week"),
            "family": "TOTAL_R4_DISAGREEMENT", "model": "RIDGE_R4", "bucket": _st_bucket(r["disagreement_pts"]),
            "selected_side": r["selected_side"], "price_american": r["act_price"], "price_decimal": dec,
            "edge_pp": r["disagreement_pts"], "p_model": None, "implied_ev": None, "w": w,
            "p_push": push, "profit": profit, "breakeven": scoring.breakeven_from_decimal(dec),
        })

    df = pl.DataFrame(rows)
    # Attach reconstructed spread book/line (populated only for spread rows).
    df = df.with_columns([
        pl.Series("reconstructed_line", [spread_recon.get(g, (None, None))[0] for g in df["game_id"].to_list()]),
        pl.Series("reconstructed_book", [spread_recon.get(g, (None, None))[1] for g in df["game_id"].to_list()]),
    ])
    return df