#!/usr/bin/env python3
"""Read-only spread model-confidence regime audit for Task05G V2.

Tests whether strictly-prior Expected Margin residual history overstated spread
cover confidence when the model entered the weak 2023 regime. No selector,
evaluator, model, candidate-region, or threshold semantics are changed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping

import numpy as np
import polars as pl

SEASONS = (2020, 2021, 2022, 2023, 2024)
SEALED = 2025
NUMERIC_HISTORY_FIELDS = (
    "qbelo_home",
    "xgb_home",
    "raw_ml_home",
    "expected_home_margin",
    "margin_residual",
)


def _load_core(root: Path):
    path = root / "scripts/task05g_model_confidence_v2_runner.py"
    spec = importlib.util.spec_from_file_location("task05g_model_confidence_v2_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load V2 core runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _patch_finite_history(core) -> None:
    original = core._history_rows

    def finite_history(root: Path):
        rows = original(root)
        for row in rows:
            for key in NUMERIC_HISTORY_FIELDS:
                value = row.get(key)
                if isinstance(value, (int, float)) and not math.isfinite(float(value)):
                    row[key] = None
        return rows

    core._history_rows = finite_history


def _json_write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _stats(values: Iterable[float]) -> dict[str, Any]:
    arr = np.asarray([float(v) for v in values if math.isfinite(float(v))], dtype=float)
    if arr.size == 0:
        return {"n": 0, "mean": None, "std": None, "mae": None, "q10": None, "q25": None, "median": None, "q75": None, "q90": None}
    return {
        "n": int(arr.size),
        "mean": float(np.mean(arr)),
        "std": None if arr.size < 2 else float(np.std(arr, ddof=1)),
        "mae": float(np.mean(np.abs(arr))),
        "q10": float(np.quantile(arr, 0.10)),
        "q25": float(np.quantile(arr, 0.25)),
        "median": float(np.quantile(arr, 0.50)),
        "q75": float(np.quantile(arr, 0.75)),
        "q90": float(np.quantile(arr, 0.90)),
    }


def _q_bucket(q: float) -> str:
    if q < 0.55:
        return "00_<55%"
    if q < 0.60:
        return "01_55-60%"
    if q < 0.65:
        return "02_60-65%"
    if q < 0.70:
        return "03_65-70%"
    if q < 0.75:
        return "04_70-75%"
    return "05_75%+"


def _cushion_bucket(points: float) -> str:
    x = abs(float(points))
    if x < 1.0:
        return "00_<1pt"
    if x < 2.0:
        return "01_1-2pt"
    if x < 3.0:
        return "02_2-3pt"
    if x < 4.0:
        return "03_3-4pt"
    if x < 6.0:
        return "04_4-6pt"
    return "05_6pt+"


def _grade(actual_home_margin: float, side: str, line: float) -> tuple[str, float]:
    if side == "home":
        value = float(actual_home_margin) + float(line)
    elif side == "away":
        value = -float(actual_home_margin) + float(line)
    else:
        raise ValueError(f"unexpected side {side}")
    if value > 1e-9:
        return "WIN", value
    if value < -1e-9:
        return "LOSS", value
    return "PUSH", value


def _model_cushion(expected_home_margin: float, side: str, line: float) -> float:
    if side == "home":
        return float(expected_home_margin) + float(line)
    if side == "away":
        return -float(expected_home_margin) + float(line)
    raise ValueError(f"unexpected side {side}")


def _calibration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    nonpush = [r for r in rows if str(r.get("settlement")) in {"WIN", "LOSS"}]
    pushes = [r for r in rows if str(r.get("settlement")) == "PUSH"]
    if not nonpush:
        return {
            "n": len(rows), "nonpush_n": 0, "wins": 0, "losses": 0, "pushes": len(pushes),
            "avg_q": None, "hit_rate": None, "calibration_gap_actual_minus_q": None,
            "brier": None, "avg_model_cushion_points": None, "avg_break_even": None,
            "avg_model_price_gap": None,
        }
    qs = np.asarray([float(r["model_confidence_probability"]) for r in nonpush], dtype=float)
    ys = np.asarray([1.0 if str(r["settlement"]) == "WIN" else 0.0 for r in nonpush], dtype=float)
    avg_q = float(np.mean(qs))
    hit = float(np.mean(ys))
    return {
        "n": len(rows),
        "nonpush_n": len(nonpush),
        "wins": int(np.sum(ys)),
        "losses": int(len(nonpush) - np.sum(ys)),
        "pushes": len(pushes),
        "avg_q": avg_q,
        "hit_rate": hit,
        "calibration_gap_actual_minus_q": hit - avg_q,
        "brier": float(np.mean((qs - ys) ** 2)),
        "avg_model_cushion_points": float(mean(float(r["model_cushion_points"]) for r in nonpush)),
        "avg_abs_model_cushion_points": float(mean(abs(float(r["model_cushion_points"])) for r in nonpush)),
        "avg_break_even": float(mean(float(r["break_even_probability"]) for r in nonpush if r.get("break_even_probability") is not None)),
        "avg_model_price_gap": float(mean(float(r["model_price_gap"]) for r in nonpush if r.get("model_price_gap") is not None)),
    }


def _by_bucket(rows: list[dict[str, Any]], key_fn) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(key_fn(row), []).append(row)
    return {key: _calibration(groups[key]) for key in sorted(groups)}


def _exact_shopped(core, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_block: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_block.setdefault(str(row["block"]), []).append(row)
    out: list[dict[str, Any]] = []
    for block in sorted(by_block, key=core._block_tuple):
        out.extend(dict(r) for r in core.shop_exact_offers(by_block[block]))
    return out


def _selected(core, rows: list[dict[str, Any]], selector) -> list[dict[str, Any]]:
    by_block: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_block.setdefault(str(row["block"]), []).append(row)
    out: list[dict[str, Any]] = []
    for block in sorted(by_block, key=core._block_tuple):
        choice = selector(by_block[block])
        if choice is not None:
            out.append(dict(choice))
    return out


def _season_calibration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        str(season): {
            "overall": _calibration([r for r in rows if int(r["season"]) == season]),
            "by_probability_bucket": _by_bucket(
                [r for r in rows if int(r["season"]) == season],
                lambda r: _q_bucket(float(r["model_confidence_probability"])),
            ),
            "by_model_cushion_bucket": _by_bucket(
                [r for r in rows if int(r["season"]) == season],
                lambda r: _cushion_bucket(float(r["model_cushion_points"])),
            ),
        }
        for season in SEASONS
    }


def run(root: Path, board_path: Path, out_path: Path) -> None:
    core = _load_core(root)
    _patch_finite_history(core)

    board = pl.read_parquet(board_path)
    seasons = {int(x) for x in board["season"].unique().to_list()}
    if seasons != set(SEASONS):
        raise RuntimeError(f"unexpected board seasons: {sorted(seasons)}")
    if SEALED in seasons:
        raise RuntimeError("sealed 2025 entered board")

    board_rows = board.to_dicts()
    enriched, states, _ = core._build_model_confidence(root, board_rows)
    history = core._history_rows(root)
    history_by_game = {str(r["game_id"]): r for r in history}

    exact = _exact_shopped(core, enriched)
    spread_rows: list[dict[str, Any]] = []
    settlement_mismatches: list[dict[str, Any]] = []
    for src in exact:
        if str(src.get("market_type")) != "spread" or not bool(src.get("model_confidence_supported")):
            continue
        if src.get("model_confidence_probability") is None or src.get("line") is None:
            continue
        game = history_by_game.get(str(src["game_id"]))
        if game is None or game.get("home_margin") is None or game.get("expected_home_margin") is None:
            continue
        row = dict(src)
        settlement, realized_grade = _grade(float(game["home_margin"]), str(row["selected_side"]), float(row["line"]))
        model_cushion = _model_cushion(float(game["expected_home_margin"]), str(row["selected_side"]), float(row["line"]))
        row["reconstructed_settlement"] = settlement
        row["realized_grade_points"] = realized_grade
        row["model_cushion_points"] = model_cushion
        row["expected_home_margin"] = float(game["expected_home_margin"])
        row["actual_home_margin"] = float(game["home_margin"])
        if settlement != str(row.get("settlement")):
            settlement_mismatches.append({
                "game_id": row["game_id"], "season": row["season"], "block": row["block"],
                "side": row["selected_side"], "line": row["line"],
                "board": row.get("settlement"), "reconstructed": settlement,
            })
        spread_rows.append(row)

    if settlement_mismatches:
        raise RuntimeError(f"spread settlement/orientation mismatches: {len(settlement_mismatches)}")

    residual_regime: dict[str, Any] = {}
    for season in SEASONS:
        prior = [float(r["margin_residual"]) for r in history if int(r["season"]) < season and r.get("margin_residual") is not None]
        current = [float(r["margin_residual"]) for r in history if int(r["season"]) == season and r.get("margin_residual") is not None]
        prior_stats = _stats(prior)
        current_stats = _stats(current)
        residual_regime[str(season)] = {
            "prior_seasons": sorted({int(r["season"]) for r in history if int(r["season"]) < season and r.get("margin_residual") is not None}),
            "entering_season_prior": prior_stats,
            "realized_season": current_stats,
            "realized_to_prior_std_ratio": None if not prior_stats["std"] else float(current_stats["std"] / prior_stats["std"]),
            "realized_to_prior_mae_ratio": None if not prior_stats["mae"] else float(current_stats["mae"] / prior_stats["mae"]),
        }

    state_by_season: dict[str, Any] = {}
    for season in SEASONS:
        ss = [s for s in states if core._block_tuple(str(s["block"]))[0] == season]
        ss = sorted(ss, key=lambda s: core._block_tuple(str(s["block"])))
        state_by_season[str(season)] = {
            "first_block": None if not ss else ss[0],
            "last_block": None if not ss else ss[-1],
        }

    hhr = _selected(core, enriched, core._select_hhr)
    balanced = _selected(core, enriched, lambda rr: core._select_balanced(rr, core.BALANCED_TOLERANCES["B0"]))
    hhr_spread = [r for r in spread_rows if any(
        str(x.get("game_id")) == str(r.get("game_id")) and str(x.get("selected_side")) == str(r.get("selected_side"))
        and float(x.get("line")) == float(r.get("line")) and str(x.get("sportsbook")) == str(r.get("sportsbook"))
        for x in hhr if str(x.get("market_type")) == "spread"
    )]
    balanced_spread = [r for r in spread_rows if any(
        str(x.get("game_id")) == str(r.get("game_id")) and str(x.get("selected_side")) == str(r.get("selected_side"))
        and float(x.get("line")) == float(r.get("line")) and str(x.get("sportsbook")) == str(r.get("sportsbook"))
        for x in balanced if str(x.get("market_type")) == "spread"
    )]

    result = {
        "verdict_scope": "read-only spread confidence regime audit; no tuning",
        "seasons": list(SEASONS),
        "sealed": [SEALED],
        "settlement_orientation_parity": {
            "spread_rows_checked": len(spread_rows),
            "mismatches": len(settlement_mismatches),
        },
        "residual_regime_by_season": residual_regime,
        "spread_state_first_last_block_by_season": state_by_season,
        "all_exact_shopped_supported_spreads": {
            "n": len(spread_rows),
            "by_season": _season_calibration(spread_rows),
        },
        "hhr_selected_spreads": {
            "n": len(hhr_spread),
            "by_season": _season_calibration(hhr_spread),
        },
        "balanced_b0_selected_spreads": {
            "n": len(balanced_spread),
            "by_season": _season_calibration(balanced_spread),
        },
    }
    _json_write(out_path, result)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--board", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    run(Path(a.root), Path(a.board), Path(a.out))
