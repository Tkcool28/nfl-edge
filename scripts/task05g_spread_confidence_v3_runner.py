#!/usr/bin/env python3
"""Preregistered Task05G Spread Confidence V3 experiment.

Changes only experimental spread model-confidence conversion. ML confidence and
V2 HHR/Balanced selector mechanics remain frozen. 2025 is prohibited.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Mapping

import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression

DEV = {2020, 2021, 2022}
DIAG = {2023, 2024}
SEALED = 2025
MIN_N = 256
SCALE = 7.0
PREREG_PATH = "docs/task05g_spread_confidence_v3_preregistration.md"


def _load_v2_core(root: Path):
    path = root / "scripts/task05g_model_confidence_v2_runner.py"
    spec = importlib.util.spec_from_file_location("task05g_model_confidence_v2_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load V2 core runner")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _block_tuple(value: str) -> tuple[int, int]:
    season, week = str(value).split("-", 1)
    return int(season), int(week)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _margin_map(root: Path) -> dict[str, float]:
    df = (
        pl.scan_parquet(root / "data/modeling/development_v1/expected_margin_predictions_2018_2024.parquet")
        .filter(pl.col("candidate_id") == "stable")
        .select(["game_id", "season", "expected_home_margin"])
        .filter(pl.col("season").cast(pl.Int64).is_in([2020, 2021, 2022, 2023, 2024]))
        .collect()
    )
    out: dict[str, float] = {}
    for r in df.to_dicts():
        value = _finite(r.get("expected_home_margin"))
        if value is not None:
            out[str(r["game_id"])] = value
    return out


def _cover_margin(expected_home_margin: float, side: str, line: float) -> float:
    if str(side).lower() == "home":
        return float(expected_home_margin) + float(line)
    if str(side).lower() == "away":
        return -float(expected_home_margin) + float(line)
    raise ValueError(f"unexpected spread side {side}")


def _group_blocks(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(str(row["block"]), []).append(dict(row))
    return out


def _calibration_observations(core, rows: list[dict[str, Any]], margins: dict[str, float]) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, float]] = set()
    for block, block_rows in sorted(_group_blocks(rows).items(), key=lambda kv: _block_tuple(kv[0])):
        for r in core.shop_exact_offers(block_rows):
            if str(r.get("market_type")) != "spread":
                continue
            settlement = str(r.get("settlement"))
            if settlement not in {"WIN", "LOSS"}:
                continue
            gid = str(r.get("game_id"))
            side = str(r.get("selected_side"))
            line = _finite(r.get("line"))
            em = margins.get(gid)
            if line is None or em is None:
                continue
            key = (gid, side, float(line))
            if key in seen:
                continue
            seen.add(key)
            m = _cover_margin(em, side, line)
            observations.append(
                {
                    "block": block,
                    "season": int(r["season"]),
                    "game_id": gid,
                    "selected_side": side,
                    "line": float(line),
                    "model_cover_margin": float(m),
                    "outcome": 1 if settlement == "WIN" else 0,
                }
            )
    return sorted(observations, key=lambda r: (_block_tuple(r["block"]), r["game_id"], r["selected_side"], r["line"]))


def _fit_state(prior: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(prior)
    if n < MIN_N or len({int(r["outcome"]) for r in prior}) < 2:
        return {"supported": False, "n": n, "intercept": None, "slope": None}
    X = np.asarray([[float(r["model_cover_margin"]) / SCALE] for r in prior], dtype=float)
    y = np.asarray([int(r["outcome"]) for r in prior], dtype=int)
    model = LogisticRegression(C=1.0, solver="lbfgs", max_iter=2000, random_state=0).fit(X, y)
    intercept = float(model.intercept_[0])
    slope = float(model.coef_[0][0])
    supported = math.isfinite(intercept) and math.isfinite(slope) and slope > 0.0
    return {"supported": supported, "n": n, "intercept": intercept, "slope": slope}


def _probability(m: float, state: Mapping[str, Any]) -> float | None:
    if not bool(state.get("supported")):
        return None
    z = float(state["intercept"]) + float(state["slope"]) * (float(m) / SCALE)
    if z >= 0:
        e = math.exp(-z)
        return 1.0 / (1.0 + e)
    e = math.exp(z)
    return e / (1.0 + e)


def _states_by_block(rows: list[dict[str, Any]], obs: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    blocks = sorted({str(r["block"]) for r in rows}, key=_block_tuple)
    state_map: dict[str, dict[str, Any]] = {}
    states: list[dict[str, Any]] = []
    for block in blocks:
        cutoff = _block_tuple(block)
        prior = [r for r in obs if _block_tuple(r["block"]) < cutoff]
        state = _fit_state(prior)
        record = {"block": block, **state, "prior_max_block": None if not prior else prior[-1]["block"]}
        state_map[block] = record
        states.append(record)
    return state_map, states


def _apply_v3(rows: list[dict[str, Any]], margins: dict[str, float], state_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for src in rows:
        r = dict(src)
        season = int(r["season"])
        if season == SEALED or season not in DEV | DIAG:
            raise RuntimeError(f"unexpected/sealed season {season}")
        if str(r.get("market_type")) == "spread":
            r["model_confidence_probability"] = None
            r["model_confidence_support_n"] = 0
            r["model_confidence_supported"] = False
            r["model_confidence_source"] = "EXPECTED_MARGIN_DIRECT_LOGISTIC_V3"
            r["model_price_gap"] = None
            r["consensus_edge"] = None
            gid = str(r.get("game_id"))
            line = _finite(r.get("line"))
            em = margins.get(gid)
            state = state_map[str(r["block"])]
            if line is not None and em is not None:
                m = _cover_margin(em, str(r.get("selected_side")), line)
                q = _probability(m, state)
                r["model_cover_margin_v3"] = float(m)
                r["spread_calibration_intercept_v3"] = state.get("intercept")
                r["spread_calibration_slope_v3"] = state.get("slope")
                if q is not None:
                    r["model_confidence_probability"] = float(q)
                    r["model_confidence_support_n"] = int(state["n"])
                    r["model_confidence_supported"] = True
                    be = _finite(r.get("break_even_probability"))
                    if be is not None:
                        r["model_price_gap"] = float(q) - be
                    eval_edge = _finite(r.get("evaluated_edge_probability"))
                    if r["model_price_gap"] is not None and eval_edge is not None:
                        r["consensus_edge"] = min(float(r["model_price_gap"]), eval_edge)
        out.append(r)
    return out


def _phase_blocks(rows: list[dict[str, Any]], seasons: set[int]) -> int:
    return len({str(r["block"]) for r in rows if int(r["season"]) in seasons})


def _select_phase(core, rows: list[dict[str, Any]], seasons: set[int], selector) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    blocks = _group_blocks([r for r in rows if int(r["season"]) in seasons])
    for block in sorted(blocks, key=_block_tuple):
        choice = selector(blocks[block])
        if choice is not None and not isinstance(choice, str):
            out.append(dict(choice))
    return out


def _safe_summary(core, rows: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(str(r.get("settlement")) == "WIN" for r in rows)
    losses = sum(str(r.get("settlement")) == "LOSS" for r in rows)
    pushes = sum(str(r.get("settlement")) == "PUSH" for r in rows)
    nonpush = wins + losses
    q = [_finite(r.get("model_confidence_probability")) for r in rows]
    q = [x for x in q if x is not None]
    gaps = [_finite(r.get("model_price_gap")) for r in rows]
    gaps = [x for x in gaps if x is not None]
    return {
        "plays": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if nonpush == 0 else wins / nonpush,
        "roi": None if not rows else float(mean(float(r["realized_profit"]) for r in rows)),
        "avg_odds": None if not rows else float(mean(int(r["american_odds"]) for r in rows)),
        "avg_model_confidence_probability": None if not q else float(mean(q)),
        "avg_model_price_gap": None if not gaps else float(mean(gaps)),
        "max_losing_streak": core._longest_losing_streak(rows),
        "by_market": {
            m: {
                "plays": sum(str(r.get("market_type")) == m for r in rows),
                "roi": None if not [r for r in rows if str(r.get("market_type")) == m] else float(mean(float(r["realized_profit"]) for r in rows if str(r.get("market_type")) == m)),
            }
            for m in ("moneyline", "spread", "total")
        },
    }


def _selector_summary(core, rows: list[dict[str, Any]], seasons: set[int], selected: list[dict[str, Any]], eligible_fn) -> dict[str, Any]:
    total_blocks = _phase_blocks(rows, seasons)
    counts = core._eligible_counts(rows, seasons, eligible_fn)
    base = _safe_summary(core, selected)
    base.update(
        {
            "seasons": sorted(seasons),
            "total_blocks": total_blocks,
            "play_blocks": len(selected),
            "no_play_blocks": total_blocks - len(selected),
            "coverage": 0.0 if total_blocks == 0 else len(selected) / total_blocks,
            "mean_eligible_candidates_per_block": None if not counts else float(mean(counts.values())),
            "median_eligible_candidates_per_block": None if not counts else float(median(counts.values())),
            "by_season": {str(s): _safe_summary(core, [r for r in selected if int(r["season"]) == s]) for s in sorted(seasons)},
        }
    )
    return base


def _bucket_q(q: float) -> str:
    if q < .50: return "<50%"
    if q < .55: return "50-55%"
    if q < .60: return "55-60%"
    if q < .65: return "60-65%"
    return ">=65%"


def _bucket_m(m: float) -> str:
    if m < 0: return "<0"
    if m < 2: return "0-2"
    if m < 4: return "2-4"
    if m < 6: return "4-6"
    if m < 8: return "6-8"
    return ">=8"


def _cal_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    material = [r for r in rows if str(r.get("settlement")) in {"WIN", "LOSS"} and _finite(r.get("model_confidence_probability")) is not None]
    if not material:
        return {"n": 0, "avg_probability": None, "hit_rate": None, "brier": None, "log_loss": None}
    probs = [float(r["model_confidence_probability"]) for r in material]
    ys = [1.0 if str(r["settlement"]) == "WIN" else 0.0 for r in material]
    eps = 1e-12
    return {
        "n": len(material),
        "avg_probability": float(mean(probs)),
        "hit_rate": float(mean(ys)),
        "calibration_error_actual_minus_predicted": float(mean(ys) - mean(probs)),
        "brier": float(mean((p-y)**2 for p,y in zip(probs,ys))),
        "log_loss": float(-mean(y*math.log(max(eps,min(1-eps,p))) + (1-y)*math.log(max(eps,min(1-eps,1-p))) for p,y in zip(probs,ys))),
    }


def _spread_diagnostics(core, rows: list[dict[str, Any]], seasons: set[int]) -> dict[str, Any]:
    shopped: list[dict[str, Any]] = []
    for _, block_rows in sorted(_group_blocks([r for r in rows if int(r["season"]) in seasons]).items(), key=lambda kv: _block_tuple(kv[0])):
        shopped.extend(dict(r) for r in core.shop_exact_offers(block_rows) if str(r.get("market_type")) == "spread" and bool(r.get("model_confidence_supported")))
    return {
        "overall": _cal_summary(shopped),
        "by_season": {str(s): _cal_summary([r for r in shopped if int(r["season"]) == s]) for s in sorted(seasons)},
        "by_confidence_bucket": {b: _cal_summary([r for r in shopped if _finite(r.get("model_confidence_probability")) is not None and _bucket_q(float(r["model_confidence_probability"])) == b]) for b in ("<50%","50-55%","55-60%","60-65%",">=65%")},
        "by_model_cover_margin": {b: _cal_summary([r for r in shopped if _finite(r.get("model_cover_margin_v3")) is not None and _bucket_m(float(r["model_cover_margin_v3"])) == b]) for b in ("<0","0-2","2-4","4-6","6-8",">=8")},
    }


def _choose_balanced(dev_summaries: dict[str, dict[str, Any]], v1_plays: int) -> tuple[str | None, dict[str, Any]]:
    minimum = 0.75 * float(v1_plays)
    usable = [name for name, s in dev_summaries.items() if float(s["plays"]) >= minimum]
    if not usable:
        return None, {"minimum_plays": minimum, "usable": []}
    order = {"B0": 0, "B1": 1, "B2": 2}
    def score(name: str):
        s = dev_summaries[name]
        hit = -1.0 if s.get("hit_rate_nonpush") is None else float(s["hit_rate_nonpush"])
        roi = -999.0 if s.get("roi") is None else float(s["roi"])
        cov = float(s["coverage"])
        return (-hit, -roi, -cov, order[name])
    winner = sorted(usable, key=score)[0]
    return winner, {"minimum_plays": minimum, "usable": usable, "tie_break_rule": "hit_rate, roi, coverage, B0>B1>B2"}


def run(root: Path, candidates_path: Path, out: Path, prereg: Path) -> None:
    if not prereg.exists():
        raise RuntimeError("missing preregistration")
    rows = pl.read_parquet(candidates_path).to_dicts()
    seasons = {int(r["season"]) for r in rows}
    if SEALED in seasons or seasons != DEV | DIAG:
        raise RuntimeError(f"unexpected candidate seasons: {sorted(seasons)}")

    core = _load_v2_core(root)
    margins = _margin_map(root)
    obs = _calibration_observations(core, rows, margins)
    state_map, states = _states_by_block(rows, obs)
    v3 = _apply_v3(rows, margins, state_map)

    # V1 comparators use frozen original selectors on the same candidate board.
    v1_hhr_dev = core._v1_selections(v3, DEV, core._legacy_v1_select_hit_rate)
    v1_bal_dev = core._v1_selections(v3, DEV, core._legacy_v1_select_balanced)

    hhr_dev = _select_phase(core, v3, DEV, core._select_hhr)
    hhr_dev_summary = _selector_summary(core, v3, DEV, hhr_dev, core._hhr_eligible)

    balanced_dev: dict[str, dict[str, Any]] = {}
    balanced_dev_rows: dict[str, list[dict[str, Any]]] = {}
    for name, tol in core.BALANCED_TOLERANCES.items():
        selector = lambda rr, t=tol: core._select_balanced(rr, t)
        selected = _select_phase(core, v3, DEV, selector)
        balanced_dev_rows[name] = selected
        balanced_dev[name] = _selector_summary(core, v3, DEV, selected, lambda r, t=tol: core._balanced_eligible(r, t))

    winner, winner_meta = _choose_balanced(balanced_dev, len(v1_bal_dev))

    hhr_diag = _select_phase(core, v3, DIAG, core._select_hhr)
    hhr_diag_summary = _selector_summary(core, v3, DIAG, hhr_diag, core._hhr_eligible)
    balanced_diag_summary = None
    balanced_diag_rows: list[dict[str, Any]] = []
    if winner is not None:
        tol = core.BALANCED_TOLERANCES[winner]
        balanced_diag_rows = _select_phase(core, v3, DIAG, lambda rr, t=tol: core._select_balanced(rr, t))
        balanced_diag_summary = _selector_summary(core, v3, DIAG, balanced_diag_rows, lambda r, t=tol: core._balanced_eligible(r, t))

    hhr_floor = 0.75 * len(v1_hhr_dev)
    result = {
        "scope": "Spread Confidence V3 direct logistic calibration; diagnostic only",
        "preregistration": {"path": PREREG_PATH, "sha256": _sha256(prereg)},
        "periods": {"development": sorted(DEV), "locked_diagnostic": sorted(DIAG), "sealed": [SEALED]},
        "frozen": {"task05f_evaluator": True, "football_models": True, "ml_confidence": True, "hhr_selector": True, "balanced_selector": True, "value_out_of_scope": True},
        "calibration": {"method": "direct_logistic_model_cover_margin", "C": 1.0, "scale": SCALE, "min_n": MIN_N, "positive_slope_required": True, "calibration_observations": len(obs)},
        "v1_development": {"hhr_plays": len(v1_hhr_dev), "balanced_plays": len(v1_bal_dev)},
        "development": {
            "hhr": hhr_dev_summary,
            "hhr_coverage_floor_min_plays": hhr_floor,
            "hhr_coverage_floor_pass": len(hhr_dev) >= hhr_floor,
            "balanced_variants": balanced_dev,
            "balanced_winner": winner,
            "balanced_winner_meta": winner_meta,
            "spread_calibration": _spread_diagnostics(core, v3, DEV),
            "selected_hhr_spread_calibration": _cal_summary([r for r in hhr_dev if str(r.get("market_type")) == "spread"]),
            "selected_balanced_spread_calibration": None if winner is None else _cal_summary([r for r in balanced_dev_rows[winner] if str(r.get("market_type")) == "spread"]),
        },
        "locked_diagnostic": {
            "hhr": hhr_diag_summary,
            "balanced_winner": winner,
            "balanced": balanced_diag_summary,
            "spread_calibration": _spread_diagnostics(core, v3, DIAG),
            "selected_hhr_spread_calibration": _cal_summary([r for r in hhr_diag if str(r.get("market_type")) == "spread"]),
            "selected_balanced_spread_calibration": _cal_summary([r for r in balanced_diag_rows if str(r.get("market_type")) == "spread"]),
        },
        "season_entry_states": {
            str(s): next((st for st in states if _block_tuple(st["block"])[0] == s), None) for s in sorted(DEV | DIAG)
        },
        "promotion_allowed": False,
        "promotion_note": "2023-2024 already exposed; V3 may only be diagnostic. 2025 remains sealed.",
    }

    out.mkdir(parents=True, exist_ok=True)
    _json_write(out / "scorecard.json", result)
    (out / "spread_calibration_state_by_block.ndjson").write_text("".join(json.dumps(r, sort_keys=True, allow_nan=False) + "\n" for r in states))
    pl.from_dicts(v3, infer_schema_length=None).write_parquet(out / "v3_candidate_table.parquet")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--v2-candidates", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--prereg", default=PREREG_PATH)
    a = p.parse_args()
    run(Path(a.root), Path(a.v2_candidates), Path(a.out), Path(a.prereg))
