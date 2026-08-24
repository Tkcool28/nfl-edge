#!/usr/bin/env python3
"""Read-only Task05G stage-by-stage model/evaluator/selector provenance audit.

This diagnostic never changes model/evaluator/selector policy. It compares the
intended full common-candidate-table selector path with the remediation-only
Task05E frozen-region gate and reports where populations degrade.
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
from nfl_edge.recommendation.remediation_provenance_v1 import (
    build_candidate_registry,
    enrich_board_rows,
)

DEV = {2020, 2021, 2022, 2023, 2024}
MARKETS = ("moneyline", "spread", "total")


def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(r[key]) for r in rows if r.get(key) is not None]
    return None if not values else float(mean(values))


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
        "avg_expected_value": _avg(rows, "expected_value"),
        "avg_model_market_disagreement": _avg(rows, "model_market_disagreement"),
        "avg_uncertainty": _avg(rows, "uncertainty"),
    }


def _decompose(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "overall": _summary(rows),
        "by_market": {m: _summary([r for r in rows if str(r.get("market_type")) == m]) for m in MARKETS},
        "by_season": {str(s): _summary([r for r in rows if int(r.get("season")) == s]) for s in sorted(DEV)},
    }


def _block_map(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
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


def _stage_table(shopped: list[dict[str, Any]]) -> dict[str, Any]:
    supported = [r for r in shopped if bool(r.get("supported"))]
    hm = [r for r in supported if str(r.get("reliability")) in {"HIGH", "MEDIUM"}]
    vp = [r for r in hm if str(r.get("price_status")) in {"VALUE", "PLAYABLE"}]
    strict_value = [r for r in hm if str(r.get("price_status")) == "VALUE"]
    hhr_eligible = [r for r in shopped if _hit_rate_eligible(r)]
    balanced_eligible = [r for r in shopped if _balanced_eligible(r)]
    return {
        "exact_shopped": _decompose(shopped),
        "supported": _decompose(supported),
        "high_medium": _decompose(hm),
        "value_or_playable": _decompose(vp),
        "strict_value": _decompose(strict_value),
        "hit_rate_eligible": _decompose(hhr_eligible),
        "balanced_eligible": _decompose(balanced_eligible),
    }


def _region_breakdown(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tags = sorted({tag for r in rows for tag in str(r.get("model_candidate_regions") or "").split(";") if tag})
    return {tag: _decompose([r for r in rows if tag in str(r.get("model_candidate_regions") or "").split(";")]) for tag in tags}


def _selected_inside_outside(rows: list[dict[str, Any]]) -> dict[str, Any]:
    inside = [r for r in rows if bool(r.get("model_candidate"))]
    outside = [r for r in rows if not bool(r.get("model_candidate"))]
    return {
        "all": _decompose(rows),
        "inside_frozen_task05e_regions": _decompose(inside),
        "outside_frozen_task05e_regions": _decompose(outside),
        "region_membership": _region_breakdown(inside),
    }


def _rank_band(rows: list[dict[str, Any]], key: str, descending: bool = True) -> dict[str, Any]:
    bands: dict[str, list[dict[str, Any]]] = {"rank1": [], "rank2": [], "rank3": [], "rank4plus": []}
    for block, block_rows in sorted(_block_map(rows).items()):
        material = [r for r in block_rows if r.get(key) is not None]
        material = sorted(material, key=lambda r: float(r[key]), reverse=descending)
        for i, row in enumerate(material, start=1):
            band = "rank1" if i == 1 else "rank2" if i == 2 else "rank3" if i == 3 else "rank4plus"
            bands[band].append(row)
    return {band: _decompose(material) for band, material in bands.items()}


def _spread_ranking_diagnostic(region_rows: list[dict[str, Any]]) -> dict[str, Any]:
    spreads = [r for r in region_rows if str(r.get("market_type")) == "spread"]
    return {
        "all_spread_region_rows": _decompose(spreads),
        "actionable_probability_rank_bands_within_block": _rank_band(spreads, "actionable_probability", True),
        "model_market_disagreement_rank_bands_within_block": _rank_band(spreads, "model_market_disagreement", True),
    }


def _load_state(path: Path) -> dict[str, dict[str, Any]]:
    return {str(r["block"]): r for r in (json.loads(line) for line in path.read_text().splitlines() if line.strip())}


def _influence_split(rows: list[dict[str, Any]], state: dict[str, dict[str, Any]], market: str) -> dict[str, Any]:
    field = {"moneyline": "ml_model_weight", "spread": "spread_beta", "total": "total_beta"}[market]
    material = [r for r in rows if str(r.get("market_type")) == market]
    zero: list[dict[str, Any]] = []
    positive: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for row in material:
        value = state.get(str(row["block"]), {}).get(field)
        if value is None:
            missing.append(row)
        elif abs(float(value)) <= 1e-12:
            zero.append(row)
        else:
            positive.append(row)
    return {
        "influence_field": field,
        "zero_influence": _decompose(zero),
        "positive_influence": _decompose(positive),
        "missing_state": _decompose(missing),
    }


def run(root: Path, board_path: Path, state_path: Path, out: Path) -> None:
    board_df = pl.read_parquet(board_path)
    seasons = {int(x) for x in board_df["season"].unique().to_list()}
    if seasons != DEV:
        raise RuntimeError(f"unexpected board seasons {sorted(seasons)}")

    discovery = pl.read_csv(root / "reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv", infer_schema_length=10000)
    confirmation = pl.read_csv(root / "reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv", infer_schema_length=10000)
    if 2025 in set(int(x) for x in pl.concat([discovery.select("season"), confirmation.select("season")])["season"].unique().to_list()):
        raise RuntimeError("sealed 2025 entered Task05E candidate ledger")

    registry = build_candidate_registry(discovery.to_dicts() + confirmation.to_dicts())
    enriched = enrich_board_rows(board_df.to_dicts(), registry)
    shopped = _exact_shopped(enriched)
    region_shopped = [r for r in shopped if bool(r.get("model_candidate"))]
    outside_shopped = [r for r in shopped if not bool(r.get("model_candidate"))]

    full_hhr = _selected(enriched, select_hit_rate)
    full_balanced = _selected(enriched, select_balanced)
    region_hhr = _selected([r for r in enriched if bool(r.get("model_candidate"))], select_hit_rate)
    region_balanced = _selected([r for r in enriched if bool(r.get("model_candidate"))], select_balanced)

    state = _load_state(state_path)

    result = {
        "purpose": "read-only stage-by-stage provenance audit; no policy/model/evaluator changes",
        "development_seasons": sorted(DEV),
        "sealed_seasons": [2025],
        "architecture_note": {
            "intended_selector_universe": "full common evaluated-wager table",
            "remediation_region_gate": "diagnostic only; not permanent Hit Rate/Balanced eligibility",
        },
        "registry_candidate_sides": len(registry),
        "full_common_table_stages": _stage_table(shopped),
        "frozen_region_stages": _stage_table(region_shopped),
        "outside_frozen_regions_stages": _stage_table(outside_shopped),
        "original_full_board_hit_rate_selected": _selected_inside_outside(full_hhr),
        "original_full_board_balanced_selected": _selected_inside_outside(full_balanced),
        "diagnostic_region_only_hit_rate_selected": _selected_inside_outside(region_hhr),
        "diagnostic_region_only_balanced_selected": _selected_inside_outside(region_balanced),
        "frozen_region_stage_by_region": _region_breakdown(region_shopped),
        "spread_region_ranking": _spread_ranking_diagnostic(region_shopped),
        "evaluator_influence_on_region_rows": {
            "moneyline": _influence_split(region_shopped, state, "moneyline"),
            "spread": _influence_split(region_shopped, state, "spread"),
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
