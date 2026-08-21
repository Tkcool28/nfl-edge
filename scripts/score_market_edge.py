#!/usr/bin/env python3
"""Score the Market Edge frozen candidates with the corrective scorer.

Usage:
    python scripts/score_market_edge.py [--period discovery|confirmation|both] [--out <dir>]

Builds the authoritative graded row-ledger per period with the repo-native scorer
(`src/nfl_edge/market_edge`), writes row-level parquet/CSV, corrected summaries,
old-vs-corrected comparison, and provenance with SHA-256 hashes. Marks the old
D4/D5 artifacts as SUPERSEDED_INVALID_IMPLEMENTATION in provenance (files are
preserved, never deleted). The same `build_ledger` code path runs for both periods;
2025 is hard-rejected. Does NOT train, retune, stack, or open 2025.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

from nfl_edge.market_edge import aggregate, candidates, config as cfgmod, provenance as prov
from nfl_edge.common import fingerprint as fp

ROOT = Path(__file__).resolve().parents[1]
CENSUS = ROOT / "data/modeling/development_v1/market_edge_census_v1.parquet"
GAMES = ROOT / "data/frozen/games/games_2018_2025.parquet"
XGB = ROOT / "data/modeling/development_v1/xgboost_candidate_predictions_2018_2024.parquet"
CFG = ROOT / "config/market_edge_validation_v1.yaml"
LOCK = ROOT / "reports/task_05e_d5_candidate_lock.json"

LOCKED_CANDIDATES = [
    ("ML_DOG_VALUE_ZONE", "AVG", "ZONE"),
    ("ML_DOG_VALUE_ZONE", "CORROB", "ZONE"),
    ("ML_AVG_DISAGREEMENT", "AVG", "0-2"),
    ("SPREAD_DISAGREEMENT", "EXPECTED_MARGIN", None),  # union [0,4)
]


def locked_union(ledger: pl.DataFrame, family: str, model: str) -> pl.DataFrame:
    f = ledger.filter((pl.col("family") == family) & (pl.col("model") == model))
    if family == "SPREAD_DISAGREEMENT":
        return f.filter(pl.col("edge_pp") < 4)
    return f


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", choices=["discovery", "confirmation", "both"], default="both")
    ap.add_argument("--out-dir", default=str(ROOT / "reports/task05e_remediated"))
    args = ap.parse_args()

    cfg = cfgmod.load_pinned_config(CFG)
    prov.verify_lock_hash(LOCK)
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)

    census = pl.read_parquet(CENSUS)
    # Observation universe only: 2020-2024. The 2025 sealed rows are NEVER loaded
    # into the grading frame; build_ledger additionally hard-rejects any 2025 row
    # that leaks through (firewall BEFORE any filtering/materialization).
    games = pl.read_parquet(GAMES).filter(pl.col("season").is_in([2020, 2021, 2022, 2023, 2024]))
    xgb_ids = set(pl.read_parquet(XGB).filter(pl.col("prediction_probability").is_not_null())
                  ["game_id"].unique().to_list())

    ledgers = {}
    summaries = {}
    periods = []
    if args.period in ("discovery", "both"):
        periods.append(("DISCOVERY", "discovery"))
    if args.period in ("confirmation", "both"):
        periods.append(("CONFIRMATION", "confirmation"))

    for split, slug in periods:
        ledger = candidates.build_ledger(census, games, xgb_ids, split)
        if split == "DISCOVERY":
            assert set(ledger["season"].unique().to_list()) <= {2020, 2021, 2022}
        else:
            assert set(ledger["season"].unique().to_list()) <= {2023, 2024}
        ldf = out_dir / f"market_edge_{slug}_corrected_ledger_v1.parquet"
        ldc = out_dir / f"market_edge_{slug}_corrected_ledger_v1.csv"
        ledger.write_parquet(ldf); ledger.write_csv(ldc)
        ledgers[f"{slug}_ledger.parquet"] = ldf
        ledgers[f"{slug}_ledger.csv"] = ldc

        # summary: full family/bucket table + locked candidates
        fam_table = aggregate.family_table(ledger)
        (out_dir / f"market_edge_{slug}_family_summary_v1.csv").write_text(
            fam_table.to_pandas().to_csv(index=False))
        cand = {}
        for fam, model, bucket in LOCKED_CANDIDATES:
            if bucket:
                s = aggregate.candidate_summary(ledger, fam, model, bucket)
                key = f"{fam}_{model}_{bucket or 'UNION'}"
                cand[key] = s
            else:
                f = locked_union(ledger, fam, model)
                cand[f"{fam}_{model}_UNION"] = {**aggregate.summarize(f), "per_season": aggregate.per_season(f)}
        summaries[slug] = cand
        sym_append = {"split": split, "seasons": sorted(ledger["season"].unique().to_list()),
                      "ledger_rows": ledger.height}
        sym_append.update(cand)
        sym_json = out_dir / f"market_edge_{slug}_corrected_summary_v1.json"
        sym_json.write_text(json.dumps(cand, indent=2))
        ledgers[f"{slug}_summary_json"] = sym_json
        print(f"[{split}] ledger rows={ledger.height} summary_json={sym_json.name}")

    # provenance
    prov_doc = prov.build_provenance(
        repo_root=ROOT, ledgers={k: str(v) for k, v in ledgers.items()},
    summaries=summaries, comparison=str(out_dir / "old_vs_corrected.md"),
        old_artifacts=[], superseded=[str(p) for p in [
            ROOT / "reports/task_05e_d4_discovery_results.csv",
            ROOT / "reports/task_05e_d4_discovery_results.md",
            ROOT / "reports/task_05e_d4_discovery_provenance.json",
            ROOT / "reports/task_05e_d4_big_opportunity_screen.json",
            ROOT / "reports/task_05e_d4_candidate_lock_recommendations.json",
            ROOT / "reports/task_05e_d4_complementarity.json",
            ROOT / "reports/task_05e_d4_display_diagnostics.json",
            ROOT / "reports/task_05e_d5_confirmation_results.csv",
            ROOT / "reports/task_05e_d5_confirmation_results.md",
            ROOT / "reports/task_05e_d5_confirmation_provenance.json",
            ROOT / "reports/task_05e_d5_final_evidence_labels.json",
            ROOT / "reports/task_05e_d5_product_alignment.json",
            ROOT / "data/modeling/development_v1/market_edge_confirmation_scored_v1.parquet",
            ROOT / "data/modeling/development_v1/market_edge_discovery_scored_v1.parquet",
        ]])
    (out_dir / "task05e_remediation_provenance.json").write_text(
        json.dumps(prov_doc, indent=1))
    print(" + provenance task05e_remediation_provenance.json")


def log(msg: str) -> None:
    print(msg, flush=True)


if __name__ == "__main__":
    main()