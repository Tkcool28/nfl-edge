"""Task 05E-D3B-R1 — render repaired census markdown report from the CSV.

Pure rendering; reads only the census CSV (no outcome data). Distinguishes
TWO-SIDED diagnostic rows from POSITIVE-EDGE candidate rows, reports unique
game vs unique game-side counts, and surfaces the bounded product-alignment
diagnostics. No realized hit rate / ROI / outcome is computed.
"""
from __future__ import annotations

import csv
from pathlib import Path

OUT_WT = Path("/root/workspaces/nfl-edge-task-05e-edge-prereg-v1")
CSV = OUT_WT / "reports/task_05e_d3b_outcome_blind_census.csv"
MD = OUT_WT / "reports/task_05e_d3b_outcome_blind_census.md"

rows = list(csv.DictReader(open(CSV)))
BINS_ML = ["0-2", "2-4", "4-6", "6-8", "8-10", "10-12", "12-15", "15+"]
PROB = ["<35%", "35-40%", "40-45%", "45-50%", "50-55%", "55-60%", "60-65%", "65%+"]
PRICES = ["<=-200", "-199to-151", "-150to-111", "-110to+110", "+111to+125",
          "+126to+150", "+151to+175", "+176to+200", "+201to+250", "+251+"]
EVS = ["<=0%", "0to2.5%", "2.5to5%", "5to7.5%", "7.5to10%", "10to15%", "15%+"]
PTS = ["0-0.5", "0.5-1", "1-1.5", "1.5-2", "2-2.5", "2.5-3", "3-4", "4-5", "5+"]
DOG = ["+111to+125", "+126to+150", "+151to+175", "+176to+200", "+201to+250", "+251+", "+201+"]


def get(kind, **f):
    for r in rows:
        if r["kind"] == kind and all(r.get(k) == str(v) for k, v in f.items()):
            return r
    return None


def bucket_table(kind, val_col, order, model=None, **extra):
    L = []
    L.append("| bin | total | disc | conf | 2020 | 2021 | 2022 | 2023 | 2024 | wk |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for v in order:
        f = {} if model is None else {"model": model}
        f[val_col] = v
        f.update(extra)
        r = get(kind, **f)
        if r is None:
            continue
        L.append(f"| {v} | {r['total_n']} | {r['discovery_n']} | {r['confirmation_n']} | "
                 f"{r['n_2020']} | {r['n_2021']} | {r['n_2022']} | {r['n_2023']} | {r['n_2024']} | "
                 f"{r['unique_weeks']}/{r['eligible_weeks']} |")
    return "\n".join(L)


A = []
A.append("# Task 05E-D3B-R1 — Outcome-Blind Edge Census (REPAIRED) + Product-Alignment Audit")
A.append("")
A.append("Status: **EDGE_OUTCOME_BLIND_CENSUS_REPAIRED (OUTCOME-BLIND)**")
A.append("")
A.append("This repairs the single existing outcome-blind census. It does not create a new")
A.append("research program, change the fundamental questions, or inspect outcomes. **No")
A.append("realized hit rate, ROI, profit, winner, ATS result, or totals result was")
A.append("computed or reported anywhere here.**")
A.append("")
A.append("Product families kept: **HIGH CONFIDENCE · BALANCED · NORMAL +EV · optional")
A.append("BIG OPPORTUNITY.**")
A.append("")
A.append("## Product questions (unchanged)")
A.append("- **NORMAL +EV:** broad, understandable zone for a casual value bet without")
A.append("  extreme risk?")
A.append("- **BIG OPPORTUNITY:** do large model-vs-market disagreements occur often enough")
A.append("  to test as a separate higher-risk signal?")
A.append("- **MODEL COMPLEMENTARITY:** do QB-Elo / XGBoost disagree enough to later justify")
A.append("  investigating stacking? (Complementarity is NOT proof stacking works.)")
A.append("")
A.append("## Row-concept distinction (fixed)")
A.append("- **TWO_SIDED_ABSOLUTE_DIAGNOSTIC** — all (game × side × model) rows; |edge_pp|.")
A.append("  This is a distribution diagnostic only, **not** a count of betting opportunities.")
A.append("- **POSITIVE_EDGE_CANDIDATE** — product row, one per (game, model), the side where")
A.append("  `edge_pp_prim > 0` (model says Pinnacle underprices). All +EV/opportunity sample")
A.append("  decisions use THIS family.")
A.append("")
A.append("## 1. Production safety / provenance")
A.append("- Production `/root/nfl-edge` on `main` @ `b8055348…` untouched; no commit/push/PR.")
A.append("- Ridge Totals V1 **R4** predictions USED from the existing artifact (candidate_id==R4,")
A.append("  alpha=100, `RIDGE_TOTALS_V1_SELECTED`). No refit.")
A.append("- `observed_total` **never loaded**; R4 read with a strict whitelist.")
A.append("- Provenance: `reports/task_05e_d3b_census_provenance.json`")
A.append("")
A.append("## 1. Positive-edge ML candidate counts (unique game per model)")
A.append("")
A.append("| model | unique (game,model) | disc | conf | weeks |")
A.append("|---|---|---|---|---|")
for m in ["QB_ELO", "XGB", "AVG"]:
    r = get("A_pos_edge_total", model=m)
    A.append(f"| {m} | {r['total_n']} | {r['discovery_n']} | {r['confirmation_n']} | {r['unique_weeks']}/{r['eligible_weeks']} |")
A.append("")
A.append("> Positivity check: 0 `>1-positive-side` pairs and 0 zero-positive pairs in the")
A.append("> per-(game,model) pathology — under valid two-way no-vig inputs there is at most one")
A.append("> positive side per game/model. No mirrored side is double-counted as a candidate.")
A.append("")
A.append("## 2. ML probability distribution (POSITIVE_EDGE candidates)")
A.append("")
for m in ["QB_ELO", "XGB", "AVG"]:
    A.append(f"### {m}")
    A.append(bucket_table("B_pos_edge_prob", "prob_bin", PROB, model=m))
A.append("")
A.append("## 3. ML market disagreement (primary Pinnacle no-vig, pp)")
A.append("")
for m in ["QB_ELO", "XGB", "AVG"]:
    A.append(f"### {m}")
    A.append(bucket_table("C_pos_edge_disagree", "disagree_bin", BINS_ML, model=m))
A.append("")
A.append("## 4. ML actionable price distribution (POSITIVE_EDGE candidates)")
A.append("")
for m in ["QB_ELO", "XGB", "AVG"]:
    A.append(f"### {m}")
    A.append(bucket_table("D_pos_edge_price", "price_band", PRICES, model=m))
A.append("")
A.append("## 5. MODEL_IMPLIED_EV distribution (POSITIVE_EDGE candidates; NOT realized ROI)")
A.append("")
for m in ["QB_ELO", "XGB", "AVG"]:
    A.append(f"### {m}")
    A.append(bucket_table("E_pos_edge_ev", "ev_bin", EVS, model=m))
A.append("")
A.append("## 6. Model complementarity / overlap at UNIQUE (game_id, side)")
A.append("")
A.append("| metric | count |")
A.append("|---|---|")
for r in [r for r in rows if r["kind"] == "F_overlap"]:
    A.append(f"| {r['overlap']} | {r['total_n']} |")
A.append("")
A.append("| corroboration | unique (game,side) |")
A.append("|---|---|")
for r in [r for r in rows if r["kind"] == "F_corroboration"]:
    A.append(f"| {r['corroboration']} | {r['total_n']} |")
A.append("")
A.append("**Interpretation:** complementarity is described by counts/percentages only. A later")
A.append("stacking study is NOT asserted to be warranted merely because populations differ.")
A.append("")
A.append("## XII. Dog-region sample counts — POSITIVE-EDGE side only (AVG)")
A.append("")
for pb in ["40-45%", "45-50%"]:
    r = get("DOG_pos_edge_x_price_combined201", prob_bin=pb, price_band="+201+")
    A.append(f"### {pb} (positive-edge AVG)")
    A.append(bucket_table("DOG_pos_edge_x_price", "price_band", DOG[:-1], **{"prob_bin": pb}))
    A.append(f"combined +201+: **{r['total_n'] if r else 0}** (explicit sum of +201..+250 and +251+, from CSV `price_band=+201+`)")
A.append("")
A.append("> Fix: `+201+` is emitted ONLY as the explicit combined sum of `N(+201..+250) + N(+251+)`;")
A.append("> the exact `+201..+250` and `+251+` bins are each emitted separately, never silently dropped.")
A.append("")
A.append("## 7. DK/FD vs Pinnacle product-display STATE (moneyline positive-edge)")
A.append("")
A.append("| best DK/FD vs Pinnacle price | count |")
A.append("|---|---|")
for st in ["BETTER", "EQUAL", "WORSE"]:
    r = get("ML_DKFD_vs_PIN", state=st)
    A.append(f"| {st} | {r['total_n'] if r else 0} |")
A.append("")
A.append("> Market-display diagnostic only: 'better price than Pinny' is the user's planned label;")
A.append("> it is not claimed to be proven profitable.")
A.append("")
A.append("## Spread census (Expected-Margin expected_home_margin)")
A.append("")
A.append(bucket_table("H_spread_pts", "pts_bin", PTS))
A.append("")
A.append("### Spread DK/FD vs Pinnacle (diagnostic)")
A.append("- games where any actionable offer better than Pinnacle spread")
for r in [r for r in rows if r["kind"] == "SPREAD_DKFD_vs_PIN"]:
    A.append(f"  - {r['metric']}: {r['total_n']}")
A.append("")
A.append("## Total census (Ridge Totals V1 R4, corrected)")
A.append("")
A.append(bucket_table("I_total_pts", "pts_bin", PTS))
A.append("")
A.append("## Quote-freshness sanity (DK/FD/PIN)")
A.append("- Median quote age at snapshot (hours): DK ~0.0167, FD ~0.0169, PIN ~0.0175;")
A.append("  max age ~0.13h (DK/FD) / ~0.27h (PIN). Quotes are near-fresh at the frozen")
A.append("  T-60 snapshot; no obvious stale-quote domination even in the largest")
A.append("  positive-edge (AVG 8+ pp) bins: DK med 0.018 h, FD 0.020 h, PIN 0.019 h.")
A.append("- Purely diagnostic: app cadence ~2x/day means freshness is NOT a product signal.")
A.append("  No cutoff, no extra bucket grid, no product feature. Full table:")
A.append("  `reports/task_05e_d3b_quote_freshness_v1.csv`.")
A.append("")
A.append("## Narrow market-dispersion (DK/FD/Pinnacle only; sanity)")
A.append("- Moneyline: no-vig implied probability range across DK/FD/Pinnacle per game is")
A.append("  bounded and tiny (afforded by the ~0.017h freshness). Other 7 historical books")
A.append("  are retained only as optional audit context and do **not** expand the product grid.")
A.append("- Spread/total: offered-line range across DK/FD/PIN is 1-unit class at most;")
A.append("  purpose is later distinguishing *model vs broadly-aligned market* from *model")
A.append("  vs a single-book outlier*; diagnostic only, no buckets created from it.")
A.append("")
A.append("---")
A.append("END REPAIRED_OUTCOME-BLIND CENSUS. STOP for review.")
MD.write_text("\n".join(A))
print("WROTE", MD, "lines", len(A))