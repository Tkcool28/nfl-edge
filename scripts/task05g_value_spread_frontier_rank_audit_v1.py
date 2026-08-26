#!/usr/bin/env python3
"""Preregistered Task05G Value spread-frontier rank audit V1."""
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
    build_candidate_registry,
    enrich_board_rows,
)

DEV = {2020, 2021, 2022}
DIAG = {2023, 2024}
ALL = DEV | DIAG
SEALED = 2025
MIN_N = 256
VALUE_ODDS = (-180, 250)
SPREAD_REGION = "SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4"
BUCKETS = ("0-1", "1-2", "2-3", "3-4")
PREREG_COMMIT = "5501ce6f2aefb6db48ad253d99f5ea93a4449712"


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
    season, week = str(block).split("-", 1)
    return int(season), int(week)


def _group(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(str(row["block"]), []).append(dict(row))
    return out


def _candidate_id(core, row: Mapping[str, Any]) -> str:
    return str(core._candidate_id(row))


def _odds(row: Mapping[str, Any]) -> int | None:
    v = row.get("american_odds")
    return None if v is None else int(v)


def _rel_rank(core, row: Mapping[str, Any]) -> int:
    return int(core._reliability_rank(row.get("reliability")))


def _tags(row: Mapping[str, Any]) -> set[str]:
    return {x for x in str(row.get("model_candidate_regions") or "").split(";") if x}


def _within(row: Mapping[str, Any]) -> bool:
    odds = _odds(row)
    return odds is not None and VALUE_ODDS[0] <= odds <= VALUE_ODDS[1]


def _eligible(row: Mapping[str, Any]) -> bool:
    ev = _finite(row.get("expected_value"))
    margin = _finite(row.get("model_cover_margin_v3"))
    return (
        str(row.get("market_type")) == "spread"
        and SPREAD_REGION in _tags(row)
        and bool(row.get("supported"))
        and bool(row.get("model_confidence_supported"))
        and int(row.get("model_confidence_support_n") or 0) >= MIN_N
        and str(row.get("sportsbook")) in {"draftkings", "fanduel"}
        and row.get("break_even_probability") is not None
        and str(row.get("price_status")) == "VALUE"
        and ev is not None and ev > 0.0
        and margin is not None and margin > 0.0
        and _within(row)
    )


def _rank_key(core, row: Mapping[str, Any]):
    return (
        -float(row["model_cover_margin_v3"]),
        -float(row.get("evaluated_edge_probability") if row.get("evaluated_edge_probability") is not None else -99.0),
        -_rel_rank(core, row),
        -int(_odds(row) or -100000),
        _candidate_id(core, row),
    )


def _bucket_map(ledger_rows: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for row in ledger_rows:
        season = int(row["season"])
        if season == SEALED:
            raise RuntimeError("2025 entered bucket ledger")
        if str(row.get("family")) != "SPREAD_DISAGREEMENT":
            continue
        if str(row.get("model")) != "EXPECTED_MARGIN":
            continue
        bucket = str(row.get("bucket") or "")
        if bucket not in BUCKETS:
            continue
        key = (str(row.get("game_id")), str(row.get("selected_side")).lower())
        prior = out.get(key)
        if prior is not None and prior != bucket:
            raise RuntimeError(f"inconsistent spread bucket {key}: {prior} vs {bucket}")
        out[key] = bucket
    return out


def _rank_rows(core, rows: list[dict[str, Any]], bucket_map: Mapping[tuple[str, str], str]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for block, block_rows in sorted(_group(rows).items(), key=lambda kv: _block_key(kv[0])):
        candidates = [dict(r) for r in core.shop_exact_offers(block_rows) if _eligible(r)]
        candidates = sorted(candidates, key=lambda r: _rank_key(core, r))
        for i, row in enumerate(candidates, start=1):
            key = (str(row["game_id"]), str(row["selected_side"]).lower())
            bucket = bucket_map.get(key)
            if bucket not in BUCKETS:
                raise RuntimeError(f"missing frozen Expected-Margin bucket for {key}")
            row["frontier_rank"] = i
            row["rank_group"] = str(i) if i <= 5 else "6_plus"
            row["task05e_bucket"] = bucket
            ranked.append(row)
    return ranked


def _settlement(row: Mapping[str, Any]) -> str:
    return str(row.get("settlement") or "")


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

    return {
        "candidates": len(rows),
        "blocks": len({str(r["block"]) for r in rows}),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if denom == 0 else wins / denom,
        "roi": None if not profits else float(mean(profits)),
        "avg_odds": None if not rows else float(mean(int(r["american_odds"]) for r in rows)),
        "avg_model_cover_margin_v3": avg("model_cover_margin_v3"),
        "avg_spread_v3_q": avg("model_confidence_probability"),
        "avg_expected_value": avg("expected_value"),
        "avg_evaluator_edge": avg("evaluated_edge_probability"),
        "reliability_mix": {tier: sum(str(r.get("reliability")) == tier for r in rows) for tier in ("HIGH", "MEDIUM", "LOW", "UNSUPPORTED")},
        "side_mix": {side: sum(str(r.get("selected_side")).lower() == side for r in rows) for side in ("home", "away")},
    }


def _slice(rows: list[dict[str, Any]], seasons: set[int]) -> list[dict[str, Any]]:
    return [r for r in rows if int(r["season"]) in seasons]


def _rank_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for group in ("1", "2", "3", "4", "5", "6_plus"):
        rr = [r for r in rows if str(r["rank_group"]) == group]
        out[group] = _summary(rr)
    return out


def _paired(rows: list[dict[str, Any]], lower_rank: int) -> dict[str, Any]:
    blocks = _group(rows)
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for block_rows in blocks.values():
        by_rank = {int(r["frontier_rank"]): r for r in block_rows if int(r["frontier_rank"]) in {1, lower_rank}}
        if 1 in by_rank and lower_rank in by_rank:
            pairs.append((by_rank[1], by_rank[lower_rank]))

    counts = {"rank1_win_lower_loss": 0, "lower_win_rank1_loss": 0, "both_win": 0, "both_loss": 0, "push_cases": 0}
    diffs = {"model_cover_margin_v3": [], "model_confidence_probability": [], "expected_value": [], "evaluated_edge_probability": [], "american_odds": []}
    for r1, rl in pairs:
        s1, sl = _settlement(r1), _settlement(rl)
        if "PUSH" in {s1, sl}:
            counts["push_cases"] += 1
        elif s1 == "WIN" and sl == "LOSS":
            counts["rank1_win_lower_loss"] += 1
        elif s1 == "LOSS" and sl == "WIN":
            counts["lower_win_rank1_loss"] += 1
        elif s1 == "WIN" and sl == "WIN":
            counts["both_win"] += 1
        elif s1 == "LOSS" and sl == "LOSS":
            counts["both_loss"] += 1
        for field in diffs:
            a = _finite(r1.get(field))
            b = _finite(rl.get(field))
            if a is not None and b is not None:
                diffs[field].append(a - b)

    return {
        "paired_blocks": len(pairs),
        **counts,
        "avg_rank1_minus_lower": {field: None if not vals else float(mean(vals)) for field, vals in diffs.items()},
    }


def _bucket_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        bucket: {
            "all": _summary([r for r in rows if r["task05e_bucket"] == bucket]),
            "rank1": _summary([r for r in rows if r["task05e_bucket"] == bucket and int(r["frontier_rank"]) == 1]),
            "rank2plus": _summary([r for r in rows if r["task05e_bucket"] == bucket and int(r["frontier_rank"]) >= 2]),
        }
        for bucket in BUCKETS
    }


def _ev_bin(v: float) -> str:
    if v <= 0.01:
        return "0_to_1pct"
    if v <= 0.025:
        return "1_to_2_5pct"
    if v <= 0.05:
        return "2_5_to_5pct"
    return "gt_5pct"


def _edge_bin(v: float) -> str:
    if v <= 0.01:
        return "0_to_1pp"
    if v <= 0.025:
        return "1_to_2_5pp"
    if v <= 0.05:
        return "2_5_to_5pp"
    return "gt_5pp"


def _odds_bin(v: int) -> str:
    if v <= -121:
        return "le_-121"
    if v <= -111:
        return "-120_to_-111"
    if v <= -101:
        return "-110_to_-101"
    if v <= 100:
        return "-100_to_100"
    return "gt_100"


def _bin_report(rows: list[dict[str, Any]], field: str, func, labels: tuple[str, ...]) -> dict[str, Any]:
    out = {}
    for label in labels:
        rr = []
        for r in rows:
            value = _finite(r.get(field))
            if value is not None and func(value) == label:
                rr.append(r)
        out[label] = {
            "all": _summary(rr),
            "rank1": _summary([r for r in rr if int(r["frontier_rank"]) == 1]),
        }
    return out


def _phase_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "population": _summary(rows),
        "ranks": _rank_table(rows),
        "paired_rank1_vs_rank2": _paired(rows, 2),
        "paired_rank1_vs_rank3": _paired(rows, 3),
        "task05e_buckets": _bucket_table(rows),
        "expected_value_bins": _bin_report(rows, "expected_value", _ev_bin, ("0_to_1pct", "1_to_2_5pct", "2_5_to_5pct", "gt_5pct")),
        "evaluator_edge_bins": _bin_report(rows, "evaluated_edge_probability", _edge_bin, ("0_to_1pp", "1_to_2_5pp", "2_5_to_5pp", "gt_5pp")),
        "odds_bins": _bin_report(rows, "american_odds", lambda x: _odds_bin(int(x)), ("le_-121", "-120_to_-111", "-110_to_-101", "-100_to_100", "gt_100")),
    }


def _ledger_row(core, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "block": row.get("block"),
        "frontier_rank": row.get("frontier_rank"),
        "candidate_id": _candidate_id(core, row),
        "game_id": row.get("game_id"),
        "selected_side": row.get("selected_side"),
        "line": row.get("line"),
        "sportsbook": row.get("sportsbook"),
        "american_odds": row.get("american_odds"),
        "task05e_bucket": row.get("task05e_bucket"),
        "model_cover_margin_v3": row.get("model_cover_margin_v3"),
        "spread_v3_q": row.get("model_confidence_probability"),
        "break_even_probability": row.get("break_even_probability"),
        "model_price_gap_reporting_only": row.get("model_price_gap"),
        "task05f_actionable_probability": row.get("actionable_probability"),
        "evaluated_edge_probability": row.get("evaluated_edge_probability"),
        "expected_value": row.get("expected_value"),
        "reliability": row.get("reliability"),
        "settlement": row.get("settlement"),
        "realized_profit": row.get("realized_profit"),
    }


def run(root: Path, v3_path: Path, discovery: Path, confirmation: Path, out: Path) -> None:
    core = _load(root / "scripts/task05g_model_confidence_v2_runner.py", "task05g_spread_rank_core")
    v3 = pl.read_parquet(v3_path).to_dicts()
    seasons = {int(r["season"]) for r in v3}
    if seasons != ALL or SEALED in seasons:
        raise RuntimeError(f"unexpected/sealed V3 seasons: {sorted(seasons)}")

    led = pl.concat([
        pl.read_csv(discovery, infer_schema_length=10000),
        pl.read_csv(confirmation, infer_schema_length=10000),
    ], how="vertical_relaxed")
    ledger_rows = led.to_dicts()
    ledger_seasons = {int(r["season"]) for r in ledger_rows}
    if ledger_seasons != ALL or SEALED in ledger_seasons:
        raise RuntimeError(f"unexpected/sealed ledger seasons: {sorted(ledger_seasons)}")

    registry = build_candidate_registry(ledger_rows)
    enriched = enrich_board_rows(v3, registry)
    buckets = _bucket_map(ledger_rows)
    ranked = _rank_rows(core, enriched, buckets)

    if any(str(r.get("market_type")) != "spread" for r in ranked):
        raise RuntimeError("non-spread entered audit")
    if any(SPREAD_REGION not in _tags(r) for r in ranked):
        raise RuntimeError("non-frozen spread provenance entered audit")
    if any(str(r.get("price_status")) != "VALUE" or float(r["expected_value"]) <= 0.0 for r in ranked):
        raise RuntimeError("non-strict Value entered audit")
    if any(float(r["model_cover_margin_v3"]) <= 0.0 for r in ranked):
        raise RuntimeError("non-positive cover margin entered audit")

    scorecard = {
        "preregistration_commit": PREREG_COMMIT,
        "periods": {"development": sorted(DEV), "exposed": sorted(DIAG), "overall": sorted(ALL), "sealed": [SEALED]},
        "by_season": {str(season): _phase_report(_slice(ranked, {season})) for season in sorted(ALL)},
        "development": _phase_report(_slice(ranked, DEV)),
        "exposed": _phase_report(_slice(ranked, DIAG)),
        "overall": _phase_report(ranked),
        "promotion_authorized": False,
    }

    out.mkdir(parents=True, exist_ok=True)
    (out / "task05g_value_spread_frontier_rank_audit_v1.json").write_text(json.dumps(scorecard, indent=2, sort_keys=True, allow_nan=False) + "\n")
    ledger_2023 = [_ledger_row(core, r) for r in ranked if int(r["season"]) == 2023]
    if ledger_2023:
        pl.DataFrame(ledger_2023).sort(["block", "frontier_rank", "candidate_id"], nulls_last=True).write_csv(out / "task05g_value_spread_frontier_rank_2023.csv")
    else:
        (out / "task05g_value_spread_frontier_rank_2023.csv").write_text("\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--v3-candidates", type=Path, required=True)
    p.add_argument("--discovery", type=Path, default=Path("reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv"))
    p.add_argument("--confirmation", type=Path, default=Path("reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv"))
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    run(a.root, a.v3_candidates, a.discovery, a.confirmation, a.out)
