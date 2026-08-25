#!/usr/bin/env python3
"""Bounded final Task05G selector audit.

Implements docs/task05g_final_selector_bounded_audit_preregistration.md.
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
HHR_LAMBDA = 0.50
BAL_LAMBDA = 0.50
ARCHITECTURE_COMMIT = "0aec344d800d7c7ab3d9f76b1ff31975ddfd54cc"
PREREG_COMMIT = "79dda37f50136ea606da027256915f4931205e32"

REGION_NAMES = tuple(spec[0] for spec in REGION_SPECS)
ML_REGIONS = frozenset(name for name in REGION_NAMES if name.startswith("ML_"))
SPREAD_REGION = "SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4"
SCENARIOS = {
    "SPREAD_ONLY": frozenset({SPREAD_REGION}),
    "ALL_ML_FROZEN_REGIONS": ML_REGIONS,
    "ALL_FROZEN_REGIONS": frozenset(REGION_NAMES),
}


def _load_core(root: Path):
    path = root / "scripts/task05g_model_confidence_v2_runner.py"
    spec = importlib.util.spec_from_file_location("task05g_model_confidence_v2_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load Task05G V2 core")
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


def _candidate_id(core, row: Mapping[str, Any]) -> str:
    return str(core._candidate_id(row))


def _block_tuple(value: str) -> tuple[int, int]:
    season, week = str(value).split("-", 1)
    return int(season), int(week)


def _group_blocks(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(str(row["block"]), []).append(dict(row))
    return out


def _shop(core, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(r) for r in core.shop_exact_offers(list(rows))]


def _q(row: Mapping[str, Any]) -> float | None:
    return _finite(row.get("model_confidence_probability"))


def _odds(row: Mapping[str, Any]) -> int | None:
    value = row.get("american_odds")
    return None if value is None else int(value)


def _reliability_rank(row: Mapping[str, Any]) -> int:
    return {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(str(row.get("reliability") or "").upper(), 0)


def _common(row: Mapping[str, Any]) -> bool:
    return (
        bool(row.get("supported"))
        and bool(row.get("model_confidence_supported"))
        and int(row.get("model_confidence_support_n") or 0) >= MIN_N
        and str(row.get("market_type")) in {"moneyline", "spread"}
    )


def _within(row: Mapping[str, Any], bounds: tuple[int, int]) -> bool:
    odds = _odds(row)
    return odds is not None and bounds[0] <= odds <= bounds[1]


def _ml_disagreement(row: Mapping[str, Any]) -> float | None:
    if str(row.get("market_type")) != "moneyline":
        return None
    qb = _finite(row.get("raw_qbelo_probability_selected"))
    xgb = _finite(row.get("raw_xgb_probability_selected"))
    if qb is None or xgb is None:
        return None
    return abs(qb - xgb)


def _hhr_trust(row: Mapping[str, Any]) -> float | None:
    q = _q(row)
    if q is None:
        return None
    if str(row.get("market_type")) == "spread":
        return q
    pin = _finite(row.get("pinnacle_anchor_probability"))
    if pin is None:
        return None
    return q - HHR_LAMBDA * max(q - pin, 0.0)


def _balanced_trust(row: Mapping[str, Any]) -> float | None:
    q = _q(row)
    if q is None:
        return None
    if str(row.get("market_type")) == "spread":
        return q
    d = _ml_disagreement(row)
    if d is None:
        return None
    return q - BAL_LAMBDA * d


def _eligible_pretrust(row: Mapping[str, Any], lane: str) -> bool:
    q = _q(row)
    if not _common(row) or q is None:
        return False
    if lane == "hhr":
        return q >= HHR_MIN_Q and _within(row, HHR_ODDS)
    if lane == "balanced":
        return q >= BAL_MIN_Q and _within(row, BAL_ODDS)
    raise ValueError(lane)


def _trust(row: Mapping[str, Any], lane: str, rule: str) -> float | None:
    if rule == "RAW_Q":
        return _q(row)
    if lane == "hhr" and rule == "PRIMARY":
        return _hhr_trust(row)
    if lane == "balanced" and rule == "PRIMARY":
        return _balanced_trust(row)
    raise ValueError((lane, rule))


def _selection_key(core, row: Mapping[str, Any], lane: str, rule: str):
    trust = _trust(row, lane, rule)
    q = _q(row)
    odds = _odds(row)
    return (
        -float(trust if trust is not None else -99.0),
        -float(q if q is not None else -99.0),
        -_reliability_rank(row),
        -int(odds if odds is not None else -100000),
        _candidate_id(core, row),
    )


def _select_block(core, rows: list[dict[str, Any]], lane: str, rule: str) -> dict[str, Any] | None:
    candidates = [r for r in _shop(core, rows) if _eligible_pretrust(r, lane)]
    candidates = [r for r in candidates if _trust(r, lane, rule) is not None]
    if not candidates:
        return None
    selected = dict(sorted(candidates, key=lambda r: _selection_key(core, r, lane, rule))[0])
    selected["selector_trust"] = _trust(selected, lane, rule)
    selected["qb_xgb_abs_disagreement"] = _ml_disagreement(selected)
    return selected


def _no_play_reason(core, rows: list[dict[str, Any]], lane: str) -> str | None:
    shopped = _shop(core, rows)
    common = [r for r in shopped if _common(r)]
    if not common:
        return "NO_SUPPORTED_MODEL_CONFIDENCE"
    floor = HHR_MIN_Q if lane == "hhr" else BAL_MIN_Q
    qrows = [r for r in common if _q(r) is not None and float(_q(r)) >= floor]
    if not qrows:
        return "NO_CANDIDATE_ABOVE_CONFIDENCE_FLOOR"
    bounds = HHR_ODDS if lane == "hhr" else BAL_ODDS
    priced = [r for r in qrows if _within(r, bounds)]
    if not priced:
        return "PRICE_OUTSIDE_PRODUCT_BAND"
    trusted = [r for r in priced if _trust(r, lane, "PRIMARY") is not None]
    if not trusted:
        return "NO_TRUST_COMPUTABLE_CANDIDATE"
    return None


def _select_phase(core, rows: list[dict[str, Any]], seasons: set[int], lane: str, rule: str):
    phase = [r for r in rows if int(r["season"]) in seasons]
    blocks = _group_blocks(phase)
    selected: dict[str, dict[str, Any]] = {}
    no_play: dict[str, str] = {}
    for block in sorted(blocks, key=_block_tuple):
        choice = _select_block(core, blocks[block], lane, rule)
        if choice is None:
            reason = _no_play_reason(core, blocks[block], lane)
            no_play[block] = reason or "NO_CANDIDATE_AFTER_SHOPPING"
        else:
            selected[block] = choice
    return selected, no_play, len(blocks)


def _settlement(row: Mapping[str, Any]) -> str:
    return str(row.get("settlement") or "")


def _summary(selected: Mapping[str, Mapping[str, Any]], total_blocks: int) -> dict[str, Any]:
    rows = list(selected.values())
    wins = sum(_settlement(r) == "WIN" for r in rows)
    losses = sum(_settlement(r) == "LOSS" for r in rows)
    pushes = sum(_settlement(r) == "PUSH" for r in rows)
    nonpush = wins + losses
    profits = [_finite(r.get("realized_profit")) for r in rows]
    profits = [x for x in profits if x is not None]
    qs = [_q(r) for r in rows]
    qs = [x for x in qs if x is not None]
    trusts = [_finite(r.get("selector_trust")) for r in rows]
    trusts = [x for x in trusts if x is not None]
    disagreements = [_ml_disagreement(r) for r in rows]
    disagreements = [x for x in disagreements if x is not None]
    gaps = [_finite(r.get("model_price_gap")) for r in rows]
    gaps = [x for x in gaps if x is not None]
    odds = [_odds(r) for r in rows]
    odds = [x for x in odds if x is not None]
    return {
        "play_blocks": len(rows),
        "total_blocks": total_blocks,
        "coverage": 0.0 if total_blocks == 0 else len(rows) / total_blocks,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if nonpush == 0 else wins / nonpush,
        "roi": None if not profits else float(mean(profits)),
        "avg_model_confidence": None if not qs else float(mean(qs)),
        "avg_selector_trust": None if not trusts else float(mean(trusts)),
        "avg_ml_disagreement": None if not disagreements else float(mean(disagreements)),
        "avg_model_price_gap": None if not gaps else float(mean(gaps)),
        "avg_odds": None if not odds else float(mean(odds)),
        "market_mix": {
            market: sum(str(r.get("market_type")) == market for r in rows)
            for market in ("moneyline", "spread", "total")
        },
    }


def _reason_counts(no_play: Mapping[str, str]) -> dict[str, int]:
    keys = [
        "NO_SUPPORTED_MODEL_CONFIDENCE",
        "NO_CANDIDATE_ABOVE_CONFIDENCE_FLOOR",
        "PRICE_OUTSIDE_PRODUCT_BAND",
        "NO_TRUST_COMPUTABLE_CANDIDATE",
        "NO_CANDIDATE_AFTER_SHOPPING",
    ]
    return {key: sum(reason == key for reason in no_play.values()) for key in keys}


def _changed(core, left: Mapping[str, Mapping[str, Any]], right: Mapping[str, Mapping[str, Any]]) -> int:
    return sum(
        _candidate_id(core, left[b]) != _candidate_id(core, right[b])
        for b in set(left).intersection(right)
    )


def _overlaps(core, rows: list[dict[str, Any]], seasons: set[int], lane: str, primary: Mapping[str, Mapping[str, Any]]):
    phase = [r for r in rows if int(r["season"]) in seasons]
    blocks = _group_blocks(phase)
    model_match = pin_match = model_den = pin_den = 0
    for block, selected in primary.items():
        candidates = [r for r in _shop(core, blocks[block]) if _eligible_pretrust(r, lane)]
        if not candidates:
            continue
        model = sorted(candidates, key=lambda r: (-float(_q(r) or -99.0), _candidate_id(core, r)))[0]
        model_den += 1
        model_match += _candidate_id(core, model) == _candidate_id(core, selected)
        ml = [r for r in candidates if str(r.get("market_type")) == "moneyline" and _finite(r.get("pinnacle_anchor_probability")) is not None]
        if str(selected.get("market_type")) == "moneyline" and ml:
            pin = sorted(ml, key=lambda r: (-float(r["pinnacle_anchor_probability"]), _candidate_id(core, r)))[0]
            pin_den += 1
            pin_match += _candidate_id(core, pin) == _candidate_id(core, selected)
    return {
        "model_rank1_overlap_n": model_match,
        "model_rank1_overlap_den": model_den,
        "model_rank1_overlap": None if model_den == 0 else model_match / model_den,
        "pinnacle_rank1_overlap_n": pin_match,
        "pinnacle_rank1_overlap_den": pin_den,
        "pinnacle_rank1_overlap": None if pin_den == 0 else pin_match / pin_den,
    }


def _confidence_buckets(selected: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    specs = [
        ("52_60", 0.52, 0.60),
        ("60_70", 0.60, 0.70),
        ("70_80", 0.70, 0.80),
        ("80_plus", 0.80, 1.01),
    ]
    output: dict[str, Any] = {}
    rows = list(selected.values())
    for name, lo, hi in specs:
        material = [r for r in rows if _q(r) is not None and lo <= float(_q(r)) < hi]
        wins = sum(_settlement(r) == "WIN" for r in material)
        losses = sum(_settlement(r) == "LOSS" for r in material)
        denom = wins + losses
        output[name] = {
            "n": len(material),
            "avg_q": None if not material else float(mean(float(_q(r)) for r in material)),
            "hit_rate_nonpush": None if denom == 0 else wins / denom,
        }
    return output


def _lane_report(core, rows: list[dict[str, Any]], seasons: set[int], lane: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    primary, no_play, total = _select_phase(core, rows, seasons, lane, "PRIMARY")
    raw, raw_no_play, raw_total = _select_phase(core, rows, seasons, lane, "RAW_Q")
    if total != raw_total or set(primary) != set(raw):
        raise RuntimeError(f"ranking-only coverage parity failed for {lane} {sorted(seasons)}")
    primary_summary = _summary(primary, total)
    raw_summary = _summary(raw, total)
    report = {
        "primary": primary_summary,
        "raw_q": raw_summary,
        "coverage_parity": set(primary) == set(raw),
        "changed_blocks": _changed(core, primary, raw),
        "hit_rate_delta_pp": None
        if primary_summary["hit_rate_nonpush"] is None or raw_summary["hit_rate_nonpush"] is None
        else 100.0 * (float(primary_summary["hit_rate_nonpush"]) - float(raw_summary["hit_rate_nonpush"])),
        "roi_delta_pp": None
        if primary_summary["roi"] is None or raw_summary["roi"] is None
        else 100.0 * (float(primary_summary["roi"]) - float(raw_summary["roi"])),
        "no_play_reasons": _reason_counts(no_play),
        "raw_no_play_reasons": _reason_counts(raw_no_play),
        "overlap": _overlaps(core, rows, seasons, lane, primary),
        "confidence_buckets": _confidence_buckets(primary),
    }
    detail: list[dict[str, Any]] = []
    for block in sorted(set(primary) | set(no_play), key=_block_tuple):
        p = primary.get(block)
        r = raw.get(block)
        detail.append(
            {
                "phase": "development" if seasons == DEV else "locked_diagnostic" if seasons == DIAG else "overall",
                "lane": lane,
                "block": block,
                "no_play_reason": no_play.get(block),
                "primary_candidate_id": None if p is None else _candidate_id(core, p),
                "raw_q_candidate_id": None if r is None else _candidate_id(core, r),
                "changed": bool(p is not None and r is not None and _candidate_id(core, p) != _candidate_id(core, r)),
                "market_type": None if p is None else p.get("market_type"),
                "american_odds": None if p is None else p.get("american_odds"),
                "model_confidence": None if p is None else p.get("model_confidence_probability"),
                "selector_trust": None if p is None else p.get("selector_trust"),
                "pinnacle_anchor_probability": None if p is None else p.get("pinnacle_anchor_probability"),
                "ml_disagreement": None if p is None else _ml_disagreement(p),
                "expected_value_reporting_only": None if p is None else p.get("expected_value"),
                "price_status_reporting_only": None if p is None else p.get("price_status"),
                "settlement": None if p is None else p.get("settlement"),
                "realized_profit": None if p is None else p.get("realized_profit"),
            }
        )
    return report, detail


def _region_tags(row: Mapping[str, Any]) -> set[str]:
    return {x for x in str(row.get("model_candidate_regions") or "").split(";") if x}


def _strict_value(row: Mapping[str, Any]) -> bool:
    ev = _finite(row.get("expected_value"))
    return (
        _common(row)
        and bool(_region_tags(row))
        and ev is not None
        and ev > 0.0
        and str(row.get("price_status")) == "VALUE"
        and _within(row, VALUE_ODDS)
        and _finite(row.get("model_price_gap")) is not None
        and _finite(row.get("evaluated_edge_probability")) is not None
    )


def _value_metric(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(_settlement(r) == "WIN" for r in rows)
    losses = sum(_settlement(r) == "LOSS" for r in rows)
    denom = wins + losses
    def avg(key: str):
        vals = [_finite(r.get(key)) for r in rows]
        vals = [x for x in vals if x is not None]
        return None if not vals else float(mean(vals))
    profits = [_finite(r.get("realized_profit")) for r in rows]
    profits = [x for x in profits if x is not None]
    return {
        "plays": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": sum(_settlement(r) == "PUSH" for r in rows),
        "hit_rate_nonpush": None if denom == 0 else wins / denom,
        "roi": None if not profits else float(mean(profits)),
        "avg_expected_value": avg("expected_value"),
        "avg_model_confidence": avg("model_confidence_probability"),
        "avg_model_price_gap": avg("model_price_gap"),
        "avg_evaluated_edge": avg("evaluated_edge_probability"),
    }


def _value_region_report(core, rows: list[dict[str, Any]]) -> dict[str, Any]:
    shopped: list[dict[str, Any]] = []
    for _, block_rows in sorted(_group_blocks(rows).items(), key=lambda kv: _block_tuple(kv[0])):
        shopped.extend(_shop(core, block_rows))
    strict = [r for r in shopped if _strict_value(r)]
    output: dict[str, Any] = {}
    for region in REGION_NAMES:
        rr = [r for r in strict if region in _region_tags(r)]
        output[region] = {
            "development": _value_metric([r for r in rr if int(r["season"]) in DEV]),
            "locked_diagnostic": _value_metric([r for r in rr if int(r["season"]) in DIAG]),
            "overall": _value_metric(rr),
        }
    return output


def _consensus_edge(row: Mapping[str, Any]) -> float:
    return min(float(row["model_price_gap"]), float(row["evaluated_edge_probability"]))


def _value_key(core, row: Mapping[str, Any]):
    return (
        -_consensus_edge(row),
        -float(_q(row) or -99.0),
        -_reliability_rank(row),
        -int(_odds(row) or -100000),
        _candidate_id(core, row),
    )


def _scenario_select(core, rows: list[dict[str, Any]], seasons: set[int], allowed: frozenset[str]):
    phase = [r for r in rows if int(r["season"]) in seasons]
    selected: dict[str, dict[str, Any]] = {}
    for block, block_rows in sorted(_group_blocks(phase).items(), key=lambda kv: _block_tuple(kv[0])):
        candidates = [
            r for r in _shop(core, block_rows)
            if _strict_value(r) and bool(_region_tags(r).intersection(allowed))
        ]
        if candidates:
            choice = dict(sorted(candidates, key=lambda r: _value_key(core, r))[0])
            choice["consensus_edge"] = _consensus_edge(choice)
            selected[block] = choice
    return selected, len(_group_blocks(phase))


def _scenario_report(core, rows: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for name, allowed in SCENARIOS.items():
        output[name] = {}
        for label, seasons in (("development", DEV), ("locked_diagnostic", DIAG), ("overall", ALL)):
            selected, total = _scenario_select(core, rows, seasons, allowed)
            s = _summary(selected, total)
            s["strict_value_blocks"] = len(selected)
            output[name][label] = s
    return output


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n")
        return
    pl.DataFrame(rows).sort(["phase", "lane", "block"], nulls_last=True).write_csv(path)


def run(root: Path, v3_path: Path, discovery: Path, confirmation: Path, out: Path) -> None:
    core = _load_core(root)
    rows = pl.read_parquet(v3_path).to_dicts()
    seasons = {int(r["season"]) for r in rows}
    if seasons != ALL or SEALED in seasons:
        raise RuntimeError(f"2025 firewall / unexpected V3 seasons: {sorted(seasons)}")

    led = pl.concat(
        [
            pl.read_csv(discovery, infer_schema_length=10000),
            pl.read_csv(confirmation, infer_schema_length=10000),
        ],
        how="vertical_relaxed",
    )
    ledger_seasons = {int(x) for x in led["season"].unique().to_list()}
    if ledger_seasons != ALL or SEALED in ledger_seasons:
        raise RuntimeError(f"2025 firewall / unexpected Task05E seasons: {sorted(ledger_seasons)}")
    registry = build_candidate_registry(led.to_dicts())
    enriched = enrich_board_rows(rows, registry)

    scorecard: dict[str, Any] = {
        "architecture_commit": ARCHITECTURE_COMMIT,
        "preregistration_commit": PREREG_COMMIT,
        "periods": {
            "development": sorted(DEV),
            "locked_diagnostic": sorted(DIAG),
            "overall": sorted(ALL),
            "sealed": [SEALED],
        },
        "coefficients": {"hhr_half_shrink": HHR_LAMBDA, "balanced_t050": BAL_LAMBDA},
        "protocol": {
            "hhr": {"min_q": HHR_MIN_Q, "odds": list(HHR_ODDS), "ev_status_used": False},
            "balanced": {"min_q": BAL_MIN_Q, "odds": list(BAL_ODDS), "ev_status_used": False},
            "value": {"odds": list(VALUE_ODDS), "strict_positive_ev": True},
        },
        "lanes": {},
        "value_regions": _value_region_report(core, enriched),
        "value_scenarios": _scenario_report(core, enriched),
        "production_promotion_allowed": False,
    }

    details: list[dict[str, Any]] = []
    for lane in ("hhr", "balanced"):
        scorecard["lanes"][lane] = {}
        for label, seasons_set in (("development", DEV), ("locked_diagnostic", DIAG), ("overall", ALL)):
            report, detail = _lane_report(core, enriched, seasons_set, lane)
            scorecard["lanes"][lane][label] = report
            details.extend(detail)

    if any(
        summary["primary"]["market_mix"].get("total", 0) != 0
        for lane in scorecard["lanes"].values()
        for summary in lane.values()
    ):
        raise RuntimeError("totals entered HHR/Balanced headline selections")
    if HHR_LAMBDA != 0.50 or BAL_LAMBDA != 0.50:
        raise RuntimeError("frozen selector coefficient changed")

    out.mkdir(parents=True, exist_ok=True)
    (out / "task05g_final_selector_bounded_audit.json").write_text(
        json.dumps(scorecard, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    _write_csv(out / "task05g_final_selector_selected_rows.csv", details)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--v3-candidates", type=Path, required=True)
    parser.add_argument(
        "--discovery",
        type=Path,
        default=Path("reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv"),
    )
    parser.add_argument(
        "--confirmation",
        type=Path,
        default=Path("reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv"),
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.root, args.v3_candidates, args.discovery, args.confirmation, args.out)
