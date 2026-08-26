#!/usr/bin/env python3
"""Preregistered coefficient-free spread Value Pareto frontier replay."""
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
PREREG_COMMIT = "b66405a9e8f6b3f485a4a021ad33a51c3df861be"
SPREAD_REGION = "SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4"
BUCKETS = ("0-1", "1-2", "2-3", "3-4")


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


def _settlement(row: Mapping[str, Any]) -> str:
    return str(row.get("settlement") or "")


def _bucket_map(ledger_rows: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for row in ledger_rows:
        if int(row["season"]) == SEALED:
            raise RuntimeError("2025 entered bucket ledger")
        if str(row.get("family")) != "SPREAD_DISAGREEMENT" or str(row.get("model")) != "EXPECTED_MARGIN":
            continue
        bucket = str(row.get("bucket") or "")
        if bucket not in BUCKETS:
            continue
        key = (str(row.get("game_id")), str(row.get("selected_side")).lower())
        if key in out and out[key] != bucket:
            raise RuntimeError(f"inconsistent bucket for {key}")
        out[key] = bucket
    return out


def _eligible_spread(final, row: Mapping[str, Any]) -> bool:
    edge = _finite(row.get("evaluated_edge_probability"))
    return (
        final._strict_value_common(row)
        and str(row.get("market_type")) == "spread"
        and SPREAD_REGION in final._tags(row)
        and _finite(row.get("model_cover_margin_v3")) is not None
        and float(row["model_cover_margin_v3"]) > 0.0
        and edge is not None
        and edge > 0.0
    )


def _spread_candidates(core, final, block_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(r) for r in final._shop(core, block_rows) if _eligible_spread(final, r)]


def _raw_frontier(core, final, block_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    # Reproduce the current Final Selector Candidate V1 implementation exactly.
    return final._spread_frontier(core, block_rows)


def _pareto_frontier(core, final, block_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = _spread_candidates(core, final, block_rows)
    if not candidates:
        return None

    model_order = sorted(
        candidates,
        key=lambda r: (-float(r["model_cover_margin_v3"]), _candidate_id(core, r)),
    )
    economic_order = sorted(
        candidates,
        key=lambda r: (
            -float(r["evaluated_edge_probability"]),
            -float(r["expected_value"]),
            _candidate_id(core, r),
        ),
    )
    model_rank = {_candidate_id(core, r): i for i, r in enumerate(model_order, start=1)}
    economic_rank = {_candidate_id(core, r): i for i, r in enumerate(economic_order, start=1)}

    decorated: list[dict[str, Any]] = []
    for src in candidates:
        r = dict(src)
        cid = _candidate_id(core, r)
        mr = model_rank[cid]
        er = economic_rank[cid]
        r["pareto_model_rank"] = mr
        r["pareto_economic_rank"] = er
        r["pareto_worst_rank"] = max(mr, er)
        r["pareto_rank_sum"] = mr + er
        decorated.append(r)

    return dict(sorted(
        decorated,
        key=lambda r: (
            int(r["pareto_worst_rank"]),
            int(r["pareto_rank_sum"]),
            int(r["pareto_model_rank"]),
            int(r["pareto_economic_rank"]),
            -int(final._rel(core, r)),
            -int(final._odds(r) or -100000),
            _candidate_id(core, r),
        ),
    )[0])


def _longest_losing_streak(rows: list[Mapping[str, Any]]) -> int:
    cur = longest = 0
    for r in sorted(rows, key=lambda x: (_block_key(str(x["block"])), str(x.get("game_id")))):
        if _settlement(r) == "LOSS":
            cur += 1
            longest = max(longest, cur)
        elif _settlement(r) == "WIN":
            cur = 0
    return longest


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

    margins = [_finite(r.get("model_cover_margin_v3")) for r in rows]
    margins = [x for x in margins if x is not None]
    return {
        "plays": len(rows),
        "blocks": len({str(r["block"]) for r in rows}),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if denom == 0 else wins / denom,
        "roi": None if not profits else float(mean(profits)),
        "max_losing_streak": _longest_losing_streak(rows),
        "avg_odds": None if not rows else float(mean(int(r["american_odds"]) for r in rows)),
        "avg_model_cover_margin_v3": avg("model_cover_margin_v3"),
        "max_model_cover_margin_v3": None if not margins else max(margins),
        "avg_spread_v3_q": avg("model_confidence_probability"),
        "avg_evaluated_edge": avg("evaluated_edge_probability"),
        "avg_expected_value": avg("expected_value"),
        "avg_original_raw_margin_rank": avg("original_raw_margin_rank"),
    }


def _bucket_summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {bucket: _summary([r for r in rows if r.get("task05e_bucket") == bucket]) for bucket in BUCKETS}


def _decorate_frontier_rows(
    core,
    blocks: Mapping[str, list[dict[str, Any]]],
    chosen: Mapping[str, dict[str, Any]],
    bucket_map: Mapping[tuple[str, str], str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block, row in chosen.items():
        r = dict(row)
        raw_sorted = sorted(
            _spread_candidates(core, _FINAL, blocks[block]),
            key=lambda x: (-float(x["model_cover_margin_v3"]), -float(x["evaluated_edge_probability"]), _candidate_id(core, x)),
        )
        rank_map = {_candidate_id(core, x): i for i, x in enumerate(raw_sorted, start=1)}
        cid = _candidate_id(core, r)
        r["original_raw_margin_rank"] = rank_map[cid]
        bkey = (str(r["game_id"]), str(r["selected_side"]).lower())
        bucket = bucket_map.get(bkey)
        if bucket not in BUCKETS:
            raise RuntimeError(f"missing frozen bucket for {bkey}")
        r["task05e_bucket"] = bucket
        out.append(r)
    return sorted(out, key=lambda r: _block_key(str(r["block"])))


def _paired(raw: Mapping[str, Mapping[str, Any]], pareto: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    counts = {
        "changed_blocks": 0,
        "pareto_win_raw_loss": 0,
        "raw_win_pareto_loss": 0,
        "both_win": 0,
        "both_loss": 0,
        "push_involved": 0,
    }
    for block in sorted(raw, key=_block_key):
        a, b = raw[block], pareto[block]
        if _candidate_id(_CORE, a) == _candidate_id(_CORE, b):
            continue
        counts["changed_blocks"] += 1
        sa, sb = _settlement(a), _settlement(b)
        if "PUSH" in {sa, sb}:
            counts["push_involved"] += 1
        elif sb == "WIN" and sa == "LOSS":
            counts["pareto_win_raw_loss"] += 1
        elif sa == "WIN" and sb == "LOSS":
            counts["raw_win_pareto_loss"] += 1
        elif sa == "WIN" and sb == "WIN":
            counts["both_win"] += 1
        elif sa == "LOSS" and sb == "LOSS":
            counts["both_loss"] += 1
    return counts


def _phase_blocks(blocks: Mapping[str, Any], seasons: set[int]) -> set[str]:
    return {b for b in blocks if _block_key(b)[0] in seasons}


def _value_primary(value_run: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    return value_run["selected"]["FRONTIER_STATE_V3"]


def _value_compare(current: Mapping[str, Any], pareto: Mapping[str, Any], all_blocks: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"by_season": {}, "periods": {}}
    cur_sel = _value_primary(current)
    par_sel = _value_primary(pareto)

    def compare_for(blockset: set[str]) -> dict[str, Any]:
        c = {b: r for b, r in cur_sel.items() if b in blockset}
        p = {b: r for b, r in par_sel.items() if b in blockset}
        cs = _summary(list(c.values()))
        ps = _summary(list(p.values()))
        changed = set(c) | set(p)
        diff = 0
        spread_to_ml = ml_to_spread = pass_changes = 0
        for b in changed:
            cr, pr = c.get(b), p.get(b)
            if cr is None or pr is None:
                pass_changes += 1
                diff += 1
                continue
            if _candidate_id(_CORE, cr) != _candidate_id(_CORE, pr):
                diff += 1
            cm, pm = str(cr.get("market_type")), str(pr.get("market_type"))
            if cm == "spread" and pm == "moneyline": spread_to_ml += 1
            if cm == "moneyline" and pm == "spread": ml_to_spread += 1
        return {
            "current": {**cs, "market_mix": {m: sum(str(r.get("market_type")) == m for r in c.values()) for m in ("moneyline","spread","total")}},
            "pareto": {**ps, "market_mix": {m: sum(str(r.get("market_type")) == m for r in p.values()) for m in ("moneyline","spread","total")}},
            "changed_value_blocks": diff,
            "spread_to_ml": spread_to_ml,
            "ml_to_spread": ml_to_spread,
            "pass_changes": pass_changes,
        }

    for season in sorted(ALL):
        out["by_season"][str(season)] = compare_for(_phase_blocks(all_blocks, {season}))
    for label, seasons in (("development", DEV), ("locked_diagnostic", DIAG), ("overall", ALL)):
        out["periods"][label] = compare_for(_phase_blocks(all_blocks, seasons))
    return out


def run(root: Path, v3_path: Path, discovery: Path, confirmation: Path, out: Path) -> None:
    global _CORE, _FINAL
    _CORE = _load(root / "scripts/task05g_model_confidence_v2_runner.py", "task05g_pareto_core")
    _FINAL = _load(root / "scripts/task05g_final_selector_candidate_v1.py", "task05g_pareto_final")

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
    blocks = _group(enriched)
    bucket_map = _bucket_map(led_rows)

    raw: dict[str, dict[str, Any]] = {}
    pareto: dict[str, dict[str, Any]] = {}
    for block in sorted(blocks, key=_block_key):
        r = _raw_frontier(_CORE, _FINAL, blocks[block])
        p = _pareto_frontier(_CORE, _FINAL, blocks[block])
        if (r is None) != (p is None):
            raise RuntimeError(f"ANTI_NEUTERING_COVERAGE_PARITY_FAIL {block}")
        if r is not None:
            raw[block] = dict(r)
            pareto[block] = dict(p)

    if set(raw) != set(pareto):
        raise RuntimeError("spread-frontier block coverage mismatch")

    raw_rows = _decorate_frontier_rows(_CORE, blocks, raw, bucket_map)
    pareto_rows = _decorate_frontier_rows(_CORE, blocks, pareto, bucket_map)

    frontier: dict[str, Any] = {"by_season": {}, "periods": {}}
    for season in sorted(ALL):
        rr = [r for r in raw_rows if int(r["season"]) == season]
        pp = [r for r in pareto_rows if int(r["season"]) == season]
        frontier["by_season"][str(season)] = {
            "raw": _summary(rr), "pareto": _summary(pp),
            "paired": _paired({str(r["block"]): r for r in rr}, {str(r["block"]): r for r in pp}),
            "raw_buckets": _bucket_summary(rr), "pareto_buckets": _bucket_summary(pp),
        }
    for label, seasons_set in (("development", DEV), ("locked_diagnostic", DIAG), ("overall", ALL)):
        rr = [r for r in raw_rows if int(r["season"]) in seasons_set]
        pp = [r for r in pareto_rows if int(r["season"]) in seasons_set]
        frontier["periods"][label] = {
            "raw": _summary(rr), "pareto": _summary(pp),
            "paired": _paired({str(r["block"]): r for r in rr}, {str(r["block"]): r for r in pp}),
            "raw_buckets": _bucket_summary(rr), "pareto_buckets": _bucket_summary(pp),
        }

    current_value = _FINAL._value_run(_CORE, enriched)
    original_spread_fn = _FINAL._spread_frontier
    try:
        _FINAL._spread_frontier = lambda core, rows: _pareto_frontier(core, _FINAL, rows)
        pareto_value = _FINAL._value_run(_CORE, enriched)
    finally:
        _FINAL._spread_frontier = original_spread_fn

    integrated = _value_compare(current_value, pareto_value, blocks)

    # Cross-market spread-preservation diagnostics.
    cur_sel = _value_primary(current_value)
    par_sel = _value_primary(pareto_value)
    preservation = {
        "valid_spread_frontier_blocks": len(raw),
        "current_final_value_spread_plays": sum(str(r.get("market_type")) == "spread" for r in cur_sel.values()),
        "pareto_final_value_spread_plays": sum(str(r.get("market_type")) == "spread" for r in par_sel.values()),
        "pareto_spread_won_final_value_where_valid": sum(b in par_sel and str(par_sel[b].get("market_type")) == "spread" for b in raw),
        "pareto_spread_lost_to_ml_where_valid": sum(b in par_sel and str(par_sel[b].get("market_type")) == "moneyline" for b in raw),
    }

    scorecard = {
        "preregistration_commit": PREREG_COMMIT,
        "sealed": [SEALED],
        "spread_frontier_coverage_parity": set(raw) == set(pareto),
        "spread_frontier_blocks": len(raw),
        "frontier": frontier,
        "integrated_value": integrated,
        "spread_preservation": preservation,
        "production_promotion_allowed": False,
    }

    out.mkdir(parents=True, exist_ok=True)
    (out / "task05g_value_spread_pareto_frontier_v1_scorecard.json").write_text(json.dumps(scorecard, indent=2, sort_keys=True, allow_nan=False) + "\n")
    rows_out = []
    for selector, rows_ in (("RAW_MARGIN_FRONTIER", raw_rows), ("PARETO_BALANCED", pareto_rows)):
        for r in rows_:
            rows_out.append({
                "selector": selector,
                "block": r.get("block"),
                "season": r.get("season"),
                "candidate_id": _candidate_id(_CORE, r),
                "game_id": r.get("game_id"),
                "selected_side": r.get("selected_side"),
                "line": r.get("line"),
                "american_odds": r.get("american_odds"),
                "task05e_bucket": r.get("task05e_bucket"),
                "model_cover_margin_v3": r.get("model_cover_margin_v3"),
                "spread_v3_q": r.get("model_confidence_probability"),
                "evaluated_edge_probability": r.get("evaluated_edge_probability"),
                "expected_value": r.get("expected_value"),
                "original_raw_margin_rank": r.get("original_raw_margin_rank"),
                "pareto_model_rank": r.get("pareto_model_rank"),
                "pareto_economic_rank": r.get("pareto_economic_rank"),
                "pareto_worst_rank": r.get("pareto_worst_rank"),
                "pareto_rank_sum": r.get("pareto_rank_sum"),
                "settlement": r.get("settlement"),
                "realized_profit": r.get("realized_profit"),
            })
    pl.DataFrame(rows_out).sort(["block", "selector"]).write_csv(out / "task05g_value_spread_pareto_frontier_v1_rows.csv")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--v3-candidates", type=Path, required=True)
    p.add_argument("--discovery", type=Path, default=Path("reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv"))
    p.add_argument("--confirmation", type=Path, default=Path("reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv"))
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    run(a.root, a.v3_candidates, a.discovery, a.confirmation, a.out)
