"""Task 04D Chunk 4 analysis: paired diagnostics, season stability,
transition forensics, and candidate-adjudication evidence.

READ-ONLY analysis over the frozen Chunk 3 official artifacts
(``data/derived/qb_elo_season_regression_v1/``). Does NOT modify model
behavior or the official prediction artifacts; only writes new derived
analysis tables/reports.

Implements a bounded paired bootstrap (game-paired and season-cluster) with
deterministic settings, following the repository's prior XGBoost blocked-
bootstrap reporting convention (percentile_2_5/97_5, proportion_favoring).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from nfl_edge.backtest.task04d_season_regression_evaluation import CANDIDATE_LABELS

SEASONS_ALL = [2018, 2019, 2020, 2021, 2022, 2023, 2024]
SEASONS_REGRESSION_ELIGIBLE = [2019, 2020, 2021, 2022, 2023, 2024]
BOOTSTRAP_SEED = 20260810
BOOTSTRAP_N = 5000
_TOL = 1e-6
POST_SEASON_TYPES = {"WC", "DIV", "CON", "SB"}
LABEL_SHORT = {
    "regression_000": "0%",
    "regression_025": "25%",
    "regression_040": "40%",
    "regression_060": "60%",
    "task04c_reference_0333": "33.3%",
}


def load(root: Path) -> dict[str, pl.DataFrame]:
    return {
        lab: pl.read_parquet(root / f"predictions_{lab}.parquet") for lab in CANDIDATE_LABELS
    }


def core_arrays(arts: dict[str, pl.DataFrame]):
    base = arts["regression_000"]
    game_id = base["game_id"].to_list()
    seasons = np.asarray(base["season"].to_list(), dtype=int)
    weeks = np.asarray(base["week"].to_list(), dtype=int)
    stype = np.asarray(base["season_type"].to_list())
    y = np.asarray(base["target_outcome"].to_list(), dtype=float)
    p = {
        lab: np.asarray(arts[lab]["predicted_home_win_probability"].to_list(), dtype=float)
        for lab in CANDIDATE_LABELS
    }
    return game_id, seasons, weeks, stype, y, p


def segmask(seasons, weeks, stype, name):
    if name == "week1_4":
        return (stype == "REG") & (weeks <= 4)
    if name == "weeks5plus":
        return (stype == "REG") & (weeks >= 5)
    if name == "reg":
        return stype == "REG"
    if name == "postseason":
        return np.isin(stype, list(POST_SEASON_TYPES))
    if name == "full":
        return np.ones(seasons.shape[0], dtype=bool)
    if name == "week1_4_2019_2024":
        return (stype == "REG") & (weeks <= 4) & (seasons >= 2019)
    raise ValueError(name)


SEGMENTS = ["week1_4", "weeks5plus", "reg", "postseason", "full"]


def brier_loss(p, yv):
    return (p - yv) ** 2


def logloss_loss(p, yv):
    p = np.clip(p, 1e-15, 1.0 - 1e-15)
    return -(yv * np.log(p) + (1.0 - yv) * np.log(1.0 - p))


def paired_stats(pc, pr, yv, mask):
    idx = np.where(mask)[0]
    a, b, yy = pc[idx], pr[idx], yv[idx]
    db = brier_loss(a, yy) - brier_loss(b, yy)
    dl = logloss_loss(a, yy) - logloss_loss(b, yy)
    return {
        "n": int(len(idx)),
        "mean_brier_delta": float(db.mean()),
        "median_brier_delta": float(np.median(db)),
        "mean_logloss_delta": float(dl.mean()),
        "median_logloss_delta": float(np.median(dl)),
        "brier_improve": int((db < 0).sum()),
        "brier_worsen": int((db > 0).sum()),
        "brier_tie": int((db == 0).sum()),
        "ll_improve": int((dl < 0).sum()),
        "ll_worsen": int((dl > 0).sum()),
        "ll_tie": int((dl == 0).sum()),
    }


def game_bootstrap(pc, pr, yv, mask, seed=BOOTSTRAP_SEED, n=BOOTSTRAP_N):
    idx = np.where(mask)[0]
    a, b, yy = pc[idx], pr[idx], yv[idx]
    db = brier_loss(a, yy) - brier_loss(b, yy)
    rng = np.random.default_rng(seed)
    N = len(db)
    means = np.empty(n)
    for k in range(n):
        s = rng.integers(0, N, N)
        means[k] = db[s].mean()
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {
        "method": "game_paired_bootstrap",
        "n_resamples": n,
        "seed": seed,
        "mean_delta": float(db.mean()),
        "percentile_2_5": float(lo),
        "percentile_97_5": float(hi),
        "proportion_favoring_candidate": float((means < 0).mean()),
        "proportion_favoring_reference": float((means > 0).mean()),
    }


def season_cluster_bootstrap(
    seasons, pc, pr, yv, mask, seed=BOOTSTRAP_SEED, n=BOOTSTRAP_N
):
    s_idx = np.where(mask)[0]
    ss = seasons[s_idx]
    a, b, yy = pc[s_idx], pr[s_idx], yv[s_idx]
    db = brier_loss(a, yy) - brier_loss(b, yy)
    uniq = np.unique(ss).tolist()
    by_season = {s: db[ss == s] for s in uniq}
    rng = np.random.default_rng(seed)
    means = np.empty(n)
    for k in range(n):
        chosen = rng.choice(np.asarray(uniq), size=len(uniq), replace=True)
        parts = [by_season[int(c)] for c in chosen]
        concat = np.concatenate(parts)
        means[k] = concat.mean()
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {
        "method": "season_cluster_bootstrap",
        "seasons": uniq,
        "n_seasons": len(uniq),
        "n_resamples": n,
        "seed": seed,
        "mean_delta": float(db.mean()),
        "percentile_2_5": float(lo),
        "percentile_97_5": float(hi),
        "proportion_favoring_candidate": float((means < 0).mean()),
        "proportion_favoring_reference": float((means > 0).mean()),
    }


def aggregate_brier(p, yv, mask):
    idx = np.where(mask)[0]
    return float(brier_loss(p[idx], yv[idx]).mean())


def season_stability(seasons, weeks, stype, y, p, cand, ref, metric="brier"):
    rows = []
    for s in SEASONS_ALL:
        mask = (seasons == s) & (stype == "REG") & (weeks <= 4)
        idx = np.where(mask)[0]
        if len(idx) == 0:
            continue
        a, b, yy = p[cand][idx], p[ref][idx], y[idx]
        if metric == "brier":
            da = brier_loss(a, yy) - brier_loss(b, yy)
        else:
            da = logloss_loss(a, yy) - logloss_loss(b, yy)
        rows.append((int(s), int(len(idx)), float(da.mean())))
    return rows


def summarize_season_deltas(rows):
    improved = [r for r in rows if r[2] < -1e-9]
    worsened = [r for r in rows if r[2] > 1e-9]
    ties = [r for r in rows if abs(r[2]) <= 1e-9]
    strongest_improve = min(improved, key=lambda r: r[2]) if improved else None
    strongest_worsen = max(worsened, key=lambda r: r[2]) if worsened else None
    return {
        "seasons_improved": [r[0] for r in improved],
        "seasons_worsened": [r[0] for r in worsened],
        "seasons_tied": [r[0] for r in ties],
        "n_improved": len(improved),
        "n_worsened": len(worsened),
        "n_tied": len(ties),
        "strongest_improvement": (
            {"season": strongest_improve[0], "delta": strongest_improve[2]}
            if strongest_improve
            else None
        ),
        "strongest_deterioration": (
            {"season": strongest_worsen[0], "delta": strongest_worsen[2]}
            if strongest_worsen
            else None
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args(argv)
    root = Path(args.project_root).resolve()
    out = root / "data/derived/qb_elo_season_regression_v1"

    arts = load(out)
    game_id, seasons, weeks, stype, y, p = core_arrays(arts)

    report: dict[str, Any] = {}

    # ---------- 1. Paired deltas vs 0% (all segments) ----------
    rep000 = []
    for seg in SEGMENTS:
        mask = segmask(seasons, weeks, stype, seg)
        for cand in ["regression_025", "regression_040", "regression_060"]:
            st = paired_stats(p[cand], p["regression_000"], y, mask)
            agg_check = (
                aggregate_brier(p[cand], y, mask) - aggregate_brier(p["regression_000"], y, mask)
            )
            st["aggregate_brier_equiv"] = agg_check
            rep000.append({"candidate": cand, "reference": "regression_000", "segment": seg, **st})
    report["paired_vs_000"] = rep000

    # ---------- 2. Paired deltas vs 33.3% (all segments) ----------
    rep333 = []
    for seg in SEGMENTS:
        mask = segmask(seasons, weeks, stype, seg)
        for cand in ["regression_000", "regression_025", "regression_040", "regression_060"]:
            st = paired_stats(p[cand], p["task04c_reference_0333"], y, mask)
            agg_check = (
                aggregate_brier(p[cand], y, mask)
                - aggregate_brier(p["task04c_reference_0333"], y, mask)
            )
            st["aggregate_brier_equiv"] = agg_check
            rep333.append({"candidate": cand, "reference": "task04c_reference_0333", "segment": seg, **st})
    report["paired_vs_0333"] = rep333

    # ---------- 3. Distributional + bootstrap for incumbent comparisons ----------
    dist = []
    boot = []
    for cand in ["regression_025", "regression_040", "regression_060"]:
        for seg in ["week1_4", "full"]:
            mask = segmask(seasons, weeks, stype, seg)
            st = paired_stats(p[cand], p["task04c_reference_0333"], y, mask)
            dist.append(
                {
                    "candidate": cand,
                    "reference": "task04c_reference_0333",
                    "segment": seg,
                    **st,
                }
            )
            # season-cluster uses regression-eligible seasons for week1_4.
            if seg == "week1_4":
                cl_mask = (stype == "REG") & (weeks <= 4) & (seasons >= 2019)
            else:
                cl_mask = mask
            boot.append(
                {
                    "candidate": cand,
                    "reference": "task04c_reference_0333",
                    "segment": seg,
                    "game_bootstrap": game_bootstrap(
                        p[cand], p["task04c_reference_0333"], y, mask
                    ),
                    "season_cluster": season_cluster_bootstrap(
                        seasons, p[cand], p["task04c_reference_0333"], y, cl_mask
                    ),
                }
            )
    report["distributional_vs_0333"] = dist
    report["bootstrap_vs_0333"] = boot

    # ---------- 4. Season stability (week1-4) vs 0% and 33.3% ----------
    stab_w14 = {"vs_000": {}, "vs_0333": {}}
    for cand in ["regression_025", "regression_040", "regression_060"]:
        for metric in ["brier", "ll"]:
            rows = season_stability(seasons, weeks, stype, y, p, cand, "regression_000", metric)
            stab_w14["vs_000"][f"{cand}/{metric}"] = {
                "rows": rows,
                **summarize_season_deltas(rows),
            }
    for cand in ["regression_000", "regression_025", "regression_040", "regression_060"]:
        for metric in ["brier", "ll"]:
            rows = season_stability(
                seasons, weeks, stype, y, p, cand, "task04c_reference_0333", metric
            )
            stab_w14["vs_0333"][f"{cand}/{metric}"] = {
                "rows": rows,
                "summary_2019_2024": summarize_season_deltas([r for r in rows if r[0] >= 2019]),
                "summary_2018": summarize_season_deltas([r for r in rows if r[0] == 2018]),
            }
    report["season_stability_week1_4"] = stab_w14

    # ---------- 5. Full-season stability by season ----------
    stab_full = {"vs_000": {}, "vs_0333": {}}
    for cand in ["regression_025", "regression_040", "regression_060"]:
        for metric in ["brier", "ll"]:
            rows = []
            for s in SEASONS_ALL:
                mask = seasons == s
                idx = np.where(mask)[0]
                a, b, yy = p[cand][idx], p["regression_000"][idx], y[idx]
                db = (
                    (brier_loss(a, yy) - brier_loss(b, yy)).mean()
                    if metric == "brier"
                    else (logloss_loss(a, yy) - logloss_loss(b, yy)).mean()
                )
                rows.append((s, int(len(idx)), float(db)))
            stab_full["vs_000"][f"{cand}/{metric}"] = {
                "rows": rows,
                **summarize_season_deltas(rows),
            }
    for cand in ["regression_000", "regression_025", "regression_040", "regression_060"]:
        for metric in ["brier", "ll"]:
            rows = []
            for s in SEASONS_ALL:
                mask = seasons == s
                idx = np.where(mask)[0]
                a, b, yy = p[cand][idx], p["task04c_reference_0333"][idx], y[idx]
                db = (
                    (brier_loss(a, yy) - brier_loss(b, yy)).mean()
                    if metric == "brier"
                    else (logloss_loss(a, yy) - logloss_loss(b, yy)).mean()
                )
                rows.append((s, int(len(idx)), float(db)))
            stab_full["vs_0333"][f"{cand}/{metric}"] = {
                "rows": rows,
                "summary_2019_2024": summarize_season_deltas([r for r in rows if r[0] >= 2019]),
                "summary_2018": summarize_season_deltas([r for r in rows if r[0] == 2018]),
            }
    report["season_stability_full"] = stab_full

    # ---------- 6. Probability-shift diagnostics ----------
    probshift = []
    for cand in ["regression_025", "regression_040", "regression_060"]:
        for seg in ["week1_4", "full"]:
            mask = segmask(seasons, weeks, stype, seg)
            idx = np.where(mask)[0]
            ad = np.abs(p[cand][idx] - p["task04c_reference_0333"][idx])
            probshift.append(
                {
                    "candidate": cand,
                    "reference": "task04c_reference_0333",
                    "segment": seg,
                    "n": int(len(ad)),
                    "mean_abs_prob_diff": float(ad.mean()),
                    "median_abs_prob_diff": float(np.median(ad)),
                    "max_abs_prob_diff": float(ad.max()),
                    "p90_abs_prob_diff": float(np.percentile(ad, 90)),
                    "p95_abs_prob_diff": float(np.percentile(ad, 95)),
                }
            )
    report["probability_shift"] = probshift

    # ---------- 7. 2019/2020 vs 2021-2024 diagnostic ----------
    era = []
    for cand in ["regression_025", "regression_040", "regression_060"]:
        for seggroup, seasons_set in [("2019_2020", [2019, 2020]), ("2021_2024", [2021, 2022, 2023, 2024])]:
            mask = (
                (stype == "REG") & (weeks <= 4) & np.isin(seasons, seasons_set)
            )
            st = paired_stats(p[cand], p["regression_000"], y, mask)
            era.append(
                {
                    "candidate": cand,
                    "era": seggroup,
                    "seasons": seasons_set,
                    "reference": "regression_000",
                    **st,
                }
            )
    report["era_week1_4_vs_000"] = era

    # preseason elo spread per season (from 0% artifact, week1 games)
    spread = []
    for s in SEASONS_ALL:
        mask = (seasons == s) & (stype == "REG") & (weeks == 1)
        idx = np.where(mask)[0]
        elos = np.concatenate(
            [
                np.asarray(arts["regression_000"]["home_elo_before"].to_list())[idx],
                np.asarray(arts["regression_000"]["away_elo_before"].to_list())[idx],
            ]
        )
        dev = np.abs(elos - 1500.0)
        spread.append(
            {
                "season": int(s),
                "games_w1": int(len(idx)),
                "mean_abs_elo_dev_w1": float(dev.mean()),
                "median_abs_elo_dev_w1": float(np.median(dev)),
                "p90_abs_elo_dev_w1": float(np.percentile(dev, 90)),
            }
        )
    report["preseason_elo_spread"] = spread

    # ---------- 8. Transition forensics ----------
    audit = pl.read_parquet(out / "season_boundary_audit_all.parquet")
    fore = {}
    key = audit.select("candidate_label", "team", "new_season")
    fore["rows"] = int(audit.height)
    fore["unique_keys"] = int(key.n_unique())
    fore["unique_keys_expect"] = 5 * 32 * 6
    fore["no_duplicate_keys"] = int(key.height) == int(key.n_unique())
    fore["all_pass"] = bool((audit["status"] == "PASS").all())
    trans_pairs = sorted(set(zip(audit["previous_season"].to_list(), audit["new_season"].to_list())))
    expect_pairs = [(2018, 2019), (2019, 2020), (2020, 2021), (2021, 2022), (2022, 2023), (2023, 2024)]
    fore["transition_pairs"] = trans_pairs
    fore["transition_pairs_correct"] = trans_pairs == expect_pairs
    fore["new_seasons"] = sorted(set(audit["new_season"].to_list()))
    # formula check: expected == center + (1-f)*(prior-center)
    formula_ok = True
    for r in audit.iter_rows(named=True):
        exp = 1500.0 + (1.0 - r["regression_fraction"]) * (r["prior_season_ending_elo"] - 1500.0)
        if abs(exp - r["expected_new_elo"]) > _TOL:
            formula_ok = False
    fore["formula_expected_matches"] = bool(formula_ok)
    # actual==expected
    fore["actual_equals_expected"] = bool(
        (np.abs(np.asarray(audit["actual_new_elo"].to_list())
                - np.asarray(audit["expected_new_elo"].to_list())) <= _TOL).all()
    )
    # transition block id == first REG block of new season
    tb_ok = all(
        str(r["transition_block_id"]) == f"{int(r['new_season'])}_REG_W01"
        for r in audit.iter_rows(named=True)
    )
    fore["transition_block_is_first_reg_w01"] = bool(tb_ok)
    fore["no_postseason_new_season"] = not set(audit["new_season"].to_list()).intersection(
        {2018, 2019, 2020, 2021, 2022, 2023, 2024}
    ) or all(
        int(ns) in {2019, 2020, 2021, 2022, 2023, 2024} for ns in audit["new_season"].to_list()
    )
    fore["prior_state_exists_all_true"] = bool(audit["prior_team_state_exists"].all())
    report["transition_forensics"] = fore

    # ---------- 9. First-divergence audit ----------
    divergence = {}
    for cand in ["regression_025", "regression_040", "regression_060", "task04c_reference_0333"]:
        for ref in ["regression_000", "task04c_reference_0333"]:
            if cand == ref:
                continue
            teams = sorted(set(arts[cand]["home_team"].to_list() + arts[cand]["away_team"].to_list()))
            first_season = {}
            for team in teams:
                # chronological scan over games using the 0% artifact order (all identical order)
                found = None
                a = arts[cand]
                b = arts[ref]
                for row_a, row_b in zip(a.iter_rows(named=True), b.iter_rows(named=True)):
                    if row_a["home_team"] == team:
                        va, vb = row_a["home_elo_before"], row_b["home_elo_before"]
                    elif row_a["away_team"] == team:
                        va, vb = row_a["away_elo_before"], row_b["away_elo_before"]
                    else:
                        continue
                    if abs(va - vb) > _TOL:
                        found = int(row_a["season"])
                        break
                first_season[team] = found
            div_seasons = set(first_season.values())
            divergence[f"{cand}_vs_{ref}"] = {
                "first_divergence_season_set": sorted(div_seasons),
                "all_first_divergence_at_2019": div_seasons == {2019},
                "n_teams": len(teams),
            }
    report["first_divergence"] = divergence

    # ---------- 10. Real-team spot checks (side-by-side fractions) ----------
    spot = []
    # Use the 40% audit to pick examples.
    aud40 = audit.filter(pl.col("candidate_label") == "regression_040")
    rows40 = aud40.to_dicts()
    hi = max(rows40, key=lambda r: r["prior_season_ending_elo"])
    lo = min(rows40, key=lambda r: r["prior_season_ending_elo"])
    near = min(rows40, key=lambda r: abs(r["prior_season_ending_elo"] - 1500.0))
    for example, r in [("high_prior", hi), ("low_prior", lo), ("near_1500", near)]:
        for cand in CANDIDATE_LABELS:
            ar = audit.filter(
                (pl.col("candidate_label") == cand)
                & (pl.col("team") == r["team"])
                & (pl.col("previous_season") == r["previous_season"])
                & (pl.col("new_season") == r["new_season"])
            )
            if ar.height == 1:
                row = ar.row(0, named=True)
                spot.append(
                    {
                        "example": example,
                        "team": row["team"],
                        "previous_season": row["previous_season"],
                        "new_season": row["new_season"],
                        "candidate": row["candidate_label"],
                        "fraction": row["regression_fraction"],
                        "prior_R": row["prior_season_ending_elo"],
                        "mean_M": row["canonical_mean"],
                        "expected": row["expected_new_elo"],
                        "actual": row["actual_new_elo"],
                        "abs_error": abs(row["actual_new_elo"] - row["expected_new_elo"]),
                        "status": row["status"],
                    }
                )
    report["spot_checks"] = spot

    # write artifacts
    paired_rows = []
    for grp in ["paired_vs_000", "paired_vs_0333"]:
        for r in report[grp]:
            paired_rows.append(r)
    paired_df = pl.DataFrame(paired_rows)
    paired_df.write_parquet(out / "paired_comparisons.parquet")

    (out / "analysis_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")

    # ---------- Print compact report ----------
    print("=== PAIRED DELTAS ===")
    for grp in ["paired_vs_000", "paired_vs_0333"]:
        print(f"-- {grp} --")
        for r in report[grp]:
            print(
                f"{LABEL_SHORT[r['candidate']]:<6} vs {LABEL_SHORT[r['reference']]:<6} "
                f"{r['segment']:<10} n={r['n']:<5} br={r['mean_brier_delta']:+.6f} "
                f"ll={r['mean_logloss_delta']:+.6f} (agg_equiv={r['aggregate_brier_equiv']:+.6f})"
            )

    print("\n=== DISTRIBUTIONAL vs 33.3% (improve/worsen/tie counts) ===")
    for r in report["distributional_vs_0333"]:
        print(
            f"{LABEL_SHORT[r['candidate']]:<6} {r['segment']:<9} n={r['n']:<5} "
            f"br mean={r['mean_brier_delta']:+.6f} median={r['median_brier_delta']:+.6f} "
            f"(I/W/T {r['brier_improve']}/{r['brier_worsen']}/{r['brier_tie']}) "
            f"ll mean={r['mean_logloss_delta']:+.6f} median={r['median_logloss_delta']:+.6f} "
            f"(I/W/T {r['ll_improve']}/{r['ll_worsen']}/{r['ll_tie']})"
        )

    print("\n=== BOOTSTRAP vs 33.3% (95% CI of mean brier delta) ===")
    for r in report["bootstrap_vs_0333"]:
        gb = r["game_bootstrap"]
        sc = r["season_cluster"]
        print(
            f"{LABEL_SHORT[r['candidate']]:<6} {r['segment']:<9} game[2.5..97.5]="
            f"{gb['percentile_2_5']:+.5f}..{gb['percentile_97_5']:+.5f} "
            f"P(cand>{'better'})={gb['proportion_favoring_candidate']:.3f} | "
            f"cluster[2.5..97.5]={sc['percentile_2_5']:+.5f}..{sc['percentile_97_5']:+.5f} "
            f"P(cand_better)={sc['proportion_favoring_candidate']:.3f} seasons={sc['seasons']}"
        )

    print("\n=== WEEK1-4 SEASON Brier deltas ===")
    for k in ["vs_0333"]:
        for key, v in stab_w14[k].items():
            cand, metric = key.split("/")
            if metric != "brier":
                continue
            s19 = v["summary_2019_2024"]
            print(
                f"{LABEL_SHORT[cand]:<6} vs 33.3%  imp={s19['n_improved']} wor={s19['n_worsened']} "
                f"tie={s19['n_tied']} strong_imp={s19['strongest_improvement']} "
                f"strong_wor={s19['strongest_deterioration']}"
            )

    print("\n=== PROB-SHIFT ===")
    for r in report["probability_shift"]:
        print(
            f"{LABEL_SHORT[r['candidate']]:<6} {r['segment']:<9} n={r['n']} "
            f"mean={r['mean_abs_prob_diff']:.5f} med={r['median_abs_prob_diff']:.5f} "
            f"p90={r['p90_abs_prob_diff']:.5f} p95={r['p95_abs_prob_diff']:.5f} max={r['max_abs_prob_diff']:.5f}"
        )

    print("\n=== TRANSITION FORENSICS ===")
    for k, v in fore.items():
        print(f"  {k}: {v}")

    print("\n=== FIRST DIVERGENCE ===")
    for k, v in divergence.items():
        print(f"  {k}: season_set={v['first_divergence_season_set']} all_2019={v['all_first_divergence_at_2019']}")

    print("\n=== SPOT CHECKS ===")
    for r in spot:
        print(
            f"  {r['example']:<10} {r['team']:<4} {r['previous_season']}->{r['new_season']} "
            f"{LABEL_SHORT[r['candidate']]:<6} R={r['prior_R']:.2f} exp={r['expected']:.4f} "
            f"act={r['actual']:.4f} err={r['abs_error']:.2e} {r['status']}"
        )

    print("\n=== PRESEASON ELO SPREAD (0%, week1) ===")
    for r in report["preseason_elo_spread"]:
        dev = r
        print(
            f"  {dev['season']}: mean={dev['mean_abs_elo_dev_w1']:.2f} "
            f"med={dev['median_abs_elo_dev_w1']:.2f} "
            f"p90={dev['p90_abs_elo_dev_w1']:.2f}"
        )

    print("\nWROTE:", out / "paired_comparisons.parquet", "and analysis_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())