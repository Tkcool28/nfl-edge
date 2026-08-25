#!/usr/bin/env python3
"""Preregistered Task05G ML Value Dynamic Trust V1 replay.

Implements docs/task05g_ml_value_dynamic_trust_v1_preregistration.md.
Diagnostic/retrospective only. No evaluator/model/policy mutation; 2025 sealed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any, Mapping

import polars as pl

PREREG_COMMIT = "151d2799044b94dd1b29f0aac31bb74af81634c8"
PREREG_BLOB = "6b8425daeef87dc8f7d4b9dc995cc2a19263fe1a"
DEV = {2020, 2021, 2022}
STRESS = {2023, 2024}
ALLOWED = DEV | STRESS
SEALED = 2025
RESET_TRUST = 0.50
PSEUDO_N = 8
RED_GATE = 0.25
RED_MIN_N = 8


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _block_key(block: str) -> tuple[int, int]:
    a, b = str(block).split("-", 1)
    return int(a), int(b)


def _summary(rows: list[dict[str, Any]], blocks_total: int) -> dict[str, Any]:
    wins = sum(str(r.get("settlement")) == "WIN" for r in rows)
    losses = sum(str(r.get("settlement")) == "LOSS" for r in rows)
    pushes = sum(str(r.get("settlement")) == "PUSH" for r in rows)
    nonpush = wins + losses
    def market(m: str) -> dict[str, Any]:
        rr = [r for r in rows if str(r.get("market_type")) == m]
        return {
            "plays": len(rr),
            "roi": None if not rr else float(mean(float(r["realized_profit"]) for r in rr)),
            "wins": sum(str(r.get("settlement")) == "WIN" for r in rr),
            "losses": sum(str(r.get("settlement")) == "LOSS" for r in rr),
        }
    longest = cur = 0
    for r in sorted(rows, key=lambda x: (_block_key(str(x["block"])), str(x.get("game_id")))):
        s = str(r.get("settlement"))
        if s == "LOSS":
            cur += 1
            longest = max(longest, cur)
        elif s == "WIN":
            cur = 0
    return {
        "plays": len(rows),
        "coverage": None if blocks_total == 0 else len(rows) / blocks_total,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if nonpush == 0 else wins / nonpush,
        "roi": None if not rows else float(mean(float(r["realized_profit"]) for r in rows)),
        "ml": market("moneyline"),
        "spread": market("spread"),
        "max_losing_streak": longest,
    }


def _trust(observations: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(observations)
    if n == 0:
        return {
            "n": 0,
            "predicted_edge_sum": 0.0,
            "realized_edge_sum": 0.0,
            "data_trust": None,
            "trust": RESET_TRUST,
        }
    pred = sum(float(o["predicted_edge"]) for o in observations)
    realized = sum(float(o["realized_edge"]) for o in observations)
    data = 0.0 if pred <= 0 else min(1.0, max(0.0, realized / pred))
    trust = (PSEUDO_N * RESET_TRUST + n * data) / (PSEUDO_N + n)
    return {
        "n": n,
        "predicted_edge_sum": float(pred),
        "realized_edge_sum": float(realized),
        "data_trust": float(data),
        "trust": float(trust),
    }


def _candidate_key(core, row: Mapping[str, Any], trust: float) -> tuple[Any, ...]:
    if str(row.get("market_type")) == "moneyline":
        gap = float(row["model_price_gap"]) * trust
        dyn = min(gap, float(row["evaluated_edge_probability"]))
    else:
        dyn = float(row.get("consensus_edge") if row.get("consensus_edge") is not None else -99.0)
    return (
        -dyn,
        -float(row["model_confidence_probability"]),
        -core._reliability_rank(row.get("reliability")),
        -int(row.get("american_odds") or -100000),
        core._candidate_id(row),
    )


def _select_dynamic(core, block_rows: list[dict[str, Any]], trust_state: dict[str, Any], red_gate: bool) -> dict[str, Any] | None:
    shopped = [dict(r) for r in core.shop_exact_offers(block_rows)]
    candidates = [r for r in shopped if core._value_eligible(r)]
    if red_gate and int(trust_state["n"]) >= RED_MIN_N and float(trust_state["trust"]) < RED_GATE:
        candidates = [r for r in candidates if str(r.get("market_type")) != "moneyline"]
    if not candidates:
        return None
    return dict(sorted(candidates, key=lambda r: _candidate_key(core, r, float(trust_state["trust"])))[0])


def _ml_observations_for_block(core, block_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    shopped = [dict(r) for r in core.shop_exact_offers(block_rows)]
    eligible = [r for r in shopped if str(r.get("market_type")) == "moneyline" and core._value_eligible(r)]
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for r in eligible:
        key = (str(r["block"]), str(r["game_id"]), str(r["selected_side"]))
        unique[key] = r
    out: list[dict[str, Any]] = []
    for r in unique.values():
        settlement = str(r.get("settlement"))
        if settlement not in {"WIN", "LOSS"}:
            continue
        q = r.get("model_confidence_probability")
        be = r.get("break_even_probability")
        if not _finite(q) or not _finite(be):
            continue
        predicted_edge = float(q) - float(be)
        if not math.isfinite(predicted_edge) or predicted_edge <= 0:
            continue
        y = 1.0 if settlement == "WIN" else 0.0
        out.append({
            "block": str(r["block"]),
            "game_id": str(r["game_id"]),
            "selected_side": str(r["selected_side"]),
            "predicted_edge": float(predicted_edge),
            "realized_edge": float(y - float(be)),
        })
    return out


def _period(core, rows: list[dict[str, Any]], seasons: set[int]) -> dict[str, Any]:
    phase = [dict(r) for r in rows if int(r["season"]) in seasons]
    blocks: dict[str, list[dict[str, Any]]] = {}
    for r in phase:
        blocks.setdefault(str(r["block"]), []).append(r)
    ordered = sorted(blocks, key=_block_key)

    selected: dict[str, list[dict[str, Any]]] = {"D0": [], "D1": [], "D2": []}
    trajectories: list[dict[str, Any]] = []
    prior_obs_by_season: dict[int, list[dict[str, Any]]] = {}
    displaced = {"D1": 0, "D2": 0}
    d2_red_no_play = 0

    for block in ordered:
        season, week = _block_key(block)
        prior_obs = prior_obs_by_season.setdefault(season, [])
        state = _trust(prior_obs)
        trajectories.append({"block": block, "season": season, "week": week, **state})

        d0_raw = core._select_value(blocks[block])
        d0 = None if d0_raw is None else dict(d0_raw)
        d1 = _select_dynamic(core, blocks[block], state, False)
        d2 = _select_dynamic(core, blocks[block], state, True)
        if d0 is not None:
            selected["D0"].append(d0)
        if d1 is not None:
            selected["D1"].append(d1)
        if d2 is not None:
            selected["D2"].append(d2)

        if d0 is not None and str(d0.get("market_type")) == "moneyline":
            if d1 is not None and str(d1.get("market_type")) == "spread":
                displaced["D1"] += 1
            if d2 is not None and str(d2.get("market_type")) == "spread":
                displaced["D2"] += 1
            if d2 is None and int(state["n"]) >= RED_MIN_N and float(state["trust"]) < RED_GATE:
                d2_red_no_play += 1

        # Only after all selections/trust states for this block are fixed do this
        # block's settled opportunities enter future trust state.
        prior_obs.extend(_ml_observations_for_block(core, blocks[block]))

    by_season: dict[str, Any] = {}
    for season in sorted(seasons):
        season_blocks = sum(_block_key(b)[0] == season for b in ordered)
        by_season[str(season)] = {
            v: _summary([r for r in selected[v] if int(r["season"]) == season], season_blocks)
            for v in ("D0", "D1", "D2")
        }

    crossings: dict[str, Any] = {}
    for season in sorted(seasons):
        tr = [r for r in trajectories if int(r["season"]) == season]
        below50 = next((r for r in tr if float(r["trust"]) < 0.50), None)
        below25 = next((r for r in tr if float(r["trust"]) < 0.25), None)
        crossings[str(season)] = {
            "below_0_50": None if below50 is None else {"block": below50["block"], "n": below50["n"], "trust": below50["trust"]},
            "below_0_25": None if below25 is None else {"block": below25["block"], "n": below25["n"], "trust": below25["trust"]},
        }

    summaries = {v: _summary(selected[v], len(ordered)) for v in ("D0", "D1", "D2")}
    d0plays = summaries["D0"]["plays"]
    d2plays = summaries["D2"]["plays"]
    coverage_ratio = None if d0plays == 0 else d2plays / d0plays
    return {
        "blocks": len(ordered),
        "variants": summaries,
        "by_season": by_season,
        "ml_displaced_by_spread": displaced,
        "d2_red_gate_no_plays": d2_red_no_play,
        "d2_coverage_ratio_vs_d0": coverage_ratio,
        "d2_coverage_collapse": bool(coverage_ratio is not None and coverage_ratio < 0.75),
        "trust_crossings": crossings,
        "trust_trajectory": trajectories,
    }


def run(root: Path, board_path: Path, out: Path) -> None:
    board = pl.read_parquet(board_path)
    seasons = {int(x) for x in board["season"].unique().to_list()}
    if SEALED in seasons or seasons != ALLOWED:
        raise RuntimeError(f"unexpected/sealed board seasons: {sorted(seasons)}")

    core = _load(root / "scripts/task05g_model_confidence_v2_runner.py", "task05g_v2_core_dynamic_trust")
    entry = _load(root / "scripts/task05g_model_confidence_v2_entrypoint.py", "task05g_v2_entry_dynamic_trust")
    entry._fail_closed_on_nonfinite_history(core)

    enriched, _, _ = core._build_model_confidence(root, board.to_dicts())
    if any(int(r["season"]) == SEALED for r in enriched):
        raise RuntimeError("sealed 2025 entered enriched board")

    result = {
        "verdict_scope": "retrospective dynamic ML Value trust experiment; not production promotion",
        "preregistration": {"commit": PREREG_COMMIT, "blob": PREREG_BLOB},
        "parameters": {
            "season_reset_trust": RESET_TRUST,
            "pseudo_count": PSEUDO_N,
            "red_gate": RED_GATE,
            "red_min_n": RED_MIN_N,
        },
        "periods": {
            "development": sorted(DEV),
            "stress_replay_exposed": sorted(STRESS),
            "sealed": [SEALED],
        },
        "development": _period(core, enriched, DEV),
        "stress_replay": _period(core, enriched, STRESS),
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
