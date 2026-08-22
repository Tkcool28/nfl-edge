#!/usr/bin/env python3
"""Read-only Task05F Spread V3 contribution diagnostic.

This script does not fit or alter an evaluator. It decomposes the already
materialized corrected OOS board to answer one review question: is the frozen
spread-region value separation actually driven by Expected Margin contribution,
or mostly by the market/residual calibration when the fitted beta is zero?
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
FINAL_RUNNER = ROOT / "scripts" / "task05f_evaluator_final_runner.py"


def _load_final():
    spec = importlib.util.spec_from_file_location("task05f_final_for_spread_diag", FINAL_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load final evaluator runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FINAL = _load_final()


def _metrics(rows: list[dict], probability_key: str) -> dict:
    material = [
        row for row in rows
        if row.get("settlement") in {"WIN", "LOSS"} and row.get(probability_key) is not None
    ]
    if not material:
        return {"n": 0, "brier": None, "auc": None}
    p = np.asarray([float(row[probability_key]) for row in material], dtype=float)
    y = np.asarray([1 if row["settlement"] == "WIN" else 0 for row in material], dtype=int)
    return {
        "n": len(material),
        "brier": float(np.mean((p - y) ** 2)),
        "auc": float(roc_auc_score(y, p)) if len(set(y.tolist())) == 2 else None,
    }


def _profit_pack(pairs: list[tuple[dict, dict, float]]) -> dict:
    if not pairs:
        return {
            "n": 0,
            "roi": None,
            "positive_ev_n": 0,
            "selected_model_favors_wager_n": 0,
            "mean_selected_model_market_gap_points": None,
            "mean_model_contribution_points": None,
        }
    selected_gaps = [float(item[2]) for item in pairs]
    contributions = [float(candidate["spread_beta"]) * gap for _, candidate, gap in pairs]
    profits = [float(base["profit"]) for base, _, _ in pairs]
    return {
        "n": len(pairs),
        "roi": float(np.mean(profits)),
        "positive_ev_n": sum(float(candidate["expected_value"]) > 0.0 for _, candidate, _ in pairs),
        "selected_model_favors_wager_n": sum(gap > 0.0 for gap in selected_gaps),
        "mean_selected_model_market_gap_points": float(np.mean(selected_gaps)),
        "mean_model_contribution_points": float(np.mean(contributions)),
    }


def run(artifact_dir: Path, out: Path) -> dict:
    states = [
        json.loads(line)
        for line in (artifact_dir / "state_by_block.ndjson").read_text().splitlines()
        if line.strip()
    ]
    beta_by_block = {
        str(row["block"]): row.get("spread_beta")
        for row in states
        if row.get("spread_beta") is not None
    }
    beta_values = np.asarray([float(value) for value in beta_by_block.values()], dtype=float)

    board = pl.read_parquet(artifact_dir / "historical_evaluator_board.parquet")
    spread_rows = board.filter(pl.col("market_type") == "spread").to_dicts()
    enriched: list[dict] = []
    for row in spread_rows:
        beta = beta_by_block.get(str(row["block"]))
        copy = dict(row)
        copy["spread_beta"] = beta
        enriched.append(copy)

    supported = [row for row in enriched if row.get("supported") and row.get("spread_beta") is not None]
    zero_beta = [row for row in supported if abs(float(row["spread_beta"])) <= 1e-12]
    positive_beta = [row for row in supported if float(row["spread_beta"]) > 1e-12]

    frozen = FINAL._frozen_candidate_rows(ROOT)["SPREAD_0_4_DISCOVERY_UNION"]
    index = {
        (
            row["game_id"],
            row["selected_side"],
            round(float(row["line"]), 6),
            int(row["american_odds"]),
        ): row
        for row in enriched
        if row.get("line") is not None
    }
    matched: list[tuple[dict, dict, float]] = []
    for base in frozen:
        if base.get("reconstructed_line") is None:
            continue
        key = (
            base["game_id"],
            base["selected_side"],
            round(float(base["reconstructed_line"]), 6),
            int(base["price_american"]),
        )
        candidate = index.get(key)
        if candidate is None or not candidate.get("supported") or candidate.get("spread_beta") is None:
            continue
        gap_home = candidate.get("model_market_disagreement")
        if gap_home is None:
            continue
        selected_gap = float(gap_home) if candidate["selected_side"] == "home" else -float(gap_home)
        matched.append((base, candidate, selected_gap))

    def subset(*, beta_positive: bool | None = None, ev_positive: bool | None = None):
        rows = matched
        if beta_positive is not None:
            rows = [
                item for item in rows
                if (float(item[1]["spread_beta"]) > 1e-12) == beta_positive
            ]
        if ev_positive is not None:
            rows = [
                item for item in rows
                if (float(item[1]["expected_value"]) > 0.0) == ev_positive
            ]
        return rows

    report = {
        "label": "OBSERVATIONAL_ONLY_NOT_TUNED",
        "question": "source_of_spread_v3_frozen_region_value_separation",
        "fit_state": {
            "supported_blocks": int(beta_values.size),
            "beta_zero_blocks": int(np.sum(np.isclose(beta_values, 0.0))),
            "beta_positive_blocks": int(np.sum(beta_values > 1e-12)),
            "beta_mean": float(np.mean(beta_values)),
            "beta_median": float(np.median(beta_values)),
            "beta_max": float(np.max(beta_values)),
        },
        "full_board_by_beta": {
            "zero_beta": {
                "rows": len(zero_beta),
                "candidate_probability": _metrics(zero_beta, "conditional_nonpush_probability"),
                "market_anchor_probability": _metrics(zero_beta, "staking_anchor_probability"),
                "positive_ev_n": sum(float(row["expected_value"]) > 0.0 for row in zero_beta),
            },
            "positive_beta": {
                "rows": len(positive_beta),
                "candidate_probability": _metrics(positive_beta, "conditional_nonpush_probability"),
                "market_anchor_probability": _metrics(positive_beta, "staking_anchor_probability"),
                "positive_ev_n": sum(float(row["expected_value"]) > 0.0 for row in positive_beta),
            },
        },
        "frozen_spread_region": {
            "supported_joined_with_gap": len(matched),
            "all": _profit_pack(matched),
            "zero_beta_all": _profit_pack(subset(beta_positive=False)),
            "positive_beta_all": _profit_pack(subset(beta_positive=True)),
            "positive_ev_kept_all": _profit_pack(subset(ev_positive=True)),
            "positive_ev_kept_zero_beta": _profit_pack(subset(beta_positive=False, ev_positive=True)),
            "positive_ev_kept_positive_beta": _profit_pack(subset(beta_positive=True, ev_positive=True)),
            "nonpositive_rejected_zero_beta": _profit_pack(subset(beta_positive=False, ev_positive=False)),
            "nonpositive_rejected_positive_beta": _profit_pack(subset(beta_positive=True, ev_positive=False)),
        },
        "interpretation_guard": {
            "may_change_beta_or_threshold_from_this_report": False,
            "may_create_market_or_roi_bucket": False,
            "sealed_2025_loaded": False,
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    run(Path(args.artifact_dir), Path(args.out))
