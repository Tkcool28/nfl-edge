#!/usr/bin/env python3
"""Read-only Task05G ML confidence-tail audit.

Consumes the Spread Confidence V3 candidate table. It does not change football
models, Task05F, selector mechanics, thresholds, or data. 2025 is prohibited.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Iterable, Mapping

import polars as pl

DEV = {2020, 2021, 2022}
DIAG = {2023, 2024}
SEALED = 2025
HHR_FLOORS = (0.55, 0.60, 0.65, 0.70, 0.75)
BAL_FLOORS = (0.52, 0.55, 0.60, 0.65, 0.70, 0.75)
PLAN_PATH = "docs/task05g_ml_confidence_tail_audit_plan.md"


def _load_core(root: Path):
    path = root / "scripts/task05g_model_confidence_v2_runner.py"
    spec = importlib.util.spec_from_file_location("task05g_model_confidence_v2_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load V2 core")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _finite(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _block_tuple(value: str) -> tuple[int, int]:
    season, week = str(value).split("-", 1)
    return int(season), int(week)


def _group_blocks(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(str(row["block"]), []).append(dict(row))
    return out


def _shop_ml(core, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for block, block_rows in sorted(_group_blocks(rows).items(), key=lambda kv: _block_tuple(kv[0])):
        for r in core.shop_exact_offers(block_rows):
            if str(r.get("market_type")) != "moneyline":
                continue
            if not bool(r.get("model_confidence_supported")):
                continue
            q = _finite(r.get("model_confidence_probability"))
            raw = _finite(r.get("raw_avg_probability_selected"))
            qb = _finite(r.get("raw_qbelo_probability_selected"))
            xgb = _finite(r.get("raw_xgb_probability_selected"))
            if q is None or raw is None or qb is None or xgb is None:
                continue
            key = (str(r.get("game_id")), str(r.get("selected_side")))
            if key in seen:
                continue
            seen.add(key)
            rr = dict(r)
            rr["qb_xgb_abs_disagreement"] = abs(qb - xgb)
            rr["calibrated_minus_raw"] = q - raw
            rr["audit_block"] = block
            out.append(rr)
    return out


def _outcome(row: Mapping[str, Any]) -> int | None:
    s = str(row.get("settlement"))
    if s == "WIN":
        return 1
    if s == "LOSS":
        return 0
    return None


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    required = (
        "model_confidence_probability",
        "raw_avg_probability_selected",
        "raw_qbelo_probability_selected",
        "raw_xgb_probability_selected",
    )
    material = [
        r
        for r in rows
        if _outcome(r) is not None
        and all(_finite(r.get(key)) is not None for key in required)
    ]
    if not material:
        return {
            "n": 0,
            "wins": 0,
            "losses": 0,
            "hit_rate": None,
            "avg_model_confidence": None,
            "avg_raw_avg_probability": None,
            "avg_calibrated_minus_raw": None,
            "avg_break_even_probability": None,
            "avg_odds": None,
            "avg_qb_xgb_abs_disagreement": None,
            "calibration_error_actual_minus_predicted": None,
            "brier": None,
            "log_loss": None,
            "roi": None,
        }
    ys = [int(_outcome(r)) for r in material]
    ps = [float(r["model_confidence_probability"]) for r in material]
    raws = [float(r["raw_avg_probability_selected"]) for r in material]
    shifts = [
        float(r["model_confidence_probability"]) - float(r["raw_avg_probability_selected"])
        for r in material
    ]
    bes = [_finite(r.get("break_even_probability")) for r in material]
    bes = [x for x in bes if x is not None]
    odds = [_finite(r.get("american_odds")) for r in material]
    odds = [x for x in odds if x is not None]
    disagreements = [
        abs(float(r["raw_qbelo_probability_selected"]) - float(r["raw_xgb_probability_selected"]))
        for r in material
    ]
    profits = [_finite(r.get("realized_profit")) for r in material]
    profits = [x for x in profits if x is not None]
    eps = 1e-12
    return {
        "n": len(material),
        "wins": sum(ys),
        "losses": len(ys) - sum(ys),
        "hit_rate": float(mean(ys)),
        "avg_model_confidence": float(mean(ps)),
        "avg_raw_avg_probability": float(mean(raws)),
        "avg_calibrated_minus_raw": float(mean(shifts)),
        "avg_break_even_probability": None if not bes else float(mean(bes)),
        "avg_odds": None if not odds else float(mean(odds)),
        "avg_qb_xgb_abs_disagreement": float(mean(disagreements)),
        "calibration_error_actual_minus_predicted": float(mean(ys) - mean(ps)),
        "brier": float(mean((p - y) ** 2 for p, y in zip(ps, ys))),
        "log_loss": float(-mean(y * math.log(max(eps, min(1 - eps, p))) + (1 - y) * math.log(max(eps, min(1 - eps, 1 - p))) for p, y in zip(ps, ys))),
        "roi": None if not profits else float(mean(profits)),
    }


def _q_bucket(q: float) -> str:
    if q < .52: return "<52%"
    if q < .55: return "52-55%"
    if q < .60: return "55-60%"
    if q < .65: return "60-65%"
    if q < .70: return "65-70%"
    if q < .75: return "70-75%"
    return ">=75%"


def _raw_bucket(q: float) -> str:
    return _q_bucket(q)


def _disagreement_bucket(d: float) -> str:
    if d < .02: return "<2pp"
    if d < .05: return "2-5pp"
    if d < .10: return "5-10pp"
    return ">=10pp"


def _odds_bucket(o: int) -> str:
    if o <= -250: return "<=-250"
    if o <= -201: return "-249..-201"
    if o <= -151: return "-200..-151"
    if o <= -111: return "-150..-111"
    if o <= 100: return "-110..+100"
    if o <= 200: return "+101..+200"
    return ">+200"


def _by_bucket(rows: list[dict[str, Any]], labels: list[str], fn: Callable[[dict[str, Any]], str]) -> dict[str, Any]:
    return {label: _summary([r for r in rows if fn(r) == label]) for label in labels}


def _hhr_key(core, r: Mapping[str, Any]):
    return (
        -float(r["model_confidence_probability"]),
        -core._reliability_rank(r.get("reliability")),
        -float(r.get("model_price_gap") if r.get("model_price_gap") is not None else -99.0),
        -int(r.get("american_odds") or -100000),
        core._candidate_id(r),
    )


def _bal_key(core, r: Mapping[str, Any]):
    return (
        -float(r["model_confidence_probability"]),
        -float(r.get("model_price_gap") if r.get("model_price_gap") is not None else -99.0),
        -core._reliability_rank(r.get("reliability")),
        -int(r.get("american_odds") or -100000),
        core._candidate_id(r),
    )


def _eligible_ml_by_block(core, rows: list[dict[str, Any]], seasons: set[int], lane: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for block, block_rows in _group_blocks([r for r in rows if int(r["season"]) in seasons]).items():
        shopped = [dict(r) for r in core.shop_exact_offers(block_rows) if str(r.get("market_type")) == "moneyline"]
        if lane == "hhr":
            candidates = [r for r in shopped if core._hhr_eligible(r)]
            candidates = sorted(candidates, key=lambda r: _hhr_key(core, r))
        elif lane == "balanced":
            candidates = [r for r in shopped if core._balanced_eligible(r, 0.0)]
            candidates = sorted(candidates, key=lambda r: _bal_key(core, r))
        else:
            raise ValueError(lane)
        out[block] = candidates
    return out


def _rank_summaries(blocks: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        f"rank_{rank}": _summary([rows[rank - 1] for rows in blocks.values() if len(rows) >= rank])
        for rank in (1, 2, 3)
    }


def _actual_headlines(core, rows: list[dict[str, Any]], seasons: set[int], lane: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block, block_rows in sorted(_group_blocks([r for r in rows if int(r["season"]) in seasons]).items(), key=lambda kv: _block_tuple(kv[0])):
        if lane == "hhr":
            choice = core._select_hhr(block_rows)
        elif lane == "balanced":
            choice = core._select_balanced(block_rows, 0.0)
        else:
            raise ValueError(lane)
        if choice is not None and str(choice.get("market_type")) == "moneyline":
            out.append(dict(choice))
    return out


def _frontier(core, rows: list[dict[str, Any]], seasons: set[int], lane: str, floors: tuple[float, ...]) -> dict[str, Any]:
    total_blocks = len({str(r["block"]) for r in rows if int(r["season"]) in seasons})
    base = _eligible_ml_by_block(core, rows, seasons, lane)
    result: dict[str, Any] = {}
    for floor in floors:
        selected: list[dict[str, Any]] = []
        for block in sorted(base, key=_block_tuple):
            candidates = [r for r in base[block] if float(r["model_confidence_probability"]) >= floor]
            if candidates:
                selected.append(dict(candidates[0]))
        s = _summary(selected)
        s["play_blocks"] = len(selected)
        s["total_blocks"] = total_blocks
        s["coverage"] = 0.0 if total_blocks == 0 else len(selected) / total_blocks
        result[f">={floor:.0%}"] = s
    return result


def _season_entry_states(core, root: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    history = core._history_rows(root)
    out: dict[str, Any] = {}
    for season in sorted(DEV | DIAG):
        blocks = sorted({str(r["block"]) for r in rows if int(r["season"]) == season}, key=_block_tuple)
        if not blocks:
            continue
        first = _block_tuple(blocks[0])
        prior = [r for r in history if _block_tuple(str(r["block"])) < first]
        out[str(season)] = core._fit_ml_state(prior)
    return out


def _phase(core, root: Path, rows: list[dict[str, Any]], shopped_ml: list[dict[str, Any]], seasons: set[int]) -> dict[str, Any]:
    pool = [r for r in shopped_ml if int(r["season"]) in seasons]
    q_labels = ["<52%", "52-55%", "55-60%", "60-65%", "65-70%", "70-75%", ">=75%"]
    d_labels = ["<2pp", "2-5pp", "5-10pp", ">=10pp"]
    o_labels = ["<=-250", "-249..-201", "-200..-151", "-150..-111", "-110..+100", "+101..+200", ">+200"]

    hhr_blocks = _eligible_ml_by_block(core, rows, seasons, "hhr")
    bal_blocks = _eligible_ml_by_block(core, rows, seasons, "balanced")
    hhr_pool = [r for rr in hhr_blocks.values() for r in rr]
    bal_pool = [r for rr in bal_blocks.values() for r in rr]
    hhr_head = _actual_headlines(core, rows, seasons, "hhr")
    bal_head = _actual_headlines(core, rows, seasons, "balanced")

    return {
        "seasons": sorted(seasons),
        "all_supported_exact_shopped_ml": {
            "overall": _summary(pool),
            "by_model_confidence_bucket": _by_bucket(pool, q_labels, lambda r: _q_bucket(float(r["model_confidence_probability"]))),
            "by_raw_avg_bucket": _by_bucket(pool, q_labels, lambda r: _raw_bucket(float(r["raw_avg_probability_selected"]))),
            "by_season": {str(s): _summary([r for r in pool if int(r["season"]) == s]) for s in sorted(seasons)},
            "by_qb_xgb_disagreement": _by_bucket(pool, d_labels, lambda r: _disagreement_bucket(float(r["qb_xgb_abs_disagreement"]))),
            "by_odds_bucket": _by_bucket(pool, o_labels, lambda r: _odds_bucket(int(r["american_odds"]))),
        },
        "hhr": {
            "eligible_ml_pool": _summary(hhr_pool),
            "actual_ml_headlines": _summary(hhr_head),
            "rank_comparison_ml_only": _rank_summaries(hhr_blocks),
            "confidence_floor_frontier_ml_only": _frontier(core, rows, seasons, "hhr", HHR_FLOORS),
        },
        "balanced_b0": {
            "eligible_ml_pool": _summary(bal_pool),
            "actual_ml_headlines": _summary(bal_head),
            "rank_comparison_ml_only": _rank_summaries(bal_blocks),
            "confidence_floor_frontier_ml_only": _frontier(core, rows, seasons, "balanced", BAL_FLOORS),
        },
    }


def run(root: Path, candidates: Path, out: Path) -> None:
    core = _load_core(root)
    rows = pl.read_parquet(candidates).to_dicts()
    seasons = {int(r["season"]) for r in rows}
    if SEALED in seasons or seasons != DEV | DIAG:
        raise RuntimeError(f"unexpected/sealed seasons: {sorted(seasons)}")
    if not (root / PLAN_PATH).exists():
        raise RuntimeError("missing frozen audit plan")

    shopped_ml = _shop_ml(core, rows)
    result = {
        "scope": "Task05G read-only ML high-confidence-tail audit",
        "source": "Spread Confidence V3 candidate table; ML confidence unchanged from V2",
        "frozen": {
            "football_models": True,
            "task05f_evaluator": True,
            "ml_confidence_method": True,
            "spread_confidence_v3": True,
            "hhr_selector": True,
            "balanced_b0_selector": True,
            "historical_data": True,
        },
        "periods": {"development_diagnostic": sorted(DEV), "locked_diagnostic": sorted(DIAG), "sealed": [SEALED]},
        "season_entry_ml_calibration_state": _season_entry_states(core, root, rows),
        "development": _phase(core, root, rows, shopped_ml, DEV),
        "locked_diagnostic": _phase(core, root, rows, shopped_ml, DIAG),
        "promotion_allowed": False,
        "threshold_selection_allowed": False,
        "2025_firewall": "PASS",
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "ml_confidence_tail_audit.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    pl.from_dicts(shopped_ml, infer_schema_length=None).write_parquet(out / "ml_confidence_tail_rows.parquet")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--v3-candidates", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    run(Path(a.root), Path(a.v3_candidates), Path(a.out))
