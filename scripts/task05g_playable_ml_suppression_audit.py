#!/usr/bin/env python3
"""Read-only Task05G PLAYABLE coverage and ML evaluator-suppression audit.

No selector/evaluator/model thresholds are changed. This diagnostic answers two
localized questions from the stage-provenance audit:

1. What coverage does PLAYABLE add beyond strict VALUE, and what is the realized
   quality of that incremental coverage by market/concession/probability/price?
2. How does ML V4 transform frozen model-derived ML candidates from raw football
   probability through calibrated Pinnacle probability to the final evaluator
   probability/status?

2025 is sealed and hard-rejected.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

import polars as pl

from nfl_edge.recommendation.policy import (
    _balanced_eligible,
    _hit_rate_eligible,
    select_balanced,
    select_hit_rate,
    shop_exact_offers,
)
from nfl_edge.recommendation.remediation_provenance_v1 import build_candidate_registry, enrich_board_rows

DEV = {2020, 2021, 2022, 2023, 2024}
MARKETS = ("moneyline", "spread", "total")


def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
    vals = [float(r[key]) for r in rows if r.get(key) is not None]
    return None if not vals else float(mean(vals))


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(str(r.get("settlement")) == "WIN" for r in rows)
    losses = sum(str(r.get("settlement")) == "LOSS" for r in rows)
    pushes = sum(str(r.get("settlement")) == "PUSH" for r in rows)
    return {
        "n": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if wins + losses == 0 else wins / (wins + losses),
        "roi": _avg(rows, "realized_profit"),
        "avg_actionable_probability": _avg(rows, "actionable_probability"),
        "avg_conditional_nonpush_probability": _avg(rows, "conditional_nonpush_probability"),
        "avg_expected_value": _avg(rows, "expected_value"),
        "avg_break_even_probability": _avg(rows, "break_even_probability"),
        "avg_play_through_concession": _avg(rows, "play_through_break_even_concession"),
        "avg_uncertainty": _avg(rows, "uncertainty"),
        "avg_odds": _avg(rows, "american_odds"),
    }


def _decompose(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "overall": _summary(rows),
        "by_market": {m: _summary([r for r in rows if str(r.get("market_type")) == m]) for m in MARKETS},
        "by_season": {str(s): _summary([r for r in rows if int(r.get("season")) == s]) for s in sorted(DEV)},
        "by_reliability": {tier: _summary([r for r in rows if str(r.get("reliability")) == tier]) for tier in ("HIGH", "MEDIUM")},
    }


def _block_map(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(str(row["block"]), []).append(row)
    return out


def _exact_shopped(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for _, block_rows in sorted(_block_map(rows).items()):
        out.extend(dict(r) for r in shop_exact_offers(block_rows))
    return out


def _selected(rows: list[dict[str, Any]], selector) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for _, block_rows in sorted(_block_map(rows).items()):
        choice = selector(block_rows)
        if not isinstance(choice, str):
            out.append(dict(choice))
    return out


def _bucket(rows: list[dict[str, Any]], fn) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(fn(row), []).append(row)
    return {key: _summary(groups[key]) for key in sorted(groups)}


def _concession_bucket(row: dict[str, Any]) -> str:
    value = row.get("play_through_break_even_concession")
    if value is None:
        return "missing"
    pp = float(value) * 100.0
    if pp <= 0.25:
        return "00_0.00-0.25pp"
    if pp <= 0.50:
        return "01_0.25-0.50pp"
    if pp <= 0.75:
        return "02_0.50-0.75pp"
    if pp <= 1.00:
        return "03_0.75-1.00pp"
    if pp <= 1.25:
        return "04_1.00-1.25pp"
    return "05_1.25-1.50pp"


def _prob_bucket(row: dict[str, Any]) -> str:
    q = float(row.get("actionable_probability") or 0.0)
    if q < .50:
        return "00_<50%"
    if q < .55:
        return "01_50-55%"
    if q < .60:
        return "02_55-60%"
    if q < .65:
        return "03_60-65%"
    return "04_>=65%"


def _odds_bucket(row: dict[str, Any]) -> str:
    odds = int(row.get("american_odds"))
    if odds < -200:
        return "00_<-200"
    if odds < -150:
        return "01_-200_to_-151"
    if odds < -110:
        return "02_-150_to_-111"
    if odds <= 100:
        return "03_-110_to_+100"
    if odds <= 200:
        return "04_+101_to_+200"
    return "05_>+200"


def _negative_ev_bucket(row: dict[str, Any]) -> str:
    ev = float(row.get("expected_value") or 0.0) * 100.0
    if ev >= -0.5:
        return "00_-0.50%_to_0%"
    if ev >= -1.0:
        return "01_-1.00%_to_-0.50%"
    if ev >= -2.0:
        return "02_-2.00%_to_-1.00%"
    return "03_<-2.00%"


def _coverage(rows: list[dict[str, Any]], eligible_fn, selector) -> dict[str, Any]:
    current_blocks: set[str] = set()
    strict_blocks: set[str] = set()
    playable_only_added: list[dict[str, Any]] = []
    selected_all: list[dict[str, Any]] = []
    selected_value: list[dict[str, Any]] = []
    selected_playable: list[dict[str, Any]] = []

    for block, block_rows in sorted(_block_map(rows).items()):
        shopped = [dict(r) for r in shop_exact_offers(block_rows)]
        eligible = [r for r in shopped if eligible_fn(r)]
        strict = [r for r in eligible if str(r.get("price_status")) == "VALUE"]
        if eligible:
            current_blocks.add(block)
        if strict:
            strict_blocks.add(block)

        choice = selector(block_rows)
        if not isinstance(choice, str):
            picked = dict(choice)
            selected_all.append(picked)
            if str(picked.get("price_status")) == "VALUE":
                selected_value.append(picked)
            elif str(picked.get("price_status")) == "PLAYABLE":
                selected_playable.append(picked)
            if block in current_blocks and block not in strict_blocks:
                playable_only_added.append(picked)

    return {
        "blocks_with_current_value_or_playable_eligibility": len(current_blocks),
        "blocks_with_strict_value_eligibility": len(strict_blocks),
        "incremental_blocks_created_by_playable": len(current_blocks - strict_blocks),
        "incremental_block_fraction": None if not current_blocks else len(current_blocks - strict_blocks) / len(current_blocks),
        "selected_all": _decompose(selected_all),
        "selected_strict_value": _decompose(selected_value),
        "selected_playable": _decompose(selected_playable),
        "selected_on_playable_only_incremental_blocks": _decompose(playable_only_added),
    }


def _playable_audit(shopped: list[dict[str, Any]]) -> dict[str, Any]:
    playable = [
        r for r in shopped
        if bool(r.get("supported"))
        and str(r.get("reliability")) in {"HIGH", "MEDIUM"}
        and str(r.get("price_status")) == "PLAYABLE"
    ]
    return {
        "all_high_medium_playable": _decompose(playable),
        "by_break_even_concession": _bucket(playable, _concession_bucket),
        "by_actionable_probability": _bucket(playable, _prob_bucket),
        "by_odds": _bucket(playable, _odds_bucket),
        "by_negative_expected_value": _bucket(playable, _negative_ev_bucket),
        "balanced_eligible_playable": _decompose([r for r in playable if _balanced_eligible(r)]),
        "hit_rate_eligible_playable": _decompose([r for r in playable if _hit_rate_eligible(r)]),
    }


def _status_breakdown(rows: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = ("VALUE", "PLAYABLE", "LEAN", "PASS", "UNSUPPORTED")
    return {status: _decompose([r for r in rows if str(r.get("price_status")) == status]) for status in statuses}


def _load_state(path: Path) -> dict[str, dict[str, Any]]:
    return {str(r["block"]): r for r in (json.loads(line) for line in path.read_text().splitlines() if line.strip())}


def _ml_transform(rows: list[dict[str, Any]], state: dict[str, dict[str, Any]]) -> dict[str, Any]:
    material = [r for r in rows if str(r.get("market_type")) == "moneyline"]
    transformed: list[dict[str, Any]] = []
    for source in material:
        r = dict(source)
        raw = r.get("raw_model_output")
        market = r.get("pinnacle_anchor_probability")
        final_q = r.get("conditional_nonpush_probability")
        r["ml_model_weight"] = state.get(str(r.get("block")), {}).get("ml_model_weight")
        if raw is not None and market is not None:
            r["raw_minus_market"] = float(raw) - float(market)
        else:
            r["raw_minus_market"] = None
        if final_q is not None and market is not None:
            r["final_minus_market"] = float(final_q) - float(market)
        else:
            r["final_minus_market"] = None
        if raw is not None and final_q is not None:
            r["final_minus_raw"] = float(final_q) - float(raw)
        else:
            r["final_minus_raw"] = None
        if raw is not None and market is not None and final_q is not None and abs(float(raw) - float(market)) > 1e-12:
            r["model_signal_retained_ratio"] = abs(float(final_q) - float(market)) / abs(float(raw) - float(market))
        else:
            r["model_signal_retained_ratio"] = None
        transformed.append(r)

    zero = [r for r in transformed if r.get("ml_model_weight") is not None and abs(float(r["ml_model_weight"])) <= 1e-12]
    positive = [r for r in transformed if r.get("ml_model_weight") is not None and float(r["ml_model_weight"]) > 1e-12]

    def transform_summary(rr: list[dict[str, Any]]) -> dict[str, Any]:
        base = _summary(rr)
        base.update({
            "avg_raw_model_probability": _avg(rr, "raw_model_output"),
            "avg_pinnacle_anchor_probability": _avg(rr, "pinnacle_anchor_probability"),
            "avg_final_conditional_probability": _avg(rr, "conditional_nonpush_probability"),
            "avg_raw_minus_market": _avg(rr, "raw_minus_market"),
            "avg_final_minus_market": _avg(rr, "final_minus_market"),
            "avg_final_minus_raw": _avg(rr, "final_minus_raw"),
            "avg_model_signal_retained_ratio": _avg(rr, "model_signal_retained_ratio"),
            "positive_model_disagreement_count": sum(r.get("raw_minus_market") is not None and float(r["raw_minus_market"]) > 0 for r in rr),
            "positive_final_disagreement_count": sum(r.get("final_minus_market") is not None and float(r["final_minus_market"]) > 0 for r in rr),
            "final_probability_below_break_even_count": sum(
                r.get("conditional_nonpush_probability") is not None
                and r.get("break_even_probability") is not None
                and float(r["conditional_nonpush_probability"]) < float(r["break_even_probability"])
                for r in rr
            ),
        })
        return base

    return {
        "overall": transform_summary(transformed),
        "by_status": {status: transform_summary([r for r in transformed if str(r.get("price_status")) == status]) for status in ("VALUE", "PLAYABLE", "LEAN", "PASS", "UNSUPPORTED")},
        "zero_model_weight": transform_summary(zero),
        "positive_model_weight": transform_summary(positive),
        "by_season": {str(s): transform_summary([r for r in transformed if int(r.get("season")) == s]) for s in sorted(DEV)},
    }


def run(root: Path, board_path: Path, state_path: Path, out: Path) -> None:
    board_df = pl.read_parquet(board_path)
    seasons = {int(x) for x in board_df["season"].unique().to_list()}
    if seasons != DEV:
        raise RuntimeError(f"unexpected board seasons {sorted(seasons)}")

    discovery = pl.read_csv(root / "reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv", infer_schema_length=10000)
    confirmation = pl.read_csv(root / "reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv", infer_schema_length=10000)
    ledgers = discovery.to_dicts() + confirmation.to_dicts()
    if any(int(r.get("season")) == 2025 for r in ledgers):
        raise RuntimeError("sealed 2025 entered Task05E candidate ledger")

    registry = build_candidate_registry(ledgers)
    enriched = enrich_board_rows(board_df.to_dicts(), registry)
    shopped = _exact_shopped(enriched)
    region = [r for r in shopped if bool(r.get("model_candidate"))]
    dog_avg = [r for r in region if "ML_DOG_VALUE_ZONE_AVG" in str(r.get("model_candidate_regions") or "").split(";")]
    dog_corrob = [r for r in region if "ML_DOG_VALUE_ZONE_CORROB" in str(r.get("model_candidate_regions") or "").split(";")]
    ml_union = [r for r in region if str(r.get("market_type")) == "moneyline"]
    state = _load_state(state_path)

    result = {
        "purpose": "read-only PLAYABLE coverage and ML suppression audit; no policy/model/evaluator changes",
        "development_seasons": sorted(DEV),
        "sealed_seasons": [2025],
        "playable": _playable_audit(shopped),
        "coverage_tradeoff": {
            "hit_rate": _coverage(enriched, _hit_rate_eligible, select_hit_rate),
            "balanced": _coverage(enriched, _balanced_eligible, select_balanced),
        },
        "frozen_region_status_breakdown": _status_breakdown(region),
        "ml_evaluator_suppression": {
            "frozen_ml_region_union": _ml_transform(ml_union, state),
            "ml_dog_value_avg": _ml_transform(dog_avg, state),
            "ml_dog_value_corrob": _ml_transform(dog_corrob, state),
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--board", required=True)
    p.add_argument("--state-by-block", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    run(Path(a.root), Path(a.board), Path(a.state_by_block), Path(a.out))
