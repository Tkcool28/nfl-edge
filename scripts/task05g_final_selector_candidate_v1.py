#!/usr/bin/env python3
"""Preregistered final Task05G three-protocol selector candidate replay.

Consumes frozen Task05F -> Model Confidence V2 -> Spread Confidence V3 evidence.
No production selector is changed here. Season 2025 is prohibited.
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
HHR_MIN_Q = 0.55
BAL_MIN_Q = 0.52
HHR_ODDS = (-300, 200)
BAL_ODDS = (-220, 200)
VALUE_ODDS = (-180, 250)
HALF = 0.50
RESET_TRUST = 0.50
PSEUDO_N = 8
AMBER_MIN_N = 3
AMBER_TRUST = 0.50
RED_MIN_N = 8
RED_TRUST = 0.25
PREREG_COMMIT = "c9ac8fd4b45c4035bf1a0aed514235396edcd65b"
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


def _q(row: Mapping[str, Any]) -> float | None:
    return _finite(row.get("model_confidence_probability"))


def _odds(row: Mapping[str, Any]) -> int | None:
    x = row.get("american_odds")
    return None if x is None else int(x)


def _rel(core, row: Mapping[str, Any]) -> int:
    return int(core._reliability_rank(row.get("reliability")))


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


def _within(row: Mapping[str, Any], bounds: tuple[int, int]) -> bool:
    o = _odds(row)
    return o is not None and bounds[0] <= o <= bounds[1]


def _disagreement(row: Mapping[str, Any]) -> float | None:
    if str(row.get("market_type")) != "moneyline":
        return None
    qb = _finite(row.get("raw_qbelo_probability_selected"))
    xgb = _finite(row.get("raw_xgb_probability_selected"))
    if qb is None or xgb is None:
        return None
    return abs(qb - xgb)


def _market_trust(row: Mapping[str, Any]) -> float | None:
    q = _q(row)
    if q is None:
        return None
    if str(row.get("market_type")) == "spread":
        return q
    pin = _finite(row.get("pinnacle_anchor_probability"))
    if pin is None:
        return None
    return q - HALF * max(q - pin, 0.0)


def _agreement_trust(row: Mapping[str, Any]) -> float | None:
    q = _q(row)
    if q is None:
        return None
    if str(row.get("market_type")) == "spread":
        return q
    d = _disagreement(row)
    if d is None:
        return None
    return q - HALF * d


def _dual_trust(row: Mapping[str, Any]) -> float | None:
    m = _market_trust(row)
    a = _agreement_trust(row)
    if m is None or a is None:
        return None
    return min(m, a)


def _lane_eligible(row: Mapping[str, Any], lane: str) -> bool:
    q = _q(row)
    if not _common(row) or q is None:
        return False
    if lane == "hhr":
        return q >= HHR_MIN_Q and _within(row, HHR_ODDS)
    if lane == "balanced":
        return q >= BAL_MIN_Q and _within(row, BAL_ODDS)
    raise ValueError(lane)


def _lane_trust(row: Mapping[str, Any], lane: str, rule: str) -> float | None:
    if rule == "RAW_Q":
        return _q(row)
    if lane == "hhr":
        if rule != "MARKET_HALF":
            raise ValueError((lane, rule))
        return _market_trust(row)
    if lane == "balanced":
        if rule == "T050_AGREEMENT_ONLY":
            return _agreement_trust(row)
        if rule == "MARKET_HALF_ONLY":
            return _market_trust(row)
        if rule == "DUAL_TRUST":
            return _dual_trust(row)
    raise ValueError((lane, rule))


def _lane_key(core, row: Mapping[str, Any], lane: str, rule: str):
    trust = _lane_trust(row, lane, rule)
    q = _q(row)
    return (
        -float(trust if trust is not None else -99.0),
        -float(q if q is not None else -99.0),
        -_rel(core, row),
        -int(_odds(row) or -100000),
        _candidate_id(core, row),
    )


def _select_lane_block(core, rows: list[dict[str, Any]], lane: str, rule: str) -> dict[str, Any] | None:
    candidates = [r for r in _shop(core, rows) if _lane_eligible(r, lane)]
    candidates = [r for r in candidates if _lane_trust(r, lane, rule) is not None]
    if not candidates:
        return None
    r = dict(sorted(candidates, key=lambda x: _lane_key(core, x, lane, rule))[0])
    r["selector_trust"] = _lane_trust(r, lane, rule)
    r["market_trust"] = _market_trust(r)
    r["agreement_trust"] = _agreement_trust(r)
    r["dual_trust"] = _dual_trust(r)
    r["qb_xgb_abs_disagreement"] = _disagreement(r)
    return r


def _lane_phase(core, rows: list[dict[str, Any]], seasons: set[int], lane: str, rule: str):
    phase = [r for r in rows if int(r["season"]) in seasons]
    blocks = _group(phase)
    out: dict[str, dict[str, Any]] = {}
    for block in sorted(blocks, key=_block_key):
        r = _select_lane_block(core, blocks[block], lane, rule)
        if r is not None:
            out[block] = r
    return out, len(blocks)


def _settlement(row: Mapping[str, Any]) -> str:
    return str(row.get("settlement") or "")


def _longest_losing_streak(rows: list[Mapping[str, Any]]) -> int:
    longest = cur = 0
    for r in sorted(rows, key=lambda x: (_block_key(str(x["block"])), str(x.get("game_id")))):
        if _settlement(r) == "LOSS":
            cur += 1
            longest = max(longest, cur)
        elif _settlement(r) == "WIN":
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
    def avg(key: str):
        vals = [_finite(r.get(key)) for r in rows]
        vals = [x for x in vals if x is not None]
        return None if not vals else float(mean(vals))
    return {
        "plays": len(rows),
        "coverage": None if total_blocks == 0 else len(rows) / total_blocks,
        "total_blocks": total_blocks,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if denom == 0 else wins / denom,
        "roi": None if not profits else float(mean(profits)),
        "avg_odds": None if not rows else float(mean(int(r["american_odds"]) for r in rows)),
        "avg_model_q": avg("model_confidence_probability"),
        "avg_selector_trust": avg("selector_trust"),
        "avg_market_trust": avg("market_trust"),
        "avg_agreement_trust": avg("agreement_trust"),
        "avg_dual_trust": avg("dual_trust"),
        "avg_ml_disagreement": avg("qb_xgb_abs_disagreement"),
        "avg_model_price_gap": avg("model_price_gap"),
        "max_losing_streak": _longest_losing_streak(rows),
        "market_mix": {m: sum(str(r.get("market_type")) == m for r in rows) for m in ("moneyline", "spread", "total")},
    }


def _confidence_buckets(selected: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    specs = [("52_60", .52, .60), ("60_70", .60, .70), ("70_80", .70, .80), ("80_plus", .80, 1.01)]
    out = {}
    rows = list(selected.values())
    for name, lo, hi in specs:
        rr = [r for r in rows if _q(r) is not None and lo <= float(_q(r)) < hi]
        w = sum(_settlement(r) == "WIN" for r in rr)
        l = sum(_settlement(r) == "LOSS" for r in rr)
        out[name] = {
            "n": len(rr),
            "avg_q": None if not rr else float(mean(float(_q(r)) for r in rr)),
            "avg_trust": None if not rr else float(mean(float(r["selector_trust"]) for r in rr)),
            "hit_rate_nonpush": None if w + l == 0 else w / (w + l),
        }
    return out


def _overlap(core, rows: list[dict[str, Any]], seasons: set[int], lane: str, selected: Mapping[str, Mapping[str, Any]]):
    blocks = _group([r for r in rows if int(r["season"]) in seasons])
    model_n = model_hit = pin_n = pin_hit = 0
    for block, choice in selected.items():
        cand = [r for r in _shop(core, blocks[block]) if _lane_eligible(r, lane)]
        if not cand:
            continue
        model = sorted(cand, key=lambda r: (-float(_q(r) or -99.0), _candidate_id(core, r)))[0]
        model_n += 1
        model_hit += _candidate_id(core, model) == _candidate_id(core, choice)
        ml = [r for r in cand if str(r.get("market_type")) == "moneyline" and _finite(r.get("pinnacle_anchor_probability")) is not None]
        if str(choice.get("market_type")) == "moneyline" and ml:
            pin = sorted(ml, key=lambda r: (-float(r["pinnacle_anchor_probability"]), _candidate_id(core, r)))[0]
            pin_n += 1
            pin_hit += _candidate_id(core, pin) == _candidate_id(core, choice)
    return {
        "model_rank1_n": model_hit,
        "model_rank1_den": model_n,
        "model_rank1_overlap": None if model_n == 0 else model_hit / model_n,
        "pinnacle_rank1_n": pin_hit,
        "pinnacle_rank1_den": pin_n,
        "pinnacle_rank1_overlap": None if pin_n == 0 else pin_hit / pin_n,
    }


def _lane_report(core, rows: list[dict[str, Any]], seasons: set[int], lane: str, primary_rule: str, comparators: list[str]):
    primary, total = _lane_phase(core, rows, seasons, lane, primary_rule)
    report = {
        "primary_rule": primary_rule,
        "primary": _summary(primary, total),
        "confidence_buckets": _confidence_buckets(primary),
        "overlap": _overlap(core, rows, seasons, lane, primary),
        "comparators": {},
    }
    for rule in comparators:
        selected, total2 = _lane_phase(core, rows, seasons, lane, rule)
        if total2 != total or set(selected) != set(primary):
            raise RuntimeError(f"coverage parity failed {lane} {primary_rule} vs {rule} {sorted(seasons)}")
        s = _summary(selected, total)
        p = report["primary"]
        report["comparators"][rule] = {
            "summary": s,
            "changed_blocks": sum(_candidate_id(core, selected[b]) != _candidate_id(core, primary[b]) for b in primary),
            "hit_delta_primary_minus_comparator_pp": None if p["hit_rate_nonpush"] is None or s["hit_rate_nonpush"] is None else 100.0 * (float(p["hit_rate_nonpush"]) - float(s["hit_rate_nonpush"])),
            "roi_delta_primary_minus_comparator_pp": None if p["roi"] is None or s["roi"] is None else 100.0 * (float(p["roi"]) - float(s["roi"])),
        }
    return report, primary


def _tags(row: Mapping[str, Any]) -> set[str]:
    return {x for x in str(row.get("model_candidate_regions") or "").split(";") if x}


def _strict_value_common(row: Mapping[str, Any]) -> bool:
    ev = _finite(row.get("expected_value"))
    return (
        _common(row)
        and bool(_tags(row))
        and ev is not None and ev > 0.0
        and str(row.get("price_status")) == "VALUE"
        and _within(row, VALUE_ODDS)
    )


def _ml_frontier(core, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = []
    for r in _shop(core, rows):
        gap = _finite(r.get("model_price_gap"))
        edge = _finite(r.get("evaluated_edge_probability"))
        if (
            _strict_value_common(r)
            and str(r.get("market_type")) == "moneyline"
            and bool(_tags(r).intersection(ML_REGIONS))
            and gap is not None and gap > 0.0
            and edge is not None
        ):
            candidates.append(r)
    if not candidates:
        return None
    return dict(sorted(candidates, key=lambda r: (
        -float(r["model_price_gap"]),
        -float(r["model_confidence_probability"]),
        -float(r["evaluated_edge_probability"]),
        -_rel(core, r),
        -int(_odds(r) or -100000),
        _candidate_id(core, r),
    ))[0])


def _spread_frontier(core, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = []
    for r in _shop(core, rows):
        margin = _finite(r.get("model_cover_margin_v3"))
        edge = _finite(r.get("evaluated_edge_probability"))
        if (
            _strict_value_common(r)
            and str(r.get("market_type")) == "spread"
            and SPREAD_REGION in _tags(r)
            and margin is not None and margin > 0.0
            and edge is not None
        ):
            candidates.append(r)
    if not candidates:
        return None
    return dict(sorted(candidates, key=lambda r: (
        -float(r["model_cover_margin_v3"]),
        -float(r["evaluated_edge_probability"]),
        -_rel(core, r),
        -int(_odds(r) or -100000),
        _candidate_id(core, r),
    ))[0])


def _trust(observations: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(observations)
    if n == 0:
        return {"n": 0, "predicted_edge_sum": 0.0, "realized_edge_sum": 0.0, "data_trust": None, "trust": RESET_TRUST}
    pred = sum(float(o["predicted_edge"]) for o in observations)
    realized = sum(float(o["realized_edge"]) for o in observations)
    data = 0.0 if pred <= 0 else min(1.0, max(0.0, realized / pred))
    trust = (PSEUDO_N * RESET_TRUST + n * data) / (PSEUDO_N + n)
    return {"n": n, "predicted_edge_sum": pred, "realized_edge_sum": realized, "data_trust": data, "trust": trust}


def _state(state: Mapping[str, Any]) -> str:
    n = int(state["n"])
    trust = float(state["trust"])
    if n >= RED_MIN_N and trust < RED_TRUST:
        return "RED"
    if n >= AMBER_MIN_N and trust < AMBER_TRUST:
        return "AMBER"
    return "GREEN"


def _ml_dynamic_edge(ml: Mapping[str, Any], trust: float) -> float:
    return min(float(ml["model_price_gap"]) * float(trust), float(ml["evaluated_edge_probability"]))


def _spread_dynamic_edge(spread: Mapping[str, Any]) -> float:
    return float(spread["evaluated_edge_probability"])


def _cross_market(core, ml: dict[str, Any] | None, spread: dict[str, Any] | None, trust: float) -> dict[str, Any] | None:
    if ml is None:
        return None if spread is None else dict(spread)
    if spread is None:
        return dict(ml)
    ml_edge = _ml_dynamic_edge(ml, trust)
    sp_edge = _spread_dynamic_edge(spread)
    candidates = [
        (ml_edge, ml),
        (sp_edge, spread),
    ]
    _, r = sorted(candidates, key=lambda x: (
        -float(x[0]),
        -_rel(core, x[1]),
        -int(_odds(x[1]) or -100000),
        _candidate_id(core, x[1]),
    ))[0]
    return dict(r)


def _value_observation(ml: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if ml is None or _settlement(ml) not in {"WIN", "LOSS"}:
        return None
    q = _q(ml)
    be = _finite(ml.get("break_even_probability"))
    if q is None or be is None:
        return None
    pred = q - be
    if pred <= 0.0:
        return None
    y = 1.0 if _settlement(ml) == "WIN" else 0.0
    return {
        "block": str(ml["block"]),
        "game_id": str(ml["game_id"]),
        "predicted_edge": pred,
        "realized_edge": y - be,
    }


def _value_summary(selected: Mapping[str, Mapping[str, Any]], total_blocks: int) -> dict[str, Any]:
    base = _summary(selected, total_blocks)
    base["avg_expected_value"] = None if not selected else float(mean(float(r["expected_value"]) for r in selected.values()))
    return base


def _value_run(core, rows: list[dict[str, Any]]) -> dict[str, Any]:
    blocks = _group(rows)
    prior: dict[int, list[dict[str, Any]]] = {}
    selected: dict[str, dict[str, dict[str, Any]]] = {v: {} for v in ("STATIC_FRONTIER", "FRONTIER_SHRINK", "FRONTIER_STATE_V3")}
    trajectory: list[dict[str, Any]] = []
    state_counts: dict[int, dict[str, int]] = {s: {"GREEN": 0, "AMBER": 0, "RED": 0} for s in ALL}
    displacements: dict[int, int] = {s: 0 for s in ALL}
    red_no_play: dict[int, int] = {s: 0 for s in ALL}
    reasons: dict[str, str] = {}

    for block in sorted(blocks, key=_block_key):
        season, week = _block_key(block)
        obs = prior.setdefault(season, [])
        trust_state = _trust(obs)
        status = _state(trust_state)
        state_counts[season][status] += 1
        trajectory.append({"block": block, "season": season, "week": week, "state": status, **trust_state})

        ml = _ml_frontier(core, blocks[block])
        spread = _spread_frontier(core, blocks[block])

        static = _cross_market(core, ml, spread, 1.0)
        shrink = _cross_market(core, ml, spread, float(trust_state["trust"]))
        if status == "RED":
            state_choice = None if spread is None else dict(spread)
            if state_choice is None:
                red_no_play[season] += 1
                reasons[block] = "ML_RED_NO_SPREAD_FRONTIER" if ml is not None else "NO_STRICT_VALUE_FRONTIER"
        elif status == "AMBER" and spread is not None:
            state_choice = dict(spread)
            if ml is not None and (shrink is None or str(shrink.get("market_type")) == "moneyline"):
                displacements[season] += 1
        else:
            state_choice = shrink

        for name, choice in (("STATIC_FRONTIER", static), ("FRONTIER_SHRINK", shrink), ("FRONTIER_STATE_V3", state_choice)):
            if choice is not None:
                selected[name][block] = dict(choice)

        if state_choice is None and block not in reasons:
            reasons[block] = "NO_STRICT_VALUE_FRONTIER"

        new_obs = _value_observation(ml)
        if new_obs is not None:
            obs.append(new_obs)

    by_period = {}
    for label, seasons in (("development", DEV), ("locked_diagnostic", DIAG), ("overall", ALL)):
        period_blocks = {b for b in blocks if _block_key(b)[0] in seasons}
        by_period[label] = {
            name: _value_summary({b: r for b, r in sel.items() if b in period_blocks}, len(period_blocks))
            for name, sel in selected.items()
        }

    by_season = {}
    crossings = {}
    for season in sorted(ALL):
        sb = {b for b in blocks if _block_key(b)[0] == season}
        by_season[str(season)] = {
            name: _value_summary({b: r for b, r in sel.items() if b in sb}, len(sb))
            for name, sel in selected.items()
        }
        tr = [r for r in trajectory if int(r["season"]) == season]
        amber = next((r for r in tr if r["state"] == "AMBER"), None)
        red = next((r for r in tr if r["state"] == "RED"), None)
        crossings[str(season)] = {
            "first_amber": None if amber is None else {"block": amber["block"], "n": amber["n"], "trust": amber["trust"]},
            "first_red": None if red is None else {"block": red["block"], "n": red["n"], "trust": red["trust"]},
        }

    return {
        "periods": by_period,
        "by_season": by_season,
        "state_counts_by_season": {str(k): v for k, v in state_counts.items()},
        "crossings": crossings,
        "amber_ml_to_spread_displacements_by_season": {str(k): v for k, v in displacements.items()},
        "red_no_play_by_season": {str(k): v for k, v in red_no_play.items()},
        "primary_no_play_reasons": {
            key: sum(v == key for v in reasons.values())
            for key in ("NO_STRICT_VALUE_FRONTIER", "ML_RED_NO_SPREAD_FRONTIER")
        },
        "trust_trajectory": trajectory,
        "selected": selected,
    }


def _write_rows(path: Path, hhr: Mapping[str, Mapping[str, Any]], bal: Mapping[str, Mapping[str, Any]], value: Mapping[str, Mapping[str, Any]]) -> None:
    rows = []
    for lane, selections in (("hhr", hhr), ("balanced", bal), ("value", value)):
        for block, r in selections.items():
            rows.append({
                "lane": lane,
                "block": block,
                "candidate_id": r.get("candidate_id"),
                "game_id": r.get("game_id"),
                "market_type": r.get("market_type"),
                "selected_side": r.get("selected_side"),
                "american_odds": r.get("american_odds"),
                "model_q": r.get("model_confidence_probability"),
                "selector_trust": r.get("selector_trust"),
                "expected_value": r.get("expected_value"),
                "settlement": r.get("settlement"),
                "realized_profit": r.get("realized_profit"),
                "model_candidate_regions": r.get("model_candidate_regions"),
            })
    df = pl.DataFrame(rows)
    if len(df):
        df.sort(["block", "lane", "candidate_id"], nulls_last=True).write_csv(path)
    else:
        path.write_text("\n")


def run(root: Path, v3_path: Path, discovery: Path, confirmation: Path, out: Path) -> None:
    core = _load(root / "scripts/task05g_model_confidence_v2_runner.py", "task05g_final_candidate_core")
    rows = pl.read_parquet(v3_path).to_dicts()
    seasons = {int(r["season"]) for r in rows}
    if seasons != ALL or SEALED in seasons:
        raise RuntimeError(f"unexpected/sealed V3 seasons: {sorted(seasons)}")

    led = pl.concat([
        pl.read_csv(discovery, infer_schema_length=10000),
        pl.read_csv(confirmation, infer_schema_length=10000),
    ], how="vertical_relaxed")
    ledger_seasons = {int(x) for x in led["season"].unique().to_list()}
    if ledger_seasons != ALL or SEALED in ledger_seasons:
        raise RuntimeError(f"unexpected/sealed provenance seasons: {sorted(ledger_seasons)}")
    registry = build_candidate_registry(led.to_dicts())
    enriched = enrich_board_rows(rows, registry)

    scorecard: dict[str, Any] = {
        "preregistration_commit": PREREG_COMMIT,
        "periods": {"development": sorted(DEV), "locked_diagnostic": sorted(DIAG), "overall": sorted(ALL), "sealed": [SEALED]},
        "constants": {
            "half": HALF,
            "reset_trust": RESET_TRUST,
            "pseudo_n": PSEUDO_N,
            "amber_min_n": AMBER_MIN_N,
            "amber_trust": AMBER_TRUST,
            "red_min_n": RED_MIN_N,
            "red_trust": RED_TRUST,
        },
        "hhr": {},
        "balanced": {},
        "value": {},
        "production_promotion_allowed": False,
    }

    primary_rows = {"hhr": {}, "balanced": {}}
    for label, seasons_set in (("development", DEV), ("locked_diagnostic", DIAG), ("overall", ALL)):
        hhr_report, hhr_selected = _lane_report(core, enriched, seasons_set, "hhr", "MARKET_HALF", ["RAW_Q"])
        bal_report, bal_selected = _lane_report(core, enriched, seasons_set, "balanced", "DUAL_TRUST", ["RAW_Q", "T050_AGREEMENT_ONLY", "MARKET_HALF_ONLY"])
        scorecard["hhr"][label] = hhr_report
        scorecard["balanced"][label] = bal_report
        if label == "overall":
            primary_rows["hhr"] = hhr_selected
            primary_rows["balanced"] = bal_selected

    value = _value_run(core, enriched)
    value_selected = value.pop("selected")
    scorecard["value"] = value

    for lane in ("hhr", "balanced"):
        for phase in ("development", "locked_diagnostic", "overall"):
            if scorecard[lane][phase]["primary"]["market_mix"]["total"] != 0:
                raise RuntimeError("total entered HHR/Balanced")
    for phase in ("development", "locked_diagnostic", "overall"):
        for variant in ("STATIC_FRONTIER", "FRONTIER_SHRINK", "FRONTIER_STATE_V3"):
            if scorecard["value"]["periods"][phase][variant]["market_mix"]["total"] != 0:
                raise RuntimeError("total entered Value")
    if HALF != 0.50 or RESET_TRUST != 0.50 or PSEUDO_N != 8 or AMBER_MIN_N != 3 or AMBER_TRUST != 0.50 or RED_MIN_N != 8 or RED_TRUST != 0.25:
        raise RuntimeError("frozen selector constants changed")

    out.mkdir(parents=True, exist_ok=True)
    (out / "task05g_final_selector_candidate_v1_scorecard.json").write_text(json.dumps(scorecard, indent=2, sort_keys=True, allow_nan=False) + "\n")
    _write_rows(out / "task05g_final_selector_candidate_v1_rows.csv", primary_rows["hhr"], primary_rows["balanced"], value_selected["FRONTIER_STATE_V3"])


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--v3-candidates", type=Path, required=True)
    p.add_argument("--discovery", type=Path, default=Path("reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv"))
    p.add_argument("--confirmation", type=Path, default=Path("reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv"))
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    run(a.root, a.v3_candidates, a.discovery, a.confirmation, a.out)
