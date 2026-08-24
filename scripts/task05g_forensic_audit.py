#!/usr/bin/env python3
"""Read-only Task05G forensic audit over the sealed 2020-2024 development board."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any, Mapping

import polars as pl

from nfl_edge.recommendation.policy import (
    _balanced_eligible,
    _candidate_id,
    _reliability_rank,
    _safe_sort_number,
    _status_rank,
    _value_eligible,
    select_balanced,
    shop_exact_offers,
)
from nfl_edge.value.market_math import american_to_decimal
from nfl_edge.value.wager_economics import moneyline_settlement, spread_settlement, total_settlement

DEV = {2020, 2021, 2022, 2023, 2024}
MARKETS = ("moneyline", "spread", "total")


def _f(row: Mapping[str, Any], key: str) -> float | None:
    value = row.get(key)
    return None if value is None else float(value)


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"plays": 0, "wins": 0, "losses": 0, "pushes": 0, "hit_rate_nonpush": None, "roi": None, "avg_ev": None, "avg_q": None, "avg_odds": None, "roi_minus_ev": None}
    wins = sum(str(r.get("settlement")) == "WIN" for r in rows)
    losses = sum(str(r.get("settlement")) == "LOSS" for r in rows)
    pushes = sum(str(r.get("settlement")) == "PUSH" for r in rows)
    nonpush = wins + losses
    return {
        "plays": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if nonpush == 0 else wins / nonpush,
        "roi": mean(float(r["realized_profit"]) for r in rows),
        "avg_ev": mean(float(r["expected_value"]) for r in rows),
        "avg_q": mean(float(r["actionable_probability"]) for r in rows),
        "avg_odds": mean(float(r["american_odds"]) for r in rows),
        "roi_minus_ev": mean(float(r["realized_profit"]) - float(r["expected_value"]) for r in rows),
    }


def _season(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {str(s): _summary([r for r in rows if int(r["season"]) == s]) for s in sorted(DEV)}


def _value_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        -_safe_sort_number(_f(row, "expected_value")),
        -_safe_sort_number(_f(row, "evaluated_edge_probability")),
        -_reliability_rank(row),
        -_safe_sort_number(_f(row, "actionable_probability")),
        _candidate_id(row),
    )


def _probability_first_balanced_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        -_safe_sort_number(_f(row, "actionable_probability")),
        -_reliability_rank(row),
        -_status_rank(row),
        -_safe_sort_number(_f(row, "expected_value")),
        -_safe_sort_number(_f(row, "evaluated_edge_probability")),
        _candidate_id(row),
    )


def _settle(row: Mapping[str, Any], home: int, away: int) -> str:
    market = str(row["market_type"])
    side = str(row["selected_side"])
    if market == "moneyline":
        return moneyline_settlement(side, home, away).value
    if market == "spread":
        return spread_settlement(side, float(row["line"]), home, away).value
    if market == "total":
        return total_settlement(side, float(row["line"]), home, away).value
    raise ValueError(market)


def _profit(settlement: str, odds: int) -> float:
    if settlement == "WIN":
        return float(american_to_decimal(odds) - 1.0)
    if settlement == "LOSS":
        return -1.0
    return 0.0


def run(board_path: Path, selector_path: Path, games_path: Path, out: Path) -> None:
    board_df = pl.read_parquet(board_path)
    seasons = {int(x) for x in board_df["season"].unique().to_list()}
    if seasons != DEV:
        raise RuntimeError(f"unexpected board seasons {sorted(seasons)}")
    board = board_df.to_dicts()
    selected = [r for r in pl.read_csv(selector_path, infer_schema_length=10000).to_dicts() if not bool(r.get("no_play"))]
    blocks = sorted({str(r["block"]) for r in board})
    by_block = {b: [r for r in board if str(r["block"]) == b] for b in blocks}

    # EV-rank / optimizer's-curse audit over the exact same Value eligibility.
    top = {"top1": [], "top3": [], "top5": [], "all_eligible": []}
    rank_bands = {"rank1": [], "rank2": [], "rank3": [], "rank4_5": [], "rank6plus": []}
    market_top1 = {m: [] for m in MARKETS}
    all_value: list[dict[str, Any]] = []
    for block in blocks:
        shopped = list(shop_exact_offers(by_block[block]))
        eligible = sorted([dict(r) for r in shopped if _value_eligible(r)], key=_value_key)
        all_value.extend(eligible)
        top["all_eligible"].extend(eligible)
        top["top1"].extend(eligible[:1])
        top["top3"].extend(eligible[:3])
        top["top5"].extend(eligible[:5])
        for rank, row in enumerate(eligible, start=1):
            band = "rank1" if rank == 1 else "rank2" if rank == 2 else "rank3" if rank == 3 else "rank4_5" if rank <= 5 else "rank6plus"
            rank_bands[band].append(row)
        for market in MARKETS:
            rows = [r for r in eligible if str(r["market_type"]) == market]
            if rows:
                market_top1[market].append(rows[0])

    ev_bins = {"2-4%": [], "4-6%": [], "6-10%": [], ">=10%": []}
    q_bins = {"35-45%": [], "45-55%": [], "55-65%": [], ">=65%": []}
    uncertainty_bins = {"<=2%": [], "2-3%": [], "3-4%": [], ">4%": []}
    for row in all_value:
        ev = float(row["expected_value"])
        q = float(row["actionable_probability"])
        uncertainty = float(row["uncertainty"])
        ev_bins["2-4%" if ev < .04 else "4-6%" if ev < .06 else "6-10%" if ev < .10 else ">=10%"].append(row)
        q_bins["35-45%" if q < .45 else "45-55%" if q < .55 else "55-65%" if q < .65 else ">=65%"].append(row)
        uncertainty_bins["<=2%" if uncertainty <= .02 else "2-3%" if uncertainty <= .03 else "3-4%" if uncertainty <= .04 else ">4%"].append(row)

    # Selected-tail market decomposition.
    selected_tail: dict[str, Any] = {}
    for role in ("hit_rate", "balanced", "value"):
        rows = [r for r in selected if str(r["role"]) == role]
        selected_tail[role] = {
            "overall": _summary(rows),
            "by_market": {m: _summary([r for r in rows if str(r["market_type"]) == m]) for m in MARKETS},
        }

    # Balanced design pathology: current lexicographic ranking vs probability-first,
    # using identical eligibility and shopping. Diagnostic only; not a replacement.
    current_rows: list[dict[str, Any]] = []
    probability_first_rows: list[dict[str, Any]] = []
    sacrifices: list[float] = []
    same = 0
    for block in blocks:
        rows = by_block[block]
        eligible = [dict(r) for r in shop_exact_offers(rows) if _balanced_eligible(r)]
        if not eligible:
            continue
        current = select_balanced(rows)
        assert not isinstance(current, str)
        current = dict(current)
        alt = sorted(eligible, key=_probability_first_balanced_key)[0]
        current_rows.append(current)
        probability_first_rows.append(alt)
        sacrifices.append(float(alt["actionable_probability"]) - float(current["actionable_probability"]))
        if (
            str(current.get("game_id")), str(current.get("market_type")), str(current.get("selected_side")),
            str(current.get("sportsbook")), current.get("line"), int(current.get("american_odds"))
        ) == (
            str(alt.get("game_id")), str(alt.get("market_type")), str(alt.get("selected_side")),
            str(alt.get("sportsbook")), alt.get("line"), int(alt.get("american_odds"))
        ):
            same += 1

    # Independent final-score settlement/profit and exact-offer/shopping integrity.
    games = (
        pl.read_parquet(games_path)
        .filter(pl.col("season").is_in(sorted(DEV)))
        .select(["game_id", "season", "home_score", "away_score"])
        .to_dicts()
    )
    game_idx = {(str(r["game_id"]), int(r["season"])): (int(r["home_score"]), int(r["away_score"])) for r in games}
    settlement_mismatches = 0
    profit_mismatches = 0
    shopping_mismatches = 0
    exact_row_missing = 0
    probability_or_ev_transfer_mismatches = 0
    missing_games = 0
    for row in selected:
        key = (str(row["game_id"]), int(row["season"]))
        if key not in game_idx:
            missing_games += 1
            continue
        home, away = game_idx[key]
        recomputed_settlement = _settle(row, home, away)
        if recomputed_settlement != str(row["settlement"]):
            settlement_mismatches += 1
        if abs(_profit(recomputed_settlement, int(row["american_odds"])) - float(row["realized_profit"])) > 1e-9:
            profit_mismatches += 1

        rows = by_block[str(row["block"])]
        shopped = [
            r for r in shop_exact_offers(rows)
            if str(r["game_id"]) == str(row["game_id"])
            and str(r["market_type"]) == str(row["market_type"])
            and str(r["selected_side"]) == str(row["selected_side"])
        ]
        if not shopped or (
            str(shopped[0]["sportsbook"]), shopped[0].get("line"), int(shopped[0]["american_odds"])
        ) != (
            str(row["sportsbook"]), row.get("line"), int(row["american_odds"])
        ):
            shopping_mismatches += 1

        exact = [
            r for r in rows
            if str(r["game_id"]) == str(row["game_id"])
            and str(r["market_type"]) == str(row["market_type"])
            and str(r["selected_side"]) == str(row["selected_side"])
            and str(r["sportsbook"]) == str(row["sportsbook"])
            and r.get("line") == row.get("line")
            and int(r["american_odds"]) == int(row["american_odds"])
        ]
        if not exact:
            exact_row_missing += 1
        elif (
            abs(float(exact[0]["actionable_probability"]) - float(row["actionable_probability"])) > 1e-12
            or abs(float(exact[0]["expected_value"]) - float(row["expected_value"])) > 1e-12
        ):
            probability_or_ev_transfer_mismatches += 1

    result = {
        "development_seasons": sorted(DEV),
        "purpose": "forensic diagnostics only; no selector/evaluator/model retuning",
        "ev_rank_calibration": {
            "top_k": {k: {"overall": _summary(v), "season": _season(v)} for k, v in top.items()},
            "within_block_rank_bands": {k: _summary(v) for k, v in rank_bands.items()},
            "market_top1_each_block": {m: {"overall": _summary(v), "season": _season(v)} for m, v in market_top1.items()},
        },
        "selected_tail": selected_tail,
        "balanced_pathology": {
            "eligible_blocks": len(current_rows),
            "current": {"overall": _summary(current_rows), "season": _season(current_rows), "value_status_count": sum(str(r["price_status"]) == "VALUE" for r in current_rows)},
            "probability_first_same_eligibility": {"overall": _summary(probability_first_rows), "season": _season(probability_first_rows)},
            "same_pick_blocks": same,
            "different_pick_blocks": len(current_rows) - same,
            "avg_probability_given_up_by_current": None if not sacrifices else mean(sacrifices),
            "current_gave_up_ge_5pp_probability": sum(x >= .05 for x in sacrifices),
            "current_gave_up_ge_10pp_probability": sum(x >= .10 for x in sacrifices),
            "counterfactual_is_diagnostic_only": True,
        },
        "uncertainty_and_tail_calibration": {
            "all_value_eligible_ev_bins": {k: _summary(v) for k, v in ev_bins.items()},
            "all_value_eligible_probability_bins": {k: _summary(v) for k, v in q_bins.items()},
            "all_value_eligible_uncertainty_bins": {k: _summary(v) for k, v in uncertainty_bins.items()},
            "selected_value_reliability_mix": {tier: sum(str(r.get("reliability")) == tier for r in selected if str(r["role"]) == "value") for tier in ("HIGH", "MEDIUM", "LOW", "UNSUPPORTED")},
        },
        "exact_offer_settlement_integrity": {
            "selected_rows": len(selected),
            "missing_final_score_games": missing_games,
            "settlement_mismatches": settlement_mismatches,
            "profit_mismatches": profit_mismatches,
            "shopping_mismatches": shopping_mismatches,
            "exact_board_row_missing": exact_row_missing,
            "exact_probability_or_ev_transfer_mismatches": probability_or_ev_transfer_mismatches,
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", required=True)
    parser.add_argument("--selector-results", required=True)
    parser.add_argument("--games", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    run(Path(args.board), Path(args.selector_results), Path(args.games), Path(args.out))
