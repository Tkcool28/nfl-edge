#!/usr/bin/env python3
"""Task05F v2 scorecard + diagnostics -> Section R artifacts.

Usage: candidate_v2_score.py <run_dir> <artifact_prefix>
Reads <run_dir>/candidate_full_board.parquet (+ _push_counts.json) and writes
  <prefix>_scorecard.json/.md, <prefix>_ev_calibration.csv,
  <prefix>_frozen_edge_preservation.json, <prefix>_coherence.json,
  <prefix>_tail_diagnostics.json
into /tmp/task05f-redesign-v2/.

Conventions (prereg):
- probability metrics (Brier/logloss/AUC/calibration): rows with p present and y in {0,1}
- realized ROI: rows with p present; y=1 -> dec-1, y=0 -> -1, y None (push) -> 0
- value definition: EV>0 positive, EV=0 fair, EV<0 negative (no threshold)
"""
from __future__ import annotations

import json
import sys

import numpy as np
import polars as pl
from scipy.stats import kendalltau
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

RUN = sys.argv[1] if len(sys.argv) > 1 else "/tmp/task05f-redesign-v2/run1"
PREFIX = sys.argv[2] if len(sys.argv) > 2 else "candidate"
OUTD = "/tmp/task05f-redesign-v2"
D = pl.read_parquet(f"{RUN}/candidate_full_board.parquet")
PUSH = json.load(open(f"{RUN}/_push_counts.json"))

EV_BANDS = [(-9.0, 0.0, "<=0%"), (0.0, 0.02, "0-2%"), (0.02, 0.05, "2-5%"),
            (0.05, 0.10, "5-10%"), (0.10, 99.0, ">10%")]


def realized(d: pl.DataFrame) -> dict:
    """Realized wagering outcome incl. pushes as 0-unit return (prereg K)."""
    d = d.filter(pl.col("p").is_not_null())
    if d.height == 0:
        return {"n": 0}
    pa = np.asarray(d["price_american"], float)
    dec = 1.0 + np.where(pa > 0, pa / 100.0, 100.0 / np.abs(pa))
    y = np.asarray([(-1 if v is None else int(v)) for v in d["y"]])  # -1 encodes push->0
    profit = np.where(y == 1, dec - 1.0, np.where(y == 0, -1.0, 0.0))
    return {"n": int(d.height), "hits": int((y == 1).sum()), "pushes": int((y == -1).sum()),
            "profit": round(float(profit.sum()), 2), "roi": round(float(profit.mean()), 4)}


def roi_of(r):
    return r.get("roi") if r and r.get("n") else None


def prob_metrics(d: pl.DataFrame) -> dict:
    d = d.filter(pl.col("p").is_not_null() & pl.col("y").is_in([0, 1]))
    if d.height == 0:
        return {"n": 0}
    p = np.asarray(d["p"], float)
    y = np.asarray(d["y"], int)
    pc = np.clip(p, 1e-6, 1 - 1e-6)
    out = {"n": int(d.height),
           "brier": round(float(np.mean((p - y) ** 2)), 6),
           "logloss": round(float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc))), 6)}
    try:
        auc = float(roc_auc_score(y, p))
        out["auc"] = round(auc, 6)
    except Exception:
        out["auc"] = None
    if len(set(y.tolist())) >= 2:
        cal = LogisticRegression(C=1e6, max_iter=2000).fit(np.log(pc / (1 - pc)).reshape(-1, 1), y)
        out["cal_intercept"] = round(float(cal.intercept_[0]), 6)
        out["cal_slope"] = round(float(cal.coef_[0][0]), 6)
    else:
        out["cal_intercept"] = out["cal_slope"] = None
    out["mean_p"] = round(float(p.mean()), 6)
    out["std_p"] = round(float(p.std(ddof=1)), 6) if d.height > 1 else None
    return out


def r0(v):
    return None if v is None else round(float(v), 4)


SC = {}
for mt in ("moneyline", "spread", "total"):
    SC[mt] = {}
    dm = D.filter(pl.col("market_type") == mt)
    for fam in sorted(dm["family"].unique().to_list()):
        d = dm.filter(pl.col("family") == fam)
        entry = {"probability_metrics": prob_metrics(d),
                 "wagering_all": realized(d)}
        dp = d.filter(pl.col("p").is_not_null())
        pos = dp.filter(pl.col("ev_unit") > 0)
        nonpos = dp.filter(pl.col("ev_unit") <= 0)
        entry["posEV"] = {**realized(pos),
                          "mean_pred_ev": r0(pos["ev_unit"].mean()) if pos.height else None}
        entry["nonposEV"] = {**realized(nonpos),
                             "mean_pred_ev": r0(nonpos["ev_unit"].mean()) if nonpos.height else None}
        bands = []
        for lo, hi, lab in EV_BANDS:
            b = dp.filter((pl.col("ev_unit") > lo) & (pl.col("ev_unit") <= hi))
            rr = {"band": lab, **realized(b),
                  "mean_pred_ev": r0(b["ev_unit"].mean()) if b.height else None}
            bands.append(rr)
        entry["ev_bands"] = bands
        if mt == "moneyline" and fam == "reliability_aware_shrinkage_v2":
            vc = dp.group_by("reliability").len().sort("reliability").to_dicts()
            entry["reliability_distribution"] = {r_["reliability"]: r_["len"] for r_ in vc}
            unc = np.asarray([u for u in dp["uncertainty"].to_list() if u is not None], float)
            entry["uncertainty_summary"] = (
                {"n": int(unc.size), "mean": r0(unc.mean()), "p50": r0(np.percentile(unc, 50)),
                 "p90": r0(np.percentile(unc, 90)), "max": r0(unc.max())} if unc.size else None)
            # sign diagnostics vs p_market
            res = np.asarray(dp["residual"], float)
            pmk = np.asarray(dp["p_market"], float)
            eg = np.asarray(dp["p"], float) - pmk
            pos_raw = res > 1e-12
            neg_raw = res < -1e-12
            preserved = int(((eg > 1e-12) & pos_raw).sum() + ((eg < -1e-12) & neg_raw).sum())
            neutral = int(((np.abs(eg) <= 1e-12) & (pos_raw | neg_raw)).sum())
            reversed_ = int(((eg < -1e-12) & pos_raw).sum() + ((eg > 1e-12) & neg_raw).sum())
            comp = np.abs(eg) / np.maximum(np.abs(res), 1e-12)
            entry["sign_diagnostics"] = {
                "n_supported": int(dp.height),
                "sign_preserved_pct": round(100.0 * preserved / max(1, preserved + neutral + reversed_), 4),
                "neutralized_pct": round(100.0 * neutral / max(1, preserved + neutral + reversed_), 4),
                "reversed_pct": round(100.0 * reversed_ / max(1, preserved + neutral + reversed_), 4)}
            entry["compression_ratio"] = {
                "mean": r0(comp.mean()), "p10": r0(np.percentile(comp, 10)),
                "p25": r0(np.percentile(comp, 25)), "median": r0(np.median(comp)),
                "p75": r0(np.percentile(comp, 75)), "p90": r0(np.percentile(comp, 90))}
            fw = np.asarray([w for w in dp["final_weight"].to_list() if w is not None], float)
            entry["final_weight_summary"] = (
                {"mean": r0(fw.mean()), "p25": r0(np.percentile(fw, 25)),
                 "median": r0(np.median(fw)), "p75": r0(np.percentile(fw, 75))} if fw.size else None)
            # staking separability (M): ordering agreement actionable vs staking
            sp_rows = dp.filter(pl.col("staking_p").is_not_null())
            if sp_rows.height > 2:
                tau = kendalltau(np.asarray(sp_rows["p"], float), np.asarray(sp_rows["staking_p"], float))
                entry["staking_separability"] = {
                    "n": int(sp_rows.height), "kendall_tau": r0(tau.statistic),
                    "identical_ordering": bool(abs(tau.statistic - 1.0) < 1e-12)}
            else:
                entry["staking_separability"] = {"n": int(sp_rows.height)}
        SC[mt][fam] = entry

# ---- EV calibration CSV ----
rows_csv = ["market_type,family,ev_band,n,mean_pred_ev,hit_rate,roi"]
for mt in SC:
    for fam in SC[mt]:
        for b in SC[mt][fam]["ev_bands"]:
            rows_csv.append(f"{mt},{fam},{b['band']},{b['n']},"
                            f"{'' if b['mean_pred_ev'] is None else b['mean_pred_ev']},"
                            f"{round(b['hits'] / b['n'], 4) if b.get('n') else ''},"
                            f"{'' if b.get('roi') is None else b['roi']}")
open(f"{OUTD}/{PREFIX}_ev_calibration.csv", "w").write("\n".join(rows_csv) + "\n")

# ---- frozen edge preservation ----
WTV = "/root/workspaces/nfl-edge-task05f-validation"
both = pl.concat([
    pl.read_parquet(WTV + "/reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.parquet"),
    pl.read_parquet(WTV + "/reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.parquet")])


def frozen_join(led_mt, mem_f):
    mem = both.filter(mem_f).select(["game_id", "season", "selected_side", "bucket"])
    led_all = (D.filter(pl.col("market_type") == led_mt)
               .select(["game_id", "family", "side", "p", "y", "ev_unit", "break_even",
                        "price_american", "line"]).rename({"side": "t_side"}))
    j = mem.join(led_all, on="game_id", how="inner").filter(pl.col("selected_side") == pl.col("t_side"))
    base = mem.join(led_all.drop(["family"]), on="game_id", how="inner").filter(
        pl.col("selected_side") == pl.col("t_side")).unique(subset=["game_id", "selected_side"])
    out = {"baseline_N": mem.height, "baseline_roi_realized_at_offered_prices": roi_of(realized(base))}
    for fam in sorted(j["family"].unique().to_list()):
        jf = j.filter(pl.col("family") == fam)
        pos = jf.filter(pl.col("ev_unit") > 0)
        rej = jf.filter(pl.col("ev_unit") <= 0)
        nosup = jf.filter(pl.col("p").is_null())
        entry = {"joined": jf.height,
                 "no_actionable_probability_N": nosup.height,
                 "posEV_N": pos.height, "posEV_roi": roi_of(realized(pos)),
                 "rejected_N": rej.height, "rejected_roi": roi_of(realized(rej)),
                 "mean_actionable_p": r0(jf.filter(pl.col("p").is_not_null())["p"].mean()),
                 "mean_break_even": r0(jf.filter(pl.col("p").is_not_null())["break_even"].mean()),
                 "mean_pred_ev": r0(jf.filter(pl.col("p").is_not_null())["ev_unit"].mean())}
        per_season = {}
        for s in sorted(jf["season"].unique().to_list()):
            ss = jf.filter(pl.col("season") == s)
            pp = ss.filter(pl.col("ev_unit") > 0)
            rr = ss.filter(pl.col("ev_unit") <= 0)
            per_season[str(int(s))] = {"kept_n": pp.height, "kept_roi": roi_of(realized(pp)),
                                       "rejected_n": rr.height, "rejected_roi": roi_of(realized(rr))}
        entry["per_season"] = per_season
        if "bucket" in jf.columns:
            per_bucket = {}
            for bk in sorted(set(x for x in jf["bucket"].to_list() if x is not None)):
                jb = jf.filter(pl.col("bucket") == bk)
                pb = jb.filter(pl.col("ev_unit") > 0)
                rb = jb.filter(pl.col("ev_unit") <= 0)
                per_bucket[bk] = {"N": jb.height, "posEV_N": pb.height,
                                  "posEV_roi": roi_of(realized(pb)),
                                  "rejected_N": rb.height, "rejected_roi": roi_of(realized(rb))}
            entry["per_frozen_bucket"] = per_bucket
        out[fam] = entry
    return out


FE = {}
FE["SPREAD_0_4"] = frozen_join("spread",
    (pl.col("family") == "SPREAD_DISAGREEMENT") & (pl.col("model") == "EXPECTED_MARGIN")
    & pl.col("bucket").is_in(["0-1", "1-2", "2-3", "3-4"]))
FE["ML_DOG_VALUE_ZONE_AVG"] = frozen_join("moneyline",
    (pl.col("family") == "ML_DOG_VALUE_ZONE") & (pl.col("model") == "AVG"))
FE["ML_CORROBORATED_DOG"] = frozen_join("moneyline",
    (pl.col("family") == "ML_DOG_VALUE_ZONE") & (pl.col("model") == "CORROB"))
FE["ML_AVG_0_2"] = frozen_join("moneyline",
    (pl.col("family") == "ML_AVG_DISAGREEMENT") & (pl.col("bucket") == "0-2"))
json.dump(FE, open(f"{OUTD}/{PREFIX}_frozen_edge_preservation.json", "w"), indent=1, sort_keys=True)

# ---- coherence ----
def dev_stats(a):
    a = np.abs(np.asarray(a, float))
    return {"n": int(a.size), "mean_abs_dev": r0(a.mean()) if a.size else None,
            "max_abs_dev": r0(a.max()) if a.size else None, "gt_0.01": int((a > 0.01).sum())}


COH = {}


def pair_frame(mt):
    d = D.filter(pl.col("market_type") == mt)
    s1, s2 = (("home", "away") if mt != "total" else ("over", "under"))
    if mt != "moneyline":
        a = d.filter(pl.col("side") == s1).select(["game_id", "family", "line", "p", "ev_unit", "break_even"]).rename(
            {"line": "l1", "p": "p1", "ev_unit": "e1", "break_even": "b1"})
        b = d.filter(pl.col("side") == s2).select(["game_id", "family", "line", "p", "ev_unit", "break_even"]).rename(
            {"line": "l2", "p": "p2", "ev_unit": "e2", "break_even": "b2"})
        j = a.join(b, on=["game_id", "family"])
        key = (pl.col("l1") + pl.col("l2")).abs() < 1e-9 if mt == "spread" else (pl.col("l1") - pl.col("l2")).abs() < 1e-9
        return j.filter(key)
    a = d.filter(pl.col("side") == s1).select(["game_id", "family", "p", "ev_unit", "break_even"]).rename(
        {"p": "p1", "ev_unit": "e1", "break_even": "b1"})
    b = d.filter(pl.col("side") == s2).select(["game_id", "family", "p", "ev_unit", "break_even"]).rename(
        {"p": "p2", "ev_unit": "e2", "break_even": "b2"})
    return a.join(b, on=["game_id", "family"])


for mt in ("moneyline", "spread", "total"):
    jj = pair_frame(mt)
    for fam in sorted(jj["family"].unique().to_list()):
        COH[f"{mt}/{fam}"] = dev_stats(jj.filter(pl.col("family") == fam)
                                       .with_columns((pl.col("p1") + pl.col("p2") - 1.0).alias("dev"))["dev"])
COH["both_sides_posEV"] = {}
for mt in ("moneyline", "spread", "total"):
    jj = pair_frame(mt)
    for fam in sorted(jj["family"].unique().to_list()):
        jf = jj.filter(pl.col("family") == fam)
        COH["both_sides_posEV"][f"{mt}/{fam}"] = int(jf.filter(
            (pl.col("e1") > 0) & (pl.col("p1") > pl.col("b1"))
            & (pl.col("e2") > 0) & (pl.col("p2") > pl.col("b2"))).height)
json.dump(COH, open(f"{OUTD}/{PREFIX}_coherence.json", "w"), indent=1, sort_keys=True)

# ---- tail diagnostics (F): >10%% predicted-EV deep-dive per ML family ----
TAIL = {}
for fam in ("global_shrinkage", "partial_shrinkage_floor", "reliability_aware_shrinkage_v2"):
    d = D.filter((pl.col("market_type") == "moneyline") & (pl.col("family") == fam)).filter(
        pl.col("p").is_not_null() & (pl.col("ev_unit") > 0.10))
    e = {"n": int(d.height)}
    if d.height:
        pa = np.asarray(d["price_american"], float)
        dec = 1.0 + np.where(pa > 0, pa / 100.0, 100.0 / np.abs(pa))
        yy = [(-1 if v is None else int(v)) for v in d["y"]]
        profit = np.where(np.asarray(yy) == 1, dec - 1.0, np.where(np.asarray(yy) == 0, -1.0, 0.0))
        e.update({
            "roi_with_pushes_zero": r0(profit.mean()),
            "n_binary": int(sum(1 for v in yy if v >= 0)),
            "price_min": int(pa.min()), "price_p25": r0(np.percentile(pa, 25)),
            "price_median": r0(np.median(pa)), "price_p75": r0(np.percentile(pa, 75)),
            "price_max": int(pa.max()),
            "mean_abs_price": r0(np.abs(pa).mean()),
            "mean_p_market": r0(d["p_market"].mean()), "mean_p_model": r0(d["p_model"].mean()),
            "mean_actionable_p": r0(d["p"].mean()),
            "mean_abs_residual": r0(d["residual"].abs().mean()),
            "mean_qb_xgb_disagreement": r0(d["disag"].mean()),
            "mean_uncertainty": r0(np.nanmean(np.asarray(
                [np.nan if u is None else u for u in d["uncertainty"].to_list()], float))),
            "realized_by_reliability": {
                r_["reliability"]: {"n": r_["len"]} for r_ in d.group_by("reliability").len().sort("reliability").to_dicts()},
        })
        rel_profit = {}
        rels = np.asarray([("" if v is None else v) for v in d["reliability"].to_list()])
        for rl in sorted(set(rels)):
            msk = rels == rl
            rel_profit[rl or "NONE"] = {"n": int(msk.sum()), "roi": r0(profit[msk].mean())}
        e["roi_by_reliability"] = rel_profit
        if fam == "reliability_aware_shrinkage_v2":
            fw = np.asarray([w for w in d["final_weight"].to_list() if w is not None], float)
            e["mean_final_weight"] = r0(fw.mean()) if fw.size else None
    TAIL[fam] = e
json.dump(TAIL, open(f"{OUTD}/{PREFIX}_tail_diagnostics.json", "w"), indent=1, sort_keys=True)

# ---- spread band counts on the board ----
spr = D.filter(pl.col("market_type") == "spread").unique(subset=["game_id", "side"])
BAND_COUNTS = {}
lv = np.asarray(spr["market_level"], float)
for name, msk in (("0_lt3", lv < 3), ("3_lt7", (lv >= 3) & (lv < 7)), ("7_plus", lv >= 7)):
    BAND_COUNTS[name] = int(msk.sum())

# ---- scorecard.md ----
md = ["# Task05F Redesign V2 Candidate Scorecard", "",
      f"Run dir: `{RUN}`", f"Push counts: `{json.dumps(PUSH, sort_keys=True)}`",
      f"Board spread band counts (per selected-side rows): `{json.dumps(BAND_COUNTS, sort_keys=True)}`", ""]
for mt in ("moneyline", "spread", "total"):
    md += [f"## {mt}", "", "| family | n | brier | logloss | auc | std_p | posEV_n | posEV_roi | rej_n | rej_roi |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for fam, e in sorted(SC[mt].items()):
        pm = e["probability_metrics"]
        pe, ne = e["posEV"], e["nonposEV"]
        md.append(f"| {fam} | {pm.get('n', 0)} | {pm.get('brier')} | {pm.get('logloss')} | {pm.get('auc')} | "
                  f"{pm.get('std_p')} | {pe.get('n', 0)} | {pe.get('roi')} | {ne.get('n', 0)} | {ne.get('roi')} |")
    md.append("")
json.dump(SC, open(f"{OUTD}/{PREFIX}_scorecard.json", "w"), indent=1, sort_keys=True)
open(f"{OUTD}/{PREFIX}_scorecard.md", "w").write("\n".join(md) + "\n")
print(json.dumps({"bands": BAND_COUNTS, "push": PUSH}, sort_keys=True))
