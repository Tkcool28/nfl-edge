#!/usr/bin/env python3
"""Task05F preregistered weekly primary-card selector evaluation.

The runner first materializes the accepted common candidate table with outcomes
physically separated. It then freezes HIGH_HIT_RATE / BALANCED / VALUE picks for
each chronological slate using candidate rows only. Historical outcomes are
joined *after* selection solely for the preregistered 2020-2024 diagnostics.
2025 remains sealed.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

import polars as pl
import yaml

from nfl_edge.value.candidate_table import OUTCOME_FIELDS
from nfl_edge.value.selectors import PRIMARY_CARDS, select_primary_cards


ROOT = Path(__file__).resolve().parents[1]
DEV = [2020, 2021, 2022, 2023, 2024]
SEALED = {2025}
VERSION = "task05f_selectors_v1"
SELECTOR_CONFIG = ROOT / "config" / "task05f_selectors_v1_prereg.yaml"
IMPLEMENTATION_LOCK = ROOT / "config" / "task05f_selectors_v1_implementation_lock.yaml"
EVAL_LOCK = ROOT / "config" / "task05f_selectors_v1_historical_eval_lock.yaml"
CANDIDATE_CONFIG = ROOT / "config" / "task05f_candidate_table_v1.yaml"
CANDIDATE_RUNNER = ROOT / "scripts" / "task05f_candidate_table_v1_runner.py"


class SelectorEvaluationError(RuntimeError):
    pass


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_yaml(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    return yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()


def _json_write(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _logical_candidate_hash(rows: list[dict[str, Any]]) -> str:
    ordered = sorted(rows, key=lambda row: str(row["candidate_id"]))
    raw = json.dumps(ordered, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _normalize_settlement(value: Any) -> str:
    text = str(value).strip().upper()
    if text.endswith(".WIN") or text == "WIN":
        return "WIN"
    if text.endswith(".PUSH") or text == "PUSH":
        return "PUSH"
    if text.endswith(".LOSS") or text == "LOSS":
        return "LOSS"
    raise SelectorEvaluationError(f"unknown settlement {value!r}")


def _selector_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "plays": 0,
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "flat_realized_roi": None,
            "hit_rate_ex_push": None,
        }
    wins = sum(row["settlement"] == "WIN" for row in rows)
    losses = sum(row["settlement"] == "LOSS" for row in rows)
    pushes = sum(row["settlement"] == "PUSH" for row in rows)
    roi = float(sum(float(row["realized_profit"]) for row in rows) / len(rows))
    decisions = wins + losses
    return {
        "plays": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "flat_realized_roi": roi,
        "hit_rate_ex_push": None if decisions == 0 else float(wins / decisions),
    }


def _count_mix(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    values = sorted({str(row[field]) for row in rows})
    return {value: sum(str(row[field]) == value for row in rows) for value in values}


def run(root: Path, out: Path) -> None:
    root = root.resolve()
    selector_cfg, selector_sha = _read_yaml(SELECTOR_CONFIG)
    impl_cfg, impl_sha = _read_yaml(IMPLEMENTATION_LOCK)
    eval_cfg, eval_sha = _read_yaml(EVAL_LOCK)
    _, candidate_cfg_sha = _read_yaml(CANDIDATE_CONFIG)

    if selector_cfg["status"] != "PREREGISTERED_BEFORE_SELECTOR_HISTORICAL_SCORING":
        raise SelectorEvaluationError("selector preregistration status mismatch")
    if impl_cfg["status"] != "LOCKED_BEFORE_SELECTOR_HISTORICAL_SCORING":
        raise SelectorEvaluationError("selector implementation lock status mismatch")
    if eval_cfg["status"] != "LOCKED_BEFORE_SELECTOR_HISTORICAL_SCORING":
        raise SelectorEvaluationError("selector evaluation lock status mismatch")
    if set(int(x) for x in selector_cfg["sealed_seasons"]) != SEALED:
        raise SelectorEvaluationError("sealed-season selector contract mismatch")
    if eval_cfg["slate_definition"]["key"] != "block":
        raise SelectorEvaluationError("unexpected historical slate key")

    candidate_runner = _load_script("task05f_selector_candidate_runtime", CANDIDATE_RUNNER)
    with tempfile.TemporaryDirectory(prefix="task05f_selector_candidate_") as tmp:
        candidate_out = Path(tmp) / "candidate"
        candidate_runner.run(root, CANDIDATE_CONFIG, candidate_out)
        candidate_df = pl.read_parquet(candidate_out / "candidate_table.parquet")
        outcome_df = pl.read_parquet(candidate_out / "historical_outcomes.parquet")

        if OUTCOME_FIELDS.intersection(candidate_df.columns):
            raise SelectorEvaluationError("outcome field entered selector candidate table")
        seasons = sorted(int(x) for x in candidate_df["season"].unique().to_list())
        if seasons != DEV or set(seasons).intersection(SEALED):
            raise SelectorEvaluationError(f"unexpected selector seasons {seasons}")
        if candidate_df.height != 8448:
            raise SelectorEvaluationError(f"expected 8448 candidate rows, found {candidate_df.height}")
        if outcome_df.height != 8448:
            raise SelectorEvaluationError(f"expected 8448 outcome rows, found {outcome_df.height}")

        candidate_rows = candidate_df.to_dicts()
        candidate_hash_before = _logical_candidate_hash(candidate_rows)
        blocks = sorted({str(row["block"]) for row in candidate_rows})
        if any(not block or block == "None" for block in blocks):
            raise SelectorEvaluationError("candidate row missing chronological block")

        pick_records: list[dict[str, Any]] = []
        for block in blocks:
            slate = [row for row in candidate_rows if str(row["block"]) == block]
            slate_seasons = {int(row["season"]) for row in slate}
            slate_weeks = {str(row["week"]) for row in slate}
            if len(slate_seasons) != 1 or len(slate_weeks) != 1:
                raise SelectorEvaluationError(f"block {block} is not one season-week slate")
            season = next(iter(slate_seasons))
            week = next(iter(slate_weeks))
            picks = select_primary_cards(slate)
            for selector in PRIMARY_CARDS:
                pick = picks[selector]
                record: dict[str, Any] = {
                    "block": block,
                    "season": season,
                    "week": week,
                    "selector": selector,
                    "has_play": pick is not None,
                    "candidate_id": None if pick is None else str(pick["candidate_id"]),
                    "candidate": None if pick is None else pick,
                }
                pick_records.append(record)

        # Hard boundary: selections are fully materialized before outcomes are read
        # into any selector-specific data structure.
        candidate_hash_after = _logical_candidate_hash(candidate_rows)
        if candidate_hash_before != candidate_hash_after:
            raise SelectorEvaluationError("selector mutated candidate table")

        outcome_map: dict[str, dict[str, Any]] = {}
        for row in outcome_df.to_dicts():
            cid = str(row["candidate_id"])
            if cid in outcome_map:
                raise SelectorEvaluationError(f"duplicate outcome row {cid}")
            outcome_map[cid] = row

        outcome_records: list[dict[str, Any]] = []
        for record in pick_records:
            cid = record["candidate_id"]
            if cid is None:
                continue
            outcome = outcome_map.get(str(cid))
            if outcome is None:
                raise SelectorEvaluationError(f"missing historical outcome for selected {cid}")
            settlement = _normalize_settlement(outcome["settlement"])
            profit = float(outcome["realized_profit"])
            if not math.isfinite(profit):
                raise SelectorEvaluationError(f"non-finite realized profit for selected {cid}")
            outcome_records.append(
                {
                    "block": record["block"],
                    "season": record["season"],
                    "week": record["week"],
                    "selector": record["selector"],
                    "candidate_id": cid,
                    "settlement": settlement,
                    "realized_profit": profit,
                }
            )

        total_slates = len(blocks)
        metrics: dict[str, Any] = {}
        market_mix_rows: list[dict[str, Any]] = []
        reliability_mix_rows: list[dict[str, Any]] = []
        status_mix_rows: list[dict[str, Any]] = []
        per_season_rows: list[dict[str, Any]] = []

        for selector in PRIMARY_CARDS:
            selected = [
                record for record in pick_records
                if record["selector"] == selector and record["has_play"]
            ]
            outcomes = [row for row in outcome_records if row["selector"] == selector]
            if len(selected) != len(outcomes):
                raise SelectorEvaluationError(f"selection/outcome count mismatch for {selector}")
            selector_metric = _selector_metrics(outcomes)
            selector_metric["no_play_count"] = total_slates - len(selected)
            selector_metric["coverage"] = float(len(selected) / total_slates) if total_slates else None
            metrics[selector] = selector_metric

            selected_candidates = [record["candidate"] for record in selected]
            for value, count in _count_mix(selected_candidates, "market_type").items():
                market_mix_rows.append({"selector": selector, "market_type": value, "n": count})
            for value, count in _count_mix(selected_candidates, "reliability").items():
                reliability_mix_rows.append({"selector": selector, "reliability": value, "n": count})
            for value, count in _count_mix(selected_candidates, "price_status").items():
                status_mix_rows.append({"selector": selector, "price_status": value, "n": count})

            for season in DEV:
                season_blocks = {
                    record["block"] for record in pick_records if int(record["season"]) == season
                }
                season_selected = [record for record in selected if int(record["season"]) == season]
                season_outcomes = [row for row in outcomes if int(row["season"]) == season]
                season_metric = _selector_metrics(season_outcomes)
                per_season_rows.append(
                    {
                        "selector": selector,
                        "season": season,
                        "slates": len(season_blocks),
                        "plays": len(season_selected),
                        "coverage": (
                            None if not season_blocks else float(len(season_selected) / len(season_blocks))
                        ),
                        "flat_realized_roi": season_metric["flat_realized_roi"],
                        "hit_rate_ex_push": season_metric["hit_rate_ex_push"],
                        "wins": season_metric["wins"],
                        "losses": season_metric["losses"],
                        "pushes": season_metric["pushes"],
                    }
                )

        duplicate_slates = 0
        duplicate_denominator = 0
        duplicate_details: list[dict[str, Any]] = []
        for block in blocks:
            slate_picks = [
                record for record in pick_records if record["block"] == block and record["has_play"]
            ]
            if len(slate_picks) >= 2:
                duplicate_denominator += 1
                ids = [str(record["candidate_id"]) for record in slate_picks]
                is_duplicate = len(set(ids)) < len(ids)
                duplicate_slates += int(is_duplicate)
                if is_duplicate:
                    duplicate_details.append(
                        {
                            "block": block,
                            "selectors": {
                                record["selector"]: record["candidate_id"] for record in slate_picks
                            },
                        }
                    )
        duplicate_rate = (
            None
            if duplicate_denominator == 0
            else float(duplicate_slates / duplicate_denominator)
        )

        out.mkdir(parents=True, exist_ok=True)
        _json_write(out / "selector_picks.json", pick_records)
        pl.DataFrame(outcome_records, infer_schema_length=None).write_csv(
            out / "selected_outcomes.csv"
        )
        pl.DataFrame(market_mix_rows, infer_schema_length=None).write_csv(out / "market_mix.csv")
        pl.DataFrame(reliability_mix_rows, infer_schema_length=None).write_csv(
            out / "reliability_mix.csv"
        )
        pl.DataFrame(status_mix_rows, infer_schema_length=None).write_csv(out / "status_mix.csv")
        pl.DataFrame(per_season_rows, infer_schema_length=None).write_csv(out / "per_season.csv")
        _json_write(
            out / "duplicate_diagnostics.json",
            {
                "duplicate_card_slates": duplicate_slates,
                "denominator_slates_with_at_least_two_non_null_cards": duplicate_denominator,
                "duplicate_card_rate": duplicate_rate,
                "details": duplicate_details,
            },
        )
        _json_write(
            out / "candidate_reproduction.json",
            {
                "candidate_rows": len(candidate_rows),
                "candidate_logical_sha256_before_selection": candidate_hash_before,
                "candidate_logical_sha256_after_selection": candidate_hash_after,
                "candidate_rows_immutable": candidate_hash_before == candidate_hash_after,
                "candidate_table_outcome_fields": sorted(OUTCOME_FIELDS.intersection(candidate_df.columns)),
                "outcome_join_occurred_after_selection": True,
            },
        )
        _json_write(
            out / "scorecard.json",
            {
                "version": VERSION,
                "label": "OBSERVATIONAL_ONLY_NOT_TUNED",
                "development_seasons": DEV,
                "sealed_seasons": [2025],
                "total_slates": total_slates,
                "selectors": metrics,
                "duplicate_card_slates": duplicate_slates,
                "duplicate_card_rate": duplicate_rate,
                "selector_rules_may_change_after_results": False,
                "production_promotion": False,
            },
        )
        _json_write(
            out / "provenance.json",
            {
                "version": VERSION,
                "github_sha": os.environ.get("GITHUB_SHA"),
                "selector_prereg_sha256": selector_sha,
                "selector_implementation_lock_sha256": impl_sha,
                "selector_historical_eval_lock_sha256": eval_sha,
                "candidate_table_config_sha256": candidate_cfg_sha,
                "candidate_upstream_reproduction": json.loads(
                    (candidate_out / "reproduction.json").read_text()
                ),
                "slate_key": "block",
                "development_seasons": DEV,
                "sealed_seasons": [2025],
                "outcome_use": "POST_SELECTION_DIAGNOSTIC_ONLY",
                "new_observation_policy": "OBSERVATIONAL_ONLY_NOT_TUNED",
            },
        )

    print(
        json.dumps(
            {
                "version": VERSION,
                "total_slates": total_slates,
                "selectors": metrics,
                "duplicate_card_rate": duplicate_rate,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "task05f" / "selectors_v1"))
    args = parser.parse_args()
    run(ROOT, Path(args.out))
