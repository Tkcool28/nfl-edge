#!/usr/bin/env python3
"""Preregistered Task05G dual-family Value frontier trust V1 replay.

Retrospective selector diagnostic only. No production policy, Task05F evaluator,
football model, Spread Confidence V3 mapping, candidate family, or sealed 2025
input is changed.
"""
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
VALUE_ODDS = (-180, 250)
RESET_TRUST = 0.50
PSEUDO_N = 8
AMBER_MIN_N = 3
AMBER_TRUST = 0.50
RED_MIN_N = 8
RED_TRUST = 0.25
PREREG_COMMIT = "8660c03bb27c581f65c3c640aaa9fd2bcfbaf8f0"
ML_REGIONS = frozenset(name for name, family, *_ in REGION_SPECS if family.startswith("ML_"))
SPREAD_REGION = "SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4"


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


def _odds(row: Mapping[str, Any]) -> int | None:
    value = row.get("american_odds")
    return None if value is None else int(value)


def _reliability(core, row: Mapping[str, Any]) -> int:
    return int(core._reliability_rank(row.get("reliability")))


def _within(row: Mapping[str, Any], bounds: tuple[int, int]) -> bool:
    odds = _odds(row)
    return odds is not None and bounds[0] <= odds <= bounds[1]


def _tags(row: Mapping[str, Any]) -> set[str]:
    return {x for x in str(row.get("model_candidate_regions") or "").split(";") if x}


def _shop(core, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(r) for r in core.shop_exact_offers(list(rows))]


def _common(row: Mapping[str, Any]) -> bool:
    return (
        bool(row.get("supported"))
        and bool(row.get("model_confidence_supported"))
        and int(row.get("model_confidence_support_n") or 0) >= MIN_N
        and str(row.get("market_type")) in {"moneyline", "spread"}
        and str(row.get("sportsbook")) in {"draftkings", "fanduel"}
        and row.get("break_even_probability") is not None
    )


def _strict_value_common(row: Mapping[str, Any]) -> bool:
    ev = _finite(row.get("expected_value"))
    return (
        _common(row)
        and bool(_tags(row))
        and ev is not None
        and ev > 0.0
        and str(row.get("price_status")) == "VALUE"
        and _within(row, VALUE_ODDS)
    )


def _ml_frontier(core, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for r in _shop(core, rows):
        gap = _finite(r.get("model_price_gap"))
        edge = _finite(r.get("evaluated_edge_probability"))
        if (
            _strict_value_common(r)
            and str(r.get("market_type")) == "moneyline"
            and bool(_tags(r).intersection(ML_REGIONS))
            and gap is not None
            and gap > 0.0
            and edge is not None
            and edge > 0.0
        ):
            candidates.append(r)
    if not candidates:
        return None
    return dict(sorted(candidates, key=lambda r: (
        -float(r["model_price_gap"]),
        -float(r["model_confidence_probability"]),
        -float(r["evaluated_edge_probability"]),
        -_reliability(core, r),
        -int(_odds(r) or -100000),
        _candidate_id(core, r),
    ))[0])


def _spread_frontier(core, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for r in _shop(core, rows):
        margin = _finite(r.get("model_cover_margin_v3"))
        edge = _finite(r.get("evaluated_edge_probability"))
        if (
            _strict_value_common(r)
            and str(r.get("market_type")) == "spread"
            and SPREAD_REGION in _tags(r)
            and margin is not None
            and margin > 0.0
            and edge is not None
            and edge > 0.0
        ):
            candidates.append(r)
    if not candidates:
        return None
    return dict(sorted(candidates, key=lambda r: (
        -float(r["model_cover_margin_v3"]),
        -float(r["evaluated_edge_probability"]),
        -_reliability(core, r),
        -int(_odds(r) or -100000),
        _candidate_id(core, r),
    ))[0])


def _settlement(row: Mapping[str, Any] | None) -> str:
    return "" if row is None else str(row.get("settlement") or "")


def _trust(observations: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(observations)
    if n == 0:
        return {"n": 0, "predicted_edge_sum": 0.0, "realized_edge_sum": 0.0, "data_trust": None, "trust": RESET_TRUST}
    pred = sum(float(o["predicted_edge"]) for o in observations)
    realized = sum(float(o["realized_edge"]) for o in observations)
    data = 0.0 if pred <= 0.0 else min(1.0, max(0.0, realized / pred))
    trust = (PSEUDO_N * RESET_TRUST + n * data) / (PSEUDO_N + n)
    return {"n": n, "predicted_edge_sum": float(pred), "realized_edge_sum": float(realized), "data_trust": float(data), "trust": float(trust)}


def _state(state: Mapping[str, Any]) -> str:
    n = int(state["n"])
    trust = float(state["trust"])
    if n >= RED_MIN_N and trust < RED_TRUST:
        return "RED"
    if n >= AMBER_MIN_N and trust < AMBER_TRUST:
        return "AMBER"
    return "GREEN"


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
    return {"block": str(row["block"]), "game_id": str(row["game_id"]), "predicted_edge": float(predicted), "realized_edge": float(y - be)}


def _spread_observation(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if row is None or _settlement(row) not in {"WIN", "LOSS"}:
        return None
    predicted = _finite(row.get("evaluated_edge_probability"))
    be = _finite(row.get("break_even_probability"))
    if predicted is None or predicted <= 0.0 or be is None:
        return None
    y = 1.0 if _settlement(row) == "WIN" else 0.0
    return {"block": str(row["block"]), "game_id": str(row["game_id"]), "predicted_edge": float(predicted), "realized_edge": float(y - be)}


def _ml_dynamic_edge(row: Mapping[str, Any], trust: float) -> float:
    return min(float(row["model_price_gap"]) * float(trust), float(row["evaluated_edge_probability"]))


def _spread_dynamic_edge(row: Mapping[str, Any], trust: float) -> float:
    return float(row["evaluated_edge_probability"]) * float(trust)


def _tie_key(core, row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (-_reliability(core, row), -int(_odds(row) or -100000), _candidate_id(core, row))


def _choose_by_edge(core, ml: dict[str, Any] | None, spread: dict[str, Any] | None, ml_trust: float, spread_trust: float) -> dict[str, Any] | None:
    candidates: list[tuple[float, dict[str, Any]]] = []
    if ml is not None:
        candidates.append((_ml_dynamic_edge(ml, ml_trust), ml))
    if spread is not None:
        candidates.append((_spread_dynamic_edge(spread, spread_trust), spread))
    if not candidates:
        return None
    _, row = sorted(candidates, key=lambda item: (-float(item[0]), *_tie_key(core, item[1])))[0]
    return dict(row)


def _select_current(core, ml, spread, ml_state):
    status = _state(ml_state)
    if status == "RED":
        return None if spread is None else dict(spread)
    if status == "AMBER" and spread is not None:
        return dict(spread)
    return _choose_by_edge(core, ml, spread, float(ml_state["trust"]), 1.0)


def _select_dual_shrink(core, ml, spread, ml_state, spread_state):
    if _state(ml_state) == "RED":
        ml = None
    if _state(spread_state) == "RED":
        spread = None
    return _choose_by_edge(core, ml, spread, float(ml_state["trust"]), float(spread_state["trust"]))


def _select_primary(core, ml, spread, ml_state, spread_state):
    ml_status = _state(ml_state)
    spread_status = _state(spread_state)
    if ml_status == "RED":
        ml = None
    if spread_status == "RED":
        spread = None
    if ml is None and spread is None:
        return None
    if ml is None:
        return dict(spread)
    if spread is None:
        return dict(ml)
    if ml_status == "GREEN" and spread_status == "AMBER":
        return dict(ml)
    if spread_status == "GREEN" and ml_status == "AMBER":
        return dict(spread)
    return _choose_by_edge(core, ml, spread, float(ml_state["trust"]), float(spread_state["trust"]))


def _longest_losing_streak(rows: list[Mapping[str, Any]]) -> int:
    longest = cur = 0
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
        "plays": len(rows), "total_blocks": total_blocks,
        "coverage": 0.0 if total_blocks == 0 else len(rows) / total_blocks,
        "wins": wins, "losses": losses, "pushes": pushes,
        "hit_rate_nonpush": None if denom == 0 else wins / denom,
        "roi": None if not profits else float(mean(profits)),
        "avg_odds": None if not rows else float(mean(int(r["american_odds"]) for r in rows)),
        "market_mix": {m: sum(str(r.get("market_type")) == m for r in rows) for m in ("moneyline", "spread", "total")},
        "max_losing_streak": _longest_losing_streak(rows),
    }


def _frontier_summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    mapping = {str(r["block"]): r for r in rows}
    return _summary(mapping, len(mapping))


def _run(core, rows: list[dict[str, Any]]) -> dict[str, Any]:
    blocks = _group(rows)
    ml_prior = {s: [] for s in ALL}
    spread_prior = {s: [] for s in ALL}
    selected = {v: {} for v in ("CURRENT_ML_ONLY_STATE", "DUAL_SHRINK_ONLY", "DUAL_FRONTIER_TRUST_V1")}
    ml_frontiers: list[dict[str, Any]] = []
    spread_frontiers: list[dict[str, Any]] = []
    trajectory: list[dict[str, Any]] = []
    state_counts = {family: {s: {"GREEN": 0, "AMBER": 0, "RED": 0} for s in ALL} for family in ("ml", "spread")}
    pass_reasons: dict[str, str] = {}

    for block in sorted(blocks, key=_block_key):
        season, week = _block_key(block)
        ml_state = _trust(ml_prior[season])
        spread_state = _trust(spread_prior[season])
        ml_status, spread_status = _state(ml_state), _state(spread_state)
        state_counts["ml"][season][ml_status] += 1
        state_counts["spread"][season][spread_status] += 1

        ml = _ml_frontier(core, blocks[block])
        spread = _spread_frontier(core, blocks[block])
        if ml is not None:
            ml_frontiers.append(dict(ml))
        if spread is not None:
            spread_frontiers.append(dict(spread))

        trajectory.append({
            "block": block, "season": season, "week": week,
            "ml_state": ml_status, "ml_n": int(ml_state["n"]), "ml_trust": float(ml_state["trust"]),
            "spread_state": spread_status, "spread_n": int(spread_state["n"]), "spread_trust": float(spread_state["trust"]),
            "ml_frontier_candidate_id": None if ml is None else _candidate_id(core, ml),
            "spread_frontier_candidate_id": None if spread is None else _candidate_id(core, spread),
        })

        choices = {
            "CURRENT_ML_ONLY_STATE": _select_current(core, ml, spread, ml_state),
            "DUAL_SHRINK_ONLY": _select_dual_shrink(core, ml, spread, ml_state, spread_state),
            "DUAL_FRONTIER_TRUST_V1": _select_primary(core, ml, spread, ml_state, spread_state),
        }
        for name, choice in choices.items():
            if choice is not None:
                selected[name][block] = dict(choice)

        if choices["DUAL_FRONTIER_TRUST_V1"] is None:
            if ml is None and spread is None:
                pass_reasons[block] = "NO_STRICT_VALUE_FRONTIER"
            elif ml_status == "RED" and spread_status == "RED":
                pass_reasons[block] = "BOTH_FAMILIES_RED"
            elif ml is not None and ml_status == "RED" and spread is None:
                pass_reasons[block] = "ML_RED_NO_SPREAD"
            elif spread is not None and spread_status == "RED" and ml is None:
                pass_reasons[block] = "SPREAD_RED_NO_ML"
            else:
                pass_reasons[block] = "NO_NONRED_VALUE_FRONTIER"

        ml_obs = _ml_observation(ml)
        spread_obs = _spread_observation(spread)
        if ml_obs is not None:
            ml_prior[season].append(ml_obs)
        if spread_obs is not None:
            spread_prior[season].append(spread_obs)

    periods = {}
    for label, seasons in (("development", DEV), ("locked_diagnostic", DIAG), ("overall", ALL)):
        period_blocks = {b for b in blocks if _block_key(b)[0] in seasons}
        periods[label] = {name: _summary({b: r for b, r in mapping.items() if b in period_blocks}, len(period_blocks)) for name, mapping in selected.items()}

    by_season = {}
    for season in sorted(ALL):
        season_blocks = {b for b in blocks if _block_key(b)[0] == season}
        by_season[str(season)] = {name: _summary({b: r for b, r in mapping.items() if b in season_blocks}, len(season_blocks)) for name, mapping in selected.items()}

    crossings = {"ml": {}, "spread": {}}
    for family in ("ml", "spread"):
        for season in sorted(ALL):
            tr = [r for r in trajectory if int(r["season"]) == season]
            amber = next((r for r in tr if r[f"{family}_state"] == "AMBER"), None)
            red = next((r for r in tr if r[f"{family}_state"] == "RED"), None)
            crossings[family][str(season)] = {
                "first_amber": None if amber is None else {"block": amber["block"], "n": amber[f"{family}_n"], "trust": amber[f"{family}_trust"]},
                "first_red": None if red is None else {"block": red["block"], "n": red[f"{family}_n"], "trust": red[f"{family}_trust"]},
            }

    selected_2023 = []
    for block in sorted([b for b in blocks if _block_key(b)[0] == 2023], key=_block_key):
        row = selected["DUAL_FRONTIER_TRUST_V1"].get(block)
        tr = next(x for x in trajectory if x["block"] == block)
        selected_2023.append({
            **tr,
            "selected_candidate_id": None if row is None else _candidate_id(core, row),
            "selected_market": None if row is None else row.get("market_type"),
            "american_odds": None if row is None else row.get("american_odds"),
            "settlement": None if row is None else row.get("settlement"),
            "realized_profit": None if row is None else row.get("realized_profit"),
            "pass_reason": pass_reasons.get(block),
        })

    return {
        "periods": periods,
        "by_season": by_season,
        "frontiers": {
            "ml": {
                "development": _frontier_summary([r for r in ml_frontiers if int(r["season"]) in DEV]),
                "locked_diagnostic": _frontier_summary([r for r in ml_frontiers if int(r["season"]) in DIAG]),
                "overall": _frontier_summary(ml_frontiers),
            },
            "spread": {
                "development": _frontier_summary([r for r in spread_frontiers if int(r["season"]) in DEV]),
                "locked_diagnostic": _frontier_summary([r for r in spread_frontiers if int(r["season"]) in DIAG]),
                "overall": _frontier_summary(spread_frontiers),
            },
        },
        "state_counts": {family: {str(s): counts for s, counts in season_map.items()} for family, season_map in state_counts.items()},
        "crossings": crossings,
        "primary_pass_reasons": {reason: sum(v == reason for v in pass_reasons.values()) for reason in sorted(set(pass_reasons.values()))},
        "trajectory": trajectory,
        "selected_2023": selected_2023,
    }


def run(root: Path, v3_path: Path, discovery: Path, confirmation: Path, out: Path) -> None:
    core = _load(root / "scripts/task05g_model_confidence_v2_runner.py", "task05g_dual_value_core")
    rows = pl.read_parquet(v3_path).to_dicts()
    seasons = {int(r["season"]) for r in rows}
    if seasons != ALL or SEALED in seasons:
        raise RuntimeError(f"unexpected/sealed V3 seasons: {sorted(seasons)}")

    led = pl.concat([pl.read_csv(discovery, infer_schema_length=10000), pl.read_csv(confirmation, infer_schema_length=10000)], how="vertical_relaxed")
    ledger_seasons = {int(x) for x in led["season"].unique().to_list()}
    if ledger_seasons != ALL or SEALED in ledger_seasons:
        raise RuntimeError(f"unexpected/sealed provenance seasons: {sorted(ledger_seasons)}")

    registry = build_candidate_registry(led.to_dicts())
    enriched = enrich_board_rows(rows, registry)
    result = {
        "preregistration_commit": PREREG_COMMIT,
        "periods_definition": {"development": sorted(DEV), "locked_diagnostic": sorted(DIAG), "overall": sorted(ALL), "sealed": [SEALED]},
        "constants": {"season_reset_trust": RESET_TRUST, "pseudo_count": PSEUDO_N, "amber_min_n": AMBER_MIN_N, "amber_trust": AMBER_TRUST, "red_min_n": RED_MIN_N, "red_trust": RED_TRUST},
        "result": _run(core, enriched),
        "production_promotion_allowed": False,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "task05g_value_dual_frontier_trust_v1.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    pl.DataFrame(result["result"]["selected_2023"]).sort("block").write_csv(out / "task05g_value_dual_frontier_trust_v1_2023.csv")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--v3-candidates", type=Path, required=True)
    p.add_argument("--discovery", type=Path, default=Path("reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv"))
    p.add_argument("--confirmation", type=Path, default=Path("reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv"))
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    run(a.root, a.v3_candidates, a.discovery, a.confirmation, a.out)
