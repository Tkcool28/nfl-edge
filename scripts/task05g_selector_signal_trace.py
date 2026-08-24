#!/usr/bin/env python3
"""Read-only selector signal trace for Task05G.

This diagnostic does not change any selector/evaluator/model rule. It asks:

* HHR PLAYABLE: does highest evaluator probability select market-juiced offers
  rather than the highest raw football-model probability?
* Balanced strict VALUE: where does the current cross-market ranking anti-select
  an already-admitted strict-VALUE pool?
* Generic strict VALUE: how do rows with frozen Task05E model provenance differ
  from evaluator-created rows outside those candidate families?

2025 is sealed and rejected.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Iterable

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
        "avg_raw_model_output": _avg(rows, "raw_model_output"),
        "avg_break_even_probability": _avg(rows, "break_even_probability"),
        "avg_expected_value": _avg(rows, "expected_value"),
        "avg_american_odds": _avg(rows, "american_odds"),
        "avg_evaluator_minus_raw_model": _avg(rows, "evaluator_minus_raw_model"),
        "avg_model_minus_break_even": _avg(rows, "model_minus_break_even"),
        "avg_model_market_disagreement": _avg(rows, "model_market_disagreement"),
    }


def _decompose(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "overall": _summary(rows),
        "by_market": {m: _summary([r for r in rows if str(r.get("market_type")) == m]) for m in MARKETS},
        "by_season": {str(s): _summary([r for r in rows if int(r.get("season")) == s]) for s in sorted(DEV)},
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


def _augment(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for source in rows:
        r = dict(source)
        market = str(r.get("market_type"))
        q = r.get("actionable_probability")
        raw = r.get("raw_model_output")
        be = r.get("break_even_probability")
        # raw_model_output is a selected-side probability only for ML. For point
        # markets it is a football point estimate (margin / total), so probability
        # arithmetic must not be applied there.
        if market == "moneyline" and q is not None and raw is not None:
            r["evaluator_minus_raw_model"] = float(q) - float(raw)
        else:
            r["evaluator_minus_raw_model"] = None
        if market == "moneyline" and raw is not None and be is not None:
            r["model_minus_break_even"] = float(raw) - float(be)
        else:
            r["model_minus_break_even"] = None
        out.append(r)
    return out


def _rank_bands(rows: list[dict[str, Any]], key: str, descending: bool = True) -> dict[str, Any]:
    bands: dict[str, list[dict[str, Any]]] = {"rank1": [], "rank2": [], "rank3": [], "rank4plus": []}
    for _, block_rows in sorted(_block_map(rows).items()):
        material = [r for r in block_rows if r.get(key) is not None]
        material.sort(key=lambda r: float(r[key]), reverse=descending)
        for i, row in enumerate(material, start=1):
            band = "rank1" if i == 1 else "rank2" if i == 2 else "rank3" if i == 3 else "rank4plus"
            bands[band].append(row)
    return {name: _decompose(material) for name, material in bands.items()}


def _selected_vs_rest(pool: list[dict[str, Any]], selected: list[dict[str, Any]]) -> dict[str, Any]:
    ids = {str(r.get("candidate_id")) for r in selected}
    rest = [r for r in pool if str(r.get("candidate_id")) not in ids]
    return {"selected": _decompose(selected), "not_selected": _decompose(rest)}


def _provenance_split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    inside = [r for r in rows if bool(r.get("model_candidate"))]
    outside = [r for r in rows if not bool(r.get("model_candidate"))]
    return {
        "all": _decompose(rows),
        "inside_frozen_model_regions": _decompose(inside),
        "outside_frozen_model_regions": _decompose(outside),
    }


def _region_tag_split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tags = sorted({tag for r in rows for tag in str(r.get("model_candidate_regions") or "").split(";") if tag})
    return {
        tag: _decompose([r for r in rows if tag in str(r.get("model_candidate_regions") or "").split(";")])
        for tag in tags
    }


def _hhr_trace(shopped: list[dict[str, Any]], all_rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [r for r in shopped if _hit_rate_eligible(r)]
    playable = [r for r in eligible if str(r.get("price_status")) == "PLAYABLE"]
    selected = _augment(_selected(all_rows, select_hit_rate))
    selected_playable = [r for r in selected if str(r.get("price_status")) == "PLAYABLE"]
    playable = _augment(playable)
    ml_playable = [r for r in playable if str(r.get("market_type")) == "moneyline"]

    # Diagnostic only: within PLAYABLE ML candidates in each block, what would
    # rank first under distinct signals? This is not a replacement HHR policy.
    return {
        "eligible_pool": _decompose(_augment(eligible)),
        "playable_pool": _decompose(playable),
        "selected_playable": _decompose(selected_playable),
        "selected_vs_unselected_playable": _selected_vs_rest(playable, selected_playable),
        "playable_ml_rank_by_current_actionable_probability": _rank_bands(ml_playable, "actionable_probability", True),
        "playable_ml_rank_by_raw_model_probability": _rank_bands(ml_playable, "raw_model_output", True),
        "playable_ml_rank_by_model_minus_break_even": _rank_bands(ml_playable, "model_minus_break_even", True),
        "playable_ml_rank_by_better_price": _rank_bands(ml_playable, "american_odds", True),
        "selected_playable_provenance": _provenance_split(selected_playable),
    }


def _balanced_trace(shopped: list[dict[str, Any]], all_rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = _augment([r for r in shopped if _balanced_eligible(r)])
    strict_pool = [r for r in eligible if str(r.get("price_status")) == "VALUE"]
    selected = _augment(_selected(all_rows, select_balanced))
    selected_strict = [r for r in selected if str(r.get("price_status")) == "VALUE"]

    by_market: dict[str, Any] = {}
    for market in MARKETS:
        pool = [r for r in strict_pool if str(r.get("market_type")) == market]
        picked = [r for r in selected_strict if str(r.get("market_type")) == market]
        market_diag: dict[str, Any] = {
            "pool": _decompose(pool),
            "selected": _decompose(picked),
            "selected_vs_rest": _selected_vs_rest(pool, picked),
            "provenance": _provenance_split(pool),
            "selected_provenance": _provenance_split(picked),
            "rank_by_expected_value": _rank_bands(pool, "expected_value", True),
            "rank_by_actionable_probability": _rank_bands(pool, "actionable_probability", True),
            "rank_by_better_price": _rank_bands(pool, "american_odds", True),
        }
        if market == "moneyline":
            market_diag["rank_by_raw_model_probability"] = _rank_bands(pool, "raw_model_output", True)
            market_diag["rank_by_model_minus_break_even"] = _rank_bands(pool, "model_minus_break_even", True)
            market_diag["rank_by_model_market_disagreement"] = _rank_bands(pool, "model_market_disagreement", True)
        elif market == "spread":
            market_diag["rank_by_model_market_disagreement"] = _rank_bands(pool, "model_market_disagreement", True)
        by_market[market] = market_diag

    return {
        "eligible_pool": _decompose(eligible),
        "strict_value_pool": _decompose(strict_pool),
        "selected_strict_value": _decompose(selected_strict),
        "strict_value_provenance": _provenance_split(strict_pool),
        "selected_strict_value_provenance": _provenance_split(selected_strict),
        "selected_strict_value_region_tags": _region_tag_split(selected_strict),
        "by_market": by_market,
    }


def _generic_strict_value_trace(shopped: list[dict[str, Any]]) -> dict[str, Any]:
    strict = _augment([
        r for r in shopped
        if bool(r.get("supported"))
        and str(r.get("reliability")) in {"HIGH", "MEDIUM"}
        and str(r.get("price_status")) == "VALUE"
    ])
    return {
        "all": _provenance_split(strict),
        "moneyline": _provenance_split([r for r in strict if str(r.get("market_type")) == "moneyline"]),
        "spread": _provenance_split([r for r in strict if str(r.get("market_type")) == "spread"]),
        "total": _provenance_split([r for r in strict if str(r.get("market_type")) == "total"]),
        "inside_region_tags": _region_tag_split([r for r in strict if bool(r.get("model_candidate"))]),
    }


def run(root: Path, board_path: Path, out: Path) -> None:
    board_df = pl.read_parquet(board_path)
    seasons = {int(x) for x in board_df["season"].unique().to_list()}
    if seasons != DEV:
        raise RuntimeError(f"unexpected board seasons {sorted(seasons)}")

    discovery = pl.read_csv(root / "reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv", infer_schema_length=10000)
    confirmation = pl.read_csv(root / "reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv", infer_schema_length=10000)
    ledgers = discovery.to_dicts() + confirmation.to_dicts()
    if any(int(r.get("season")) == 2025 for r in ledgers):
        raise RuntimeError("sealed 2025 entered Task05E ledger")

    registry = build_candidate_registry(ledgers)
    enriched = enrich_board_rows(board_df.to_dicts(), registry)
    shopped = _augment(_exact_shopped(enriched))

    result = {
        "purpose": "read-only HHR model-signal / Balanced strict-VALUE selection trace",
        "development_seasons": sorted(DEV),
        "sealed_seasons": [2025],
        "notes": {
            "hhr_model_probability": "raw_model_output is a selected-side probability only for moneyline; point markets are not compared as probabilities",
            "counterfactual_rank_bands": "diagnostic only; no replacement selector adopted",
        },
        "hit_rate": _hhr_trace(shopped, enriched),
        "balanced": _balanced_trace(shopped, enriched),
        "generic_strict_value": _generic_strict_value_trace(shopped),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--board", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    run(Path(a.root), Path(a.board), Path(a.out))
