#!/usr/bin/env python3
"""Preregistered Task05G ML nonmature singleton Value fail-safe V1 replay."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any, Mapping

import polars as pl

from nfl_edge.recommendation.remediation_provenance_v1 import build_candidate_registry, enrich_board_rows

DEV = {2020, 2021, 2022}
DIAG = {2023, 2024}
ALL = DEV | DIAG
SEALED = 2025
PREREG_COMMIT = "b3fd4521c16cfb42e2067c13baf370995154a926"


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


def _candidate_id(core, row: Mapping[str, Any]) -> str:
    return str(core._candidate_id(row))


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
        "max_losing_streak": _max_losing_streak(rows),
        "avg_odds": None if not rows else float(mean(int(r["american_odds"]) for r in rows)),
        "market_mix": {m: sum(str(r.get("market_type")) == m for r in rows) for m in ("moneyline", "spread", "total")},
    }


def _subset(mapping: Mapping[str, Mapping[str, Any]], seasons: set[int]) -> dict[str, dict[str, Any]]:
    return {b: dict(r) for b, r in mapping.items() if _block_key(b)[0] in seasons}


def _block_count(blocks: Mapping[str, Any], seasons: set[int]) -> int:
    return sum(_block_key(b)[0] in seasons for b in blocks)


def run(root: Path, v3_path: Path, discovery: Path, confirmation: Path, out: Path) -> None:
    core = _load(root / "scripts/task05g_model_confidence_v2_runner.py", "task05g_ml_safe_core")
    final = _load(root / "scripts/task05g_final_selector_candidate_v1.py", "task05g_ml_safe_final")
    pareto = _load(root / "scripts/task05g_value_spread_pareto_frontier_v1.py", "task05g_ml_safe_pareto")
    spreadsafe = _load(root / "scripts/task05g_value_nongreen_singleton_failsafe_v1.py", "task05g_ml_safe_spreadsafe")
    mlaudit = _load(root / "scripts/task05g_value_ml_2023_state_depth_audit_v1.py", "task05g_ml_safe_audit")

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
    enriched = enrich_board_rows(v3, build_candidate_registry(led_rows))
    blocks = pareto._group(enriched)

    # Step 1: PR #45 user-facing Value baseline with Pareto spread frontier.
    original_spread_fn = final._spread_frontier
    try:
        final._spread_frontier = lambda c, rows: pareto._pareto_frontier(c, final, rows)
        value_run = final._value_run(core, enriched)
    finally:
        final._spread_frontier = original_spread_fn
    pareto_value = {b: dict(r) for b, r in value_run["selected"]["FRONTIER_STATE_V3"].items()}

    # Step 2: reproduce PR #47 non-GREEN singleton spread fail-safe exactly.
    spread_prior = {s: [] for s in ALL}
    baseline: dict[str, dict[str, Any]] = {}
    spread_removed: list[str] = []
    for block in sorted(blocks, key=_block_key):
        season, _ = _block_key(block)
        trust = spreadsafe._trust(spread_prior[season])
        status = spreadsafe._state(trust)
        spread_candidates = pareto._spread_candidates(core, final, blocks[block])
        spread = pareto._pareto_frontier(core, final, blocks[block])
        base = pareto_value.get(block)

        if base is not None:
            if str(base.get("market_type")) != "spread":
                baseline[block] = dict(base)
            else:
                if spread is None or _candidate_id(core, base) != _candidate_id(core, spread):
                    raise RuntimeError(f"spread baseline mismatch in {block}")
                suppress = status in {"AMBER", "RED"} and len(spread_candidates) == 1
                if suppress:
                    spread_removed.append(block)
                else:
                    baseline[block] = dict(base)

        obs = spreadsafe._spread_observation(spread)
        if obs is not None:
            spread_prior[season].append(obs)

    # Step 3: apply only the preregistered ML fail-safe to the PR #47 baseline.
    ml_prior = {s: [] for s in ALL}
    failsafe: dict[str, dict[str, Any]] = {}
    removed: list[dict[str, Any]] = []
    trajectory: list[dict[str, Any]] = []

    for block in sorted(blocks, key=_block_key):
        season, week = _block_key(block)
        trust = mlaudit._trust(ml_prior[season])
        evidence = mlaudit._evidence_status(trust)
        ml_candidates = mlaudit._ml_candidates(core, final, blocks[block])
        ml = final._ml_frontier(core, blocks[block])
        spread_candidates = pareto._spread_candidates(core, final, blocks[block])
        spread = pareto._pareto_frontier(core, final, blocks[block])
        base = baseline.get(block)

        if (ml is None) != (len(ml_candidates) == 0):
            raise RuntimeError(f"ML frontier/depth mismatch in {block}")
        if (spread is None) != (len(spread_candidates) == 0):
            raise RuntimeError(f"spread frontier/depth mismatch in {block}")

        action = "BASE_PASS"
        if base is not None:
            if str(base.get("market_type")) != "moneyline":
                failsafe[block] = dict(base)
                action = "KEEP_SPREAD"
            else:
                if ml is None or _candidate_id(core, base) != _candidate_id(core, ml):
                    raise RuntimeError(f"ML baseline mismatch in {block}")
                suppress = evidence in {"COLD", "AMBER"} and len(ml_candidates) == 1 and spread is None
                if suppress:
                    action = "PASS_NONMATURE_SINGLETON_ML_NO_SPREAD"
                    removed.append({
                        "block": block,
                        "season": season,
                        "week": week,
                        "evidence_status": evidence,
                        "existing_ml_state": mlaudit._state(trust),
                        "ml_n": int(trust["n"]),
                        "ml_trust": float(trust["trust"]),
                        "ml_candidate_depth": len(ml_candidates),
                        "spread_frontier_present": False,
                        "spread_candidate_depth": len(spread_candidates),
                        "candidate_id": _candidate_id(core, ml),
                        "game_id": ml.get("game_id"),
                        "selected_side": ml.get("selected_side"),
                        "american_odds": ml.get("american_odds"),
                        "model_confidence_probability": ml.get("model_confidence_probability"),
                        "break_even_probability": ml.get("break_even_probability"),
                        "model_price_gap": ml.get("model_price_gap"),
                        "evaluated_edge_probability": ml.get("evaluated_edge_probability"),
                        "expected_value": ml.get("expected_value"),
                        "settlement": ml.get("settlement"),
                        "realized_profit": ml.get("realized_profit"),
                    })
                else:
                    failsafe[block] = dict(base)
                    action = "KEEP_ML"

        trajectory.append({
            "block": block,
            "season": season,
            "week": week,
            "evidence_status": evidence,
            "existing_ml_state": mlaudit._state(trust),
            "ml_n": int(trust["n"]),
            "ml_trust": float(trust["trust"]),
            "ml_candidate_depth": len(ml_candidates),
            "spread_frontier_present": spread is not None,
            "spread_candidate_depth": len(spread_candidates),
            "baseline_candidate_id": None if base is None else _candidate_id(core, base),
            "baseline_market": None if base is None else base.get("market_type"),
            "failsafe_action": action,
        })

        obs = mlaudit._ml_observation(ml)
        if obs is not None:
            ml_prior[season].append(obs)

    # Isolation invariants.
    removed_blocks = {str(r["block"]) for r in removed}
    changed_blocks = set(baseline) - set(failsafe)
    if changed_blocks != removed_blocks:
        raise RuntimeError("changed blocks do not exactly match preregistered removals")
    if set(failsafe) - set(baseline):
        raise RuntimeError("fail-safe created new play")
    for block, row in failsafe.items():
        base = baseline[block]
        if _candidate_id(core, row) != _candidate_id(core, base):
            raise RuntimeError(f"fail-safe changed unaffected play identity in {block}")
    for row in removed:
        if not (
            row["evidence_status"] in {"COLD", "AMBER"}
            and int(row["ml_candidate_depth"]) == 1
            and row["spread_frontier_present"] is False
        ):
            raise RuntimeError("non-preregistered ML removal detected")
    if any(int(r["season"]) == SEALED for r in removed):
        raise RuntimeError("2025 entered fail-safe output")

    scorecard: dict[str, Any] = {
        "preregistration_commit": PREREG_COMMIT,
        "sealed": [SEALED],
        "production_promotion_allowed": False,
        "invariants": {
            "only_cold_or_amber_singleton_ml_without_spread_to_pass": True,
            "no_backfill": True,
            "no_new_plays": True,
            "unchanged_play_identity": True,
            "spread_failsafe_baseline_removed_blocks": sorted(spread_removed, key=_block_key),
            "ml_removed_blocks": sorted(removed_blocks, key=_block_key),
        },
        "by_season": {},
        "periods": {},
        "removed_ml": removed,
    }

    for season in sorted(ALL):
        total = _block_count(blocks, {season})
        b = _subset(baseline, {season})
        f = _subset(failsafe, {season})
        scorecard["by_season"][str(season)] = {
            "baseline": _summary(b, total),
            "failsafe": _summary(f, total),
            "ml_to_pass_changes": sum(int(r["season"]) == season for r in removed),
        }

    for label, seasons_set in (("development", DEV), ("locked_diagnostic", DIAG), ("overall", ALL)):
        total = _block_count(blocks, seasons_set)
        b = _subset(baseline, seasons_set)
        f = _subset(failsafe, seasons_set)
        scorecard["periods"][label] = {
            "baseline": _summary(b, total),
            "failsafe": _summary(f, total),
            "ml_to_pass_changes": sum(int(r["season"]) in seasons_set for r in removed),
        }

    out.mkdir(parents=True, exist_ok=True)
    (out / "task05g_value_ml_nonmature_singleton_failsafe_v1_scorecard.json").write_text(
        json.dumps(scorecard, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    pl.DataFrame(trajectory).sort(["season", "week"]).write_csv(
        out / "task05g_value_ml_nonmature_singleton_failsafe_v1_trajectory.csv"
    )
    if removed:
        pl.DataFrame(removed).sort(["season", "week"]).write_csv(
            out / "task05g_value_ml_nonmature_singleton_failsafe_v1_removed.csv"
        )
    else:
        pl.DataFrame({"block": []}, schema={"block": pl.String}).write_csv(
            out / "task05g_value_ml_nonmature_singleton_failsafe_v1_removed.csv"
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--v3-candidates", type=Path, required=True)
    p.add_argument("--discovery", type=Path, default=Path("reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv"))
    p.add_argument("--confirmation", type=Path, default=Path("reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv"))
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    run(a.root, a.v3_candidates, a.discovery, a.confirmation, a.out)
