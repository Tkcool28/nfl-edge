#!/usr/bin/env python3
"""Preregistered Task05G ML Value Frontier State V1 replay."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

import polars as pl

PREREG_COMMIT = "73de12dd34ef97fe445cb29300c2b85a5e48c37e"
PREREG_BLOB = "5844dc8d62c0e9504bf3ee2719862cdd97a3f383"
DEV = {2020, 2021, 2022}
STRESS = {2023, 2024}
ALLOWED = DEV | STRESS
SEALED = 2025
AMBER_MIN_N = 3
AMBER_TRUST = 0.50
RED_MIN_N = 8
RED_TRUST = 0.25


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _state_name(state: dict[str, Any]) -> str:
    n = int(state["n"])
    trust = float(state["trust"])
    if n >= RED_MIN_N and trust < RED_TRUST:
        return "RED"
    if n >= AMBER_MIN_N and trust < AMBER_TRUST:
        return "AMBER"
    return "GREEN"


def _select_state(core, frontier, block_rows: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any] | None:
    shopped = [dict(r) for r in core.shop_exact_offers(block_rows)]
    candidates = [r for r in shopped if core._value_eligible(r)]
    if not candidates:
        return None
    status = _state_name(state)
    if status == "RED":
        candidates = [r for r in candidates if str(r.get("market_type")) != "moneyline"]
        if not candidates:
            return None
    elif status == "AMBER":
        spreads = [r for r in candidates if str(r.get("market_type")) == "spread"]
        if spreads:
            candidates = spreads
    return dict(sorted(candidates, key=lambda r: frontier._dynamic_key(core, r, float(state["trust"])))[0])


def _period(core, frontier, rows: list[dict[str, Any]], seasons: set[int]) -> dict[str, Any]:
    phase = [dict(r) for r in rows if int(r["season"]) in seasons]
    blocks: dict[str, list[dict[str, Any]]] = {}
    for r in phase:
        blocks.setdefault(str(r["block"]), []).append(r)
    ordered = sorted(blocks, key=frontier._block_key)

    selected = {"S0": [], "S1": [], "S2": []}
    prior_obs: dict[int, list[dict[str, Any]]] = {}
    trajectory: list[dict[str, Any]] = []
    state_counts: dict[int, dict[str, int]] = {s: {"GREEN": 0, "AMBER": 0, "RED": 0} for s in seasons}
    amber_displacements: dict[int, int] = {s: 0 for s in seasons}
    red_no_plays: dict[int, int] = {s: 0 for s in seasons}

    for block in ordered:
        season, week = frontier._block_key(block)
        obs = prior_obs.setdefault(season, [])
        trust = frontier._trust(obs)
        status = _state_name(trust)
        state_counts[season][status] += 1
        trajectory.append({"block": block, "season": season, "week": week, "state": status, **trust})

        s0_raw = core._select_value(blocks[block])
        s0 = None if s0_raw is None else dict(s0_raw)
        s1 = frontier._select_dynamic(core, blocks[block], trust, False)
        s2 = _select_state(core, frontier, blocks[block], trust)
        if s0 is not None:
            selected["S0"].append(s0)
        if s1 is not None:
            selected["S1"].append(dict(s1))
        if s2 is not None:
            selected["S2"].append(dict(s2))

        if status == "AMBER" and s0 is not None and str(s0.get("market_type")) == "moneyline" and s2 is not None and str(s2.get("market_type")) == "spread":
            amber_displacements[season] += 1
        if status == "RED" and s2 is None:
            red_no_plays[season] += 1

        new_obs = frontier._frontier_observation_for_block(core, blocks[block])
        if new_obs is not None:
            obs.append(new_obs)

    by_season: dict[str, Any] = {}
    crossings: dict[str, Any] = {}
    for season in sorted(seasons):
        nblocks = sum(frontier._block_key(b)[0] == season for b in ordered)
        by_season[str(season)] = {
            v: frontier._summary([r for r in selected[v] if int(r["season"]) == season], nblocks)
            for v in ("S0", "S1", "S2")
        }
        tr = [r for r in trajectory if int(r["season"]) == season]
        first_amber = next((r for r in tr if r["state"] == "AMBER"), None)
        first_red = next((r for r in tr if r["state"] == "RED"), None)
        crossings[str(season)] = {
            "first_amber": None if first_amber is None else {"block": first_amber["block"], "n": first_amber["n"], "trust": first_amber["trust"]},
            "first_red": None if first_red is None else {"block": first_red["block"], "n": first_red["n"], "trust": first_red["trust"]},
        }

    summaries = {v: frontier._summary(selected[v], len(ordered)) for v in ("S0", "S1", "S2")}
    ratio = None if summaries["S0"]["plays"] == 0 else summaries["S2"]["plays"] / summaries["S0"]["plays"]
    return {
        "blocks": len(ordered),
        "variants": summaries,
        "by_season": by_season,
        "state_counts_by_season": {str(k): v for k, v in sorted(state_counts.items())},
        "amber_ml_to_spread_displacements_by_season": {str(k): v for k, v in sorted(amber_displacements.items())},
        "red_no_plays_by_season": {str(k): v for k, v in sorted(red_no_plays.items())},
        "crossings": crossings,
        "s2_coverage_ratio_vs_s0": ratio,
        "s2_coverage_collapse": bool(ratio is not None and ratio < 0.75),
        "trust_trajectory": trajectory,
    }


def run(root: Path, board_path: Path, out: Path) -> None:
    board = pl.read_parquet(board_path)
    seasons = {int(x) for x in board["season"].unique().to_list()}
    if SEALED in seasons or seasons != ALLOWED:
        raise RuntimeError(f"unexpected/sealed board seasons: {sorted(seasons)}")

    core = _load(root / "scripts/task05g_model_confidence_v2_runner.py", "task05g_v2_core_state")
    entry = _load(root / "scripts/task05g_model_confidence_v2_entrypoint.py", "task05g_v2_entry_state")
    frontier = _load(root / "scripts/task05g_ml_value_frontier_trust_v1.py", "task05g_frontier_state_base")
    entry._fail_closed_on_nonfinite_history(core)
    enriched, _, _ = core._build_model_confidence(root, board.to_dicts())
    if any(int(r["season"]) == SEALED for r in enriched):
        raise RuntimeError("sealed 2025 entered enriched board")

    result = {
        "verdict_scope": "retrospective ML Value frontier state-machine experiment; not production promotion",
        "preregistration": {"commit": PREREG_COMMIT, "blob": PREREG_BLOB},
        "states": {"amber_min_n": AMBER_MIN_N, "amber_trust": AMBER_TRUST, "red_min_n": RED_MIN_N, "red_trust": RED_TRUST},
        "periods": {"development": sorted(DEV), "stress_replay_exposed": sorted(STRESS), "sealed": [SEALED]},
        "development": _period(core, frontier, enriched, DEV),
        "stress_replay": _period(core, frontier, enriched, STRESS),
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
