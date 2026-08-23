#!/usr/bin/env python3
"""Task05G preregistered selector sensitivity and validation diagnostics.

This script is diagnostic only. It evaluates the three Value threshold families
that were frozen in config before broad retrospective evaluation. It never
chooses a family based on ROI and never changes Task05F evaluator output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean
from typing import Any

import polars as pl

DEV = {2020, 2021, 2022, 2023, 2024}
SEALED = {2025}

FAMILIES = {
    "conservative": {"min_probability": 0.40, "max_odds": 200, "min_ev": 0.03},
    "frozen_primary": {"min_probability": 0.35, "max_odds": 250, "min_ev": 0.02},
    "permissive": {"min_probability": 0.30, "max_odds": 300, "min_ev": 0.015},
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _candidate_id(row: dict[str, Any]) -> str:
    return "|".join([str(row["game_id"]), str(row["market_type"]), str(row["selected_side"])])


def _rank(row: dict[str, Any]) -> tuple[Any, ...]:
    reliability_rank = 2 if row.get("reliability") == "HIGH" else 1
    return (
        -float(row["expected_value"]),
        -float(row["evaluated_edge_probability"]),
        -reliability_rank,
        -float(row["actionable_probability"]),
        _candidate_id(row),
    )


def _eligible(row: dict[str, Any], family: dict[str, float]) -> bool:
    return bool(
        row.get("supported")
        and row.get("reliability") in {"HIGH", "MEDIUM"}
        and row.get("price_status") == "VALUE"
        and row.get("actionable_probability") is not None
        and float(row["actionable_probability"]) >= family["min_probability"]
        and row.get("american_odds") is not None
        and -180 <= int(row["american_odds"]) <= int(family["max_odds"])
        and row.get("expected_value") is not None
        and float(row["expected_value"]) >= family["min_ev"]
        and row.get("support_n") is not None
        and int(row["support_n"]) >= 256
        and row.get("support_distance") is not None
        and float(row["support_distance"]) <= 0.05
        and row.get("uncertainty") is not None
        and float(row["uncertainty"]) <= 0.045
    )


def _hit_rate(rows: list[dict[str, Any]]) -> float | None:
    decisions = [row for row in rows if row.get("settlement") in {"WIN", "LOSS"}]
    if not decisions:
        return None
    return sum(row["settlement"] == "WIN" for row in decisions) / len(decisions)


def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return None if not values else float(mean(values))


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "plays": len(rows),
        "weeks_with_play": len({str(row["block"]) for row in rows}),
        "market_mix": {
            market: sum(row.get("market_type") == market for row in rows)
            for market in ("moneyline", "spread", "total")
        },
        "average_american_odds": _avg(rows, "american_odds"),
        "average_probability": _avg(rows, "actionable_probability"),
        "average_ev": _avg(rows, "expected_value"),
        "hit_rate_nonpush": _hit_rate(rows),
        "roi_per_unit_risked": _avg(rows, "realized_profit"),
    }


def _season_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for season in sorted(DEV):
        rr = [row for row in rows if int(row["season"]) == season]
        output[str(season)] = _summary(rr)
    return output


def _select_family(board_rows: list[dict[str, Any]], family: dict[str, float]) -> list[dict[str, Any]]:
    blocks = sorted({str(row["block"]) for row in board_rows})
    selected: list[dict[str, Any]] = []
    for block in blocks:
        eligible = [row for row in board_rows if str(row["block"]) == block and _eligible(row, family)]
        if eligible:
            selected.append(sorted(eligible, key=_rank)[0])
    return selected


def _role_rows(selector_results: pl.DataFrame, role: str) -> list[dict[str, Any]]:
    return selector_results.filter((pl.col("role") == role) & (~pl.col("no_play"))).to_dicts()


def run(board_path: Path, selector_results_path: Path, out: Path) -> None:
    board = pl.read_parquet(board_path)
    seasons = {int(value) for value in board["season"].unique().to_list()}
    if seasons != DEV or seasons.intersection(SEALED):
        raise RuntimeError(f"Task05G sensitivity firewall: unexpected seasons {sorted(seasons)}")
    board_rows = board.to_dicts()

    family_report: dict[str, Any] = {}
    selected_by_family: dict[str, list[dict[str, Any]]] = {}
    for name, family in FAMILIES.items():
        selected = _select_family(board_rows, family)
        selected_by_family[name] = selected
        family_report[name] = {
            "thresholds": family,
            "overall": _summary(selected),
            "by_season": _season_summary(selected),
        }

    selector_results = pl.read_csv(selector_results_path)
    selected_seasons = {
        int(value)
        for value in selector_results.filter(~pl.col("no_play"))["season"].drop_nulls().unique().to_list()
    }
    if selected_seasons - DEV or selected_seasons.intersection(SEALED):
        raise RuntimeError(f"Task05G selector result firewall: unexpected seasons {sorted(selected_seasons)}")

    hit_rows = _role_rows(selector_results, "hit_rate")
    balanced_rows = _role_rows(selector_results, "balanced")
    value_rows = _role_rows(selector_results, "value")

    def active_season_rois(rows: list[dict[str, Any]]) -> list[float]:
        result: list[float] = []
        for season in sorted(DEV):
            rr = [row for row in rows if int(row["season"]) == season]
            roi = _avg(rr, "realized_profit")
            if roi is not None:
                result.append(float(roi))
        return result

    by_block_role: dict[str, dict[str, str]] = {}
    for row in hit_rows + balanced_rows + value_rows:
        by_block_role.setdefault(str(row["block"]), {})[str(row["role"])] = str(row["offer_id"])
    balanced_value_overlap = sum(
        roles.get("balanced") is not None
        and roles.get("balanced") == roles.get("value")
        for roles in by_block_role.values()
    )
    all_three_overlap = sum(
        len(roles) == 3 and len(set(roles.values())) == 1
        for roles in by_block_role.values()
    )

    hit_rois = active_season_rois(hit_rows)
    balanced_rois = active_season_rois(balanced_rows)
    value_rois = active_season_rois(value_rows)

    report = {
        "purpose": "preregistered_sensitivity_only_not_post_hoc_family_selection",
        "development_seasons": sorted(DEV),
        "sealed_seasons": sorted(SEALED),
        "inputs": {
            "historical_evaluator_board_sha256": _sha(board_path),
            "chronological_selector_results_sha256": _sha(selector_results_path),
        },
        "value_threshold_families": family_report,
        "primary_policy_validation": {
            "hit_rate_active_seasons": len(hit_rois),
            "hit_rate_positive_roi_seasons": sum(value > 0 for value in hit_rois),
            "balanced_active_seasons": len(balanced_rois),
            "balanced_negative_roi_seasons": sum(value < 0 for value in balanced_rois),
            "value_active_seasons": len(value_rois),
            "value_negative_roi_seasons": sum(value < 0 for value in value_rois),
            "balanced_value_same_offer_blocks": balanced_value_overlap,
            "all_three_same_offer_blocks": all_three_overlap,
            "value_all_active_seasons_negative": bool(value_rois) and all(value < 0 for value in value_rois),
        },
        "family_selection_performed": False,
    }
    _write(out, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", required=True)
    parser.add_argument("--selector-results", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    run(Path(args.board), Path(args.selector_results), Path(args.out))
