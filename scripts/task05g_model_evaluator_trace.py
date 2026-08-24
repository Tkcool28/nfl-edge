#!/usr/bin/env python3
"""Trace frozen football-model signal through Task05F evaluators into Task05G selections.

Read-only 2020-2024 diagnostic.  This script does not change thresholds, models,
evaluators, selector policy, or any sealed-season material.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

import polars as pl

from nfl_edge.recommendation.policy import _value_eligible, shop_exact_offers

DEV = {2020, 2021, 2022, 2023, 2024}


def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
    vals = [float(r[key]) for r in rows if r.get(key) is not None]
    return None if not vals else float(mean(vals))


def _roi(rows: list[dict[str, Any]]) -> float | None:
    return _avg(rows, "realized_profit")


def _basic(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(r.get("settlement") == "WIN" for r in rows)
    losses = sum(r.get("settlement") == "LOSS" for r in rows)
    pushes = sum(r.get("settlement") == "PUSH" for r in rows)
    return {
        "n": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if wins + losses == 0 else wins / (wins + losses),
        "roi": _roi(rows),
        "avg_raw_model_output": _avg(rows, "raw_model_output"),
        "avg_pinnacle_anchor_probability": _avg(rows, "pinnacle_anchor_probability"),
        "avg_evaluator_actionable_probability": _avg(rows, "actionable_probability"),
        "avg_expected_value": _avg(rows, "expected_value"),
        "avg_model_market_disagreement": _avg(rows, "model_market_disagreement"),
    }


def _exact_frozen_sets(root: Path) -> dict[str, set[tuple[Any, ...]]]:
    discovery = pl.read_csv(root / "reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv")
    confirmation = pl.read_csv(root / "reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv")
    ledger = pl.concat([discovery, confirmation], how="vertical_relaxed")
    specs = {
        "ML_DOG_VALUE_ZONE_AVG": ((pl.col("family") == "ML_DOG_VALUE_ZONE") & (pl.col("model") == "AVG") & (pl.col("bucket") == "ZONE")),
        "ML_CORROBORATED_DOG_VALUE_ZONE": ((pl.col("family") == "ML_DOG_VALUE_ZONE") & (pl.col("model") == "CORROB") & (pl.col("bucket") == "ZONE")),
        "ML_AVG_0_2": ((pl.col("family") == "ML_AVG_DISAGREEMENT") & (pl.col("model") == "AVG") & (pl.col("bucket") == "0-2")),
        "SPREAD_0_4": ((pl.col("family") == "SPREAD_DISAGREEMENT") & (pl.col("model") == "EXPECTED_MARGIN") & pl.col("bucket").is_in(["0-1", "1-2", "2-3", "3-4"])),
    }
    out: dict[str, set[tuple[Any, ...]]] = {}
    for name, expr in specs.items():
        rows = ledger.filter(expr).to_dicts()
        if name.startswith("SPREAD"):
            out[name] = {
                (str(r["game_id"]), str(r["selected_side"]), round(float(r["reconstructed_line"]), 6), int(r["price_american"]))
                for r in rows if r.get("reconstructed_line") is not None
            }
        else:
            out[name] = {(str(r["game_id"]), str(r["selected_side"]), int(r["price_american"])) for r in rows}
    return out


def _membership(rows: list[dict[str, Any]], frozen: dict[str, set[tuple[Any, ...]]], market: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    names = [k for k in frozen if (market == "moneyline" and k.startswith("ML_")) or (market == "spread" and k.startswith("SPREAD"))]
    for name in names:
        if market == "moneyline":
            matched = [r for r in rows if (str(r["game_id"]), str(r["selected_side"]), int(r["american_odds"])) in frozen[name]]
        else:
            matched = [
                r for r in rows
                if r.get("line") is not None
                and (str(r["game_id"]), str(r["selected_side"]), round(float(r["line"]), 6), int(r["american_odds"])) in frozen[name]
            ]
        result[name] = _basic(matched)
    return result


def _state_trace(path: Path) -> dict[str, Any]:
    states = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    def season_of(block: str) -> int:
        return int(str(block).split("-")[0])

    output: dict[str, Any] = {}
    for market, field in (("moneyline", "ml_model_weight"), ("spread", "spread_beta"), ("total", "total_beta")):
        supported = [r for r in states if r.get(field) is not None]
        per_season = {}
        for season in sorted(DEV):
            rr = [r for r in supported if season_of(r["block"]) == season]
            vals = [float(r[field]) for r in rr]
            per_season[str(season)] = {
                "supported_blocks": len(vals),
                "zero_influence_blocks": sum(abs(v) <= 1e-12 for v in vals),
                "positive_influence_blocks": sum(v > 1e-12 for v in vals),
                "mean_influence": None if not vals else float(mean(vals)),
                "max_influence": None if not vals else max(vals),
            }
        vals = [float(r[field]) for r in supported]
        output[market] = {
            "field": field,
            "supported_blocks": len(vals),
            "zero_influence_blocks": sum(abs(v) <= 1e-12 for v in vals),
            "positive_influence_blocks": sum(v > 1e-12 for v in vals),
            "mean_influence": None if not vals else float(mean(vals)),
            "max_influence": None if not vals else max(vals),
            "per_season": per_season,
        }
    return output


def run(root: Path, board_path: Path, selector_path: Path, state_path: Path, out: Path) -> None:
    board_df = pl.read_parquet(board_path)
    seasons = {int(x) for x in board_df["season"].unique().to_list()}
    if seasons != DEV:
        raise RuntimeError(f"unexpected seasons {sorted(seasons)}")
    board = board_df.to_dicts()
    selected = [r for r in pl.read_csv(selector_path, infer_schema_length=10000).to_dicts() if not bool(r.get("no_play"))]
    frozen = _exact_frozen_sets(root)

    # ML generic Value opportunity side skew before cross-market ranking.
    ml_value_eligible: list[dict[str, Any]] = []
    for block in sorted({str(r["block"]) for r in board}):
        rows = [r for r in board if str(r["block"]) == block]
        ml_value_eligible.extend(
            dict(r) for r in shop_exact_offers(rows)
            if str(r.get("market_type")) == "moneyline" and _value_eligible(r)
        )

    roles: dict[str, Any] = {}
    for role in ("hit_rate", "balanced", "value"):
        role_rows = [r for r in selected if str(r["role"]) == role]
        roles[role] = {}
        for market in ("moneyline", "spread", "total"):
            rr = [r for r in role_rows if str(r["market_type"]) == market]
            entry = {
                "overall": _basic(rr),
                "side_counts": {str(side): sum(str(r.get("selected_side")) == str(side) for r in rr) for side in sorted({str(r.get("selected_side")) for r in rr})},
            }
            if market == "moneyline":
                positive_gap = [r for r in rr if r.get("model_market_disagreement") is not None and float(r["model_market_disagreement"]) > 0]
                zero_or_negative_gap = [r for r in rr if r.get("model_market_disagreement") is not None and float(r["model_market_disagreement"]) <= 0]
                entry["model_more_bullish_than_market"] = _basic(positive_gap)
                entry["model_not_more_bullish_than_market"] = _basic(zero_or_negative_gap)
                entry["raw_model_selected_side_above_50pct"] = sum(r.get("raw_model_output") is not None and float(r["raw_model_output"]) > .5 for r in rr)
                entry["raw_model_selected_side_below_50pct"] = sum(r.get("raw_model_output") is not None and float(r["raw_model_output"]) < .5 for r in rr)
                entry["frozen_region_exact_membership"] = _membership(rr, frozen, "moneyline")
            elif market == "spread":
                entry["frozen_region_exact_membership"] = _membership(rr, frozen, "spread")
            roles[role][market] = entry

    result = {
        "development_seasons": sorted(DEV),
        "purpose": "read-only model-to-evaluator-to-selector trace; no retuning or family selection",
        "evaluator_model_influence_by_block": _state_trace(state_path),
        "generic_moneyline_value_eligibility": {
            "overall": _basic(ml_value_eligible),
            "side_counts": {
                "home": sum(str(r.get("selected_side")) == "home" for r in ml_value_eligible),
                "away": sum(str(r.get("selected_side")) == "away" for r in ml_value_eligible),
            },
            "model_more_bullish_than_market": _basic([r for r in ml_value_eligible if r.get("model_market_disagreement") is not None and float(r["model_market_disagreement"]) > 0]),
            "model_not_more_bullish_than_market": _basic([r for r in ml_value_eligible if r.get("model_market_disagreement") is not None and float(r["model_market_disagreement"]) <= 0]),
            "frozen_region_exact_membership": _membership(ml_value_eligible, frozen, "moneyline"),
        },
        "selected_roles": roles,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--board", required=True)
    p.add_argument("--selector-results", required=True)
    p.add_argument("--state-by-block", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    run(Path(a.root), Path(a.board), Path(a.selector_results), Path(a.state_by_block), Path(a.out))
