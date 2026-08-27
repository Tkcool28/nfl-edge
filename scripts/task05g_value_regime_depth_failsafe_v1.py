#!/usr/bin/env python3
"""Preregistered Task05G Value regime-depth fail-safe V1 replay."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping

import polars as pl

from nfl_edge.recommendation.remediation_provenance_v1 import build_candidate_registry, enrich_board_rows

DEV = {2020, 2021, 2022}
DIAG = {2023, 2024}
ALL = DEV | DIAG
SEALED = 2025
PREREG_COMMIT = "d544cbfdd63a6f6858ed568ff5ed0fe9e1dd5ed8"
RESET_TRUST = 0.50
PSEUDO_N = 8
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


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _block_key(block: str) -> tuple[int, int]:
    a, b = str(block).split("-", 1)
    return int(a), int(b)


def _settlement(row: Mapping[str, Any] | None) -> str:
    return "" if row is None else str(row.get("settlement") or "")


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
    predicted = sum(float(o["predicted_edge"]) for o in observations)
    realized = sum(float(o["realized_edge"]) for o in observations)
    data_trust = 0.0 if predicted <= 0.0 else min(1.0, max(0.0, realized / predicted))
    trust = (PSEUDO_N * RESET_TRUST + n * data_trust) / (PSEUDO_N + n)
    return {
        "n": n,
        "predicted_edge_sum": float(predicted),
        "realized_edge_sum": float(realized),
        "data_trust": float(data_trust),
        "trust": float(trust),
    }


def _state(t: Mapping[str, Any]) -> str:
    n = int(t["n"])
    trust = float(t["trust"])
    if n >= RED_MIN_N and trust < RED_TRUST:
        return "RED"
    if n >= AMBER_MIN_N and trust < AMBER_TRUST:
        return "AMBER"
    return "GREEN"


def _spread_observation(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if row is None or _settlement(row) not in {"WIN", "LOSS"}:
        return None
    predicted = _finite(row.get("evaluated_edge_probability"))
    be = _finite(row.get("break_even_probability"))
    if predicted is None or predicted <= 0.0 or be is None:
        return None
    y = 1.0 if _settlement(row) == "WIN" else 0.0
    return {
        "block": str(row["block"]),
        "game_id": str(row["game_id"]),
        "predicted_edge": float(predicted),
        "realized_edge": float(y - be),
    }


def _max_losing_streak(rows: list[Mapping[str, Any]]) -> int:
    cur = longest = 0
    for row in sorted(rows, key=lambda r: (_block_key(str(r["block"])), str(r.get("game_id")))):
        if _settlement(row) == "LOSS":
            cur += 1
            longest = max(longest, cur)
        elif _settlement(row) == "WIN":
            cur = 0
    return longest


def _summary(selected: Mapping[str, Mapping[str, Any]], total_blocks: int) -> dict[str, Any]:
    rows = list(selected.values())
    wins = sum(_settlement(r) == "WIN" for r in rows)
    losses = sum(_settlement(r) == "LOSS" for r in rows)
    pushes = sum(_settlement(r) == "PUSH" for r in rows)
    denom = wins + losses
    profits = [_finite(r.get("realized_profit")) for r in rows]
    profits = [x for x in profits if x is not None]
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
        "avg_odds": None if not rows else float(mean(int(r["american_odds"]) for r in rows)),
        "market_mix": {
            m: sum(str(r.get("market_type")) == m for r in rows)
            for m in ("moneyline", "spread", "total")
        },
        "max_losing_streak": _max_losing_streak(rows),
    }


def _frontier_cell_summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    wins = sum(_settlement(r) == "WIN" for r in rows)
    losses = sum(_settlement(r) == "LOSS" for r in rows)
    pushes = sum(_settlement(r) == "PUSH" for r in rows)
    denom = wins + losses
    profits = [_finite(r.get("realized_profit")) for r in rows]
    profits = [x for x in profits if x is not None]
    return {
        "plays": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if denom == 0 else wins / denom,
        "roi": None if not profits else float(mean(profits)),
        "cumulative_flat_units": float(sum(profits)),
        "seasons": sorted({int(r["season"]) for r in rows}),
    }


def _subset(mapping: Mapping[str, Mapping[str, Any]], seasons: set[int]) -> dict[str, dict[str, Any]]:
    return {b: dict(r) for b, r in mapping.items() if _block_key(b)[0] in seasons}


def _period_block_count(blocks: Mapping[str, Any], seasons: set[int]) -> int:
    return sum(_block_key(b)[0] in seasons for b in blocks)


def run(root: Path, v3_path: Path, discovery: Path, confirmation: Path, out: Path) -> None:
    pareto = _load(root / "scripts/task05g_value_spread_pareto_frontier_v1.py", "task05g_regime_depth_pareto")
    core = _load(root / "scripts/task05g_model_confidence_v2_runner.py", "task05g_regime_depth_core")
    final = _load(root / "scripts/task05g_final_selector_candidate_v1.py", "task05g_regime_depth_final")

    v3 = pl.read_parquet(v3_path).to_dicts()
    seasons = {int(r["season"]) for r in v3}
    if seasons != ALL or SEALED in seasons:
        raise RuntimeError(f"unexpected/sealed V3 seasons: {sorted(seasons)}")

    led = pl.concat([
        pl.read_csv(discovery, infer_schema_length=10000),
        pl.read_csv(confirmation, infer_schema_length=10000),
    ], how="vertical_relaxed")
    led_rows = led.to_dicts()
    if {int(r["season"]) for r in led_rows} != ALL:
        raise RuntimeError("unexpected provenance seasons")
    registry = build_candidate_registry(led_rows)
    enriched = enrich_board_rows(v3, registry)
    blocks = pareto._group(enriched)

    # Exact PR45 comparator: existing final Value run with only spread frontier
    # replaced by the frozen Pareto frontier.
    original_spread_fn = final._spread_frontier
    try:
        final._spread_frontier = lambda c, rows: pareto._pareto_frontier(c, final, rows)
        baseline_run = final._value_run(core, enriched)
    finally:
        final._spread_frontier = original_spread_fn
    baseline = {b: dict(r) for b, r in baseline_run["selected"]["FRONTIER_STATE_V3"].items()}

    spread_prior = {season: [] for season in ALL}
    trajectory: list[dict[str, Any]] = []
    frontier_cells: dict[str, list[dict[str, Any]]] = {
        f"{state}_{depth}": []
        for state in ("GREEN", "AMBER", "RED")
        for depth in ("singleton", "competitive")
    }
    failsafe: dict[str, dict[str, Any]] = {}
    removed: list[dict[str, Any]] = []

    for block in sorted(blocks, key=_block_key):
        season, week = _block_key(block)
        trust = _trust(spread_prior[season])
        status = _state(trust)
        candidates = pareto._spread_candidates(core, final, blocks[block])
        depth = len(candidates)
        spread = pareto._pareto_frontier(core, final, blocks[block])
        base = baseline.get(block)

        if spread is not None:
            depth_label = "singleton" if depth == 1 else "competitive"
            cell_row = dict(spread)
            cell_row.update({"season": season, "week": week, "trust_state": status, "candidate_depth": depth})
            frontier_cells[f"{status}_{depth_label}"].append(cell_row)

        action = "BASE_PASS"
        if base is not None:
            if str(base.get("market_type")) != "spread":
                failsafe[block] = dict(base)
                action = "KEEP_ML"
            else:
                if spread is None:
                    raise RuntimeError(f"baseline selected spread but no Pareto spread frontier in {block}")
                base_id = pareto._candidate_id(core, base)
                spread_id = pareto._candidate_id(core, spread)
                if base_id != spread_id:
                    raise RuntimeError(f"baseline spread identity mismatch in {block}: {base_id} != {spread_id}")
                keep = status == "GREEN" or (status == "AMBER" and depth >= 2)
                if keep:
                    failsafe[block] = dict(base)
                    action = "KEEP_SPREAD"
                else:
                    action = "PASS_AMBER_SINGLETON" if status == "AMBER" else "PASS_RED_SPREAD"
                    removed.append({
                        "block": block,
                        "season": season,
                        "week": week,
                        "trust_state": status,
                        "trust_n": int(trust["n"]),
                        "trust": float(trust["trust"]),
                        "candidate_depth": depth,
                        "candidate_id": spread_id,
                        "game_id": spread.get("game_id"),
                        "selected_side": spread.get("selected_side"),
                        "line": spread.get("line"),
                        "american_odds": spread.get("american_odds"),
                        "model_cover_margin_v3": spread.get("model_cover_margin_v3"),
                        "spread_v3_q": spread.get("model_confidence_probability"),
                        "evaluated_edge_probability": spread.get("evaluated_edge_probability"),
                        "expected_value": spread.get("expected_value"),
                        "settlement": spread.get("settlement"),
                        "realized_profit": spread.get("realized_profit"),
                    })

        trajectory.append({
            "block": block,
            "season": season,
            "week": week,
            "spread_state": status,
            "spread_trust_n": int(trust["n"]),
            "spread_trust": float(trust["trust"]),
            "spread_candidate_depth": depth,
            "spread_frontier_candidate_id": None if spread is None else pareto._candidate_id(core, spread),
            "spread_frontier_settlement": None if spread is None else spread.get("settlement"),
            "baseline_value_candidate_id": None if base is None else pareto._candidate_id(core, base),
            "baseline_value_market": None if base is None else base.get("market_type"),
            "failsafe_action": action,
        })

        obs = _spread_observation(spread)
        if obs is not None:
            spread_prior[season].append(obs)

    # Hard no-backfill / isolation invariants.
    for block, row in failsafe.items():
        base = baseline.get(block)
        if base is None:
            raise RuntimeError(f"failsafe created a new play in {block}")
        if pareto._candidate_id(core, row) != pareto._candidate_id(core, base):
            raise RuntimeError(f"failsafe changed candidate identity in {block}")
    for block, base in baseline.items():
        if str(base.get("market_type")) == "moneyline" and block not in failsafe:
            raise RuntimeError(f"failsafe removed ML play in {block}")
    changed_blocks = sorted(set(baseline) - set(failsafe), key=_block_key)
    if set(changed_blocks) != {str(r["block"]) for r in removed}:
        raise RuntimeError("changed blocks do not equal recorded spread->PASS removals")

    scorecard: dict[str, Any] = {
        "preregistration_commit": PREREG_COMMIT,
        "sealed": [SEALED],
        "production_promotion_allowed": False,
        "invariants": {
            "only_spread_to_pass_changes": True,
            "no_ml_backfill": True,
            "no_new_plays": True,
            "changed_blocks": changed_blocks,
        },
        "by_season": {},
        "periods": {},
        "frontier_state_depth_cells": {k: _frontier_cell_summary(v) for k, v in frontier_cells.items()},
        "removed_spreads": removed,
    }

    for season in sorted(ALL):
        seasons_set = {season}
        total = _period_block_count(blocks, seasons_set)
        b = _subset(baseline, seasons_set)
        f = _subset(failsafe, seasons_set)
        scorecard["by_season"][str(season)] = {
            "baseline_pareto_value": _summary(b, total),
            "failsafe": _summary(f, total),
            "spread_to_pass_changes": sum(int(r["season"]) == season for r in removed),
        }

    for label, seasons_set in (("development", DEV), ("locked_diagnostic", DIAG), ("overall", ALL)):
        total = _period_block_count(blocks, seasons_set)
        b = _subset(baseline, seasons_set)
        f = _subset(failsafe, seasons_set)
        scorecard["periods"][label] = {
            "baseline_pareto_value": _summary(b, total),
            "failsafe": _summary(f, total),
            "spread_to_pass_changes": sum(int(r["season"]) in seasons_set for r in removed),
        }

    # Required 2023 causal diagnosis.
    traj23 = [r for r in trajectory if int(r["season"]) == 2023]
    amber = [r for r in traj23 if r["spread_state"] == "AMBER"]
    red = [r for r in traj23 if r["spread_state"] == "RED"]
    first_amber_week = None if not amber else min(int(r["week"]) for r in amber)
    first_red_week = None if not red else min(int(r["week"]) for r in red)
    removed23 = [r for r in removed if int(r["season"]) == 2023]
    removed23_profits = [_finite(r.get("realized_profit")) for r in removed23]
    removed23_profits = [x for x in removed23_profits if x is not None]
    scorecard["diagnosis_2023"] = {
        "first_amber_week": first_amber_week,
        "first_red_week": first_red_week,
        "baseline_spread_plays_before_first_amber": sum(
            _block_key(b)[0] == 2023 and (first_amber_week is None or _block_key(b)[1] < first_amber_week) and str(r.get("market_type")) == "spread"
            for b, r in baseline.items()
        ),
        "baseline_spread_plays_at_or_after_first_amber": sum(
            _block_key(b)[0] == 2023 and first_amber_week is not None and _block_key(b)[1] >= first_amber_week and str(r.get("market_type")) == "spread"
            for b, r in baseline.items()
        ),
        "removed_spreads": len(removed23),
        "removed_wins": sum(str(r.get("settlement")) == "WIN" for r in removed23),
        "removed_losses": sum(str(r.get("settlement")) == "LOSS" for r in removed23),
        "removed_pushes": sum(str(r.get("settlement")) == "PUSH" for r in removed23),
        "counterfactual_units_removed": float(sum(removed23_profits)),
        "loss_units_avoided_if_negative": float(-sum(x for x in removed23_profits if x < 0.0)),
        "win_units_forfeited_if_positive": float(sum(x for x in removed23_profits if x > 0.0)),
        "removed_amber_singletons": sum(r["trust_state"] == "AMBER" and int(r["candidate_depth"]) == 1 for r in removed23),
        "removed_red_spreads": sum(r["trust_state"] == "RED" for r in removed23),
    }

    out.mkdir(parents=True, exist_ok=True)
    (out / "task05g_value_regime_depth_failsafe_v1_scorecard.json").write_text(
        json.dumps(scorecard, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    pl.DataFrame(trajectory).sort(["season", "week"]).write_csv(
        out / "task05g_value_regime_depth_failsafe_v1_trajectory.csv"
    )
    if removed:
        pl.DataFrame(removed).sort(["season", "week"]).write_csv(
            out / "task05g_value_regime_depth_failsafe_v1_removed.csv"
        )
    else:
        pl.DataFrame({"block": []}).write_csv(out / "task05g_value_regime_depth_failsafe_v1_removed.csv")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--v3-candidates", type=Path, required=True)
    p.add_argument("--discovery", type=Path, default=Path("reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv"))
    p.add_argument("--confirmation", type=Path, default=Path("reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv"))
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    run(a.root, a.v3_candidates, a.discovery, a.confirmation, a.out)
