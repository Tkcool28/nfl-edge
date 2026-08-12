"""Task 04D official five-run season-regression evaluation (Chunk 3).

Executes exactly five frozen configurations on the development universe
(2018-2024, 1,942 games), writes per-candidate prediction artifacts + the
season-boundary audit ledger + machine-readable metrics under
``data/derived/qb_elo_season_regression_v1/``, and performs:

- 33.3% Task04C identity verification
- cross-run pairability proof
- pre-boundary divergence sanity check
- determinism replay (0% + best-apparent nonzero candidate by Week 1-4 Brier)

The only candidate-dependent model parameter is
``season_mean_reversion_fraction``. No candidate is selected / adjudicated
here; that is Chunk 4.

Usage (from the Task04D worktree root, main checkout's venv):

    PYTHONPATH=src /root/nfl-edge/.venv/bin/python scripts/official_qb_elo_season_regression.py \
        --project-root . --out data/derived/qb_elo_season_regression_v1
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from nfl_edge.backtest.task04c_paired_evaluation import OracleQBAdjustments
from nfl_edge.backtest.task04d_season_regression_evaluation import (
    CANDIDATE_FRACTIONS,
    CANDIDATE_LABELS,
    build_candidate_config,
    build_prediction_artifact,
    build_season_boundary_audit,
    load_canonical_config,
    metric_deltas,
    metrics_for,
    postseason_metrics_for,
    reg_metrics_for,
    season_week1_4_metrics,
    week1_4_metrics_for,
    weeks5plus_metrics_for,
)
from nfl_edge.backtest.walk_forward import run_development_walk_forward

SEASONS = [2018, 2019, 2020, 2021, 2022, 2023, 2024]
ROLE = {
    "regression_000": "control",
    "regression_025": "candidate",
    "regression_040": "candidate",
    "regression_060": "candidate",
    "task04c_reference_0333": "incumbent_reference",
}
ACCEPTED_TASK04C = {
    "brier": 0.221918210006,
    "log_loss": 0.635506991355,
    "accuracy": 0.647785787848,
}
CREATED_AT = datetime(2026, 8, 10, 16, 0, 0, tzinfo=timezone.utc)
_TOL = 1e-6


def rel(root: str | Path, *parts: str) -> Path:
    return Path(root).joinpath(*parts)


def run_candidate(
    root: Path,
    out_root: Path,
    label: str,
    oracle: OracleQBAdjustments,
    base_config: dict[str, Any],
) -> dict[str, Any]:
    fraction = CANDIDATE_FRACTIONS[label]
    run_dir = out_root / "runs" / label
    run_development_walk_forward(
        games_path=rel(root, "data/derived/features_v1/game_features_2018_2025.parquet"),
        team_features_path=rel(
            root, "data/derived/features_v1/team_pregame_features_2018_2025.parquet"
        ),
        output_dir=run_dir,
        config=build_candidate_config(base_config, fraction),
        created_at=CREATED_AT,
        project_root=root,
        qb_adjustment_resolver=oracle,
    )
    preds = pl.read_parquet(run_dir / "qb_elo_predictions_2018_2024.parquet")
    state = pl.read_parquet(run_dir / "qb_elo_state_transitions_2018_2024.parquet")
    artifact = build_prediction_artifact(preds, label, fraction)
    artifact.write_parquet(out_root / f"predictions_{label}.parquet")
    audit = build_season_boundary_audit(preds, state, fraction, candidate_label=label)
    audit.write_parquet(out_root / f"season_boundary_audit_{label}.parquet")
    return {
        "label": label,
        "fraction": fraction,
        "role": ROLE[label],
        "preds": preds,
        "state": state,
        "artifact": artifact,
        "audit": audit,
        "run_dir": str(run_dir),
    }


def collect_metrics(res: dict[str, Any]) -> dict[str, Any]:
    p = res["preds"]
    return {
        "label": res["label"],
        "fraction": res["fraction"],
        "role": res["role"],
        "week1_4": week1_4_metrics_for(p),
        "weeks5plus": weeks5plus_metrics_for(p),
        "reg": reg_metrics_for(p),
        "postseason": postseason_metrics_for(p),
        "full": metrics_for(p),
        "season_week1_4": {
            str(s): season_week1_4_metrics(p, s) for s in SEASONS
        },
    }


def build_segment_table(
    metrics: dict[str, dict[str, Any]], base000: dict[str, Any], base333: dict[str, Any]
) -> list[dict[str, Any]]:
    segments = ["week1_4", "weeks5plus", "reg", "postseason", "full"]
    rows: list[dict[str, Any]] = []
    for label in CANDIDATE_LABELS:
        m = metrics[label]
        for seg in segments:
            mv = m[seg]
            d0 = metric_deltas(mv, base000[seg])
            d3 = metric_deltas(mv, base333[seg])
            rows.append(
                {
                    "candidate": label,
                    "fraction": m["fraction"],
                    "role": m["role"],
                    "segment": seg,
                    "n": mv["n_scored"],
                    "brier": mv["brier"],
                    "log_loss": mv["log_loss"],
                    "accuracy": mv["accuracy"],
                    "brier_delta_vs_000": d0["brier_delta"],
                    "log_loss_delta_vs_000": d0["log_loss_delta"],
                    "brier_delta_vs_0333": d3["brier_delta"],
                    "log_loss_delta_vs_0333": d3["log_loss_delta"],
                }
            )
    return rows


def build_season_week1_4_table(metrics: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label in CANDIDATE_LABELS:
        m = metrics[label]["season_week1_4"]
        for s in SEASONS:
            sv = m[str(s)]
            rows.append(
                {
                    "candidate": label,
                    "fraction": CANDIDATE_FRACTIONS[label],
                    "season": s,
                    "n": sv["n_scored"],
                    "brier": sv["brier"],
                    "log_loss": sv["log_loss"],
                    "accuracy": sv["accuracy"],
                }
            )
    return rows


def pairability(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ref = results["regression_000"]["artifact"]
    ref_gid = ref["game_id"].to_list()
    checks_cols = {
        "target_outcome": "targets",
        "season": "seasons",
        "week": "weeks",
        "season_type": "season_types",
        "home_team": "home_teams",
        "away_team": "away_teams",
        "block_id": "block_ids",
    }
    all_ok = True
    matrix: dict[str, dict[str, bool]] = {}
    for label in CANDIDATE_LABELS:
        a = results[label]["artifact"]
        m: dict[str, bool] = {
            "row_count_1942": a.height == 1942,
            "game_id_order": a["game_id"].to_list() == ref_gid,
        }
        for col, name in checks_cols.items():
            m[f"{name}_match"] = a[col].to_list() == ref[col].to_list()
        matrix[label] = m
        if not all(m.values()):
            all_ok = False
    return {"pairable": bool(all_ok), "matrix": matrix}


def verify_identity(res: dict[str, Any], committed: Path) -> dict[str, Any]:
    mine = res["preds"].sort("game_id")
    theirs = pl.read_parquet(committed).sort("game_id")
    ok_order = mine["game_id"].to_list() == theirs["game_id"].to_list()
    max_diffs: dict[str, float] = {}
    for col in (
        "home_elo_before",
        "away_elo_before",
        "home_qb_adjustment",
        "away_qb_adjustment",
        "predicted_home_win_probability",
    ):
        a = mine[col].to_list()
        b = theirs[col].to_list()
        max_diffs[col] = max(abs(x - y) for x, y in zip(a, b))
    pred_max = max_diffs["predicted_home_win_probability"]
    m = metrics_for(mine)
    metric_match = all(
        math.isclose(m[k], v, rel_tol=1e-9, abs_tol=1e-9) for k, v in ACCEPTED_TASK04C.items()
    )
    passed = (
        ok_order
        and pred_max <= _TOL
        and max(max_diffs.values()) <= _TOL
        and metric_match
    )
    return {
        "identity_passed": bool(passed),
        "game_id_order_identical": bool(ok_order),
        "max_abs_diff_by_column": max_diffs,
        "my_metrics": m,
        "accepted_metrics": ACCEPTED_TASK04C,
        "metric_match": bool(metric_match),
    }


def pre_boundary_sanity(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    # 2018 predictions identical across all candidates (no pre-window regression).
    for col in ("home_elo_before", "away_elo_before", "predicted_home_win_probability"):
        vals = {}
        for label in CANDIDATE_LABELS:
            a = results[label]["artifact"].filter(pl.col("season") == 2018)
            vals[label] = a[col].to_list()
        ref = vals["regression_000"]
        checks[f"2018_{col}_identical"] = all(v == ref for v in vals.values())
    # QB adjustments identical across all candidates for ALL games.
    qb_home = {}
    qb_away = {}
    for label in CANDIDATE_LABELS:
        a = results[label]["artifact"]
        qb_home[label] = a["home_qb_adjustment"].to_list()
        qb_away[label] = a["away_qb_adjustment"].to_list()
    refh = qb_home["regression_000"]
    refa = qb_away["regression_000"]
    checks["qb_home_identical_all"] = all(v == refh for v in qb_home.values())
    checks["qb_away_identical_all"] = all(v == refa for v in qb_away.values())
    # At 2018->2019 boundary each candidate applies its fraction.
    sample = {}
    for label in CANDIDATE_LABELS:
        aud = results[label]["audit"].filter(
            (pl.col("previous_season") == 2018) & (pl.col("new_season") == 2019)
        )
        # verify all PASS
        checks[f"{label}_2018_2019_all_pass"] = bool((aud["status"] == "PASS").all())
        row_ari = aud.filter(pl.col("team") == "ARI")
        if row_ari.height:
            r = row_ari.row(0, named=True)
            sample[label] = {
                "prior": r["prior_season_ending_elo"],
                "expected": r["expected_new_elo"],
                "actual": r["actual_new_elo"],
                "frac": r["regression_fraction"],
            }
    passed = all(checks.values())
    return {"passed": bool(passed), "checks": checks, "ari_2018_2019_sample": sample}


def replay_check(
    results: dict[str, dict[str, Any]],
    root: Path,
    out_root: Path,
    oracle: OracleQBAdjustments,
    base_config: dict[str, Any],
    labels: list[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label in labels:
        with tempfile.TemporaryDirectory(prefix=f"task04d_replay_{label}_") as td:
            run_development_walk_forward(
                games_path=rel(root, "data/derived/features_v1/game_features_2018_2025.parquet"),
                team_features_path=rel(
                    root, "data/derived/features_v1/team_pregame_features_2018_2025.parquet"
                ),
                output_dir=Path(td),
                config=build_candidate_config(base_config, CANDIDATE_FRACTIONS[label]),
                created_at=CREATED_AT,
                project_root=root,
                qb_adjustment_resolver=oracle,
            )
            replay_preds = pl.read_parquet(Path(td) / "qb_elo_predictions_2018_2024.parquet")
        official = results[label]["preds"].sort("game_id")
        replay = replay_preds.sort("game_id")
        same_order = official["game_id"].to_list() == replay["game_id"].to_list()
        p_diff = max(
            abs(x - y)
            for x, y in zip(
                official["predicted_home_win_probability"].to_list(),
                replay["predicted_home_win_probability"].to_list(),
            )
        )
        m_o = metrics_for(official)
        m_r = metrics_for(replay)
        metric_equal = all(math.isclose(m_o[k], m_r[k], rel_tol=1e-9, abs_tol=1e-9) for k in m_o)
        out[label] = {
            "game_id_order_identical": bool(same_order),
            "max_prob_diff": float(p_diff),
            "metrics_equal": bool(metric_equal),
            "official_metrics": m_o,
            "replay_metrics": m_r,
        }
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    root = Path(args.project_root).resolve()
    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    oracle = OracleQBAdjustments(
        rel(root, "data/derived/oracle_qb_entering_state_v2"
            "/oracle_qb_pregame_adjustments_by_game_2018_2024_v2.parquet")
    )
    base_config = load_canonical_config(root)
    committed_0333 = rel(
        root,
        "data/derived/qb_elo_oracle_comparison_v1"
        "/qb_elo_oracle_predictions_2018_2024.parquet",
    )

    # Phase 1: run all five candidates.
    results: dict[str, dict[str, Any]] = {}
    for label in CANDIDATE_LABELS:
        print(f"running {label} (fraction={CANDIDATE_FRACTIONS[label]})...", flush=True)
        results[label] = run_candidate(root, out_root, label, oracle, base_config)

    # Combined audit ledger.
    combined = pl.concat([results[lb]["audit"] for lb in CANDIDATE_LABELS])
    combined.write_parquet(out_root / "season_boundary_audit_all.parquet")

    # Phase 2: metrics.
    metrics = {lb: collect_metrics(results[lb]) for lb in CANDIDATE_LABELS}
    segment_table = build_segment_table(metrics, metrics["regression_000"], metrics["task04c_reference_0333"])
    season_table = build_season_week1_4_table(metrics)
    (out_root / "metrics_segments.json").write_text(json.dumps(segment_table, indent=2) + "\n")
    (out_root / "metrics_season_week1_4.json").write_text(json.dumps(season_table, indent=2) + "\n")

    # Phase 3: identity verification.
    identity = verify_identity(results["task04c_reference_0333"], committed_0333)
    (out_root / "identity_verification.json").write_text(json.dumps(identity, indent=2) + "\n")

    # Phase 4: pairability.
    pair = pairability(results)
    (out_root / "pairability_matrix.json").write_text(json.dumps(pair, indent=2) + "\n")

    # Phase 5: pre-boundary sanity.
    sanity = pre_boundary_sanity(results)
    (out_root / "boundary_sanity.json").write_text(json.dumps(sanity, indent=2) + "\n")

    # Phase 6: determinism replay (0% + best nonzero by Week 1-4 Brier).
    nonzero = [lb for lb in ("regression_025", "regression_040", "regression_060")]
    best = min(nonzero, key=lambda lb: metrics[lb]["week1_4"]["brier"])
    replay = replay_check(results, root, out_root, oracle, base_config, ["regression_000", best])
    (out_root / "replay_determinism.json").write_text(json.dumps(replay, indent=2) + "\n")

    summary = {
        "task04c_identity": identity["identity_passed"],
        "pairable": pair["pairable"],
        "pre_boundary_sanity_passed": sanity["passed"],
        "week1_4_n": int(metrics["regression_000"]["week1_4"]["n_scored"]),
        "combined_audit_rows": int(combined.height),
        "combined_audit_pass": int(combined.filter(pl.col("status") == "PASS").height),
        "replay_validation_passed": bool(
            all(
                replay[lb]["game_id_order_identical"] and replay[lb]["metrics_equal"]
                for lb in replay
            )
        ),
        "best_nonzero_week1_4_brier": {"candidate": best, "brier": metrics[best]["week1_4"]["brier"]},
    }
    (out_root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))

    # ---- Official run aggregate fail-closed gate (Phase 5B-1) ----
    # Every validation produced by this workflow must pass before the run is
    # treated as official. A failed gate returns nonzero instead of silently
    # reporting success; nothing that failed is promoted to "true".
    official_gates = {
        "identity": bool(identity["identity_passed"]),
        "pairability": bool(pair["pairable"]),
        "boundary_sanity": bool(sanity["passed"]),
        "combined_audit": int(combined.filter(pl.col("status") == "PASS").height) == int(combined.height),
        "replay_validation": bool(summary["replay_validation_passed"]),
    }
    failed = [k for k, v in official_gates.items() if not v]
    if failed:
        sys.stderr.write(f"OFFICIAL RUN FAILED GATES: {failed}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
