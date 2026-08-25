#!/usr/bin/env python3
"""Preregistered Task05G HHR model-market corroboration V1 experiment.

Ranking-only experiment. Eligibility is frozen, 2025 is prohibited, and the
primary HALF_SHRINK rule is fixed by the preregistration committed before output.
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
SHRINK = 0.50
PREREG_PATH = "docs/task05g_hhr_model_market_corroboration_v1_preregistration.md"


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


def _candidate_id(core, row: Mapping[str, Any]) -> str:
    return str(core._candidate_id(row))


def _pin(row: Mapping[str, Any]) -> float | None:
    if str(row.get("market_type")) != "moneyline":
        return None
    return _finite(row.get("pinnacle_anchor_probability"))


def _q(row: Mapping[str, Any]) -> float:
    q = _finite(row.get("model_confidence_probability"))
    if q is None:
        raise RuntimeError("eligible row missing model confidence")
    return q


def _qb_xgb_gap(row: Mapping[str, Any]) -> float | None:
    if str(row.get("market_type")) != "moneyline":
        return None
    qb = _finite(row.get("raw_qbelo_probability_selected"))
    xgb = _finite(row.get("raw_xgb_probability_selected"))
    if qb is None or xgb is None:
        return None
    return abs(qb - xgb)


def _half_shrink_score(row: Mapping[str, Any]) -> float:
    q = _q(row)
    if str(row.get("market_type")) != "moneyline":
        return q
    pin = _pin(row)
    if pin is None:
        raise RuntimeError("eligible ML row missing Pinnacle no-vig probability")
    return q - SHRINK * max(q - pin, 0.0)


def _min_cap_score(row: Mapping[str, Any]) -> float:
    q = _q(row)
    if str(row.get("market_type")) != "moneyline":
        return q
    pin = _pin(row)
    if pin is None:
        raise RuntimeError("eligible ML row missing Pinnacle no-vig probability")
    return min(q, pin)


def _eligible_rows(core, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    shopped = [dict(r) for r in core.shop_exact_offers(rows)]
    out = [r for r in shopped if bool(core._hhr_eligible(r))]
    for r in out:
        if str(r.get("market_type")) == "moneyline" and _pin(r) is None:
            raise RuntimeError("HHR-eligible ML candidate lacks Pinnacle anchor")
    return out


def _baseline_key(core, row: Mapping[str, Any]):
    return (
        -_q(row),
        -core._reliability_rank(row.get("reliability")),
        -float(row.get("model_price_gap") if row.get("model_price_gap") is not None else -99.0),
        -int(row.get("american_odds") or -100000),
        _candidate_id(core, row),
    )


def _rank_key(core, row: Mapping[str, Any], score_fn):
    return (
        -float(score_fn(row)),
        -core._reliability_rank(row.get("reliability")),
        -float(row.get("model_price_gap") if row.get("model_price_gap") is not None else -99.0),
        -int(row.get("american_odds") or -100000),
        _candidate_id(core, row),
    )


def _select(core, rows: list[dict[str, Any]], rule: str) -> dict[str, Any] | None:
    candidates = _eligible_rows(core, rows)
    if not candidates:
        return None
    if rule == "baseline":
        return dict(sorted(candidates, key=lambda r: _baseline_key(core, r))[0])
    if rule == "half_shrink":
        return dict(sorted(candidates, key=lambda r: _rank_key(core, r, _half_shrink_score))[0])
    if rule == "min_cap":
        return dict(sorted(candidates, key=lambda r: _rank_key(core, r, _min_cap_score))[0])
    raise ValueError(rule)


def _select_phase(core, rows: list[dict[str, Any]], seasons: set[int], rule: str) -> dict[str, dict[str, Any]]:
    phase = [r for r in rows if int(r["season"]) in seasons]
    blocks = _group_blocks(phase)
    out: dict[str, dict[str, Any]] = {}
    for block in sorted(blocks, key=_block_tuple):
        choice = _select(core, blocks[block], rule)
        if choice is not None:
            choice["half_shrink_score"] = _half_shrink_score(choice)
            choice["min_cap_score"] = _min_cap_score(choice)
            out[block] = choice
    return out


def _pure_ml_rank_ids(core, block_rows: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    ml = [r for r in _eligible_rows(core, block_rows) if str(r.get("market_type")) == "moneyline"]
    if not ml:
        return None, None
    model = sorted(ml, key=lambda r: (-_q(r), _candidate_id(core, r)))[0]
    pin = sorted(ml, key=lambda r: (-float(_pin(r)), _candidate_id(core, r)))[0]
    return _candidate_id(core, model), _candidate_id(core, pin)


def _summary(rows: dict[str, dict[str, Any]], total_blocks: int) -> dict[str, Any]:
    rr = list(rows.values())
    wins = sum(str(r.get("settlement")) == "WIN" for r in rr)
    losses = sum(str(r.get("settlement")) == "LOSS" for r in rr)
    pushes = sum(str(r.get("settlement")) == "PUSH" for r in rr)
    nonpush = wins + losses
    ml = [r for r in rr if str(r.get("market_type")) == "moneyline"]
    def avg(values):
        vals = [v for v in values if v is not None]
        return None if not vals else float(mean(vals))
    return {
        "plays": len(rr),
        "play_blocks": len(rows),
        "total_blocks": total_blocks,
        "coverage": 0.0 if total_blocks == 0 else len(rows) / total_blocks,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if nonpush == 0 else wins / nonpush,
        "roi": None if not rr else float(mean(float(r["realized_profit"]) for r in rr)),
        "avg_odds": None if not rr else float(mean(int(r["american_odds"]) for r in rr)),
        "moneyline_plays": len(ml),
        "spread_plays": sum(str(r.get("market_type")) == "spread" for r in rr),
        "avg_ml_model_confidence": avg([_q(r) for r in ml]),
        "avg_ml_pinnacle_no_vig": avg([_pin(r) for r in ml]),
        "avg_ml_model_minus_pinnacle": avg([_q(r) - float(_pin(r)) for r in ml]),
        "avg_ml_qb_xgb_disagreement": avg([_qb_xgb_gap(r) for r in ml]),
        "avg_ml_half_shrink_score": avg([_half_shrink_score(r) for r in ml]),
    }


def _agency(core, all_rows: list[dict[str, Any]], seasons: set[int], selected: dict[str, dict[str, Any]]) -> dict[str, Any]:
    blocks = _group_blocks([r for r in all_rows if int(r["season"]) in seasons])
    eligible_ml_blocks = 0
    selected_ml_blocks = 0
    matches_model_rank1 = 0
    matches_pin_rank1 = 0
    differs_from_both = 0
    model_equals_pin_rank1 = 0
    for block, choice in selected.items():
        model_id, pin_id = _pure_ml_rank_ids(core, blocks[block])
        if model_id is None:
            continue
        eligible_ml_blocks += 1
        if model_id == pin_id:
            model_equals_pin_rank1 += 1
        if str(choice.get("market_type")) != "moneyline":
            continue
        selected_ml_blocks += 1
        cid = _candidate_id(core, choice)
        if cid == model_id:
            matches_model_rank1 += 1
        if cid == pin_id:
            matches_pin_rank1 += 1
        if cid != model_id and cid != pin_id:
            differs_from_both += 1
    return {
        "eligible_ml_blocks": eligible_ml_blocks,
        "selected_ml_blocks": selected_ml_blocks,
        "model_rank1_equals_pinnacle_rank1_blocks": model_equals_pin_rank1,
        "selected_matches_model_rank1": matches_model_rank1,
        "selected_matches_pinnacle_rank1": matches_pin_rank1,
        "selected_differs_from_both": differs_from_both,
        "model_rank1_overlap_rate": None if selected_ml_blocks == 0 else matches_model_rank1 / selected_ml_blocks,
        "pinnacle_rank1_overlap_rate": None if selected_ml_blocks == 0 else matches_pin_rank1 / selected_ml_blocks,
    }


def _paired(core, baseline: dict[str, dict[str, Any]], primary: dict[str, dict[str, Any]]) -> dict[str, Any]:
    changed = 0
    both_win = both_lose = new_only_win = old_only_win = paired_nonpush = 0
    for block in sorted(baseline, key=_block_tuple):
        old = baseline[block]
        new = primary[block]
        if _candidate_id(core, old) != _candidate_id(core, new):
            changed += 1
        os = str(old.get("settlement")); ns = str(new.get("settlement"))
        if os not in {"WIN", "LOSS"} or ns not in {"WIN", "LOSS"}:
            continue
        paired_nonpush += 1
        if os == "WIN" and ns == "WIN": both_win += 1
        elif os == "LOSS" and ns == "LOSS": both_lose += 1
        elif os == "LOSS" and ns == "WIN": new_only_win += 1
        elif os == "WIN" and ns == "LOSS": old_only_win += 1
    return {
        "changed_blocks": changed,
        "changed_block_rate": 0.0 if not baseline else changed / len(baseline),
        "paired_nonpush": paired_nonpush,
        "both_win": both_win,
        "both_lose": both_lose,
        "new_only_win": new_only_win,
        "old_only_win": old_only_win,
    }


def _phase_report(core, rows: list[dict[str, Any]], seasons: set[int]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    total_blocks = len({str(r["block"]) for r in rows if int(r["season"]) in seasons})
    baseline = _select_phase(core, rows, seasons, "baseline")
    primary = _select_phase(core, rows, seasons, "half_shrink")
    min_cap = _select_phase(core, rows, seasons, "min_cap")
    if set(baseline) != set(primary) or set(baseline) != set(min_cap):
        raise RuntimeError("coverage parity failure")
    base_s = _summary(baseline, total_blocks)
    prim_s = _summary(primary, total_blocks)
    min_s = _summary(min_cap, total_blocks)
    hit_delta = None if base_s["hit_rate_nonpush"] is None or prim_s["hit_rate_nonpush"] is None else 100.0 * (prim_s["hit_rate_nonpush"] - base_s["hit_rate_nonpush"])
    roi_delta = None if base_s["roi"] is None or prim_s["roi"] is None else 100.0 * (prim_s["roi"] - base_s["roi"])
    comparison_rows: list[dict[str, Any]] = []
    label = "development" if seasons == DEV else "locked_diagnostic"
    for block in sorted(baseline, key=_block_tuple):
        b = baseline[block]; p = primary[block]; m = min_cap[block]
        comparison_rows.append({
            "phase": label,
            "block": block,
            "baseline_candidate_id": _candidate_id(core, b),
            "primary_candidate_id": _candidate_id(core, p),
            "min_cap_candidate_id": _candidate_id(core, m),
            "primary_changed": _candidate_id(core, b) != _candidate_id(core, p),
            "baseline_market": str(b.get("market_type")),
            "primary_market": str(p.get("market_type")),
            "baseline_q": _q(b),
            "primary_q": _q(p),
            "baseline_pin": _pin(b),
            "primary_pin": _pin(p),
            "baseline_half_shrink_score": _half_shrink_score(b),
            "primary_half_shrink_score": _half_shrink_score(p),
            "baseline_settlement": str(b.get("settlement")),
            "primary_settlement": str(p.get("settlement")),
        })
    return {
        "baseline_v3": base_s,
        "primary_half_shrink": prim_s,
        "secondary_min_cap": min_s,
        "coverage_parity": True,
        "hit_rate_delta_pp": hit_delta,
        "roi_delta_pp": roi_delta,
        "paired": _paired(core, baseline, primary),
        "primary_model_agency": _agency(core, rows, seasons, primary),
        "baseline_model_agency": _agency(core, rows, seasons, baseline),
        "min_cap_model_agency": _agency(core, rows, seasons, min_cap),
    }, comparison_rows


def run(root: Path, v3_candidates: Path, out: Path, prereg: Path) -> None:
    rows = pl.read_parquet(v3_candidates).to_dicts()
    seasons = {int(r["season"]) for r in rows}
    if seasons != DEV | DIAG or SEALED in seasons:
        raise RuntimeError(f"unexpected candidate seasons: {sorted(seasons)}")
    dev, dev_rows = _phase_report(_load_core(root), rows, DEV)
    core = _load_core(root)
    diag, diag_rows = _phase_report(core, rows, DIAG)
    hit_ok = dev["hit_rate_delta_pp"] is not None and float(dev["hit_rate_delta_pp"]) >= 5.0
    roi_ok = dev["roi_delta_pp"] is not None and float(dev["roi_delta_pp"]) >= -1e-12
    verdict = "HALF_SHRINK_DIRECTIONALLY_SUCCESSFUL" if dev["coverage_parity"] and hit_ok and roi_ok else "HALF_SHRINK_NOT_DIRECTIONALLY_SUCCESSFUL"
    score = {
        "verdict": verdict,
        "preregistration_path": PREREG_PATH,
        "preregistration_sha256": _sha256(prereg),
        "periods": {"development": [2020, 2021, 2022], "locked_diagnostic": [2023, 2024], "sealed": [2025]},
        "primary_rule": {"name": "HALF_SHRINK", "coefficient": SHRINK, "ranking_only": True, "eligibility_changed": False},
        "secondary_rule": {"name": "MIN_CAP", "diagnostic_only": True},
        "development_success_gate": {"coverage_parity": bool(dev["coverage_parity"]), "hit_rate_plus_5pp": bool(hit_ok), "roi_nonworse": bool(roi_ok)},
        "development": dev,
        "locked_diagnostic": diag,
        "production_promotion_allowed": False,
        "threshold_selection_allowed": False,
        "2025_firewall": "PASS",
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "hhr_model_market_corroboration_v1_scorecard.json").write_text(json.dumps(score, indent=2, sort_keys=True, allow_nan=False) + "\n")
    pl.DataFrame(dev_rows + diag_rows).write_parquet(out / "hhr_model_market_corroboration_v1_rows.parquet")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--v3-candidates", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--prereg", type=Path, default=Path(PREREG_PATH))
    args = ap.parse_args()
    run(args.root.resolve(), args.v3_candidates, args.out, args.prereg)


if __name__ == "__main__":
    main()
