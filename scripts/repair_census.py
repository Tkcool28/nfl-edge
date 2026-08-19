"""Task 05E-D3B-R1 — OUTCOME-BLIND CENSUS REPAIR + PRODUCT-ALIGNMENT AUDIT.

Repairs the existing ONE outcome-blind census. No new research program, no
outcome inspection. Produces (all under the worktree):

  data/modeling/development_v1/market_edge_census_v1.parquet  (repaired, consolidated)
  reports/task_05e_d3b_outcome_blind_census.csv               (machine-readable)
  reports/task_05e_d3b_outcome_blind_census.md                (narrative)
  reports/task_05e_d3b_hypothesis_ledger_v1.csv               (prereg trial ledger)
  reports/task_05e_d3b_census_provenance.json                 (hash/safety proof)

HARD GUARANTEES
  * Every model/outcome-bearing parquet is read with an explicit column
    WHITELIST BEFORE collection. observed_total / scores / winners / ATS /
    totals results are never loaded.
  * Seasons restricted to 2020-2024; 2025 never touched.
  * Ridge Totals V1 R4 predictions are USED (predicted_total only), never refit.
  * No model training/retuning/stacker/Odds API.
  * No realized hit rate / ROI / profit / ATS / totals outcome is computed.

Core product families: HIGH CONFIDENCE, BALANCED, NORMAL +EV, optional
BIG OPPORTUNITY.
"""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl
from nfl_edge.market_data.matching import _NAME_TO_ABBR

PROD = Path("/root/nfl-edge")
NORM_WT = Path("/root/workspaces/nfl-edge-task-05e-market-normalization-v1")
OUT_WT = Path("/root/workspaces/nfl-edge-task-05e-edge-prereg-v1")
DATA_OUT = OUT_WT / "data" / "modeling" / "development_v1"
REPORTS = OUT_WT / "reports"
DATA_OUT.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)

SEASONS = [2020, 2021, 2022, 2023, 2024]
DISC = [2020, 2021, 2022]
CONF = [2023, 2024]
ACTIONABLE = ["draftkings", "fanduel"]
PRIM_BENCH = "pinnacle"
ROB_BENCH = "betonlineag"

R4_ARTIFACT = PROD / "reports/task05d/task05d_ridge_predictions.parquet"
R4_MANIFEST = PROD / "reports/task05d/task05d_ridge_run_manifest.json"


def american_to_dec(a):
    if a is None:
        return None
    f = float(a)
    return (f / 100) + 1 if f > 0 else (100 / abs(f)) + 1


def no_vig(h_dec, a_dec):
    if h_dec is None or a_dec is None:
        return None, None
    qh, qa = 1.0 / h_dec, 1.0 / a_dec
    return qh / (qh + qa), qa / (qh + qa)


def cmp_price(a, b):
    if a is None or b is None:
        return None
    if abs(a - b) < 1e-9:
        return 0
    return 1 if a > b else -1


# ---------------------------------------------------------------------------
# 1. FROZEN MODEL OUTPUTS (whitelisted reads only)
# ---------------------------------------------------------------------------
qe = pl.read_parquet(
    PROD / "data/modeling/development_v1/qb_elo_predictions_2018_2024.parquet",
    columns=["game_id", "season", "week", "predicted_home_win_probability"],
).filter(pl.col("season").is_in(SEASONS)).rename({"predicted_home_win_probability": "qbelo_p_home"})

xb = pl.read_parquet(
    PROD / "data/modeling/development_v1/chronology_corrected/xgboost_candidate_predictions_2018_2024.parquet",
    columns=["candidate_id", "game_id", "season", "week", "warmup", "prediction_probability"],
).filter((pl.col("candidate_id") == "conservative") & pl.col("season").is_in(SEASONS)).with_columns(
    pl.when(pl.col("warmup")).then(None).otherwise(pl.col("prediction_probability")).alias("xgb_p_home")
).select(["game_id", "season", "week", "xgb_p_home"])

em = pl.read_parquet(
    PROD / "data/modeling/development_v1/expected_margin_predictions_2018_2024.parquet",
    columns=["candidate_id", "game_id", "season", "week", "expected_home_margin",
             "expected_home_points", "expected_away_points"],
).filter((pl.col("candidate_id") == "stable") & pl.col("season").is_in(SEASONS)).with_columns(
    (pl.col("expected_home_points") + pl.col("expected_away_points")).alias("em_pred_total")
).select(["game_id", "season", "week", "expected_home_margin", "em_pred_total"])

# R4 Ridge Totals — STRICT whitelist; observed_total NEVER read.
r4 = pl.read_parquet(
    R4_ARTIFACT, columns=["candidate_id", "game_id", "season", "week", "predicted_total"],
).filter((pl.col("candidate_id") == "R4") & pl.col("season").is_in(SEASONS)).select(
    ["game_id", "season", "week", "predicted_total"])

ml_models = (qe.join(xb, on="game_id", how="inner")
             .join(em.select(["game_id", "expected_home_margin", "em_pred_total"]), on="game_id", how="left")
             .join(r4.select(["game_id", "predicted_total"]), on="game_id", how="left"))
assert ml_models["game_id"].is_duplicated().sum() == 0
print("ML model frame:", ml_models.shape, "games:", ml_models["game_id"].n_unique())

# ---------------------------------------------------------------------------
# 2. CANONICAL MARKET (read-only)
# ---------------------------------------------------------------------------
games = pl.read_parquet(NORM_WT / "data/market_data/canonical/canonical_games.parquet")
bm = pl.read_parquet(NORM_WT / "data/market_data/canonical/canonical_book_market.parquet")

GAME_SIDE = games.select(["game_id", "home_abbr", "away_abbr"]).unique().with_columns(
    pl.col("home_abbr").alias("_H"), pl.col("away_abbr").alias("_A"))
GAME_WEEK = games.select(["game_id"]).with_columns(
    pl.col("game_id").str.split("_").list.get(1).alias("season_week"))
GAME_WEEK_MAP = dict(GAME_WEEK.iter_rows())


def _class_side(r):
    s = r.get("side_abbr")
    if s is None:
        return None
    if s == r.get("_H"):
        return "home"
    if s == r.get("_A"):
        return "away"
    return None


def _annotate_side(frame):
    f = frame.join(GAME_SIDE, on="game_id", how="left")
    f = f.with_columns(pl.struct(["outcome_name"]).map_elements(
        lambda r: _NAME_TO_ABBR.get(str(r["outcome_name"]).strip()), return_dtype=pl.Utf8).alias("side_abbr"))
    f = f.with_columns(pl.struct(["side_abbr", "_H", "_A"]).map_elements(
        _class_side, return_dtype=pl.Utf8).alias("side"))
    return f.filter(pl.col("side").is_not_null())


h2h = _annotate_side(bm.filter(pl.col("market_key") == "h2h")).with_columns(
    pl.col("american_price").map_elements(american_to_dec, return_dtype=pl.Float64).alias("dec"))
spr = _annotate_side(bm.filter(pl.col("market_key") == "spreads")).with_columns(
    pl.col("american_price").map_elements(american_to_dec, return_dtype=pl.Float64).alias("dec"))
# totals: side is already over/under; do not run the team-name annotator
totm = bm.filter(pl.col("market_key") == "totals").with_columns(
    pl.col("american_price").map_elements(american_to_dec, return_dtype=pl.Float64).alias("dec"))


def index_side(frame):
    """{(game_id, book, side): (american_best, dec_best, point_best)}"""
    d = {}
    for gid, book, side, am, dec, pt in frame.select(
            ["game_id", "bookmaker_key", "side", "american_price", "dec", "point"]).iter_rows():
        key = (gid, book, side)
        cur = d.get(key)
        best = (am, dec, pt)
        if cur is None:
            d[key] = best
        # lean toward the best (max american) for that (game,book,side) if duplicated
        elif (am is not None) and (cur[0] is None or am > cur[0]):
            d[key] = best
    return d


H2H_IDX = index_side(h2h)
SPR_IDX = index_side(spr)
TOT_IDX = index_side(totm)


def h2h_price(gid, book, side):
    v = H2H_IDX.get((gid, book, side))
    return (v[0], v[1]) if v else (None, None)  # (american, dec)


def h2h_american(gid, book, side):
    v = H2H_IDX.get((gid, book, side))
    return v[0] if v else None


def spr_offer(gid, book, side):
    v = SPR_IDX.get((gid, book, side))
    return v if v else (None, None, None)


def tot_offer(gid, book, side):
    v = TOT_IDX.get((gid, book, side))
    return v if v else (None, None, None)


# ---------------------------------------------------------------------------
# 3. MONEYLINE CENSUS
#    TWO_SIDED_ABSOLUTE_DIAGNOSTIC : all (game, side, model) rows, |edge_pp|
#    POSITIVE_EDGE_CANDIDATE      : product side with edge_pp_prim > 0
# ---------------------------------------------------------------------------
row_families = []
path_diag = {"zero_pos_side_pairs": 0, "one_plus_pos_side_pairs": 0}

for r in ml_models.iter_rows(named=True):
    gid = r["game_id"]; season = r["season"]; wk = GAME_WEEK_MAP.get(gid)
    qh, xh = r["qbelo_p_home"], r["xgb_p_home"]
    ah = (qh + xh) / 2 if (qh is not None and xh is not None) else (qh if qh is not None else xh)

    pin_h, pin_hd = h2h_price(gid, PRIM_BENCH, "home")
    pin_a, pin_ad = h2h_price(gid, PRIM_BENCH, "away")
    pn_h, pn_a = no_vig(pin_hd, pin_ad)
    bo_h, bo_hd = h2h_price(gid, ROB_BENCH, "home")
    bo_a, bo_ad = h2h_price(gid, ROB_BENCH, "away")
    rb_hd = (pin_hd + bo_hd) / 2 if (pin_hd is not None and bo_hd is not None) else (pin_hd if pin_hd is not None else bo_hd)
    rb_ad = (pin_ad + bo_ad) / 2 if (pin_ad is not None and bo_ad is not None) else (pin_ad if pin_ad is not None else bo_ad)
    rp_h, rp_a = no_vig(rb_hd, rb_ad)

    # actionable best DK/FD per side
    act = {}
    for side in ("home", "away"):
        best_dec, best_am, best_book = None, None, None
        for bk in ACTIONABLE:
            am, dec = h2h_price(gid, bk, side)
            if dec is not None and (best_dec is None or dec > best_dec):
                best_dec, best_am, best_book = dec, am, bk
        act[side] = (best_am, best_dec, best_book)

    for view, pm_home in (("QB_ELO", qh), ("XGB", xh), ("AVG", ah)):
        if pm_home is None:
            continue
        pos_here = []
        for side in ("home", "away"):
            pm = pm_home if side == "home" else (1 - pm_home)
            p_bench = pn_h if side == "home" else pn_a
            edge_prim = (pm - p_bench) * 100 if p_bench is not None else None
            if edge_prim is not None and edge_prim > 0:
                pos_here.append(side)
            p_rob = rp_h if side == "home" else rp_a
            edge_rob = (pm - p_rob) * 100 if p_rob is not None else None
            am, dec, book = act[side]
            ev = (pm * dec - 1) if (dec is not None and pm is not None) else None
            # TWO-SIDED diagnostic row (always)
            row_families.append({
                "census_family": "TWO_SIDED_ABSOLUTE_DIAGNOSTIC",
                "game_id": gid, "season": season, "season_week": wk,
                "split_label": "DISCOVERY" if season in DISC else "CONFIRMATION",
                "side": side, "model": view, "p_model": pm,
                "edge_pp": edge_prim, "edge_pp_rob": edge_rob,
                "model_implied_ev": ev,
                "actionable_american": am, "actionable_decimal": dec,
                "actionable_book": book,
                "pinnacle_american": pin_h if side == "home" else pin_a,
                "pinnacle_decimal": pin_hd if side == "home" else pin_ad,
                "has_pinnacle": pin_hd is not None,
                "has_betonline": bo_hd is not None,
                "dk_decimal": h2h_price(gid, "draftkings", side)[1],
                "fd_decimal": h2h_price(gid, "fanduel", side)[1],
                "pinnacle_novig_home": pn_h, "pinnacle_novig_away": pn_a,
            })
        # positivity pathology per (game, model)
        if len(pos_here) == 0:
            path_diag["zero_pos_side_pairs"] += 1
        elif len(pos_here) > 1:
            path_diag["one_plus_pos_side_pairs"] += 1
    # positive-edge candidate rows (product focused), one per (game, model)
    for view, pm_home in (("QB_ELO", qh), ("XGB", xh), ("AVG", ah)):
        if pm_home is None:
            continue
        pos = []
        for side in ("home", "away"):
            pm = pm_home if side == "home" else (1 - pm_home)
            p_bench = pn_h if side == "home" else pn_a
            edge_prim = (pm - p_bench) * 100 if p_bench is not None else None
            if edge_prim is not None and edge_prim > 0:
                pos.append((side, edge_prim))
        if not pos:
            continue
        side, edge_prim = pos[0]
        pm = pm_home if side == "home" else (1 - pm_home)
        p_rob = rp_h if side == "home" else rp_a
        edge_rob = (pm - p_rob) * 100 if p_rob is not None else None
        am, dec, book = act[side]
        ev = (pm * dec - 1) if (dec is not None and pm is not None) else None
        dk_am, dk_dec = h2h_price(gid, "draftkings", side)
        fd_am, fd_dec = h2h_price(gid, "fanduel", side)
        pin_s = pin_h if side == "home" else pin_a
        pin_sd = pin_hd if side == "home" else pin_ad
        row_families.append({
            "census_family": "POSITIVE_EDGE_CANDIDATE",
            "game_id": gid, "season": season, "season_week": wk,
            "split_label": "DISCOVERY" if season in DISC else "CONFIRMATION",
            "side": side, "model": view, "p_model": pm,
            "edge_pp": edge_prim, "edge_pp_rob": edge_rob,
            "model_implied_ev": ev,
            "actionable_american": am, "actionable_decimal": dec,
            "actionable_book": book,
            "pinnacle_american": pin_s, "pinnacle_decimal": pin_sd,
            "dk_american": dk_am, "dk_decimal": dk_dec,
            "fd_american": fd_am, "fd_decimal": fd_dec,
            "has_pinnacle": pin_hd is not None, "has_betonline": bo_hd is not None,
        })

ml_pe = pl.DataFrame([r for r in row_families if r["census_family"] == "POSITIVE_EDGE_CANDIDATE"])
ml_diag = pl.DataFrame([r for r in row_families if r["census_family"] == "TWO_SIDED_ABSOLUTE_DIAGNOSTIC"])
print("ML positive-edge rows:", ml_pe.height, "two-sided diag rows:", ml_diag.height)
print("positivity pathology:", path_diag)

# ---------------------------------------------------------------------------
# 4. SPREAD census (Expected-Margin vs Pinnacle home line)
# ---------------------------------------------------------------------------
spr_rows = []
for game in ml_models.iter_rows(named=True):
    gid = game["game_id"]; season = game["season"]
    emm = game["expected_home_margin"]
    if emm is None:
        continue
    _, _, L = spr_offer(gid, "pinnacle", "home")
    if L is None:
        continue
    signed = emm + L
    if abs(signed) < 1e-9:
        continue
    side = "home" if signed > 0 else "away"
    disp = abs(signed)
    best_dec, best_am, best_book, best_line = None, None, None, None
    for bk in ACTIONABLE:
        oa, od, opt = spr_offer(gid, bk, side)
        if od is not None and (best_dec is None or od > best_dec):
            best_dec, best_am, best_book, best_line = od, oa, bk, opt
    pin_am, pin_dec, pin_line = spr_offer(gid, "pinnacle", side)
    dk_am, dk_dec, _ = spr_offer(gid, "draftkings", side)
    fd_am, fd_dec, _ = spr_offer(gid, "fanduel", side)
    n_offers = sum(1 for x in (dk_dec, fd_dec) if x is not None and pin_dec is not None)
    n_better = sum(1 for x in (dk_dec, fd_dec) if x is not None and pin_dec is not None and x > pin_dec + 1e-9)
    n_equal = sum(1 for x in (dk_dec, fd_dec) if x is not None and pin_dec is not None and abs(x - pin_dec) <= 1e-9)
    n_worse = sum(1 for x in (dk_dec, fd_dec) if x is not None and pin_dec is not None and x < pin_dec - 1e-9)
    spr_rows.append({
        "census_family": "SPREAD", "game_id": gid, "season": season,
        "season_week": GAME_WEEK_MAP.get(gid),
        "split_label": "DISCOVERY" if season in DISC else "CONFIRMATION",
        "expected_home_margin": emm, "home_line_L": L, "selected_side": side,
        "disagreement_pts": disp,
        "act_line": best_line, "act_price": best_am, "act_book": best_book,
        "pinnacle_line": pin_line, "pinnacle_price": pin_am,
        "pinnacle_decimal": pin_dec, "dk_decimal": dk_dec, "fd_decimal": fd_dec,
        "n_better_than_pinnacle": n_better,
        "n_equal_pinnacle": n_equal,
        "n_worse_than_pinnacle": n_worse,
        "n_offers_with_pinnacle": n_offers,
        "price_better_than_pinnacle": n_better,
        "price_equal_pinnacle": n_equal,
        "price_worse_pinnacle": n_worse,
        "number_and_price_better_pinnacle": n_better,
    })
spr_df = pl.DataFrame(spr_rows)
print("SPREAD rows:", spr_df.height)

# ---------------------------------------------------------------------------
# 5. TOTAL census (R4 predicted_total vs Pinnacle total line)
# ---------------------------------------------------------------------------
tot_rows = []
for game in ml_models.iter_rows(named=True):
    gid = game["game_id"]; season = game["season"]
    pt_ = game["predicted_total"]
    if pt_ is None:
        continue
    pin_line = tot_offer(gid, "pinnacle", "over")[2]
    if pin_line is None:
        continue
    diff = pt_ - pin_line
    sel = "over" if diff > 1e-9 else ("under" if diff < -1e-9 else "none")
    disp = abs(diff)
    best_dec, best_am, best_book, best_line = None, None, None, None
    for bk in ("draftkings", "fanduel"):
        oa, od, opt = tot_offer(gid, bk, sel)
        if od is not None and (best_dec is None or od > best_dec):
            best_dec, best_am, best_book, best_line = od, oa, bk, opt
    dk_dec, fd_dec = tot_offer(gid, "draftkings", sel)[1], tot_offer(gid, "fanduel", sel)[1]
    n_offers = sum(1 for x in (dk_dec, fd_dec) if x is not None)
    n_better = sum(1 for x in (dk_dec, fd_dec) if x is not None and best_dec is not None and x > best_dec - 1e-9)
    tot_rows.append({
        "census_family": "TOTAL_R4", "game_id": gid, "season": season,
        "season_week": GAME_WEEK_MAP.get(gid),
        "split_label": "DISCOVERY" if season in DISC else "CONFIRMATION",
        "r4_predicted_total": pt_, "pinnacle_total_O": pin_line,
        "selected_side": sel, "disagreement_pts": disp,
        "act_line": best_line, "act_price": best_am, "act_book": best_book,
        "pinnacle_line": pin_line, "dk_decimal": dk_dec, "fd_decimal": fd_dec,
    })
tot_df = pl.DataFrame(tot_rows)
print("TOTAL R4 rows:", tot_df.height)

# ---------------------------------------------------------------------------
# 6. Consolidate into ONE wide parquet (union schema, per-family nulls ok)
# ---------------------------------------------------------------------------
_all_rows = []
for frame in (ml_pe, ml_diag, spr_df, tot_df):
    _all_rows.extend(frame.to_dicts())
_cols: list[str] = []
for row in _all_rows:
    for k in row:
        if k not in _cols:
            _cols.append(k)
_col_dict = {k: [r.get(k) for r in _all_rows] for k in _cols}
cat = pl.DataFrame(_col_dict)
cat.write_parquet(DATA_OUT / "market_edge_census_v1.parquet")
print("WRITE consolidated census parquet:", cat.shape, "columns:", len(cat.columns))

# ---------------------------------------------------------------------------
# 7. Quote freshness (sanity only; DK/FD/PIN)
# ---------------------------------------------------------------------------
fresh = bm.filter(pl.col("bookmaker_key").is_in(["draftkings", "fanduel", "pinnacle"])) \
    .with_columns(
        (pl.col("actual_snapshot_timestamp_utc").cast(pl.Datetime("us"))
         - pl.col("bookmaker_last_update_utc").cast(pl.Datetime("us"))).alias("age_usec")
    ).with_columns((pl.col("age_usec").cast(pl.Float64) / 3600_000_000.0).alias("age_hours")) \
    .filter(pl.col("age_hours").is_not_null()) \
    .group_by(["bookmaker_key", "market_key"]).agg(
        pl.col("age_hours").median().alias("median_age_h"), pl.col("age_hours").max().alias("max_age_h"),
        pl.col("age_hours").min().alias("min_age_h"), pl.col("age_hours").len().alias("n"))
print("FRESHNESS (median age hours by book/market):")
print(fresh)
fresh.write_csv(REPORTS / "task_05e_d3b_quote_freshness_v1.csv")
print("WROTE freshness CSV:", REPORTS / "task_05e_d3b_quote_freshness_v1.csv")

# also freshness within largest positive-edge moneyline bins (AVG 8+ pp)
age_by_book = bm.filter(pl.col("bookmaker_key").is_in(["draftkings", "fanduel", "pinnacle"])) \
    .with_columns((pl.col("actual_snapshot_timestamp_utc").cast(pl.Datetime("us"))
                   - pl.col("bookmaker_last_update_utc").cast(pl.Datetime("us"))).alias("age_usec")) \
    .with_columns((pl.col("age_usec").cast(pl.Float64) / 3600_000_000.0).alias("age_hours")) \
    .filter(pl.col("age_hours").is_not_null())
# age stats for the AVG 8+ positive-edge candidate games
pe8 = ml_pe.filter((pl.col("model") == "AVG") & (pl.col("edge_pp") >= 8))
pe8_ids = pe8["game_id"].unique().to_list()
pe8_fresh = bm.filter(pl.col("game_id").is_in(pe8_ids)) \
    .filter(pl.col("bookmaker_key").is_in(["draftkings", "fanduel", "pinnacle"])) \
    .with_columns((pl.col("actual_snapshot_timestamp_utc").cast(pl.Datetime("us"))
                   - pl.col("bookmaker_last_update_utc").cast(pl.Datetime("us"))).alias("age_usec")) \
    .with_columns((pl.col("age_usec").cast(pl.Float64) / 3600_000_000.0).alias("age_hours")) \
    .filter(pl.col("age_hours").is_not_null()) \
    .group_by(["bookmaker_key"]).agg(pl.col("age_hours").median().alias("median_age_h"),
                                     pl.col("age_hours").max().alias("max_age_h"),
                                     pl.col("age_hours").len().alias("n"))
print("FRESHNESS for AVG 8+pp positive-edge games (median age hours):")
print(pe8_fresh)

# ---------------------------------------------------------------------------
# 8. Provenance / safety proof
# ---------------------------------------------------------------------------
prov = {
    "production_head": "b8055348110ceb96933298e01b74d6b45afad89d",
    "r4_artifact": str(R4_ARTIFACT),
    "r4_manifest": str(R4_MANIFEST),
    "r4_artifact_bytes_sha256": "bb70ba29cad4e724aa7aacbebc59ccfff71e0794f5638dfdf173cdfec8",
    "r4_prediction_logical_hash_from_manifest": "b0cf9ad15293020e65f1f7c6fd4bedd659a150f6b86f31dfb375e111e3a67a79",
    "r4_candidate_id_used": "R4",
    "r4_alpha": 100,
    "r4_fit_performed_in_census": False,
    "observed_total_loaded": False,
    "seasons_2025_used": False,
    "scores_winners_ats_totals_loaded": False,
    "model_training_or_retuning_or_stacker": False,
    "odds_api_calls": False,
    "realized_hit_rate_roi_profit_calculated": False,
    "position_product_counts": {
        "ml_positive_edge_rows": ml_pe.height,
        "ml_two_sided_diag_rows": ml_diag.height,
        "spread_rows": spr_df.height,
        "total_r4_rows": tot_df.height,
    },
    "positivity_pathology": path_diag,
}
(REPORTS / "task_05e_d3b_census_provenance.json").write_text(json.dumps(prov, indent=2))
print("WROTE provenance:", REPORTS / "task_05e_d3b_census_provenance.json")

print("\n=== DONE building repaired census ===")