#!/usr/bin/env python3
"""Retrospective Task05G ML Value state/depth forensic audit V1."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping

import polars as pl

from nfl_edge.recommendation.remediation_provenance_v1 import (
    REGION_SPECS,
    build_candidate_registry,
    enrich_board_rows,
)

DEV = {2020, 2021, 2022}
DIAG = {2023, 2024}
ALL = DEV | DIAG
SEALED = 2025
MIN_N = 256
RESET_TRUST = 0.50
PSEUDO_N = 8
AMBER_MIN_N = 3
AMBER_TRUST = 0.50
RED_MIN_N = 8
RED_TRUST = 0.25
PREREG_COMMIT = "e9257250dc937e360e60d14473b062d65cbff6d5"
ML_REGIONS = frozenset(name for name, family, *_ in REGION_SPECS if family.startswith("ML_"))


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


def _group(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(str(row["block"]), []).append(dict(row))
    return out


def _candidate_id(core, row: Mapping[str, Any]) -> str:
    return str(core._candidate_id(row))


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


def _evidence_status(t: Mapping[str, Any]) -> str:
    n = int(t["n"])
    state = _state(t)
    if n < AMBER_MIN_N:
        return "COLD"
    if state == "GREEN":
        return "MATURE_GREEN"
    return state


def _ml_observation(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if row is None or _settlement(row) not in {"WIN", "LOSS"}:
        return None
    q = _finite(row.get("model_confidence_probability"))
    be = _finite(row.get("break_even_probability"))
    if q is None or be is None:
        return None
    predicted = q - be
    if predicted <= 0.0:
        return None
    y = 1.0 if _settlement(row) == "WIN" else 0.0
    return {
        "block": str(row["block"]),
        "game_id": str(row["game_id"]),
        "predicted_edge": float(predicted),
        "realized_edge": float(y - be),
    }


def _ml_candidates(core, final, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in final._shop(core, rows):
        gap = _finite(r.get("model_price_gap"))
        edge = _finite(r.get("evaluated_edge_probability"))
        if (
            final._strict_value_common(r)
            and str(r.get("market_type")) == "moneyline"
            and bool(final._tags(r).intersection(ML_REGIONS))
            and gap is not None
            and gap > 0.0
            and edge is not None
            and edge > 0.0
        ):
            out.append(dict(r))
    return out


def _summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    wins = sum(_settlement(r) == "WIN" for r in rows)
    losses = sum(_settlement(r) == "LOSS" for r in rows)
    pushes = sum(_settlement(r) == "PUSH" for r in rows)
    denom = wins + losses
    profits = [_finite(r.get("realized_profit")) for r in rows]
    profits = [x for x in profits if x is not None]

    def avg(field: str) -> float | None:
        vals = [_finite(r.get(field)) for r in rows]
        vals = [x for x in vals if x is not None]
        return None if not vals else float(mean(vals))

    odds = [int(r["american_odds"]) for r in rows if r.get("american_odds") is not None]
    return {
        "rows": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if denom == 0 else wins / denom,
        "roi": None if not profits else float(mean(profits)),
        "cumulative_flat_units": float(sum(profits)),
        "seasons": sorted({int(r["season"]) for r in rows}) if rows else [],
        "avg_odds": None if not odds else float(mean(odds)),
        "avg_q": avg("model_confidence_probability"),
        "avg_break_even": avg("break_even_probability"),
        "avg_model_price_gap": avg("model_price_gap"),
        "avg_evaluated_edge": avg("evaluated_edge_probability"),
        "avg_expected_value": avg("expected_value"),
        "avg_ml_trust": avg("ml_trust"),
        "avg_candidate_depth": avg("ml_candidate_depth"),
    }


def _cell_key(row: Mapping[str, Any]) -> str:
    depth = "singleton" if int(row["ml_candidate_depth"]) == 1 else "competitive"
    return f"{row['evidence_status']}_{depth}"


def _selection_reason(
    selected_ml: Mapping[str, Any],
    spread: Mapping[str, Any] | None,
    ml_state: str,
    evidence_status: str,
) -> str:
    if spread is None:
        if ml_state == "AMBER":
            return "AMBER_ONLY_FAMILY"
        if evidence_status == "COLD":
            return "COLD_ONLY_FAMILY"
        return "GREEN_ONLY_FAMILY"
    if ml_state == "AMBER":
        return "UNEXPECTED_AMBER_WITH_SPREAD"
    if ml_state == "RED":
        return "UNEXPECTED_RED_ML_SELECTION"
    return "GREEN_CROSSMARKET_WIN"


def _row_out(
    core,
    row: Mapping[str, Any],
    *,
    block: str,
    season: int,
    week: int,
    trust: Mapping[str, Any],
    ml_depth: int,
    spread_depth: int,
    spread: Mapping[str, Any] | None,
    selected: bool,
    selection_reason: str | None,
) -> dict[str, Any]:
    return {
        "block": block,
        "season": season,
        "week": week,
        "candidate_id": _candidate_id(core, row),
        "game_id": row.get("game_id"),
        "selected_side": row.get("selected_side"),
        "american_odds": row.get("american_odds"),
        "settlement": row.get("settlement"),
        "realized_profit": row.get("realized_profit"),
        "existing_ml_state": _state(trust),
        "evidence_status": _evidence_status(trust),
        "ml_n": int(trust["n"]),
        "ml_trust": float(trust["trust"]),
        "ml_candidate_depth": ml_depth,
        "model_confidence_probability": row.get("model_confidence_probability"),
        "break_even_probability": row.get("break_even_probability"),
        "model_price_gap": row.get("model_price_gap"),
        "evaluated_edge_probability": row.get("evaluated_edge_probability"),
        "expected_value": row.get("expected_value"),
        "reliability": row.get("reliability"),
        "spread_alternative_present": spread is not None,
        "spread_candidate_depth": spread_depth,
        "spread_candidate_id": None if spread is None else _candidate_id(core, spread),
        "spread_settlement": None if spread is None else spread.get("settlement"),
        "ml_only_strict_value_family": spread is None,
        "selected_ml_headline": selected,
        "selection_reason": selection_reason,
    }


def run(root: Path, v3_path: Path, discovery: Path, confirmation: Path, out: Path) -> None:
    core = _load(root / "scripts/task05g_model_confidence_v2_runner.py", "task05g_ml_audit_core")
    final = _load(root / "scripts/task05g_final_selector_candidate_v1.py", "task05g_ml_audit_final")
    pareto = _load(root / "scripts/task05g_value_spread_pareto_frontier_v1.py", "task05g_ml_audit_pareto")

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
    blocks = _group(enriched)

    # User-facing Value baseline for ML identity: PR #45 Pareto spread substitution.
    original_spread_fn = final._spread_frontier
    try:
        final._spread_frontier = lambda c, rows: pareto._pareto_frontier(c, final, rows)
        value_run = final._value_run(core, enriched)
    finally:
        final._spread_frontier = original_spread_fn
    selected_value = {b: dict(r) for b, r in value_run["selected"]["FRONTIER_STATE_V3"].items()}

    ml_prior = {s: [] for s in ALL}
    frontier_rows: list[dict[str, Any]] = []
    selected_ml_rows: list[dict[str, Any]] = []
    early_trajectory: dict[str, list[dict[str, Any]]] = {str(s): [] for s in sorted(ALL)}

    for block in sorted(blocks, key=_block_key):
        season, week = _block_key(block)
        t = _trust(ml_prior[season])
        ml_candidates = _ml_candidates(core, final, blocks[block])
        ml_depth = len(ml_candidates)
        ml = final._ml_frontier(core, blocks[block])
        spread_candidates = pareto._spread_candidates(core, final, blocks[block])
        spread_depth = len(spread_candidates)
        spread = pareto._pareto_frontier(core, final, blocks[block])
        selected = selected_value.get(block)

        if (ml is None) != (ml_depth == 0):
            raise RuntimeError(f"ML frontier/depth mismatch in {block}")
        if (spread is None) != (spread_depth == 0):
            raise RuntimeError(f"spread frontier/depth mismatch in {block}")

        if ml is not None:
            is_selected_ml = selected is not None and str(selected.get("market_type")) == "moneyline"
            if is_selected_ml and _candidate_id(core, selected) != _candidate_id(core, ml):
                raise RuntimeError(f"selected ML is not frontier in {block}")
            reason = None
            if is_selected_ml:
                reason = _selection_reason(ml, spread, _state(t), _evidence_status(t))
            outrow = _row_out(
                core,
                ml,
                block=block,
                season=season,
                week=week,
                trust=t,
                ml_depth=ml_depth,
                spread_depth=spread_depth,
                spread=spread,
                selected=is_selected_ml,
                selection_reason=reason,
            )
            frontier_rows.append(outrow)
            if is_selected_ml:
                selected_ml_rows.append(dict(outrow))

            if int(t["n"]) < AMBER_MIN_N:
                early_trajectory[str(season)].append({
                    "block": block,
                    "week": week,
                    "pre_n": int(t["n"]),
                    "pre_trust": float(t["trust"]),
                    "frontier_candidate_id": _candidate_id(core, ml),
                    "candidate_depth": ml_depth,
                    "settlement": ml.get("settlement"),
                    "selected_ml_headline": is_selected_ml,
                    "spread_alternative_present": spread is not None,
                })

        obs = _ml_observation(ml)
        if obs is not None:
            ml_prior[season].append(obs)

    # The first three settled frontier observations define the frozen cold-start window.
    for season in sorted(ALL):
        seen = 0
        trimmed: list[dict[str, Any]] = []
        for row in early_trajectory[str(season)]:
            if seen >= AMBER_MIN_N:
                break
            trimmed.append(row)
            if row.get("settlement") in {"WIN", "LOSS"}:
                seen += 1
        early_trajectory[str(season)] = trimmed

    expected_2023_blocks = {"2023-04", "2023-07", "2023-08", "2023-12"}
    actual_2023_blocks = {str(r["block"]) for r in selected_ml_rows if int(r["season"]) == 2023}
    if actual_2023_blocks != expected_2023_blocks:
        raise RuntimeError(f"unexpected 2023 selected ML blocks: {sorted(actual_2023_blocks)}")
    if any(int(r["season"]) == SEALED for r in frontier_rows + selected_ml_rows):
        raise RuntimeError("2025 entered ML audit")

    evidence_levels = ("COLD", "MATURE_GREEN", "AMBER", "RED")
    depth_levels = ("singleton", "competitive")
    frontier_cells: dict[str, Any] = {}
    selected_cells: dict[str, Any] = {}
    for evidence in evidence_levels:
        for depth in depth_levels:
            key = f"{evidence}_{depth}"
            frontier_cells[key] = _summary([
                r for r in frontier_rows
                if r["evidence_status"] == evidence
                and ("singleton" if int(r["ml_candidate_depth"]) == 1 else "competitive") == depth
            ])
            selected_cells[key] = _summary([
                r for r in selected_ml_rows
                if r["evidence_status"] == evidence
                and ("singleton" if int(r["ml_candidate_depth"]) == 1 else "competitive") == depth
            ])

    selected_by_spread_alt = {
        "spread_alternative_present": _summary([r for r in selected_ml_rows if bool(r["spread_alternative_present"])]),
        "no_spread_alternative": _summary([r for r in selected_ml_rows if not bool(r["spread_alternative_present"])]),
    }
    selected_by_evidence_spread_alt: dict[str, Any] = {}
    for evidence in evidence_levels:
        selected_by_evidence_spread_alt[evidence] = {
            "spread_alternative_present": _summary([
                r for r in selected_ml_rows if r["evidence_status"] == evidence and bool(r["spread_alternative_present"])
            ]),
            "no_spread_alternative": _summary([
                r for r in selected_ml_rows if r["evidence_status"] == evidence and not bool(r["spread_alternative_present"])
            ]),
        }

    by_season: dict[str, Any] = {}
    for season in sorted(ALL):
        by_season[str(season)] = {
            "ml_frontier": _summary([r for r in frontier_rows if int(r["season"]) == season]),
            "selected_ml_value": _summary([r for r in selected_ml_rows if int(r["season"]) == season]),
            "selected_ml_by_evidence": {
                e: _summary([r for r in selected_ml_rows if int(r["season"]) == season and r["evidence_status"] == e])
                for e in evidence_levels
            },
        }

    trace_2023 = [r for r in selected_ml_rows if int(r["season"]) == 2023]
    scorecard = {
        "preregistration_commit": PREREG_COMMIT,
        "sealed": [SEALED],
        "production_promotion_allowed": False,
        "invariants": {
            "selected_2023_ml_blocks": sorted(actual_2023_blocks),
            "selected_ml_headlines_unchanged_by_pr47_spread_failsafe": True,
            "no_2025": True,
            "no_selector_change": True,
        },
        "by_season": by_season,
        "ml_frontier_state_depth_cells": frontier_cells,
        "selected_ml_state_depth_cells": selected_cells,
        "selected_ml_by_spread_alternative": selected_by_spread_alt,
        "selected_ml_by_evidence_and_spread_alternative": selected_by_evidence_spread_alt,
        "early_cold_start_trajectory": early_trajectory,
        "selected_ml_2023": trace_2023,
    }

    out.mkdir(parents=True, exist_ok=True)
    (out / "task05g_value_ml_2023_state_depth_audit_v1_scorecard.json").write_text(
        json.dumps(scorecard, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    pl.DataFrame(frontier_rows).sort(["season", "week"]).write_csv(
        out / "task05g_value_ml_2023_state_depth_audit_v1_frontiers.csv"
    )
    pl.DataFrame(selected_ml_rows).sort(["season", "week"]).write_csv(
        out / "task05g_value_ml_2023_state_depth_audit_v1_selected_ml.csv"
    )
    pl.DataFrame(trace_2023).sort(["week"]).write_csv(
        out / "task05g_value_ml_2023_state_depth_audit_v1_2023.csv"
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
