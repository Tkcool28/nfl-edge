#!/usr/bin/env python3
"""Integrated 2020-24 replay for canonical Task05G final selectors V1."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any, Mapping

import polars as pl

from nfl_edge.recommendation.final_selectors_v1 import (
    ValueSelectorState,
    advance_value_state,
    family_trust,
    select_balanced,
    select_hit_rate,
    select_value,
)
from nfl_edge.recommendation.policy import NO_BALANCED_PLAY, NO_HIT_RATE_PLAY, NO_VALUE_PLAY
from nfl_edge.recommendation.remediation_provenance_v1 import build_candidate_registry, enrich_board_rows

DEV = {2020, 2021, 2022}
DIAG = {2023, 2024}
ALL = DEV | DIAG
SEALED = 2025


def _block_key(block: str) -> tuple[int, int]:
    season, week = str(block).split("-", 1)
    return int(season), int(week)


def _group(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(str(row["block"]), []).append(dict(row))
    return out


def _cid(row: Mapping[str, Any]) -> str:
    return str(row.get("candidate_id") or "|".join([str(row.get("game_id", "")), str(row.get("market_type", "")), str(row.get("selected_side", ""))]))


def _settlement(row: Mapping[str, Any]) -> str:
    return str(row.get("settlement") or "").upper()


def _summary(selected: Mapping[str, Mapping[str, Any]], total_blocks: int) -> dict[str, Any]:
    rows = list(selected.values())
    wins = sum(_settlement(row) == "WIN" for row in rows)
    losses = sum(_settlement(row) == "LOSS" for row in rows)
    pushes = sum(_settlement(row) == "PUSH" for row in rows)
    denom = wins + losses
    profits = [float(row["realized_profit"]) for row in rows if row.get("realized_profit") is not None]
    return {
        "plays": len(rows),
        "total_blocks": total_blocks,
        "coverage": 0.0 if total_blocks == 0 else len(rows) / total_blocks,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if denom == 0 else wins / denom,
        "roi": None if not profits else float(mean(profits)),
        "cumulative_flat_units": float(sum(profits)),
        "avg_odds": None if not rows else float(mean(int(row["american_odds"]) for row in rows)),
        "market_mix": {market: sum(str(row.get("market_type")) == market for row in rows) for market in ("moneyline", "spread", "total")},
    }


def _subset(selected: Mapping[str, Mapping[str, Any]], seasons: set[int]) -> dict[str, dict[str, Any]]:
    return {block: dict(row) for block, row in selected.items() if _block_key(block)[0] in seasons}


def _block_count(blocks: Mapping[str, Any], seasons: set[int]) -> int:
    return sum(_block_key(block)[0] in seasons for block in blocks)


def _row_out(lane: str, block: str, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lane": lane,
        "block": block,
        "candidate_id": _cid(row),
        "game_id": row.get("game_id"),
        "market_type": row.get("market_type"),
        "selected_side": row.get("selected_side"),
        "sportsbook": row.get("sportsbook"),
        "line": row.get("line"),
        "american_odds": row.get("american_odds"),
        "model_confidence_probability": row.get("model_confidence_probability"),
        "selector_trust": row.get("selector_trust"),
        "expected_value": row.get("expected_value"),
        "price_status": row.get("price_status"),
        "model_candidate_regions": row.get("model_candidate_regions"),
        "settlement": row.get("settlement"),
        "realized_profit": row.get("realized_profit"),
    }


def run(root: Path, v3_path: Path, discovery: Path, confirmation: Path, out: Path) -> None:
    rows = pl.read_parquet(v3_path).to_dicts()
    seasons = {int(row["season"]) for row in rows}
    if seasons != ALL or SEALED in seasons:
        raise RuntimeError(f"unexpected/sealed V3 seasons: {sorted(seasons)}")

    ledger = pl.concat(
        [
            pl.read_csv(discovery, infer_schema_length=10000),
            pl.read_csv(confirmation, infer_schema_length=10000),
        ],
        how="vertical_relaxed",
    ).to_dicts()
    ledger_seasons = {int(row["season"]) for row in ledger}
    if ledger_seasons != ALL or SEALED in ledger_seasons:
        raise RuntimeError(f"unexpected/sealed provenance seasons: {sorted(ledger_seasons)}")

    enriched = enrich_board_rows(rows, build_candidate_registry(ledger))
    blocks = _group(enriched)

    hhr: dict[str, dict[str, Any]] = {}
    balanced: dict[str, dict[str, Any]] = {}
    value: dict[str, dict[str, Any]] = {}
    value_no_play: dict[str, int] = {"NO_VALUE_PLAY": 0}
    trust_trajectory: list[dict[str, Any]] = []
    state = ValueSelectorState()
    current_season: int | None = None

    for block in sorted(blocks, key=_block_key):
        season, week = _block_key(block)
        if current_season != season:
            state = ValueSelectorState()
            current_season = season

        block_rows = blocks[block]
        h = select_hit_rate(block_rows)
        b = select_balanced(block_rows)
        v = select_value(block_rows, state)

        if h != NO_HIT_RATE_PLAY:
            hhr[block] = dict(h)
        if b != NO_BALANCED_PLAY:
            balanced[block] = dict(b)
        if v != NO_VALUE_PLAY:
            value[block] = dict(v)
        else:
            value_no_play["NO_VALUE_PLAY"] += 1

        ml_trust = family_trust(state.ml_observations)
        spread_trust = family_trust(state.spread_observations)
        trust_trajectory.append(
            {
                "block": block,
                "season": season,
                "week": week,
                "ml_n": ml_trust.n,
                "ml_trust": ml_trust.trust,
                "ml_state": ml_trust.state,
                "ml_evidence": ml_trust.evidence_status,
                "spread_n": spread_trust.n,
                "spread_trust": spread_trust.trust,
                "spread_state": spread_trust.state,
                "value_candidate_id": None if v == NO_VALUE_PLAY else _cid(v),
                "value_market": None if v == NO_VALUE_PLAY else v.get("market_type"),
            }
        )
        state = advance_value_state(state, block_rows)

    scorecard: dict[str, Any] = {
        "version": "task05g_final_selectors_v1",
        "periods": {},
        "by_season": {},
        "sealed": [SEALED],
        "invariants": {
            "no_2025": True,
            "totals_excluded": all(row.get("market_type") != "total" for selected in (hhr, balanced, value) for row in selected.values()),
            "hhr_balanced_do_not_require_value_status": True,
            "value_strict_protocol": True,
            "deterministic_season_reset": True,
        },
        "value_no_play_counts": value_no_play,
    }

    for label, season_set in (("development", DEV), ("locked_diagnostic", DIAG), ("overall", ALL)):
        total = _block_count(blocks, season_set)
        scorecard["periods"][label] = {
            "hit_rate": _summary(_subset(hhr, season_set), total),
            "balanced": _summary(_subset(balanced, season_set), total),
            "value": _summary(_subset(value, season_set), total),
        }

    for season in sorted(ALL):
        total = _block_count(blocks, {season})
        scorecard["by_season"][str(season)] = {
            "hit_rate": _summary(_subset(hhr, {season}), total),
            "balanced": _summary(_subset(balanced, {season}), total),
            "value": _summary(_subset(value, {season}), total),
        }

    if not scorecard["invariants"]["totals_excluded"]:
        raise RuntimeError("total entered final selector output")

    out.mkdir(parents=True, exist_ok=True)
    (out / "task05g_final_selectors_v1_scorecard.json").write_text(json.dumps(scorecard, indent=2, sort_keys=True, allow_nan=False) + "\n")
    selected_rows = []
    for lane, selected in (("hit_rate", hhr), ("balanced", balanced), ("value", value)):
        for block, row in selected.items():
            selected_rows.append(_row_out(lane, block, row))
    pl.DataFrame(selected_rows).sort(["block", "lane", "candidate_id"]).write_csv(out / "task05g_final_selectors_v1_rows.csv")
    pl.DataFrame(trust_trajectory).sort(["season", "week"]).write_csv(out / "task05g_final_selectors_v1_trust.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--v3-candidates", type=Path, required=True)
    parser.add_argument("--discovery", type=Path, default=Path("reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv"))
    parser.add_argument("--confirmation", type=Path, default=Path("reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.root, args.v3_candidates, args.discovery, args.confirmation, args.out)
