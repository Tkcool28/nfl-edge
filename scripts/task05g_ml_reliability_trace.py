#!/usr/bin/env python3
"""Read-only ML reliability-cause trace for frozen Task05E candidate families."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

import polars as pl

from nfl_edge.recommendation.policy import shop_exact_offers
from nfl_edge.recommendation.remediation_provenance_v1 import build_candidate_registry, enrich_board_rows
from nfl_edge.value.reliability import MIN_SUPPORT_MEDIUM, UNCERTAINTY_MEDIUM_MAX

DEV = {2020, 2021, 2022, 2023, 2024}


def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
    vals = [float(r[key]) for r in rows if r.get(key) is not None]
    return None if not vals else float(mean(vals))


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(str(r.get("settlement")) == "WIN" for r in rows)
    losses = sum(str(r.get("settlement")) == "LOSS" for r in rows)
    return {
        "n": len(rows), "wins": wins, "losses": losses,
        "hit_rate": None if wins + losses == 0 else wins / (wins + losses),
        "roi": _avg(rows, "realized_profit"),
        "avg_support_n": _avg(rows, "support_n"),
        "avg_uncertainty": _avg(rows, "uncertainty"),
        "avg_support_distance": _avg(rows, "support_distance"),
        "avg_constituent_gap": _avg(rows, "constituent_gap"),
        "avg_model_market_disagreement": _avg(rows, "model_market_disagreement"),
        "avg_raw_model_probability": _avg(rows, "raw_model_output"),
        "stable_fraction": None if not rows else sum(bool(r.get("reliability_stable")) for r in rows) / len(rows),
    }


def _state(path: Path) -> dict[str, dict[str, Any]]:
    return {str(x["block"]): x for x in (json.loads(line) for line in path.read_text().splitlines() if line.strip())}


def _model_probs(root: Path) -> dict[str, tuple[float | None, float | None]]:
    qb = (
        pl.read_parquet(root / "data/modeling/development_v1/qb_elo_predictions_2018_2024.parquet")
        .filter(pl.col("season").is_in(sorted(DEV)))
        .select(["game_id", pl.col("predicted_home_win_probability").alias("qb")])
    )
    xgb = (
        pl.read_parquet(root / "data/modeling/development_v1/chronology_corrected/xgboost_candidate_predictions_2018_2024.parquet")
        .filter((pl.col("season").is_in(sorted(DEV))) & (pl.col("candidate_id") == "conservative"))
        .with_columns(pl.when(pl.col("warmup")).then(None).otherwise(pl.col("prediction_probability")).alias("xgb"))
        .select(["game_id", "xgb"])
    )
    df = qb.join(xgb, on="game_id", how="left")
    return {str(r["game_id"]): (r.get("qb"), r.get("xgb")) for r in df.to_dicts()}


def _shop(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        blocks.setdefault(str(row["block"]), []).append(row)
    out: list[dict[str, Any]] = []
    for _, rr in sorted(blocks.items()):
        out.extend(dict(r) for r in shop_exact_offers(rr))
    return out


def _augment(rows: list[dict[str, Any]], probs: dict[str, tuple[float | None, float | None]], states: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for source in rows:
        r = dict(source)
        qb_home, xgb_home = probs.get(str(r.get("game_id")), (None, None))
        side = str(r.get("selected_side"))
        qb = None if qb_home is None else (float(qb_home) if side == "home" else 1.0 - float(qb_home))
        xgb = None if xgb_home is None else (float(xgb_home) if side == "home" else 1.0 - float(xgb_home))
        r["selected_qb_probability"] = qb
        r["selected_xgb_probability"] = xgb
        r["constituent_gap"] = None if qb is None or xgb is None else abs(qb - xgb)
        rel = states.get(str(r.get("block")), {}).get("reliability", {}).get("moneyline", {})
        r["reliability_stable"] = bool(rel.get("stable", False))
        r["reliability_history_support_n"] = rel.get("support_n")
        r["reliability_history_radius"] = rel.get("radius")
        # MEDIUM eligibility causes. LOW may fail one or several.
        r["fails_medium_support"] = int(r.get("support_n") or 0) < MIN_SUPPORT_MEDIUM
        r["fails_medium_stability"] = not bool(r["reliability_stable"])
        u = r.get("uncertainty")
        r["fails_medium_uncertainty"] = u is None or not (0.0 < float(u) <= UNCERTAINTY_MEDIUM_MAX)
        gap = r.get("constituent_gap")
        r["fails_medium_constituent_gap"] = gap is None or float(gap) > 0.15
        out.append(r)
    return out


def _reason_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ["fails_medium_support", "fails_medium_stability", "fails_medium_uncertainty", "fails_medium_constituent_gap"]
    return {
        key: {
            "count": sum(bool(r.get(key)) for r in rows),
            "rows": _summary([r for r in rows if bool(r.get(key))]),
        }
        for key in keys
    }


def _family(rows: list[dict[str, Any]], tag: str) -> dict[str, Any]:
    material = [r for r in rows if tag in str(r.get("model_candidate_regions") or "").split(";") and str(r.get("price_status")) == "VALUE"]
    tiers = sorted({str(r.get("reliability")) for r in material})
    by_tier = {tier: _summary([r for r in material if str(r.get("reliability")) == tier]) for tier in tiers}
    by_season = {
        str(s): {
            "all": _summary([r for r in material if int(r.get("season")) == s]),
            "by_reliability": {
                tier: _summary([r for r in material if int(r.get("season")) == s and str(r.get("reliability")) == tier])
                for tier in tiers
            },
        }
        for s in sorted(DEV)
    }
    low = [r for r in material if str(r.get("reliability")) == "LOW"]
    return {
        "all_value_rows": _summary(material),
        "by_reliability": by_tier,
        "by_season": by_season,
        "low_failure_reasons": _reason_summary(low),
    }


def run(root: Path, board_path: Path, state_path: Path, out: Path) -> None:
    board = pl.read_parquet(board_path)
    seasons = {int(x) for x in board["season"].unique().to_list()}
    if seasons != DEV:
        raise RuntimeError(f"unexpected seasons {sorted(seasons)}")
    disc = pl.read_csv(root / "reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv", infer_schema_length=10000)
    conf = pl.read_csv(root / "reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv", infer_schema_length=10000)
    ledgers = disc.to_dicts() + conf.to_dicts()
    if any(int(r["season"]) == 2025 for r in ledgers):
        raise RuntimeError("sealed 2025 entered candidate ledger")
    registry = build_candidate_registry(ledgers)
    enriched = enrich_board_rows(board.to_dicts(), registry)
    shopped = [r for r in _shop(enriched) if str(r.get("market_type")) == "moneyline" and bool(r.get("model_candidate"))]
    augmented = _augment(shopped, _model_probs(root), _state(state_path))
    result = {
        "purpose": "read-only ML reliability-cause trace",
        "development_seasons": sorted(DEV), "sealed_seasons": [2025],
        "medium_requirements": {"support_n_min": MIN_SUPPORT_MEDIUM, "uncertainty_max": UNCERTAINTY_MEDIUM_MAX, "constituent_gap_max": 0.15, "stable_required": True},
        "ML_DOG_VALUE_ZONE_AVG": _family(augmented, "ML_DOG_VALUE_ZONE_AVG"),
        "ML_DOG_VALUE_ZONE_CORROB": _family(augmented, "ML_DOG_VALUE_ZONE_CORROB"),
        "ML_AVG_DISAGREEMENT_AVG_0_2": _family(augmented, "ML_AVG_DISAGREEMENT_AVG_0_2"),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--board", required=True)
    p.add_argument("--state-by-block", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    run(Path(a.root), Path(a.board), Path(a.state_by_block), Path(a.out))
