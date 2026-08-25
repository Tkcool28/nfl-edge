#!/usr/bin/env python3
"""Read-only audit of Task05G V2 spread model-confidence behavior.

This diagnostic does not change the Expected Margin model, Task05F evaluator,
V2 selector rules, price thresholds, or 2025 seal. It measures whether the
strictly-prior empirical-residual confidence mapping is stale/overconfident,
with special attention to the 2023 regime change observed in prior forensics.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Mapping

import numpy as np
import polars as pl

DEV_CONFIRM = (2020, 2021, 2022, 2023, 2024)
CONF_BUCKETS = (
    (0.00, 0.55, "<55%"),
    (0.55, 0.60, "55-60%"),
    (0.60, 0.65, "60-65%"),
    (0.65, 0.70, "65-70%"),
    (0.70, 0.75, "70-75%"),
    (0.75, 0.80, "75-80%"),
    (0.80, 1.01, ">=80%"),
)
COVER_MARGIN_BUCKETS = (
    (-999.0, 0.0, "<0"),
    (0.0, 2.0, "0-2"),
    (2.0, 4.0, "2-4"),
    (4.0, 6.0, "4-6"),
    (6.0, 8.0, "6-8"),
    (8.0, 999.0, ">=8"),
)


def _load_core():
    path = Path(__file__).with_name("task05g_model_confidence_v2_runner.py")
    spec = importlib.util.spec_from_file_location("task05g_model_confidence_v2_runner_audit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load V2 core runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    x = float(value)
    return x if math.isfinite(x) else None


def _bucket(value: float, bins) -> str:
    for lo, hi, label in bins:
        if lo <= value < hi:
            return label
    return "out_of_range"


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(str(r.get("settlement")) == "WIN" for r in rows)
    losses = sum(str(r.get("settlement")) == "LOSS" for r in rows)
    pushes = sum(str(r.get("settlement")) == "PUSH" for r in rows)
    nonpush = wins + losses
    qs = [_finite(r.get("model_confidence_probability")) for r in rows]
    qs = [x for x in qs if x is not None]
    margins = [_finite(r.get("model_cover_margin")) for r in rows]
    margins = [x for x in margins if x is not None]
    profits = [_finite(r.get("realized_profit")) for r in rows]
    profits = [x for x in profits if x is not None]
    actual = None if nonpush == 0 else wins / nonpush
    avg_q = None if not qs else float(mean(qs))
    return {
        "n": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": actual,
        "avg_model_confidence_probability": avg_q,
        "calibration_error_actual_minus_predicted": None if actual is None or avg_q is None else actual - avg_q,
        "avg_model_cover_margin": None if not margins else float(mean(margins)),
        "roi": None if not profits else float(mean(profits)),
    }


def _group_summary(rows: list[dict[str, Any]], key_fn) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(str(key_fn(r)), []).append(r)
    return {k: _summary(groups[k]) for k in sorted(groups)}


def _residual_stats(values: Iterable[float]) -> dict[str, Any]:
    xs = [float(x) for x in values if math.isfinite(float(x))]
    if not xs:
        return {"n": 0, "mean": None, "std": None, "mae": None, "abs_p50": None, "abs_p75": None, "abs_p90": None, "abs_p95": None}
    arr = np.asarray(xs, dtype=float)
    abs_arr = np.abs(arr)
    return {
        "n": len(xs),
        "mean": float(np.mean(arr)),
        "std": None if len(xs) < 2 else float(np.std(arr, ddof=1)),
        "mae": float(np.mean(abs_arr)),
        "abs_p50": float(np.quantile(abs_arr, 0.50)),
        "abs_p75": float(np.quantile(abs_arr, 0.75)),
        "abs_p90": float(np.quantile(abs_arr, 0.90)),
        "abs_p95": float(np.quantile(abs_arr, 0.95)),
    }


def _season_residual_comparison(history: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    finite_history = [r for r in history if _finite(r.get("margin_residual")) is not None]
    for season in DEV_CONFIRM:
        prior = [_finite(r["margin_residual"]) for r in finite_history if int(r["season"]) < season]
        actual = [_finite(r["margin_residual"]) for r in finite_history if int(r["season"]) == season]
        prior_stats = _residual_stats(x for x in prior if x is not None)
        actual_stats = _residual_stats(x for x in actual if x is not None)
        out[str(season)] = {
            "entering_season_prior": prior_stats,
            "realized_in_season": actual_stats,
            "std_ratio_actual_to_prior": None if not prior_stats["std"] or actual_stats["std"] is None else actual_stats["std"] / prior_stats["std"],
            "mae_ratio_actual_to_prior": None if not prior_stats["mae"] or actual_stats["mae"] is None else actual_stats["mae"] / prior_stats["mae"],
            "p90_abs_ratio_actual_to_prior": None if not prior_stats["abs_p90"] or actual_stats["abs_p90"] is None else actual_stats["abs_p90"] / prior_stats["abs_p90"],
        }
    return out


def _conditional_residuals(history: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [r for r in history if _finite(r.get("margin_residual")) is not None and _finite(r.get("expected_home_margin")) is not None]
    buckets = {
        "abs_expected_margin_<3": [],
        "abs_expected_margin_3-7": [],
        "abs_expected_margin_7-10": [],
        "abs_expected_margin_>=10": [],
    }
    signed = {"expected_home_negative": [], "expected_home_0-7": [], "expected_home_>=7": []}
    for r in rows:
        pred = float(r["expected_home_margin"])
        resid = float(r["margin_residual"])
        a = abs(pred)
        if a < 3:
            buckets["abs_expected_margin_<3"].append(resid)
        elif a < 7:
            buckets["abs_expected_margin_3-7"].append(resid)
        elif a < 10:
            buckets["abs_expected_margin_7-10"].append(resid)
        else:
            buckets["abs_expected_margin_>=10"].append(resid)
        if pred < 0:
            signed["expected_home_negative"].append(resid)
        elif pred < 7:
            signed["expected_home_0-7"].append(resid)
        else:
            signed["expected_home_>=7"].append(resid)
    return {
        "by_abs_expected_margin": {k: _residual_stats(v) for k, v in buckets.items()},
        "by_signed_expected_margin": {k: _residual_stats(v) for k, v in signed.items()},
    }


def _manual_settlement(home_margin: float, side: str, line: float) -> str:
    graded = home_margin + line if side == "home" else -home_margin + line
    if graded > 1e-9:
        return "WIN"
    if graded < -1e-9:
        return "LOSS"
    return "PUSH"


def run(root: Path, candidate_path: Path, out: Path) -> None:
    core = _load_core()
    history = core._history_rows(root)
    game = {str(r["game_id"]): r for r in history}
    raw_rows = pl.read_parquet(candidate_path).to_dicts()
    if any(int(r["season"]) == 2025 for r in raw_rows):
        raise RuntimeError("sealed 2025 entered spread-confidence audit")

    # Match the selector's common exact-offer shopping stage block by block.
    shopped: list[dict[str, Any]] = []
    by_block: dict[str, list[dict[str, Any]]] = {}
    for r in raw_rows:
        by_block.setdefault(str(r["block"]), []).append(dict(r))
    for block in sorted(by_block, key=core._block_tuple):
        shopped.extend(dict(r) for r in core.shop_exact_offers(by_block[block]))

    spreads: list[dict[str, Any]] = []
    orientation_mismatches: list[dict[str, Any]] = []
    for src in shopped:
        if str(src.get("market_type")) != "spread":
            continue
        q = _finite(src.get("model_confidence_probability"))
        if q is None or not bool(src.get("model_confidence_supported")):
            continue
        g = game.get(str(src["game_id"]))
        if g is None or _finite(g.get("expected_home_margin")) is None or _finite(g.get("home_margin")) is None:
            continue
        r = dict(src)
        expected = float(g["expected_home_margin"])
        line = float(r["line"])
        side = str(r["selected_side"]).lower()
        r["expected_home_margin"] = expected
        r["actual_home_margin"] = float(g["home_margin"])
        r["actual_margin_residual"] = float(g["margin_residual"])
        r["model_cover_margin"] = expected + line if side == "home" else -expected + line
        r["confidence_bucket"] = _bucket(q, CONF_BUCKETS)
        r["model_cover_margin_bucket"] = _bucket(float(r["model_cover_margin"]), COVER_MARGIN_BUCKETS)
        manual = _manual_settlement(float(g["home_margin"]), side, line)
        if manual != str(r.get("settlement")):
            orientation_mismatches.append({"game_id": r["game_id"], "side": side, "line": line, "stored": r.get("settlement"), "manual": manual})
        spreads.append(r)

    # Reconstruct actual V2 HHR and frozen Balanced B0 selections.
    hhr: list[dict[str, Any]] = []
    balanced: list[dict[str, Any]] = []
    for block in sorted(by_block, key=core._block_tuple):
        block_rows = by_block[block]
        h = core._select_hhr(block_rows)
        b = core._select_balanced(block_rows, core.BALANCED_TOLERANCES["B0"])
        for choice, target in ((h, hhr), (b, balanced)):
            if choice is None or str(choice.get("market_type")) != "spread":
                continue
            g = game[str(choice["game_id"])]
            r = dict(choice)
            expected = float(g["expected_home_margin"])
            line = float(r["line"])
            side = str(r["selected_side"]).lower()
            r["model_cover_margin"] = expected + line if side == "home" else -expected + line
            r["confidence_bucket"] = _bucket(float(r["model_confidence_probability"]), CONF_BUCKETS)
            r["model_cover_margin_bucket"] = _bucket(float(r["model_cover_margin"]), COVER_MARGIN_BUCKETS)
            target.append(r)

    # First half / second half of 2023 reveals whether weekly residual updates corrected confidence.
    y2023 = [r for r in spreads if int(r["season"]) == 2023]
    early23 = [r for r in y2023 if int(str(r["week"])) <= 9]
    late23 = [r for r in y2023 if int(str(r["week"])) >= 10]

    result = {
        "verdict_scope": "read-only spread confidence chronology/calibration audit",
        "sealed_season": 2025,
        "orientation_settlement_mismatch_count": len(orientation_mismatches),
        "orientation_settlement_mismatch_examples": orientation_mismatches[:10],
        "season_residual_regime": _season_residual_comparison(history),
        "residual_conditioning": _conditional_residuals(history),
        "all_exact_shopped_supported_spreads": {
            "overall": _summary(spreads),
            "by_season": _group_summary(spreads, lambda r: int(r["season"])),
            "by_confidence_bucket": _group_summary(spreads, lambda r: r["confidence_bucket"]),
            "by_season_and_confidence_bucket": {
                str(s): _group_summary([r for r in spreads if int(r["season"]) == s], lambda r: r["confidence_bucket"])
                for s in DEV_CONFIRM
            },
            "by_model_cover_margin_bucket": _group_summary(spreads, lambda r: r["model_cover_margin_bucket"]),
            "y2023_early_weeks_1_9": _summary(early23),
            "y2023_late_weeks_10_plus": _summary(late23),
        },
        "selected_hhr_spreads": {
            "overall": _summary(hhr),
            "by_season": _group_summary(hhr, lambda r: int(r["season"])),
            "by_confidence_bucket": _group_summary(hhr, lambda r: r["confidence_bucket"]),
            "by_model_cover_margin_bucket": _group_summary(hhr, lambda r: r["model_cover_margin_bucket"]),
        },
        "selected_balanced_b0_spreads": {
            "overall": _summary(balanced),
            "by_season": _group_summary(balanced, lambda r: int(r["season"])),
            "by_confidence_bucket": _group_summary(balanced, lambda r: r["confidence_bucket"]),
            "by_model_cover_margin_bucket": _group_summary(balanced, lambda r: r["model_cover_margin_bucket"]),
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    run(Path(args.root), Path(args.candidates), Path(args.out))
