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

# Canonical Task04D evidence package (relative to the Task04D derived root).
# Single source of truth -- no competing hard-coded lists. 23 top-level
# artifacts + 20 run artifacts (5 candidates x 4 files) = 43 permanent files.
_RUN_ARTIFACT_NAMES: tuple[str, ...] = (
    "qb_elo_predictions_2018_2024.parquet",
    "qb_elo_state_transitions_2018_2024.parquet",
    "qb_elo_run_manifest_v1.json",
    "qb_elo_tuning_ledger_v1.json",
)
_TOP_LEVEL_PERMANENT: tuple[str, ...] = (
    "analysis_report.json",
    "artifact_reproducibility.json",
    "boundary_sanity.json",
    "final_artifact_inventory.json",
    "final_evidence_summary.json",
    "identity_verification.json",
    "metrics_season_week1_4.json",
    "metrics_segments.json",
    "pairability_matrix.json",
    "paired_comparisons.parquet",
    "predictions_regression_000.parquet",
    "predictions_regression_025.parquet",
    "predictions_regression_040.parquet",
    "predictions_regression_060.parquet",
    "predictions_task04c_reference_0333.parquet",
    "replay_determinism.json",
    "season_boundary_audit_all.parquet",
    "season_boundary_audit_regression_000.parquet",
    "season_boundary_audit_regression_025.parquet",
    "season_boundary_audit_regression_040.parquet",
    "season_boundary_audit_regression_060.parquet",
    "season_boundary_audit_task04c_reference_0333.parquet",
    "summary.json",
)


def canonical_permanent_artifacts() -> tuple[str, ...]:
    """Return the deterministic, complete set of permanent Task04D artifacts.

    All paths are relative to the Task04D derived-data root. This is the
    single source of truth for the expected permanent evidence package.
    """
    top = _TOP_LEVEL_PERMANENT
    runs = tuple(
        f"runs/{lab}/{name}"
        for lab in CANDIDATE_LABELS
        for name in _RUN_ARTIFACT_NAMES
    )
    return tuple(sorted(top + runs))


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _read_sha_or_none(p: Path, rel: str) -> str:
    """SHA-256 of a repository path, or '' if missing (fail-closed below)."""
    full = p / rel if p is not None else Path(rel)
    if not Path(full).is_file():
        return ""
    return sha256(Path(full))


def _current_git_head(root: Path) -> str:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=10,
        )
        return out.stdout.strip()
    except Exception:
        return ""


TASK04C_REFERENCE_INPUT_REL = (
    "data/derived/qb_elo_oracle_comparison_v1/qb_elo_oracle_predictions_2018_2024.parquet"
)
ORACLE_RESOLVER_INPUT_REL = (
    "data/derived/oracle_qb_entering_state_v2"
    "/oracle_qb_pregame_adjustments_by_game_2018_2024_v2.parquet"
)
CONFIG_REL = "config/qb_elo_v1.yaml"
EVALUATOR_REL = "src/nfl_edge/backtest/task04d_season_regression_evaluation.py"
FINALIZER_REL = "scripts/finalize_qb_elo_season_regression.py"
OFFICIAL_RUNNER_REL = "scripts/official_qb_elo_season_regression.py"
ANALYZE_SCRIPT_REL = "scripts/analyze_qb_elo_season_regression.py"
EVALUATE_SCRIPT_REL = "scripts/evaluate_qb_elo_season_regression.py"
INCUMBENT_CANDIDATE_PARQUET = "predictions_task04c_reference_0333.parquet"


def build_provenance(root: Path, out: Path) -> dict[str, Any]:
    """Assemble deterministic final-evidence provenance (Phase 5B-2).

    Records the actual Task04D dependency edges and the frozen repository
    state. No self-referential hashing: the final report is excluded from the
    repository-state fingerprint so generation stays finite and deterministic.
    `out` is the Task04D derived-data root under which candidate artifacts live.
    """
    config_fraction: float | None = None
    try:
        config_fraction = float(
            load_canonical_config(root)["season_mean_reversion_fraction"]
        )
    except Exception:  # noqa: BLE001 - missing/unparseable config is a failed provenance gate
        config_fraction = None
    prov: dict[str, Any] = {
        "finalizer_source_path": FINALIZER_REL,
        "finalizer_source_sha256": _read_sha_or_none(root, FINALIZER_REL),
        "evaluator_source_path": EVALUATOR_REL,
        "evaluator_source_sha256": _read_sha_or_none(root, EVALUATOR_REL),
        "official_runner_source_path": OFFICIAL_RUNNER_REL,
        "official_runner_source_sha256": _read_sha_or_none(root, OFFICIAL_RUNNER_REL),
        "analyze_script_source_path": ANALYZE_SCRIPT_REL,
        "analyze_script_source_sha256": _read_sha_or_none(root, ANALYZE_SCRIPT_REL),
        "evaluate_script_source_path": EVALUATE_SCRIPT_REL,
        "evaluate_script_source_sha256": _read_sha_or_none(root, EVALUATE_SCRIPT_REL),
        "qb_elo_config_path": CONFIG_REL,
        "qb_elo_config_sha256": _read_sha_or_none(root, CONFIG_REL),
        "qb_elo_config_season_mean_reversion_fraction": config_fraction,
        "task04c_reference_input_path": TASK04C_REFERENCE_INPUT_REL,
        "task04c_reference_input_sha256": _read_sha_or_none(root, TASK04C_REFERENCE_INPUT_REL),
        "task04c_oracle_resolver_input_path": ORACLE_RESOLVER_INPUT_REL,
        "task04c_oracle_resolver_input_sha256": _read_sha_or_none(root, ORACLE_RESOLVER_INPUT_REL),
        "incumbent_reference_candidate_path": INCUMBENT_CANDIDATE_PARQUET,
        "incumbent_reference_candidate_sha256": _read_sha_or_none(out, INCUMBENT_CANDIDATE_PARQUET),
        "git_head_sha": _current_git_head(root),
    }
    # Deterministic content-based repository-state fingerprint (excludes the
    # final report itself to avoid recursive self-hash).
    fp_input = "|".join(
        [
            prov["finalizer_source_sha256"],
            prov["evaluator_source_sha256"],
            prov["qb_elo_config_sha256"],
            prov["task04c_reference_input_sha256"],
            prov["incumbent_reference_candidate_sha256"] or "",
        ]
    )
    prov["repository_state_id"] = (
        hashlib.sha256(fp_input.encode("utf-8")).hexdigest()
        if fp_input else ""
    )
    return prov


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

    # ---- 10. Write artifact_reproducibility.json FIRST (final bytes). ----
    # The finalizer produces this file itself; its SHA must describe the final
    # on-disk bytes. We write it before building the inventory so the inventory
    # can record the post-write SHA.
    repro_path = out / "artifact_reproducibility.json"
    repro_path.write_text(json.dumps(repro, indent=2, default=str) + "\n")

    # ---- 11. Artifact inventory (canonical permanent set, fail-closed) ----
    # Self-reference / write-order handling:
    #  - artifact_reproducibility.json : SHA recorded from the file just written.
    #  - final_evidence_summary.json   : generated by finalizer; MUST NOT embed
    #    its own (impossible/recursive) SHA -> sha256:null + self_referential.
    #  - final_artifact_inventory.json : same non-recursive treatment as before.
    #  - every other permanent artifact: SHA from actual file bytes (must exist).
    FINALIZER_GENERATED = ("artifact_reproducibility.json",
                          "final_evidence_summary.json",
                          "final_artifact_inventory.json")
    canonical = canonical_permanent_artifacts()
    canonical_set = set(canonical)
    inventory: dict[str, Any] = {}
    for fn in canonical:
        p = out / fn
        entry: dict[str, Any] = {"role": "permanent_artifact"}
        if fn == "artifact_reproducibility.json":
            # Just-written final bytes -> real SHA.
            entry["bytes"] = int(p.stat().st_size)
            entry["sha256"] = sha256(p)
            entry["inclusion_status"] = "generated_by_finalizer"
        elif fn == "final_evidence_summary.json":
            # Impossible self-SHA: declare deterministically, never require the
            # not-yet-written file to exist, never embed its own SHA.
            entry["sha256"] = None
            entry["self_referential"] = True
            entry["inclusion_status"] = "generated_by_finalizer"
        elif fn == "final_artifact_inventory.json":
            # Continue non-recursive handling.
            entry["sha256"] = None
            entry["self_inventory"] = True
            entry["inclusion_status"] = "generated_by_finalizer"
        elif p.is_file():
            entry["bytes"] = int(p.stat().st_size)
            entry["sha256"] = sha256(p)
        else:
            entry["missing"] = True
        inventory[fn] = entry

    # Inventory completeness gate inputs (evaluated in the aggregate below).
    duplicate_paths = [w for w in set(canonical) if canonical.count(w) > 1]
    missing_expected = sorted(canonical_set - set(inventory))
    inventory_missing_files = [fn for fn, e in inventory.items() if e.get("missing")]
    declared_inventory = set(inventory.keys())

    # Corruption detection: if a previously published final_artifact_inventory
    # exists, verify every non-self, non-finalizer-generated SHA it declared
    # still matches the current file bytes. This detects a permanent artifact
    # that changed after it was documented. Regenerated finalizer outputs
    # (summary + inventory) are intentionally excluded because they are
    # self-referential; artifact_reproducibility is validated from its final
    # post-write bytes above.
    prior_inventory_path = out / "final_artifact_inventory.json"
    inventory_sha_mismatches: list[str] = []
    if prior_inventory_path.is_file():
        try:
            prior = json.loads(prior_inventory_path.read_text()) or {}
        except Exception:  # noqa: BLE001 - malformed prior manifest is itself a mismatch
            prior = {}
        for prior_fn, prior_entry in prior.items():
            if not isinstance(prior_entry, dict) or prior_entry.get("sha256") is None:
                continue  # skip self-inventory / non-sha entries
            if prior_fn in FINALIZER_GENERATED:
                continue  # regenerated each run; not a stable corruption probe
            prior_p = out / prior_fn
            if not prior_p.is_file():
                inventory_sha_mismatches.append(prior_fn)
                continue
            if sha256(prior_p) != prior_entry["sha256"]:
                inventory_sha_mismatches.append(prior_fn)

    inventory_ok = bool(
        not duplicate_paths
        and not missing_expected
        and not inventory_missing_files
        and not inventory_sha_mismatches
        and declared_inventory == canonical_set
    )

    # ---- 12. Final-evidence provenance (Phase 5B-2) ----
    provenance = build_provenance(root, out)

    # ---- 13. Assemble evidence summary ----
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
        "provenance": provenance,
    }
    (out / "final_evidence_summary.json").write_text(
        json.dumps(evidence, indent=2, default=str) + "\n"
    )
    (out / "final_artifact_inventory.json").write_text(
        json.dumps(inventory, indent=2, default=str) + "\n"
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
    # Inventory completeness: canonical permanent set == declared inventory,
    # no missing files, no duplicate paths, all recorded SHAs match bytes.
    finalize_gates["inventory_complete"] = inventory_ok
    # Provenance completeness: every mandatory provenance source must exist
    # and be hashable (non-empty SHA). Fail closed if any is unavailable.
    provenance_required = [
        "finalizer_source_sha256", "evaluator_source_sha256",
        "official_runner_source_sha256", "analyze_script_source_sha256",
        "evaluate_script_source_sha256", "qb_elo_config_sha256",
        "task04c_reference_input_sha256", "task04c_oracle_resolver_input_sha256",
        "incumbent_reference_candidate_sha256",
    ]
    finalize_gates["provenance_sources_present"] = all(
        provenance.get(k) for k in provenance_required
    )
    # Config / incumbent consistency: the production season reversion fraction
    # read from config/qb_elo_v1.yaml must equal the Task04D incumbent fraction.
    # A missing/unparseable config already fails the provenance-source gate.
    config_fraction = provenance["qb_elo_config_season_mean_reversion_fraction"]
    finalize_gates["config_reference_consistency"] = (
        config_fraction is not None
        and abs(config_fraction - TASK04C_REFERENCE_FRACTION) <= 1e-9
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