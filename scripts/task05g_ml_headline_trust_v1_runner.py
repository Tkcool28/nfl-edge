#!/usr/bin/env python3
"""Preregistered Task05G ML Headline Trust V1 diagnostic.

Consumes the validated Spread Confidence V3 candidate table and changes ranking
trust only. It never changes model-confidence calibration or candidate eligibility.
Season 2025 is prohibited.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping

import polars as pl

DEV = {2020, 2021, 2022}
DIAG = {2023, 2024}
SEALED = 2025
PRIMARY_LAMBDA = 0.50
SENSITIVITY = {"T025": 0.25, "T100": 1.00}
PREREG_PATH = "docs/task05g_ml_headline_trust_v1_preregistration.md"


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


def _block_tuple(value: str) -> tuple[int, int]:
    season, week = str(value).split("-", 1)
    return int(season), int(week)


def _group_blocks(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(str(row["block"]), []).append(dict(row))
    return out


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def _candidate_id(core, row: Mapping[str, Any]) -> str:
    return str(core._candidate_id(row))


def _disagreement(row: Mapping[str, Any]) -> float | None:
    if str(row.get("market_type")) != "moneyline":
        return None
    qb = _finite(row.get("raw_qbelo_probability_selected"))
    xgb = _finite(row.get("raw_xgb_probability_selected"))
    if qb is None or xgb is None:
        return None
    return abs(qb - xgb)


def _trust_score(row: Mapping[str, Any], penalty: float) -> float:
    q = _finite(row.get("model_confidence_probability"))
    if q is None:
        raise RuntimeError("trust score requested for unsupported confidence row")
    if str(row.get("market_type")) != "moneyline":
        return q
    d = _disagreement(row)
    if d is None:
        raise RuntimeError("eligible ML row missing constituent-model probabilities")
    return q - float(penalty) * d


def _shop(core, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(r) for r in core.shop_exact_offers(rows)]


def _eligible(core, row: Mapping[str, Any], lane: str) -> bool:
    if lane == "hhr":
        return bool(core._hhr_eligible(row))
    if lane == "balanced":
        return bool(core._balanced_eligible(row, 0.0))
    raise ValueError(lane)


def _baseline_key(core, row: Mapping[str, Any], lane: str):
    if lane == "hhr":
        return (
            -float(row["model_confidence_probability"]),
            -core._reliability_rank(row.get("reliability")),
            -float(row.get("model_price_gap") if row.get("model_price_gap") is not None else -99.0),
            -int(row.get("american_odds") or -100000),
            _candidate_id(core, row),
        )
    if lane == "balanced":
        return (
            -float(row["model_confidence_probability"]),
            -float(row.get("model_price_gap") if row.get("model_price_gap") is not None else -99.0),
            -core._reliability_rank(row.get("reliability")),
            -int(row.get("american_odds") or -100000),
            _candidate_id(core, row),
        )
    raise ValueError(lane)


def _trust_key(core, row: Mapping[str, Any], lane: str, penalty: float):
    score = _trust_score(row, penalty)
    if lane == "hhr":
        return (
            -score,
            -core._reliability_rank(row.get("reliability")),
            -float(row.get("model_price_gap") if row.get("model_price_gap") is not None else -99.0),
            -int(row.get("american_odds") or -100000),
            _candidate_id(core, row),
        )
    if lane == "balanced":
        return (
            -score,
            -float(row.get("model_price_gap") if row.get("model_price_gap") is not None else -99.0),
            -core._reliability_rank(row.get("reliability")),
            -int(row.get("american_odds") or -100000),
            _candidate_id(core, row),
        )
    raise ValueError(lane)


def _select_block(core, rows: list[dict[str, Any]], lane: str, penalty: float | None) -> dict[str, Any] | None:
    shopped = _shop(core, rows)
    candidates = [r for r in shopped if _eligible(core, r, lane)]
    if not candidates:
        return None
    if penalty is None:
        return dict(sorted(candidates, key=lambda r: _baseline_key(core, r, lane))[0])
    return dict(sorted(candidates, key=lambda r: _trust_key(core, r, lane, penalty))[0])


def _select_phase(
    core,
    rows: list[dict[str, Any]],
    seasons: set[int],
    lane: str,
    penalty: float | None,
) -> dict[str, dict[str, Any]]:
    phase = [r for r in rows if int(r["season"]) in seasons]
    blocks = _group_blocks(phase)
    out: dict[str, dict[str, Any]] = {}
    for block in sorted(blocks, key=_block_tuple):
        choice = _select_block(core, blocks[block], lane, penalty)
        if choice is not None:
            choice["headline_trust_score"] = _trust_score(choice, PRIMARY_LAMBDA if penalty is None else penalty)
            choice["qb_xgb_abs_disagreement"] = _disagreement(choice)
            out[block] = choice
    return out


def _settlement(row: Mapping[str, Any] | None) -> str | None:
    return None if row is None else str(row.get("settlement"))


def _summary(selected: dict[str, dict[str, Any]], total_blocks: int, penalty: float) -> dict[str, Any]:
    rows = list(selected.values())
    wins = sum(_settlement(r) == "WIN" for r in rows)
    losses = sum(_settlement(r) == "LOSS" for r in rows)
    pushes = sum(_settlement(r) == "PUSH" for r in rows)
    nonpush = wins + losses
    profits = [_finite(r.get("realized_profit")) for r in rows]
    profits = [x for x in profits if x is not None]
    ml = [r for r in rows if str(r.get("market_type")) == "moneyline"]
    q = [_finite(r.get("model_confidence_probability")) for r in ml]
    q = [x for x in q if x is not None]
    d = [_disagreement(r) for r in ml]
    d = [x for x in d if x is not None]
    trust = [_trust_score(r, penalty) for r in rows]
    odds = [_finite(r.get("american_odds")) for r in rows]
    odds = [x for x in odds if x is not None]
    return {
        "plays": len(rows),
        "play_blocks": len(selected),
        "total_blocks": total_blocks,
        "coverage": 0.0 if total_blocks == 0 else len(selected) / total_blocks,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if nonpush == 0 else wins / nonpush,
        "roi": None if not profits else float(mean(profits)),
        "avg_odds": None if not odds else float(mean(odds)),
        "avg_headline_trust_score": None if not trust else float(mean(trust)),
        "selected_ml_n": len(ml),
        "avg_selected_ml_confidence": None if not q else float(mean(q)),
        "avg_selected_ml_disagreement": None if not d else float(mean(d)),
        "by_market": {
            market: sum(str(r.get("market_type")) == market for r in rows)
            for market in ("moneyline", "spread", "total")
        },
    }


def _paired(baseline: dict[str, dict[str, Any]], primary: dict[str, dict[str, Any]]) -> dict[str, int]:
    out = {"both_win": 0, "both_lose": 0, "new_only_win": 0, "old_only_win": 0, "paired_nonpush": 0}
    for block in sorted(set(baseline) & set(primary), key=_block_tuple):
        old = _settlement(baseline[block])
        new = _settlement(primary[block])
        if old not in {"WIN", "LOSS"} or new not in {"WIN", "LOSS"}:
            continue
        out["paired_nonpush"] += 1
        if old == "WIN" and new == "WIN":
            out["both_win"] += 1
        elif old == "LOSS" and new == "LOSS":
            out["both_lose"] += 1
        elif old == "LOSS" and new == "WIN":
            out["new_only_win"] += 1
        elif old == "WIN" and new == "LOSS":
            out["old_only_win"] += 1
    return out


def _comparison_rows(
    core,
    seasons_label: str,
    lane: str,
    baseline: dict[str, dict[str, Any]],
    primary: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for block in sorted(set(baseline) | set(primary), key=_block_tuple):
        old = baseline.get(block)
        new = primary.get(block)
        rows.append(
            {
                "phase": seasons_label,
                "lane": lane,
                "block": block,
                "baseline_candidate_id": None if old is None else _candidate_id(core, old),
                "primary_candidate_id": None if new is None else _candidate_id(core, new),
                "changed": bool(old is not None and new is not None and _candidate_id(core, old) != _candidate_id(core, new)),
                "baseline_market": None if old is None else str(old.get("market_type")),
                "primary_market": None if new is None else str(new.get("market_type")),
                "baseline_odds": None if old is None else old.get("american_odds"),
                "primary_odds": None if new is None else new.get("american_odds"),
                "baseline_q": None if old is None else old.get("model_confidence_probability"),
                "primary_q": None if new is None else new.get("model_confidence_probability"),
                "baseline_trust_score": None if old is None else _trust_score(old, PRIMARY_LAMBDA),
                "primary_trust_score": None if new is None else _trust_score(new, PRIMARY_LAMBDA),
                "baseline_ml_disagreement": None if old is None else _disagreement(old),
                "primary_ml_disagreement": None if new is None else _disagreement(new),
                "baseline_settlement": _settlement(old),
                "primary_settlement": _settlement(new),
            }
        )
    return rows


def _lane_report(core, rows: list[dict[str, Any]], seasons: set[int], lane: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    total_blocks = len({str(r["block"]) for r in rows if int(r["season"]) in seasons})
    baseline = _select_phase(core, rows, seasons, lane, None)
    primary = _select_phase(core, rows, seasons, lane, PRIMARY_LAMBDA)
    if set(baseline) != set(primary):
        raise RuntimeError(f"coverage parity failure for {lane} {sorted(seasons)}")

    base_summary = _summary(baseline, total_blocks, PRIMARY_LAMBDA)
    primary_summary = _summary(primary, total_blocks, PRIMARY_LAMBDA)
    changed = sum(_candidate_id(core, baseline[b]) != _candidate_id(core, primary[b]) for b in baseline)
    comparison = {
        "baseline_v3": base_summary,
        "primary_t050": primary_summary,
        "changed_blocks": changed,
        "changed_block_rate": 0.0 if not baseline else changed / len(baseline),
        "paired_outcomes": _paired(baseline, primary),
        "coverage_parity": base_summary["play_blocks"] == primary_summary["play_blocks"],
        "hit_rate_delta_pp": None
        if base_summary["hit_rate_nonpush"] is None or primary_summary["hit_rate_nonpush"] is None
        else 100.0 * (float(primary_summary["hit_rate_nonpush"]) - float(base_summary["hit_rate_nonpush"])),
        "roi_delta_pp": None
        if base_summary["roi"] is None or primary_summary["roi"] is None
        else 100.0 * (float(primary_summary["roi"]) - float(base_summary["roi"])),
        "sensitivities": {},
    }
    for name, penalty in SENSITIVITY.items():
        selected = _select_phase(core, rows, seasons, lane, penalty)
        if set(selected) != set(baseline):
            raise RuntimeError(f"sensitivity coverage parity failure {name} {lane} {sorted(seasons)}")
        s = _summary(selected, total_blocks, penalty)
        changed_s = sum(_candidate_id(core, baseline[b]) != _candidate_id(core, selected[b]) for b in baseline)
        comparison["sensitivities"][name] = {
            "penalty": penalty,
            "summary": s,
            "changed_blocks": changed_s,
            "changed_block_rate": 0.0 if not baseline else changed_s / len(baseline),
        }
    label = "development" if seasons == DEV else "locked_diagnostic"
    return comparison, _comparison_rows(core, label, lane, baseline, primary)


def _development_verdict(dev: dict[str, Any]) -> str:
    hhr = dev["hhr"]
    bal = dev["balanced_b0"]
    invariants = hhr["coverage_parity"] and bal["coverage_parity"]
    if not invariants:
        return "PRIMARY_TRUST_CORRECTION_INVALID"
    hhr_hit = hhr["hit_rate_delta_pp"] is not None and float(hhr["hit_rate_delta_pp"]) >= 5.0
    bal_hit = bal["hit_rate_delta_pp"] is not None and float(bal["hit_rate_delta_pp"]) >= 5.0
    hhr_roi = hhr["roi_delta_pp"] is not None and float(hhr["roi_delta_pp"]) >= -1e-12
    bal_roi = bal["roi_delta_pp"] is not None and float(bal["roi_delta_pp"]) >= -1e-12
    return (
        "PRIMARY_TRUST_CORRECTION_DIRECTIONALLY_SUCCESSFUL"
        if hhr_hit and bal_hit and hhr_roi and bal_roi
        else "PRIMARY_TRUST_CORRECTION_MIXED"
    )


def run(root: Path, candidates: Path, out: Path) -> None:
    prereg = root / PREREG_PATH
    if not prereg.exists():
        raise RuntimeError("missing frozen preregistration")
    rows = pl.read_parquet(candidates).to_dicts()
    seasons = {int(r["season"]) for r in rows}
    if seasons != DEV | DIAG or SEALED in seasons:
        raise RuntimeError(f"unexpected/sealed seasons: {sorted(seasons)}")

    core = _load_core(root)
    dev_hhr, dev_hhr_rows = _lane_report(core, rows, DEV, "hhr")
    dev_bal, dev_bal_rows = _lane_report(core, rows, DEV, "balanced")
    diag_hhr, diag_hhr_rows = _lane_report(core, rows, DIAG, "hhr")
    diag_bal, diag_bal_rows = _lane_report(core, rows, DIAG, "balanced")

    development = {"hhr": dev_hhr, "balanced_b0": dev_bal}
    locked = {"hhr": diag_hhr, "balanced_b0": diag_bal}
    verdict = _development_verdict(development)
    robust = all(
        locked[lane]["hit_rate_delta_pp"] is not None and float(locked[lane]["hit_rate_delta_pp"]) >= -2.0
        for lane in ("hhr", "balanced_b0")
    )

    score = {
        "verdict": verdict,
        "scope": "diagnostic_only_no_production_promotion",
        "preregistration": {"path": PREREG_PATH, "sha256": _sha256(prereg)},
        "primary_rule": {
            "penalty": PRIMARY_LAMBDA,
            "formula": "q - 0.50 * abs(qbelo_selected - xgb_selected) for ML; q for spread",
            "ranking_only": True,
            "eligibility_changed": False,
        },
        "sensitivity_rules": SENSITIVITY,
        "periods": {"development": sorted(DEV), "locked_diagnostic": sorted(DIAG), "sealed": [SEALED]},
        "development": development,
        "locked_diagnostic": locked,
        "locked_diagnostic_robustness_note_eligible": robust,
        "production_promotion_allowed": False,
    }
    out.mkdir(parents=True, exist_ok=True)
    _json_write(out / "ml_headline_trust_v1_scorecard.json", score)
    comparison_rows = dev_hhr_rows + dev_bal_rows + diag_hhr_rows + diag_bal_rows
    pl.DataFrame(comparison_rows).sort(["phase", "lane", "block"]).write_parquet(out / "ml_headline_trust_v1_rows.parquet")
    print(json.dumps(score, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--v3-candidates", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    run(Path(a.root), Path(a.v3_candidates), Path(a.out))
