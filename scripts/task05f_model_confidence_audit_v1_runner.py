#!/usr/bin/env python3
"""Task05F diagnostic audit: football-model confidence vs evaluator/selector filtering.

This runner is observational only. It freezes every compared choice before the
historical outcome sidecar is exposed and never changes model/evaluator/selector
or staking policy.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile
from typing import Any, Iterable

import polars as pl
import yaml

from nfl_edge.value.candidate_table import OUTCOME_FIELDS
from nfl_edge.value.selectors_v3_1 import select_primary_cards_v3_1

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/task05f_model_confidence_audit_v1.yaml"
CANDIDATE_CONFIG = ROOT / "config/task05f_candidate_table_v1.yaml"
CANDIDATE_RUNNER = ROOT / "scripts/task05f_candidate_table_v1_runner.py"
DEV = [2020, 2021, 2022, 2023, 2024]
SEALED = {2025}
BUCKETS = [(0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.01)]


class AuditError(RuntimeError):
    pass


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AuditError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_yaml(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    return yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()


def _json_write(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _normalize_settlement(value: Any) -> str:
    text = str(value).strip().upper()
    if text.endswith(".WIN") or text == "WIN":
        return "WIN"
    if text.endswith(".PUSH") or text == "PUSH":
        return "PUSH"
    if text.endswith(".LOSS") or text == "LOSS":
        return "LOSS"
    raise AuditError(f"unknown settlement {value!r}")


def _score_ids(ids: Iterable[str], outcomes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = [outcomes[cid] for cid in ids]
    wins = sum(_normalize_settlement(r["settlement"]) == "WIN" for r in rows)
    losses = sum(_normalize_settlement(r["settlement"]) == "LOSS" for r in rows)
    pushes = sum(_normalize_settlement(r["settlement"]) == "PUSH" for r in rows)
    denom = wins + losses
    return {
        "n": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_ex_push": None if denom == 0 else wins / denom,
    }


def _ml_raw_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        r for r in rows
        if str(r.get("market_type", "")).lower() == "moneyline"
        and _finite(r.get("raw_football_output"))
    ]


def _top_raw_ml(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = _ml_raw_rows(rows)
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda r: (-float(r["raw_football_output"]), str(r["candidate_id"])),
    )


def _hm(row: dict[str, Any]) -> bool:
    return bool(row.get("supported")) and str(row.get("reliability")) in {"HIGH", "MEDIUM"}


def _actionable(row: dict[str, Any]) -> bool:
    return _hm(row) and str(row.get("price_status")) in {"VALUE", "PLAYABLE"}


def _spread_cover_edge(row: dict[str, Any]) -> float | None:
    if str(row.get("market_type")) != "spread":
        return None
    if not _finite(row.get("raw_football_output")) or not _finite(row.get("actionable_line")):
        return None
    raw = float(row["raw_football_output"])
    line = float(row["actionable_line"])
    return raw + line if str(row.get("selection")) == "home" else -raw + line


def _bucket(p: float) -> str:
    for lo, hi in BUCKETS:
        if lo <= p < hi:
            return f"{lo:.2f}-{hi:.2f}"
    return "OUTSIDE"


def run(root: Path, config_path: Path, out: Path) -> None:
    root = root.resolve()
    if not config_path.is_absolute():
        config_path = (root / config_path).resolve()
    cfg, cfg_sha = _read_yaml(config_path)
    if cfg["status"] != "PREREGISTERED_BEFORE_MODEL_CONFIDENCE_AUDIT_EXECUTION":
        raise AuditError("audit preregistration status mismatch")
    if cfg["results_label"] != "OBSERVATIONAL_ONLY_NOT_TUNED":
        raise AuditError("audit label mismatch")

    candidate_runner = _load_script("task05f_confidence_candidate_runtime", CANDIDATE_RUNNER)
    with tempfile.TemporaryDirectory(prefix="task05f_confidence_") as tmp:
        candidate_out = Path(tmp) / "candidate"
        candidate_runner.run(root, CANDIDATE_CONFIG, candidate_out)
        cdf = pl.read_parquet(candidate_out / "candidate_table.parquet")
        odf = pl.read_parquet(candidate_out / "historical_outcomes.parquet")

        if cdf.height != 8448 or odf.height != 8448:
            raise AuditError("candidate fixture mismatch")
        if OUTCOME_FIELDS.intersection(cdf.columns):
            raise AuditError("outcome field entered candidate table")
        seasons = sorted(int(x) for x in cdf["season"].unique().to_list())
        if seasons != DEV or set(seasons).intersection(SEALED):
            raise AuditError(f"unexpected seasons {seasons}")

        rows = cdf.to_dicts()
        blocks = sorted({str(r["block"]) for r in rows})
        if len(blocks) != int(cfg["expected_slates"]):
            raise AuditError("slate count mismatch")

        # Freeze every current selector choice and every model-native comparison
        # BEFORE constructing the historical outcome lookup.
        current: dict[str, dict[str, dict[str, Any] | None]] = {}
        raw_top_slate: dict[str, dict[str, Any] | None] = {}
        hm_top_slate: dict[str, dict[str, Any] | None] = {}
        actionable_top_slate: dict[str, dict[str, Any] | None] = {}
        no_play_rows: list[dict[str, Any]] = []
        alignment_rows: list[dict[str, Any]] = []

        for block in blocks:
            slate = [r for r in rows if str(r["block"]) == block]
            picks = select_primary_cards_v3_1(slate)
            current[block] = picks
            raw_top_slate[block] = _top_raw_ml(slate)
            hm_top_slate[block] = _top_raw_ml([r for r in slate if _hm(r)])
            actionable_top_slate[block] = _top_raw_ml([r for r in slate if _actionable(r)])

            hhr = picks["HIGH_HIT_RATE"]
            if hhr is None:
                raw_top = raw_top_slate[block]
                hm_top = hm_top_slate[block]
                act_top = actionable_top_slate[block]
                available_actionable = [r for r in slate if _actionable(r)]
                used_ids = {
                    str(p["candidate_id"])
                    for p in (picks.get("VALUE"), picks.get("BALANCED"))
                    if p is not None
                }
                if act_top is not None and str(act_top["candidate_id"]) in used_ids:
                    reason = "DISTINCTNESS_CONFLICT_WITH_OTHER_FEATURED_CARD"
                elif act_top is not None:
                    reason = "ACTIONABLE_ROW_EXISTS_BUT_HHR_NONE_UNEXPECTED"
                elif hm_top is not None:
                    reason = f"TOP_HM_ML_PRICE_STATUS_{hm_top.get('price_status')}"
                elif raw_top is not None:
                    if not bool(raw_top.get("supported")):
                        reason = "RAW_ML_EVALUATOR_UNSUPPORTED"
                    else:
                        reason = f"RAW_ML_RELIABILITY_{raw_top.get('reliability')}"
                else:
                    reason = "NO_RAW_ML_MODEL_OUTPUT"
                no_play_rows.append({
                    "block": block,
                    "season": slate[0]["season"],
                    "week": slate[0]["week"],
                    "reason": reason,
                    "raw_top_candidate_id": None if raw_top is None else raw_top["candidate_id"],
                    "raw_top_probability": None if raw_top is None else raw_top["raw_football_output"],
                    "raw_top_reliability": None if raw_top is None else raw_top["reliability"],
                    "raw_top_price_status": None if raw_top is None else raw_top["price_status"],
                    "hm_top_candidate_id": None if hm_top is None else hm_top["candidate_id"],
                    "hm_top_probability": None if hm_top is None else hm_top["raw_football_output"],
                    "hm_top_price_status": None if hm_top is None else hm_top["price_status"],
                    "actionable_top_candidate_id": None if act_top is None else act_top["candidate_id"],
                    "actionable_top_probability": None if act_top is None else act_top["raw_football_output"],
                    "available_actionable_hm_rows": len(available_actionable),
                })

            for card in ("HIGH_HIT_RATE", "BALANCED"):
                pick = picks[card]
                if pick is None:
                    continue
                market = str(pick["market_type"])
                model_signal = None
                model_agrees = None
                if market == "moneyline" and _finite(pick.get("raw_football_output")):
                    model_signal = float(pick["raw_football_output"])
                    model_agrees = model_signal > 0.5
                elif market == "spread":
                    model_signal = _spread_cover_edge(pick)
                    model_agrees = None if model_signal is None else model_signal > 0.0
                alignment_rows.append({
                    "block": block,
                    "card": card,
                    "candidate_id": pick["candidate_id"],
                    "market_type": market,
                    "selection": pick["selection"],
                    "football_model_name": pick["football_model_name"],
                    "raw_model_signal": model_signal,
                    "model_agrees_with_selected_wager": model_agrees,
                    "evaluator_actionable_probability": pick["actionable_probability"],
                    "price_status": pick["price_status"],
                    "reliability": pick["reliability"],
                })

        # Freeze model-native favorite for every game, independent of price/evaluator.
        by_game: dict[str, list[dict[str, Any]]] = {}
        for r in _ml_raw_rows(rows):
            by_game.setdefault(str(r["game_id"]), []).append(r)
        raw_game_favorites = {
            gid: _top_raw_ml(game_rows) for gid, game_rows in by_game.items()
        }

        # Only now expose outcomes.
        outcomes: dict[str, dict[str, Any]] = {}
        for r in odf.to_dicts():
            cid = str(r["candidate_id"])
            if cid in outcomes:
                raise AuditError(f"duplicate outcome {cid}")
            outcomes[cid] = r

        raw_game_ids = [str(r["candidate_id"]) for r in raw_game_favorites.values() if r is not None]
        raw_game_score = _score_ids(raw_game_ids, outcomes)
        bucket_summary: dict[str, Any] = {}
        for lo, hi in BUCKETS:
            label = f"{lo:.2f}-{hi:.2f}"
            ids = [
                str(r["candidate_id"]) for r in raw_game_favorites.values()
                if r is not None and lo <= float(r["raw_football_output"]) < hi
            ]
            bucket_summary[label] = _score_ids(ids, outcomes)
            bucket_summary[label]["mean_raw_probability"] = (
                None if not ids else sum(
                    float(r["raw_football_output"]) for r in raw_game_favorites.values()
                    if r is not None and lo <= float(r["raw_football_output"]) < hi
                ) / len(ids)
            )

        def score_slate_map(mapping: dict[str, dict[str, Any] | None]) -> dict[str, Any]:
            chosen = [r for r in mapping.values() if r is not None]
            result = _score_ids([str(r["candidate_id"]) for r in chosen], outcomes)
            result["mean_raw_probability"] = None if not chosen else sum(float(r["raw_football_output"]) for r in chosen) / len(chosen)
            return result

        current_hhr = [p["HIGH_HIT_RATE"] for p in current.values() if p["HIGH_HIT_RATE"] is not None]
        hhr_ml = [r for r in current_hhr if r["market_type"] == "moneyline"]
        hhr_spread = [r for r in current_hhr if r["market_type"] == "spread"]
        hhr_ml_agree = [r for r in hhr_ml if _finite(r.get("raw_football_output")) and float(r["raw_football_output"]) > 0.5]
        hhr_ml_oppose = [r for r in hhr_ml if _finite(r.get("raw_football_output")) and float(r["raw_football_output"]) <= 0.5]
        hhr_spread_agree = [r for r in hhr_spread if (_spread_cover_edge(r) or 0.0) > 0.0]
        hhr_spread_oppose = [r for r in hhr_spread if (_spread_cover_edge(r) or 0.0) <= 0.0]

        balanced = [p["BALANCED"] for p in current.values() if p["BALANCED"] is not None]
        bal_ml = [r for r in balanced if r["market_type"] == "moneyline"]
        bal_spread = [r for r in balanced if r["market_type"] == "spread"]

        for row in no_play_rows:
            cid = row.get("raw_top_candidate_id")
            row["raw_top_settlement"] = None if not cid else _normalize_settlement(outcomes[str(cid)]["settlement"])
            p = row.get("raw_top_probability")
            row["raw_top_confidence_bucket"] = None if p is None else _bucket(float(p))
        for row in alignment_rows:
            row["settlement"] = _normalize_settlement(outcomes[str(row["candidate_id"])]["settlement"])

        no_play_reason_counts: dict[str, int] = {}
        for row in no_play_rows:
            no_play_reason_counts[row["reason"]] = no_play_reason_counts.get(row["reason"], 0) + 1
        no_play_buckets: dict[str, int] = {}
        for row in no_play_rows:
            b = row.get("raw_top_confidence_bucket") or "NONE"
            no_play_buckets[b] = no_play_buckets.get(b, 0) + 1

        summary = {
            "label": cfg["results_label"],
            "development_seasons": DEV,
            "sealed_seasons": sorted(SEALED),
            "slates": len(blocks),
            "candidate_rows": len(rows),
            "raw_exact_avg_every_game": {
                **raw_game_score,
                "confidence_buckets": bucket_summary,
            },
            "raw_exact_avg_top_per_slate": {
                "raw_model_available": score_slate_map(raw_top_slate),
                "high_medium_reliability": score_slate_map(hm_top_slate),
                "current_value_or_playable_high_medium": score_slate_map(actionable_top_slate),
            },
            "current_high_hit_rate": {
                "all": _score_ids([str(r["candidate_id"]) for r in current_hhr], outcomes),
                "moneyline": {
                    **_score_ids([str(r["candidate_id"]) for r in hhr_ml], outcomes),
                    "mean_raw_model_probability": None if not hhr_ml else sum(float(r["raw_football_output"]) for r in hhr_ml) / len(hhr_ml),
                    "mean_evaluator_probability": None if not hhr_ml else sum(float(r["actionable_probability"]) for r in hhr_ml) / len(hhr_ml),
                },
                "moneyline_model_agrees": _score_ids([str(r["candidate_id"]) for r in hhr_ml_agree], outcomes),
                "moneyline_model_opposes": _score_ids([str(r["candidate_id"]) for r in hhr_ml_oppose], outcomes),
                "spread": _score_ids([str(r["candidate_id"]) for r in hhr_spread], outcomes),
                "spread_model_cover_direction_agrees": _score_ids([str(r["candidate_id"]) for r in hhr_spread_agree], outcomes),
                "spread_model_cover_direction_opposes": _score_ids([str(r["candidate_id"]) for r in hhr_spread_oppose], outcomes),
            },
            "current_balanced": {
                "all": _score_ids([str(r["candidate_id"]) for r in balanced], outcomes),
                "moneyline": {
                    **_score_ids([str(r["candidate_id"]) for r in bal_ml], outcomes),
                    "mean_raw_model_probability": None if not bal_ml else sum(float(r["raw_football_output"]) for r in bal_ml) / len(bal_ml),
                    "mean_evaluator_probability": None if not bal_ml else sum(float(r["actionable_probability"]) for r in bal_ml) / len(bal_ml),
                },
                "spread": _score_ids([str(r["candidate_id"]) for r in bal_spread], outcomes),
            },
            "hhr_no_play": {
                "count": len(no_play_rows),
                "reason_counts": dict(sorted(no_play_reason_counts.items())),
                "raw_top_confidence_bucket_counts": dict(sorted(no_play_buckets.items())),
            },
            "warnings": {
                "expected_margin_60pct_is_straight_up_not_ats": True,
                "historical_results_are_observational_only_not_tuned": True,
            },
        }

        out.mkdir(parents=True, exist_ok=True)
        _json_write(out / "summary.json", summary)
        _json_write(out / "provenance.json", {
            "version": cfg["version"],
            "config_sha256": cfg_sha,
            "candidate_rows": len(rows),
            "selection_and_model_choices_frozen_before_outcome_join": True,
            "outcome_fields_in_candidate_table": [],
            "sealed_2025_loaded": False,
        })
        for name, data in (("no_play_audit.csv", no_play_rows), ("selected_alignment.csv", alignment_rows)):
            fields = sorted({k for row in data for k in row}) if data else []
            with (out / name).open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(data)
        print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.root, args.config, args.out)


if __name__ == "__main__":
    main()
