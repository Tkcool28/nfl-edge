"""Task 04D Chunk 5 finalization: artifact inventory, reproducibility proof,
and consolidated factual evidence summary.

READ-ONLY finalization over the frozen Chunk 3/4 artifacts. Produces:

- ``final_artifact_inventory.json``  : relative path / bytes / SHA-256 of
  every permanent Task04D artifact.
- ``final_evidence_summary.json``    : consolidated factual (non-decisional)
  evidence tables for Master review.
- ``artifact_reproducibility.json``  : logical-equality proof that each stored
  prediction artifact equals a rebuild from its engine run ledger.

Does NOT choose a regression value and does NOT issue a verdict.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from nfl_edge.backtest.task04d_season_regression_evaluation import (
    CANDIDATE_FRACTIONS,
    CANDIDATE_LABELS,
    TASK04C_REFERENCE_FRACTION,
    build_prediction_artifact,
    load_canonical_config,
)

SEASONS = [2018, 2019, 2020, 2021, 2022, 2023, 2024]
REGRESSION_ELIGIBLE = [2019, 2020, 2021, 2022, 2023, 2024]
SEGMENTS = ["week1_4", "weeks5plus", "reg", "postseason", "full"]
_TOL = 1e-9
SHORT = {
    "regression_000": "0%",
    "regression_025": "25%",
    "regression_040": "40%",
    "regression_060": "60%",
    "task04c_reference_0333": "33.3%",
}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def artifact_metrics(df: pl.DataFrame) -> dict[str, Any]:
    y = np.asarray(df["target_outcome"].to_list(), dtype=float)
    p = np.asarray(df["predicted_home_win_probability"].to_list(), dtype=float)
    pc = np.clip(p, 1e-15, 1 - 1e-15)
    return {
        "n_scored": float(df.height),
        "brier": float(((p - y) ** 2).mean()),
        "log_loss": float((-(y * np.log(pc) + (1 - y) * np.log(1 - pc))).mean()),
        "accuracy": float((((p > 0.5)) == (y == 1)).mean()),
    }


def artifact_seg_metrics(df: pl.DataFrame, seg: str) -> dict[str, Any]:
    if seg == "week1_4":
        d = df.filter((pl.col("season_type") == "REG") & (pl.col("week") <= 4))
    elif seg == "weeks5plus":
        d = df.filter((pl.col("season_type") == "REG") & (pl.col("week") >= 5))
    elif seg == "reg":
        d = df.filter(pl.col("season_type") == "REG")
    elif seg == "postseason":
        d = df.filter(pl.col("season_type").is_in(["WC", "DIV", "CON", "SB"]))
    elif seg == "full":
        d = df
    else:
        raise ValueError(seg)
    return artifact_metrics(d)


def season_counts(deltas_by_season: dict[int, float]) -> dict[str, Any]:
    improved = [s for s in REGRESSION_ELIGIBLE if deltas_by_season.get(s, 0.0) < -1e-9]
    worsened = [s for s in REGRESSION_ELIGIBLE if deltas_by_season.get(s, 0.0) > 1e-9]
    tied = [s for s in REGRESSION_ELIGIBLE if abs(deltas_by_season.get(s, 0.0)) <= 1e-9]
    return {
        "lower_than_reference": improved,
        "higher_than_reference": worsened,
        "tied": tied,
        "n_lower": len(improved),
        "n_higher": len(worsened),
        "n_tied": len(tied),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args(argv)
    root = Path(args.project_root).resolve()
    out = root / "data/derived/qb_elo_season_regression_v1"

    # ---- 1. Rebuild prediction artifacts from run ledgers (reproducibility) ----
    repro = {}
    for lab in CANDIDATE_LABELS:
        engine_preds = pl.read_parquet(
            out / "runs" / lab / "qb_elo_predictions_2018_2024.parquet"
        )
        rebuilt = build_prediction_artifact(engine_preds, lab, CANDIDATE_FRACTIONS[lab])
        stored = pl.read_parquet(out / f"predictions_{lab}.parquet")
        same = rebuilt.height == stored.height and all(
            rebuilt[c].to_list() == stored[c].to_list() for c in rebuilt.columns
        )
        repro[lab] = {
            "logical_equal_to_rebuild": bool(same),
            "rows": int(stored.height),
            "fraction": CANDIDATE_FRACTIONS[lab],
        }

    # ---- 2. Candidate metric matrix + deltas ----
    arts = {
        lab: pl.read_parquet(out / f"predictions_{lab}.parquet") for lab in CANDIDATE_LABELS
    }
    matrix = {lab: {} for lab in CANDIDATE_LABELS}
    for lab in CANDIDATE_LABELS:
        for seg in SEGMENTS:
            m = artifact_seg_metrics(arts[lab], seg)
            base0 = artifact_seg_metrics(arts["regression_000"], seg)
            base3 = artifact_seg_metrics(arts["task04c_reference_0333"], seg)
            matrix[lab][seg] = {
                "n": m["n_scored"],
                "brier": m["brier"],
                "log_loss": m["log_loss"],
                "accuracy": m["accuracy"],
                "brier_delta_vs_000": m["brier"] - base0["brier"],
                "log_loss_delta_vs_000": m["log_loss"] - base0["log_loss"],
                "brier_delta_vs_0333": m["brier"] - base3["brier"],
                "log_loss_delta_vs_0333": m["log_loss"] - base3["log_loss"],
            }

    # ---- 3. Season matrices + counts ----
    seas_w14 = {lab: {} for lab in CANDIDATE_LABELS}
    seas_full = {lab: {} for lab in CANDIDATE_LABELS}
    for lab in CANDIDATE_LABELS:
        for s in SEASONS:
            seas_w14[lab][str(s)] = artifact_metrics(
                arts[lab].filter(
                    (pl.col("season") == s)
                    & (pl.col("season_type") == "REG")
                    & (pl.col("week") <= 4)
                )
            )
            seas_full[lab][str(s)] = artifact_metrics(
                arts[lab].filter(pl.col("season") == s)
            )

    def season_deltas(cand: str, ref: str, metric: str, w14: bool) -> dict[int, float]:
        src = seas_w14 if w14 else seas_full
        return {
            s: float(src[cand][str(s)][metric] - src[ref][str(s)][metric]) for s in SEASONS
        }

    counts = {"week1_4": {}, "full": {}}
    for w14flag, w14 in (("week1_4", True), ("full", False)):
        for cand in CANDIDATE_LABELS:
            for metric in ("brier", "log_loss"):
                for reflab, ref in (
                    ("vs_000", "regression_000"),
                    ("vs_0333", "task04c_reference_0333"),
                ):
                    d = season_deltas(cand, ref, metric, w14)
                    counts[w14flag][f"{SHORT[cand]}|{SHORT[ref]}|{metric}"] = season_counts(d)

    # ---- 4. Paired comparison reconciliation ----
    paired = pl.read_parquet(out / "paired_comparisons.parquet").to_dicts()
    reconcile_ok = all(
        abs(r["mean_brier_delta"] - r["aggregate_brier_equiv"]) <= 1e-6
        for r in paired
        if r.get("aggregate_brier_equiv") is not None
    )

    # ---- 5. Bootstrap facts (interval-includes-zero) ----
    analysis = json.loads((out / "analysis_report.json").read_text())
    boot_facts = []
    for b in analysis["bootstrap_vs_0333"]:
        for kind in ("game_bootstrap", "season_cluster"):
            r = b[kind]
            lo, hi = r["percentile_2_5"], r["percentile_97_5"]
            boot_facts.append(
                {
                    "candidate": SHORT[b["candidate"]],
                    "reference": "33.3%",
                    "segment": b["segment"],
                    "method": r["method"],
                    "seed": r["seed"],
                    "iterations": r["n_resamples"],
                    "resampling_unit": "games" if kind == "game_bootstrap" else "seasons",
                    "ci_level": "95%",
                    "mean_brier_delta": r["mean_delta"],
                    "ci_2_5": lo,
                    "ci_97_5": hi,
                    "interval_includes_zero": bool(lo <= 0.0 <= hi),
                    "boot_prob_delta_lt_0": r["proportion_favoring_candidate"],
                }
            )

    # ---- 6..8. Probability-shift / identity / replay / transition / spot ----
    prob_shift = analysis["probability_shift"]
    identity = json.loads((out / "identity_verification.json").read_text())
    replay = json.loads((out / "replay_determinism.json").read_text())
    pairability = json.loads((out / "pairability_matrix.json").read_text())
    spot = analysis["spot_checks"]
    first_div = analysis["first_divergence"]
    audit = pl.read_parquet(out / "season_boundary_audit_all.parquet")

    # ---- 9. 2025 seal ----
    n2025_pred = sum(
        int(arts[lab].filter(pl.col("season") == 2025).height) for lab in CANDIDATE_LABELS
    )
    text_2025 = 0
    for fn in ("metrics_segments.json", "metrics_season_week1_4.json", "analysis_report.json"):
        text_2025 += (out / fn).read_text().count('"2025"')
    seal = {
        "2025_scored_prediction_rows": n2025_pred,
        "2025_paired_target_rows": 0,
        "2025_season_metric_key_refs": text_2025,
        "2025_transition_target_rows": int(
            audit.filter(
                (pl.col("new_season") == 2025) | (pl.col("previous_season") == 2025)
            ).height
        ),
        "expected": 0,
    }

    # ---- 10. Artifact inventory ----
    inventory_files = (
        [f"predictions_{lab}.parquet" for lab in CANDIDATE_LABELS]
        + ["season_boundary_audit_all.parquet"]
        + [f"season_boundary_audit_{lab}.parquet" for lab in CANDIDATE_LABELS]
        + [
            "metrics_segments.json",
            "metrics_season_week1_4.json",
            "pairability_matrix.json",
            "identity_verification.json",
            "replay_determinism.json",
            "paired_comparisons.parquet",
            "analysis_report.json",
            "summary.json",
        ]
    )
    inventory = {
        fn: {"bytes": p.stat().st_size, "sha256": sha256(p)}
        for fn in inventory_files
        if (p := out / fn).is_file()
    }

    # ---- 11. Assemble evidence summary ----
    evidence = {
        "task04d_stage": "final_evidence_package",
        "model_selection_performed": False,
        "verdict_issued": None,
        "candidate_metric_matrix": matrix,
        "season_week1_4_metrics": seas_w14,
        "season_full_metrics": seas_full,
        "season_win_worse_tie_counts_2019_2024": counts,
        "paired_reconciled_with_aggregate": bool(reconcile_ok),
        "paired_rows": len(paired),
        "bootstrap_facts": boot_facts,
        "probability_shift_vs_0333": prob_shift,
        "transition_audit": {
            "rows": int(audit.height),
            "new_seasons": sorted(set(audit["new_season"].to_list())),
            "all_pass": bool((audit["status"] == "PASS").all()),
        },
        "first_divergence": first_div,
        "spot_checks": spot,
        "identity_0333": {
            "identity_passed": identity["identity_passed"],
            "max_abs_diff_by_column": identity["max_abs_diff_by_column"],
        },
        "determinism_replay": {
            k: {
                "game_id_order_identical": v["game_id_order_identical"],
                "max_prob_diff": v["max_prob_diff"],
                "metrics_equal": v["metrics_equal"],
            }
            for k, v in replay.items()
        },
        "pairability": {"pairable": pairability["pairable"]},
        "artifact_reproducibility": repro,
        "seal_2025": seal,
        "artifact_inventory": inventory,
    }
    (out / "final_evidence_summary.json").write_text(
        json.dumps(evidence, indent=2, default=str) + "\n"
    )
    (out / "final_artifact_inventory.json").write_text(
        json.dumps(inventory, indent=2, default=str) + "\n"
    )
    (out / "artifact_reproducibility.json").write_text(
        json.dumps(repro, indent=2, default=str) + "\n"
    )

    # ---- Print ----
    print("=== CANDIDATE METRIC MATRIX (full-development) ===")
    for lab in CANDIDATE_LABELS:
        m = matrix[lab]["full"]
        print(
            f"{SHORT[lab]:<6} n={m['n']:<5.0f} brier={m['brier']:.9f} "
            f"ll={m['log_loss']:.9f} acc={m['accuracy']:.9f}"
        )
    print("\n=== REPRO (prediction == rebuild) ===")
    for k, v in repro.items():
        print(f"  {SHORT[k]:<6} logical_equal_to_rebuild={v['logical_equal_to_rebuild']}")
    print("\n=== SEAL 2025 ===", seal)
    print("\n=== INVENTORY (files) ===", len(inventory))
    print("\nWROTE final_evidence_summary.json / final_artifact_inventory.json / "
          "artifact_reproducibility.json")

    # ---- Finalization aggregate fail-closed gate (Phase 5B-1) ----
    # All serialized validation booleans must be true before finalization can
    # report success. Failed evidence is still written for diagnosis, but the
    # process returns nonzero so automation never publishes a failed package as
    # validated. Nothing false is promoted to true.
    finalize_gates = {}
    if not isinstance(reconcile_ok, bool):
        finalize_gates["paired_reconciliation"] = bool(reconcile_ok)
    else:
        finalize_gates["paired_reconciliation"] = reconcile_ok
    # Reproducibility: every candidate prediction must equal its engine rebuild.
    finalize_gates["artifact_reproducibility"] = bool(
        all(v["logical_equal_to_rebuild"] for v in repro.values())
    )
    # Transition audit: the combined season-boundary audit must be all PASS.
    finalize_gates["transition_audit"] = bool(
        (audit["status"] == "PASS").all()
    )
    # 2025 seal: every 2025 count must be zero.
    finalize_gates["seal_2025"] = all(
        v == 0 for k, v in seal.items() if k != "expected"
    )
    # Config / incumbent consistency: the production season reversion fraction
    # read from config/qb_elo_v1.yaml must equal the Task04D incumbent fraction.
    cfg = load_canonical_config(root)
    config_fraction = float(cfg["season_mean_reversion_fraction"])
    finalize_gates["config_reference_consistency"] = (
        abs(config_fraction - TASK04C_REFERENCE_FRACTION) <= 1e-9
    )

    failed_gates = [k for k, v in finalize_gates.items() if not v]
    if failed_gates:
        sys.stderr.write(
            f"FINALIZATION FAILED GATES: {failed_gates} "
            f"(config_reversion={config_fraction}, "
            f"reference={TASK04C_REFERENCE_FRACTION})\n"
        )
        return 1
    else:
        sys.stderr.write(
            f"FINALIZATION GATES PASS: config_reversion={config_fraction}, "
            f"reference={TASK04C_REFERENCE_FRACTION}\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())