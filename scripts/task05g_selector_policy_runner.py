#!/usr/bin/env python3
"""Chronological 2020-2024 Task05G selector/unit/risk-profile diagnostics."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean
from typing import Any

import polars as pl

from nfl_edge.recommendation.policy import (
    NO_BALANCED_PLAY,
    NO_HIT_RATE_PLAY,
    NO_VALUE_PLAY,
    RISK_PROFILES,
    cap_slate_stakes,
    dollar_stake,
    recommended_units,
    select_headlines,
)

ROOT = Path(__file__).resolve().parents[1]
DEV = {2020, 2021, 2022, 2023, 2024}
SEALED = {2025}
NO_PLAY = {NO_HIT_RATE_PLAY, NO_BALANCED_PLAY, NO_VALUE_PLAY}


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _avg(rows: list[dict], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return None if not values else float(mean(values))


def _roi(rows: list[dict]) -> float | None:
    return _avg(rows, "realized_profit")


def _hit_rate(rows: list[dict]) -> float | None:
    decisions = [row for row in rows if row.get("settlement") in {"WIN", "LOSS"}]
    if not decisions:
        return None
    return sum(row["settlement"] == "WIN" for row in decisions) / len(decisions)


def _market_mix(rows: list[dict]) -> dict[str, int]:
    return {market: sum(row.get("market_type") == market for row in rows) for market in ("moneyline", "spread", "total")}


def _rel_mix(rows: list[dict]) -> dict[str, int]:
    return {tier: sum(row.get("reliability") == tier for row in rows) for tier in ("HIGH", "MEDIUM", "LOW", "UNSUPPORTED")}


def _summary(rows: list[dict], total_blocks: int) -> dict[str, Any]:
    ranks = {"HIGH": 2.0, "MEDIUM": 1.0, "LOW": 0.0, "UNSUPPORTED": 0.0}
    return {
        "plays": len(rows),
        "weeks_with_play": len({str(row["block"]) for row in rows}),
        "weeks_no_play": total_blocks - len({str(row["block"]) for row in rows}),
        "market_mix": _market_mix(rows),
        "average_american_odds": _avg(rows, "american_odds"),
        "average_actionable_probability": _avg(rows, "actionable_probability"),
        "average_expected_value": _avg(rows, "expected_value"),
        "reliability_mix": _rel_mix(rows),
        "average_reliability_ordinal": None if not rows else float(mean(ranks.get(str(row.get("reliability")), 0.0) for row in rows)),
        "hit_rate_nonpush": _hit_rate(rows),
        "roi_per_unit_risked": _roi(rows),
        "push_rate": None if not rows else sum(row.get("settlement") == "PUSH" for row in rows) / len(rows),
    }


def _coverage_band(weeks: int) -> str:
    if weeks >= 9:
        return "STRONG"
    if weeks >= 6:
        return "ACCEPTABLE"
    if weeks >= 3:
        return "SPARSE_BUT_POTENTIALLY_USEFUL"
    return "NOT_READY_FOR_HEADLINE_PROMINENCE"


def _selected_row(role: str, selected: dict, block: str) -> dict[str, Any]:
    row = dict(selected)
    row["role"] = role
    row["block"] = str(block)
    row["recommended_units"] = recommended_units(row)
    row["no_play"] = False
    row["candidate_id"] = row.get("candidate_id") or "|".join(
        [str(row.get("game_id", "")), str(row.get("market_type", "")), str(row.get("selected_side", row.get("selection", "")))]
    )
    row["offer_id"] = row.get("offer_id") or "|".join(
        [
            row["candidate_id"],
            str(row.get("sportsbook", row.get("actionable_book", ""))),
            str(row.get("line", row.get("actionable_line"))),
            str(row.get("american_odds", row.get("actionable_price_american"))),
        ]
    )
    return row


def _season_stability(selected: dict[str, list[dict]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for role, rows in selected.items():
        output[role] = {}
        for season in sorted(DEV):
            rr = [row for row in rows if int(row["season"]) == season]
            output[role][str(season)] = {
                "plays": len(rr),
                "weeks_with_play": len({str(row["block"]) for row in rr}),
                "hit_rate_nonpush": _hit_rate(rr),
                "roi_per_unit_risked": _roi(rr),
                "average_probability": _avg(rr, "actionable_probability"),
                "average_ev": _avg(rr, "expected_value"),
                "market_mix": _market_mix(rr),
            }
    return output


def _unique_headline_wagers(selected: dict[str, list[dict]]) -> list[dict]:
    merged = sorted(
        [row for rows in selected.values() for row in rows],
        key=lambda row: (str(row["block"]), str(row["offer_id"]), str(row["role"])),
    )
    unique: dict[tuple[str, str], dict] = {}
    for row in merged:
        unique.setdefault((str(row["block"]), str(row["offer_id"])), row)
    return list(unique.values())


def _risk_simulation(wagers: list[dict], profile_name: str, starting_bankroll: float = 1000.0) -> dict[str, Any]:
    bankroll = float(starting_bankroll)
    peak = bankroll
    max_drawdown = 0.0
    total_risked = 0.0
    stakes: list[float] = []
    peak_exposure = 0.0
    losing_streak = 0
    worst_losing_streak = 0
    by_block: dict[str, list[dict]] = {}
    for row in wagers:
        by_block.setdefault(str(row["block"]), []).append(row)

    for block in sorted(by_block):
        block_rows = sorted(by_block[block], key=lambda row: str(row["offer_id"]))
        opening = bankroll
        proposed = [
            (str(row["offer_id"]), dollar_stake(opening, profile_name, float(row["recommended_units"])))
            for row in block_rows
        ]
        capped = cap_slate_stakes(opening, proposed)
        exposure = sum(capped.values())
        peak_exposure = max(peak_exposure, 0.0 if opening <= 0 else exposure / opening)
        block_profit = 0.0
        for row in block_rows:
            stake = float(capped[str(row["offer_id"])])
            stakes.append(stake)
            total_risked += stake
            block_profit += stake * float(row["realized_profit"])
            if row.get("settlement") == "LOSS":
                losing_streak += 1
                worst_losing_streak = max(worst_losing_streak, losing_streak)
            elif row.get("settlement") == "WIN":
                losing_streak = 0
        bankroll += block_profit
        peak = max(peak, bankroll)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - bankroll) / peak)

    return {
        "profile": profile_name,
        "starting_bankroll": starting_bankroll,
        "ending_bankroll": bankroll,
        "max_drawdown_pct": max_drawdown,
        "worst_losing_streak": worst_losing_streak,
        "peak_slate_exposure_pct": peak_exposure,
        "average_wager_size": None if not stakes else float(mean(stakes)),
        "total_risked": total_risked,
        "wagers": len(stakes),
    }


def run(task05f_dir: Path, out: Path) -> None:
    board_path = task05f_dir / "historical_evaluator_board.parquet"
    board = pl.read_parquet(board_path)
    seasons = {int(value) for value in board["season"].unique().to_list()}
    if seasons != DEV or seasons.intersection(SEALED):
        raise RuntimeError(f"Task05G 2025 firewall: unexpected seasons {sorted(seasons)}")
    rows = board.to_dicts()
    blocks = sorted({str(row["block"]) for row in rows})
    selected: dict[str, list[dict]] = {"hit_rate": [], "balanced": [], "value": []}
    result_rows: list[dict] = []

    for block in blocks:
        block_rows = [row for row in rows if str(row["block"]) == block]
        headlines = select_headlines(block_rows)
        for role in ("hit_rate", "balanced", "value"):
            choice = headlines[role]
            if isinstance(choice, str):
                result_rows.append({"block": block, "role": role, "no_play": True, "no_play_code": choice})
                continue
            packed = _selected_row(role, dict(choice), block)
            selected[role].append(packed)
            result_rows.append(packed)

    out.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(result_rows, infer_schema_length=None).write_csv(out / "chronological_selector_results.csv")

    diagnostics = {role: _summary(rows_for_role, len(blocks)) for role, rows_for_role in selected.items()}
    diagnostics["development_seasons"] = sorted(DEV)
    diagnostics["sealed_seasons"] = sorted(SEALED)
    diagnostics["chronological_blocks"] = len(blocks)
    _write_json(out / "selector_diagnostics.json", diagnostics)

    coverage = {
        role: {
            str(season): {
                "weeks_with_play": len({str(row["block"]) for row in rows_for_role if int(row["season"]) == season}),
                "interpretation": _coverage_band(len({str(row["block"]) for row in rows_for_role if int(row["season"]) == season})) if role == "value" else None,
            }
            for season in sorted(DEV)
        }
        for role, rows_for_role in selected.items()
    }
    _write_json(out / "coverage_report.json", coverage)
    _write_json(out / "season_stability_report.json", _season_stability(selected))

    unique_wagers = _unique_headline_wagers(selected)
    simulations = [_risk_simulation(unique_wagers, profile.name) for profile in RISK_PROFILES]
    _write_json(
        out / "unit_risk_profile_simulation.json",
        {
            "selector_identity_shared_across_profiles": True,
            "recommended_units_shared_across_profiles": True,
            "overlapping_headline_offer_counted_once": True,
            "profiles": simulations,
        },
    )

    longshots = [
        row for row in selected["value"]
        if int(row["american_odds"]) > 250 or float(row["actionable_probability"]) < 0.35
    ]
    _write_json(
        out / "longshot_behavior.json",
        {
            "selected_value_longshot_guardrail_violations": len(longshots),
            "guardrail": {"min_probability": 0.35, "max_positive_american_odds": 250, "min_ev": 0.02},
        },
    )

    artifact_names = [
        "chronological_selector_results.csv",
        "selector_diagnostics.json",
        "coverage_report.json",
        "season_stability_report.json",
        "unit_risk_profile_simulation.json",
        "longshot_behavior.json",
    ]
    _write_json(
        out / "artifact_hashes.json",
        {name: _sha(out / name) for name in artifact_names},
    )

    print(json.dumps(diagnostics, indent=2, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task05f-dir", required=True)
    parser.add_argument("--out", default=str(ROOT / "artifacts/task05g/policy_v1"))
    args = parser.parse_args()
    run(Path(args.task05f_dir), Path(args.out))
