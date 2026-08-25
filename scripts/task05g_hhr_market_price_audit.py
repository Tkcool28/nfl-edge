#!/usr/bin/env python3
"""Read-only Task05G HHR market-price corroboration audit.

Consumes the validated Spread Confidence V3 candidate table. It does not change
models, Task05F, ML calibration, selectors, eligibility, thresholds, or policy.
Season 2025 is prohibited.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping

import polars as pl

DEV = {2020, 2021, 2022}
DIAG = {2023, 2024}
SEALED = 2025
PLAN_PATH = "docs/task05g_hhr_market_price_audit_plan.md"
PIN_LABELS = ["<55%", "55-60%", "60-65%", "65-70%", "70-75%", ">=75%"]
JUICE_LABELS = ["<=0pp", "0-1pp", "1-2.5pp", "2.5-5pp", ">5pp"]
MODEL_GAP_LABELS = ["<=0pp", "0-5pp", "5-10pp", "10-15pp", ">15pp"]
ODDS_LABELS = ["<=-250", "-249..-201", "-200..-151", "-150..-111", "-110..+100", "+101..+200"]
QUADRANT_LABELS = [
    "genuine_heavy_not_overjuiced",
    "genuine_heavy_overjuiced",
    "not_genuine_heavy_not_overjuiced",
    "not_genuine_heavy_overjuiced",
]


def _load_core(root: Path):
    path = root / "scripts/task05g_model_confidence_v2_runner.py"
    spec = importlib.util.spec_from_file_location("task05g_model_confidence_v2_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load V2 core")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


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


def _group_blocks(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(str(row["block"]), []).append(dict(row))
    return out


def _hhr_key(core, row: Mapping[str, Any]):
    return (
        -float(row["model_confidence_probability"]),
        -core._reliability_rank(row.get("reliability")),
        -float(row.get("model_price_gap") if row.get("model_price_gap") is not None else -99.0),
        -int(row.get("american_odds") or -100000),
        core._candidate_id(row),
    )


def _derived(row: Mapping[str, Any]) -> dict[str, Any]:
    r = dict(row)
    pin = _finite(r.get("pinnacle_anchor_probability"))
    be = _finite(r.get("break_even_probability"))
    q = _finite(r.get("model_confidence_probability"))
    qb = _finite(r.get("raw_qbelo_probability_selected"))
    xgb = _finite(r.get("raw_xgb_probability_selected"))
    if pin is None or be is None or q is None or qb is None or xgb is None:
        raise RuntimeError(f"HHR-eligible ML row missing price/model evidence: {r.get('candidate_id')}")
    r["retail_juice_premium"] = be - pin
    r["model_minus_pinnacle"] = q - pin
    r["qb_xgb_abs_disagreement"] = abs(qb - xgb)
    r["genuine_heavy"] = pin >= 0.65
    r["material_retail_overjuice"] = (be - pin) >= 0.025
    return r


def _outcome(row: Mapping[str, Any]) -> int | None:
    settlement = str(row.get("settlement"))
    if settlement == "WIN":
        return 1
    if settlement == "LOSS":
        return 0
    return None


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    material = [r for r in rows if _outcome(r) is not None]
    wins = sum(int(_outcome(r)) for r in material)
    losses = len(material) - wins
    pushes = sum(str(r.get("settlement")) == "PUSH" for r in rows)
    profits = [_finite(r.get("realized_profit")) for r in rows]
    profits = [x for x in profits if x is not None]

    def avg(field: str) -> float | None:
        vals = [_finite(r.get(field)) for r in rows]
        vals = [x for x in vals if x is not None]
        return None if not vals else float(mean(vals))

    return {
        "n": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if not material else wins / len(material),
        "roi": None if not profits else float(mean(profits)),
        "avg_model_confidence": avg("model_confidence_probability"),
        "avg_pinnacle_no_vig": avg("pinnacle_anchor_probability"),
        "avg_break_even_probability": avg("break_even_probability"),
        "avg_retail_juice_premium": avg("retail_juice_premium"),
        "avg_model_minus_pinnacle": avg("model_minus_pinnacle"),
        "avg_qb_xgb_abs_disagreement": avg("qb_xgb_abs_disagreement"),
        "avg_odds": avg("american_odds"),
    }


def _pin_bucket(p: float) -> str:
    if p < 0.55:
        return "<55%"
    if p < 0.60:
        return "55-60%"
    if p < 0.65:
        return "60-65%"
    if p < 0.70:
        return "65-70%"
    if p < 0.75:
        return "70-75%"
    return ">=75%"


def _juice_bucket(x: float) -> str:
    if x <= 0.0:
        return "<=0pp"
    if x < 0.01:
        return "0-1pp"
    if x < 0.025:
        return "1-2.5pp"
    if x < 0.05:
        return "2.5-5pp"
    return ">5pp"


def _model_gap_bucket(x: float) -> str:
    if x <= 0.0:
        return "<=0pp"
    if x < 0.05:
        return "0-5pp"
    if x < 0.10:
        return "5-10pp"
    if x < 0.15:
        return "10-15pp"
    return ">15pp"


def _odds_bucket(o: int) -> str:
    if o <= -250:
        return "<=-250"
    if o <= -201:
        return "-249..-201"
    if o <= -151:
        return "-200..-151"
    if o <= -111:
        return "-150..-111"
    if o <= 100:
        return "-110..+100"
    return "+101..+200"


def _quadrant(row: Mapping[str, Any]) -> str:
    heavy = bool(row["genuine_heavy"])
    over = bool(row["material_retail_overjuice"])
    if heavy and not over:
        return "genuine_heavy_not_overjuiced"
    if heavy and over:
        return "genuine_heavy_overjuiced"
    if not heavy and not over:
        return "not_genuine_heavy_not_overjuiced"
    return "not_genuine_heavy_overjuiced"


def _by_bucket(rows: list[dict[str, Any]], labels: list[str], fn) -> dict[str, Any]:
    return {label: _summary([r for r in rows if fn(r) == label]) for label in labels}


def _phase(core, rows: list[dict[str, Any]], seasons: set[int]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    phase_rows = [r for r in rows if int(r["season"]) in seasons]
    blocks = _group_blocks(phase_rows)
    eligible_pool: list[dict[str, Any]] = []
    actual_headlines: list[dict[str, Any]] = []
    ranks: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: []}
    enriched_rows: list[dict[str, Any]] = []

    for block in sorted(blocks, key=_block_tuple):
        shopped = [dict(r) for r in core.shop_exact_offers(blocks[block])]
        eligible_ml = [
            _derived(r)
            for r in shopped
            if str(r.get("market_type")) == "moneyline" and core._hhr_eligible(r)
        ]
        eligible_ml.sort(key=lambda r: _hhr_key(core, r))
        eligible_pool.extend(eligible_ml)
        for idx, r in enumerate(eligible_ml[:3], start=1):
            rr = dict(r)
            rr["hhr_ml_rank"] = idx
            ranks[idx].append(rr)

        actual = core._select_hhr(blocks[block])
        actual_cid = None
        if actual is not None and str(actual.get("market_type")) == "moneyline":
            actual_d = _derived(actual)
            actual_headlines.append(actual_d)
            actual_cid = str(core._candidate_id(actual_d))

        for idx, r in enumerate(eligible_ml, start=1):
            rr = dict(r)
            rr["hhr_ml_rank"] = idx
            rr["actual_hhr_ml_headline"] = str(core._candidate_id(rr)) == actual_cid
            rr["price_quadrant"] = _quadrant(rr)
            enriched_rows.append(rr)

    rank_report = {f"rank_{rank}": _summary(ranks[rank]) for rank in (1, 2, 3)}
    selected_rank2 = {
        "rank1_minus_rank2_avg_pinnacle_pp": None,
        "rank1_minus_rank2_avg_retail_juice_pp": None,
        "rank1_minus_rank2_avg_model_minus_pinnacle_pp": None,
        "rank1_minus_rank2_avg_disagreement_pp": None,
        "rank1_minus_rank2_avg_odds": None,
        "rank1_minus_rank2_hit_rate_pp": None,
        "rank1_minus_rank2_roi_pp": None,
    }
    if ranks[1] and ranks[2]:
        s1 = _summary(ranks[1])
        s2 = _summary(ranks[2])
        def delta(a: str, scale: float = 1.0):
            x, y = s1.get(a), s2.get(a)
            return None if x is None or y is None else scale * (float(x) - float(y))
        selected_rank2 = {
            "rank1_minus_rank2_avg_pinnacle_pp": delta("avg_pinnacle_no_vig", 100.0),
            "rank1_minus_rank2_avg_retail_juice_pp": delta("avg_retail_juice_premium", 100.0),
            "rank1_minus_rank2_avg_model_minus_pinnacle_pp": delta("avg_model_minus_pinnacle", 100.0),
            "rank1_minus_rank2_avg_disagreement_pp": delta("avg_qb_xgb_abs_disagreement", 100.0),
            "rank1_minus_rank2_avg_odds": delta("avg_odds"),
            "rank1_minus_rank2_hit_rate_pp": delta("hit_rate_nonpush", 100.0),
            "rank1_minus_rank2_roi_pp": delta("roi", 100.0),
        }

    report = {
        "seasons": sorted(seasons),
        "total_blocks": len(blocks),
        "all_hhr_eligible_ml": {
            "overall": _summary(eligible_pool),
            "by_pinnacle_strength": _by_bucket(eligible_pool, PIN_LABELS, lambda r: _pin_bucket(float(r["pinnacle_anchor_probability"]))),
            "by_retail_juice_premium": _by_bucket(eligible_pool, JUICE_LABELS, lambda r: _juice_bucket(float(r["retail_juice_premium"]))),
            "by_model_minus_pinnacle": _by_bucket(eligible_pool, MODEL_GAP_LABELS, lambda r: _model_gap_bucket(float(r["model_minus_pinnacle"]))),
            "by_actionable_odds": _by_bucket(eligible_pool, ODDS_LABELS, lambda r: _odds_bucket(int(r["american_odds"]))),
            "by_price_quadrant": {label: _summary([r for r in eligible_pool if _quadrant(r) == label]) for label in QUADRANT_LABELS},
        },
        "actual_hhr_ml_headlines": {
            "overall": _summary(actual_headlines),
            "by_pinnacle_strength": _by_bucket(actual_headlines, PIN_LABELS, lambda r: _pin_bucket(float(r["pinnacle_anchor_probability"]))),
            "by_retail_juice_premium": _by_bucket(actual_headlines, JUICE_LABELS, lambda r: _juice_bucket(float(r["retail_juice_premium"]))),
            "by_model_minus_pinnacle": _by_bucket(actual_headlines, MODEL_GAP_LABELS, lambda r: _model_gap_bucket(float(r["model_minus_pinnacle"]))),
            "by_actionable_odds": _by_bucket(actual_headlines, ODDS_LABELS, lambda r: _odds_bucket(int(r["american_odds"]))),
            "by_price_quadrant": {label: _summary([r for r in actual_headlines if _quadrant(r) == label]) for label in QUADRANT_LABELS},
        },
        "ml_only_rank_comparison": rank_report,
        "rank1_minus_rank2": selected_rank2,
    }
    return report, enriched_rows


def run(root: Path, candidates: Path, out: Path) -> None:
    plan = root / PLAN_PATH
    if not plan.exists():
        raise RuntimeError("missing frozen audit plan")
    core = _load_core(root)
    rows = pl.read_parquet(candidates).to_dicts()
    seasons = {int(r["season"]) for r in rows}
    if seasons != DEV | DIAG or SEALED in seasons:
        raise RuntimeError(f"unexpected/sealed candidate seasons: {sorted(seasons)}")

    dev, dev_rows = _phase(core, rows, DEV)
    diag, diag_rows = _phase(core, rows, DIAG)
    score = {
        "verdict": "DIAGNOSTIC_ONLY",
        "plan_sha256": _sha256(plan),
        "periods": {"development_diagnostic": sorted(DEV), "locked_diagnostic": sorted(DIAG), "sealed": [SEALED]},
        "definitions": {
            "genuine_heavy_pinnacle_no_vig_min": 0.65,
            "material_retail_overjuice_min": 0.025,
            "retail_juice_premium": "break_even_probability - pinnacle_anchor_probability",
            "model_minus_pinnacle": "model_confidence_probability - pinnacle_anchor_probability",
        },
        "frozen": {
            "task05f": True,
            "ml_calibration": True,
            "spread_v3": True,
            "hhr_eligibility": True,
            "hhr_ordering": True,
            "football_models": True,
            "2025_sealed": True,
        },
        "threshold_selection_allowed": False,
        "production_promotion_allowed": False,
        "2025_firewall": "PASS",
        "development": dev,
        "locked_diagnostic": diag,
    }
    out.mkdir(parents=True, exist_ok=True)
    _json_write(out / "hhr_market_price_audit.json", score)
    all_rows = dev_rows + diag_rows
    if not all_rows:
        raise RuntimeError("no HHR-eligible ML rows produced")
    pl.DataFrame(all_rows).write_parquet(out / "hhr_market_price_rows.parquet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--v3-candidates", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    run(Path(args.root), Path(args.v3_candidates), Path(args.out))
