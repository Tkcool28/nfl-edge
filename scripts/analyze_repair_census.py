"""Task 05E-D3B-R1 — analyze repaired census -> CSV + diagnostics.

Reads ONLY the repaired census parquet (contains no outcome columns).
Produces:
  reports/task_05e_d3b_outcome_blind_census.csv        (machine-readable)
  reports/task_05e_d3b_hypothesis_ledger_v1.csv        (prereg trial ledger)
Every product table carries total/discovery/confirmation/per-season/week
with invariant assertions. No realized hit rate / ROI / outcome is computed.
"""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl

OUT_WT = Path("/root/workspaces/nfl-edge-task-05e-edge-prereg-v1")
CENSUS = OUT_WT / "data/modeling/development_v1/market_edge_census_v1.parquet"
REPORT_CSV = OUT_WT / "reports/task_05e_d3b_outcome_blind_census.csv"
LEDGER = OUT_WT / "reports/task_05e_d3b_hypothesis_ledger_v1.csv"

DISC = [2020, 2021, 2022]
CONF = [2023, 2024]
SEASONS = [2020, 2021, 2022, 2023, 2024]
BINS_ML = ["0-2", "2-4", "4-6", "6-8", "8-10", "10-12", "12-15", "15+"]
PROB = ["<35%", "35-40%", "40-45%", "45-50%", "50-55%", "55-60%", "60-65%", "65%+"]
PRICES = ["<=-200", "-199to-151", "-150to-111", "-110to+110", "+111to+125",
          "+126to+150", "+151to+175", "+176to+200", "+201to+250", "+251+"]
EVS = ["<=0%", "0to2.5%", "2.5to5%", "5to7.5%", "7.5to10%", "10to15%", "15%+"]
PTS = ["0-0.5", "0.5-1", "1-1.5", "1.5-2", "2-2.5", "2.5-3", "3-4", "4-5", "5+"]
DOG_PRICE_BANDS = ["+111to+125", "+126to+150", "+151to+175", "+176to+200", "+201to+250", "+251+"]
ELIGIBLE_WEEKS = 109  # distinct (season, season_week) across 2020-2024 canonical


def prob_bin(p):
    if p is None: return None
    e = int(round(p * 100))
    if e < 35: return "<35%"
    if e < 40: return "35-40%"
    if e < 45: return "40-45%"
    if e < 50: return "45-50%"
    if e < 55: return "50-55%"
    if e < 60: return "55-60%"
    if e < 65: return "60-65%"
    return "65%+"


def ml_disagree_bin(pp):
    if pp is None: return None
    v = abs(pp)
    if v < 2: return "0-2"
    if v < 4: return "2-4"
    if v < 6: return "4-6"
    if v < 8: return "6-8"
    if v < 10: return "8-10"
    if v < 12: return "10-12"
    if v < 15: return "12-15"
    return "15+"


def price_bin(am):
    if am is None: return None
    a = float(am)
    if a <= -200: return "<=-200"
    if a < -150: return "-199to-151"
    if a < -110: return "-150to-111"
    if a < 110: return "-110to+110"
    if a < 125: return "+111to+125"
    if a < 150: return "+126to+150"
    if a < 175: return "+151to+175"
    if a < 200: return "+176to+200"
    if a < 250: return "+201to+250"
    return "+251+"


def ev_bin(v):
    if v is None: return None
    if v <= 0: return "<=0%"
    if v < 0.025: return "0to2.5%"
    if v < 0.05: return "2.5to5%"
    if v < 0.075: return "5to7.5%"
    if v < 0.10: return "7.5to10%"
    if v < 0.15: return "10to15%"
    return "15%+"


def pts_bin(v):
    if v is None: return None
    v = abs(v)
    if v < 0.5: return "0-0.5"
    if v < 1: return "0.5-1"
    if v < 1.5: return "1-1.5"
    if v < 2: return "1.5-2"
    if v < 2.5: return "2-2.5"
    if v < 3: return "2.5-3"
    if v < 4: return "3-4"
    if v < 5: return "4-5"
    return "5+"


cat = pl.read_parquet(CENSUS)
pe = cat.filter(pl.col("census_family") == "POSITIVE_EDGE_CANDIDATE").to_dicts()
diag = [r for r in cat.filter(pl.col("census_family") == "TWO_SIDED_ABSOLUTE_DIAGNOSTIC").to_dicts()]
spr = cat.filter(pl.col("census_family") == "SPREAD").to_dicts()
totr = cat.filter(pl.col("census_family") == "TOTAL_R4").to_dicts()

ROWS: list[dict] = []


def emit(kind, dims, rows):
    total = len(rows)
    disc = sum(1 for r in rows if r.get("season") in DISC)
    conf = sum(1 for r in rows if r.get("season") in CONF)
    assert disc + conf == total, f"{kind} {dims} disc+conf!=total"
    per = {s: sum(1 for r in rows if r.get("season") == s) for s in SEASONS}
    assert sum(per.values()) == total, f"{kind} {dims} per-season sum != total"
    weeks = len({(r.get("season"), r.get("season_week")) for r in rows if r.get("season_week")})
    rec = {"kind": kind, **dims, "total_n": total, "discovery_n": disc,
           "confirmation_n": conf, "n_2020": per[2020], "n_2021": per[2021],
           "n_2022": per[2022], "n_2023": per[2023], "n_2024": per[2024],
           "unique_weeks": weeks, "eligible_weeks": ELIGIBLE_WEEKS}
    ROWS.append(rec)


def by_dim(frame_rows, dim):
    return frame_rows  # pass-through; caller filters


# ------------------------------------------------------------------
# A-C. positive-edge candidate distributions (product focused)
# ------------------------------------------------------------------
for m in ["QB_ELO", "XGB", "AVG"]:
    sub = [r for r in pe if r["model"] == m]
    emit("A_pos_edge_total", {"model": m}, sub)
    assert len({r["game_id"] for r in sub}) == len(sub), f"model {m} not unique per game"

for m in ["QB_ELO", "XGB", "AVG"]:
    for b in PROB:
        sub = [r for r in pe if r["model"] == m and prob_bin(r["p_model"]) == b]
        emit("B_pos_edge_prob", {"model": m, "prob_bin": b}, sub)

for m in ["QB_ELO", "XGB", "AVG"]:
    for b in BINS_ML:
        sub = [r for r in pe if r["model"] == m and ml_disagree_bin(r["edge_pp"]) == b]
        emit("C_pos_edge_disagree", {"model": m, "disagree_bin": b}, sub)

for m in ["QB_ELO", "XGB", "AVG"]:
    for b in PRICES:
        sub = [r for r in pe if r["model"] == m and price_bin(r["actionable_american"]) == b]
        emit("D_pos_edge_price", {"model": m, "price_band": b}, sub)

for m in ["QB_ELO", "XGB", "AVG"]:
    for b in EVS:
        sub = [r for r in pe if r["model"] == m and ev_bin(r["model_implied_ev"]) == b]
        emit("E_pos_edge_ev", {"model": m, "ev_bin": b}, sub)

# ------------------------------------------------------------------
# F. complementarity / overlap at unique (game_id, side)
# ------------------------------------------------------------------
pe_sides = pl.DataFrame(pe).select(["game_id", "side", "model"]).unique()


def sides_for(model):
    return set((r["game_id"], r["side"]) for r in pe_sides.iter_rows(named=True) if r["model"] == model)


S_QB = sides_for("QB_ELO")
S_XGB = sides_for("XGB")
S_AVG = sides_for("AVG")
ove = {
    "QB_ELO": len(S_QB), "XGB": len(S_XGB), "AVG": len(S_AVG),
    "QB_cap_XGB": len(S_QB & S_XGB),
    "QB_cap_AVG": len(S_QB & S_AVG),
    "XGB_cap_AVG": len(S_XGB & S_AVG),
    "QB_cap_XGB_cap_AVG": len(S_QB & S_XGB & S_AVG),
    "QB_ELO_ONLY": len(S_QB - S_XGB - S_AVG),
    "XGB_ONLY": len(S_XGB - S_QB - S_AVG),
    "AVG_ONLY": len(S_AVG - S_QB - S_XGB),
    "BOTH_QB_XGB_share": round(len(S_QB & S_XGB) / max(1, len(S_QB | S_XGB)), 4),
    "jaccard_QB_XGB": round(len(S_QB & S_XGB) / max(1, len(S_QB | S_XGB)), 4),
}
for k, v in ove.items():
    if isinstance(v, int):
        ROWS.append({"kind": "F_overlap", "overlap": k, "total_n": v})
for k in ("BOTH_QB_XGB_share", "jaccard_QB_XGB"):
    ROWS.append({"kind": "F_overlap", "overlap": k, "total_n": ove[k]})

# corrob / qb-only / xgb-only unique (game,side) via QB & XGB intersection
both = S_QB & S_XGB
ROWS.extend([
    {"kind": "F_corroboration", "corroboration": "BOTH_MODELS_CORROBORATE", "total_n": len(both)},
    {"kind": "F_corroboration", "corroboration": "QB_ELO_ONLY", "total_n": len(S_QB - S_XGB)},
    {"kind": "F_corroboration", "corroboration": "XGB_ONLY", "total_n": len(S_XGB - S_QB)},
])

# ------------------------------------------------------------------
# XII. dog-region limited to POSITIVE-EDGE candidates (AVG), +201 fix
# ------------------------------------------------------------------
avg_pe = [r for r in pe if r["model"] == "AVG"]
for pb in ["40-45%", "45-50%"]:
    sub = [r for r in avg_pe if prob_bin(r["p_model"]) == pb]
    emit("DOG_pos_edge_prob", {"prob_bin": pb}, sub)
    for b in BINS_ML:
        s2 = [r for r in sub if ml_disagree_bin(r["edge_pp"]) == b]
        emit("DOG_pos_edge_x_disagree", {"prob_bin": pb, "disagree_bin": b}, s2)
    # NOTE: exact band +201to+250 and +251+ emitted separately, never silently
    # merged; a combined +201+ is also emitted as the explicit sum.
    for band in DOG_PRICE_BANDS:
        s3 = [r for r in sub if price_bin(r["actionable_american"]) == band]
        emit("DOG_pos_edge_x_price", {"prob_bin": pb, "price_band": band}, s3)
    combined = [r for r in sub if price_bin(r["actionable_american"]) in ("+201to+250", "+251+")]
    emit("DOG_pos_edge_x_price_combined201", {"prob_bin": pb, "price_band": "+201+"}, combined)

# ------------------------------------------------------------------
# 6. DK/FD vs Pinnacle display state (positive-edge moneyline)
# ------------------------------------------------------------------
for r in pe:
    side = r["side"]
    pinn = r.get("pinnacle_decimal")
    best = r.get("actionable_decimal")
    state = None
    if best is not None and pinn is not None:
        if best > pinn + 1e-9:
            state = "BETTER"
        elif abs(best - pinn) <= 1e-9:
            state = "EQUAL"
        else:
            state = "WORSE"
    r["_dk_fd_vs_pin_state"] = state
for st in ["BETTER", "EQUAL", "WORSE"]:
    sub = [r for r in pe if r.get("_dk_fd_vs_pin_state") == st]
    emit("ML_DKFD_vs_PIN", {"state": st}, sub)

# ------------------------------------------------------------------
# spread / total alignment + dispersion (DK/FD vs Pinnacle)
# ------------------------------------------------------------------
for b in PTS:
    sub = [r for r in spr if pts_bin(r["disagreement_pts"]) == b]
    emit("H_spread_pts", {"pts_bin": b}, sub)
for s in ["home", "away"]:
    for b in PTS:
        sub = [r for r in spr if r["selected_side"] == s and pts_bin(r["disagreement_pts"]) == b]
        emit("H2_spread_side", {"selected_side": s, "pts_bin": b}, sub)
# spread DK/FD vs PIN price states (bounded diagnostic) — from stored fields
n_better = sum(1 for r in spr if (r.get("n_better_than_pinnacle") or 0) > 0)
n_off = sum(1 for r in spr if (r.get("n_offers_with_pinnacle") or 0) > 0)
nb0 = sum(1 for r in spr if (r.get("n_better_than_pinnacle") or 0) == 0)
ROWS.append({"kind": "SPREAD_DKFD_vs_PIN", "metric": "num_offers_with_pinnacle", "total_n": n_off})
ROWS.append({"kind": "SPREAD_DKFD_vs_PIN", "metric": "games_any_actionable_better_than_pinnacle", "total_n": n_better})
ROWS.append({"kind": "SPREAD_DKFD_vs_PIN", "metric": "games_no_actionable_better_than_pinnacle", "total_n": nb0})

# totals
for b in PTS:
    sub = [r for r in totr if pts_bin(r["disagreement_pts"]) == b]
    emit("I_total_pts", {"pts_bin": b}, sub)
for s in ["over", "under"]:
    for b in PTS:
        sub = [r for r in totr if r["selected_side"] == s and pts_bin(r["disagreement_pts"]) == b]
        emit("I2_total_side", {"selected_side": s, "pts_bin": b}, sub)

# ------------------------------------------------------------------
# quote freshness (sanity) - separate summary
# ------------------------------------------------------------------
# (freshness already computed in build; record here for ledger)

# write CSV (robust union via stdlib csv — mixed int/float/None safe)
import csv as _csv
_all_keys = []
for r in ROWS:
    for k in r:
        if k not in _all_keys:
            _all_keys.append(k)
with open(REPORT_CSV, "w", newline="") as fh:
    w = _csv.DictWriter(fh, fieldnames=_all_keys, extrasaction="ignore")
    w.writeheader()
    for r in ROWS:
        w.writerow(r)
print("WROTE CSV:", REPORT_CSV, "rows", len(ROWS))

# ------------------------------------------------------------------
# hypothesis ledger
# ------------------------------------------------------------------
ledger_rows = [
    {"hypothesis_id": "ML_QBELO_DISAGREEMENT", "family": "ML_disagreement", "desc": "QB-Elo edge over Pinnacle no-vig; positive-edge side", "model": "QB_ELO", "frozen": True},
    {"hypothesis_id": "ML_XGB_DISAGREEMENT", "family": "ML_disagreement", "desc": "XGBoost edge over Pinnacle no-vig; positive-edge side", "model": "XGB", "frozen": True},
    {"hypothesis_id": "ML_AVG_DISAGREEMENT", "family": "ML_disagreement", "desc": "50/50-avg edge over Pinnacle no-vig; positive-edge side", "model": "AVG", "frozen": True},
    {"hypothesis_id": "ML_CORROBORATED_DISAGREEMENT", "family": "ML_disagreement", "desc": "QB_ELO & XGB both positive edge same side", "model": "BOTH", "frozen": True},
    {"hypothesis_id": "ML_DOG_VALUE_ZONE", "family": "dog_zone", "desc": "40-45% 45-50% positive-edge side at plus-money price", "model": "AVG", "frozen": True},
    {"hypothesis_id": "SPREAD_DISAGREEMENT", "family": "point_disagreement", "desc": "expected_margin vs spread line", "model": "expected_margin", "frozen": True},
    {"hypothesis_id": "TOTAL_R4_DISAGREEMENT", "family": "point_disagreement", "desc": "Ridge Totals R4 vs total line (over/under)", "model": "ridge_R4", "frozen": True},
]
pl.from_dicts(ledger_rows).write_csv(LEDGER)
print("WROTE LEADER:", LEDGER)
print("CSV rows:", len(ROWS))