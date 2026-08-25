#!/usr/bin/env python3
"""Read-only Task05G ML edge-decay audit.

This diagnostic uses the frozen failed-confirmation V2 candidate table plus the
frozen Task05E candidate ledgers. It changes no model, evaluator, selector,
threshold, candidate region, or data and keeps 2025 sealed.

Questions:
- Is general model-only ML probability calibration stable by season/bucket?
- Which ML candidate families/price bands drove the 2023-24 Value collapse?
- Is the failure calibration, candidate-family nonstationarity, or selector rank?
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

import polars as pl

from nfl_edge.recommendation.policy import shop_exact_offers
from nfl_edge.recommendation.remediation_provenance_v1 import build_candidate_registry, enrich_board_rows

SEASONS = {2020, 2021, 2022, 2023, 2024}
SEALED = 2025


def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
    vals = [float(r[key]) for r in rows if r.get(key) is not None and math.isfinite(float(r[key]))]
    return None if not vals else float(mean(vals))


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(str(r.get("settlement")) == "WIN" for r in rows)
    losses = sum(str(r.get("settlement")) == "LOSS" for r in rows)
    pushes = sum(str(r.get("settlement")) == "PUSH" for r in rows)
    nonpush = wins + losses
    return {
        "n": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if nonpush == 0 else wins / nonpush,
        "roi": _avg(rows, "realized_profit"),
        "avg_model_confidence": _avg(rows, "model_confidence_probability"),
        "avg_break_even": _avg(rows, "break_even_probability"),
        "avg_model_price_gap": _avg(rows, "model_price_gap"),
        "avg_evaluator_ev": _avg(rows, "expected_value"),
        "avg_odds": _avg(rows, "american_odds"),
    }


def _group(rows: list[dict[str, Any]], fn) -> dict[str, Any]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(str(fn(r)), []).append(r)
    return {k: _summary(out[k]) for k in sorted(out)}


def _prob_bucket(r: dict[str, Any]) -> str:
    q = float(r.get("model_confidence_probability") or 0.0)
    if q < .45: return "00_<45%"
    if q < .50: return "01_45-50%"
    if q < .55: return "02_50-55%"
    if q < .60: return "03_55-60%"
    if q < .65: return "04_60-65%"
    if q < .70: return "05_65-70%"
    return "06_>=70%"


def _odds_bucket(r: dict[str, Any]) -> str:
    o = int(r.get("american_odds"))
    if o < -200: return "00_<-200"
    if o < -150: return "01_-200_to_-151"
    if o < -110: return "02_-150_to_-111"
    if o <= 100: return "03_-110_to_+100"
    if o <= 150: return "04_+101_to_+150"
    if o <= 200: return "05_+151_to_+200"
    return "06_>+200"


def _gap_bucket(r: dict[str, Any]) -> str:
    g = float(r.get("model_price_gap") or 0.0) * 100.0
    if g < 0: return "00_<0pp"
    if g < 2: return "01_0-2pp"
    if g < 5: return "02_2-5pp"
    if g < 8: return "03_5-8pp"
    if g < 12: return "04_8-12pp"
    return "05_>=12pp"


def _candidate_families(r: dict[str, Any]) -> list[str]:
    raw = str(r.get("model_candidate_regions") or "").strip()
    return [x for x in raw.split(";") if x]


def _family_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    families = sorted({f for r in rows for f in _candidate_families(r)})
    return {f: _summary([r for r in rows if f in _candidate_families(r)]) for f in families}


def _block_map(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(str(r["block"]), []).append(r)
    return out


def _rank(rows: list[dict[str, Any]], key) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for _, block_rows in sorted(_block_map(rows).items()):
        ordered = sorted(block_rows, key=key)
        for i, r in enumerate(ordered, 1):
            x = dict(r)
            x["diagnostic_rank"] = i
            ranked.append(x)
    return ranked


def _calibration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    settled = [r for r in rows if str(r.get("settlement")) in {"WIN", "LOSS"} and r.get("model_confidence_probability") is not None]
    by_bucket: dict[str, Any] = {}
    for bucket, rr in _partition(settled, _prob_bucket).items():
        actual = sum(str(r["settlement"]) == "WIN" for r in rr) / len(rr) if rr else None
        by_bucket[bucket] = {
            **_summary(rr),
            "actual_win_rate": actual,
            "calibration_error": None if actual is None else _avg(rr, "model_confidence_probability") - actual,
        }
    return {
        "overall": _summary(settled),
        "by_probability_bucket": by_bucket,
        "by_season": {str(s): _summary([r for r in settled if int(r["season"]) == s]) for s in sorted(SEASONS)},
    }


def _partition(rows: list[dict[str, Any]], fn) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(str(fn(r)), []).append(r)
    return out


def _decompose(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "overall": _summary(rows),
        "by_season": {str(s): _summary([r for r in rows if int(r["season"]) == s]) for s in sorted(SEASONS)},
        "by_home_away": _group(rows, lambda r: r.get("selected_side")),
        "by_favorite_dog": _group(rows, lambda r: "favorite" if int(r.get("american_odds")) < 0 else "dog_or_even"),
        "by_odds": _group(rows, _odds_bucket),
        "by_model_price_gap": _group(rows, _gap_bucket),
        "by_candidate_family": _family_summary(rows),
    }


def run(root: Path, candidate_path: Path, out: Path) -> None:
    df = pl.read_parquet(candidate_path)
    seasons = {int(x) for x in df["season"].unique().to_list()}
    if SEALED in seasons or not seasons.issubset(SEASONS):
        raise RuntimeError(f"sealed/unexpected season in V2 candidate table: {sorted(seasons)}")
    board_rows = df.to_dicts()

    discovery = pl.read_csv(root / "reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv", infer_schema_length=10000)
    confirmation = pl.read_csv(root / "reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv", infer_schema_length=10000)
    ledger_rows = discovery.to_dicts() + confirmation.to_dicts()
    if any(int(r.get("season")) == SEALED for r in ledger_rows):
        raise RuntimeError("sealed 2025 entered Task05E candidate ledger")
    registry = build_candidate_registry(ledger_rows)
    enriched = enrich_board_rows(board_rows, registry)

    shopped: list[dict[str, Any]] = []
    for _, rr in sorted(_block_map(enriched).items()):
        shopped.extend(dict(r) for r in shop_exact_offers(rr))

    ml = [r for r in shopped if str(r.get("market_type")) == "moneyline" and bool(r.get("model_confidence_supported"))]
    value_eligible = [
        r for r in ml
        if r.get("model_price_gap") is not None
        and float(r["model_price_gap"]) > 0
        and str(r.get("price_status")) == "VALUE"
        and r.get("expected_value") is not None
        and float(r["expected_value"]) > 0
        and -180 <= int(r.get("american_odds")) <= 250
    ]

    ranked = _rank(
        value_eligible,
        lambda r: (
            -min(float(r.get("model_price_gap") or -99), float(r.get("evaluated_edge_probability") or -99)),
            -float(r.get("model_confidence_probability") or -99),
            str(r.get("candidate_id") or ""),
        ),
    )
    rank_groups = {
        "rank1": _summary([r for r in ranked if int(r["diagnostic_rank"]) == 1]),
        "rank2": _summary([r for r in ranked if int(r["diagnostic_rank"]) == 2]),
        "rank3": _summary([r for r in ranked if int(r["diagnostic_rank"]) == 3]),
        "rank4plus": _summary([r for r in ranked if int(r["diagnostic_rank"]) >= 4]),
    }

    # Reproduce Value V2 ML headline choice within each block.
    selected: list[dict[str, Any]] = []
    for _, rr in sorted(_block_map(value_eligible).items()):
        if not rr:
            continue
        choice = sorted(
            rr,
            key=lambda r: (
                -min(float(r.get("model_price_gap") or -99), float(r.get("evaluated_edge_probability") or -99)),
                -float(r.get("model_confidence_probability") or -99),
                -int(r.get("american_odds") or -100000),
                str(r.get("candidate_id") or ""),
            ),
        )[0]
        selected.append(dict(choice))

    result = {
        "purpose": "read-only ML calibration and betting-edge decay audit",
        "development_seasons": [2020, 2021, 2022],
        "confirmation_seasons": [2023, 2024],
        "sealed_seasons": [2025],
        "all_model_confidence_ml": _calibration(ml),
        "value_eligible_ml_pool": _decompose(value_eligible),
        "value_selected_ml": _decompose(selected),
        "value_eligible_rank_performance": rank_groups,
        "candidate_provenance_counts": {
            "all_ml": len(ml),
            "value_eligible": len(value_eligible),
            "value_selected": len(selected),
            "value_eligible_with_frozen_region": sum(bool(r.get("model_candidate")) for r in value_eligible),
            "value_selected_with_frozen_region": sum(bool(r.get("model_candidate")) for r in selected),
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--candidate-table", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    run(Path(a.root), Path(a.candidate_table), Path(a.out))
