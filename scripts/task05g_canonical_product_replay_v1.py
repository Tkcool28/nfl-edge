#!/usr/bin/env python3
"""Canonical Task05G 2020-24 product replay after headline staking integration.

This runner intentionally imports only canonical recommendation modules. Audit
staking helpers are forbidden. 2025 is sealed and must never enter the replay.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

import polars as pl

from nfl_edge.recommendation.final_selectors_v1 import (
    ValueSelectorState,
    advance_value_state,
    select_balanced,
    select_hit_rate,
    select_value,
)
from nfl_edge.recommendation.headline_staking_v1 import headline_actionability
from nfl_edge.recommendation.policy import NO_BALANCED_PLAY, NO_HIT_RATE_PLAY, NO_VALUE_PLAY
from nfl_edge.recommendation.remediation_provenance_v1 import build_candidate_registry, enrich_board_rows
from nfl_edge.recommendation.staking_v1 import cap_slate_stakes, dollar_stake

ALL = {2020, 2021, 2022, 2023, 2024}
SEALED = 2025
PROFILES = ["Cautious", "Conservative", "Normal", "Aggressive", "Ultra"]
STARTS = [100.0, 250.0, 500.0, 1000.0, 2500.0]
LANES = ["hit_rate", "balanced", "value"]
EXPECTED_COUNTS = {"hit_rate": 81, "balanced": 88, "value": 68}


def block_key(block: str) -> tuple[int, int]:
    season, week = str(block).split("-", 1)
    return int(season), int(week)


def candidate_id(row: Mapping[str, Any]) -> str:
    explicit = row.get("candidate_id")
    if explicit is not None:
        return str(explicit)
    return "|".join(
        [
            str(row.get("game_id", "")),
            str(row.get("market_type", "")),
            str(row.get("selected_side", "")),
        ]
    )


def offer_key(row: Mapping[str, Any]) -> str:
    return "|".join(
        [
            candidate_id(row),
            str(row.get("sportsbook") or row.get("actionable_book") or ""),
            str(row.get("line") if row.get("line") is not None else row.get("actionable_line")),
            str(
                row.get("american_odds")
                if row.get("american_odds") is not None
                else row.get("actionable_price_american")
            ),
        ]
    )


def settlement(row: Mapping[str, Any]) -> str:
    return str(row.get("settlement") or "").upper()


def profit_per_unit(row: Mapping[str, Any]) -> float:
    value = row.get("realized_profit")
    return 0.0 if value is None else float(value)


def summarize_current_bets(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    wins = sum(settlement(row) == "WIN" for row in rows)
    losses = sum(settlement(row) == "LOSS" for row in rows)
    pushes = sum(settlement(row) == "PUSH" for row in rows)
    denom = wins + losses
    return {
        "current_bets": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if denom == 0 else wins / denom,
        "units_staked": sum(float(row["current_units"]) for row in rows),
        "weighted_profit_units": sum(
            float(row["current_units"]) * profit_per_unit(row) for row in rows
        ),
    }


def select_block(rows: list[dict[str, Any]], state: ValueSelectorState):
    hit = select_hit_rate(rows)
    balanced = select_balanced(rows)
    value = select_value(rows, state)
    return {
        "hit_rate": None if hit == NO_HIT_RATE_PLAY else dict(hit),
        "balanced": None if balanced == NO_BALANCED_PLAY else dict(balanced),
        "value": None if value == NO_VALUE_PLAY else dict(value),
    }


def run(v3_path: Path, discovery: Path, confirmation: Path, out: Path) -> None:
    board = pl.read_parquet(v3_path).to_dicts()
    seasons = {int(row["season"]) for row in board}
    if seasons != ALL or SEALED in seasons:
        raise RuntimeError(f"2025 firewall / unexpected board seasons: {sorted(seasons)}")

    provenance = pl.concat(
        [
            pl.read_csv(discovery, infer_schema_length=10000),
            pl.read_csv(confirmation, infer_schema_length=10000),
        ],
        how="vertical_relaxed",
    ).to_dicts()
    provenance_seasons = {int(row["season"]) for row in provenance}
    if provenance_seasons != ALL or SEALED in provenance_seasons:
        raise RuntimeError(
            f"2025 firewall / unexpected provenance seasons: {sorted(provenance_seasons)}"
        )

    enriched = enrich_board_rows(board, build_candidate_registry(provenance))
    blocks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        blocks[str(row["block"])].append(row)

    headline_rows: list[dict[str, Any]] = []
    current_bets_by_block: dict[str, list[dict[str, Any]]] = {}
    duplicate_conflicts: list[dict[str, Any]] = []
    state = ValueSelectorState()
    season_now: int | None = None

    for block in sorted(blocks, key=block_key):
        season, _ = block_key(block)
        if season_now != season:
            state = ValueSelectorState()
            season_now = season

        block_rows = blocks[block]
        selections = select_block(block_rows, state)
        unique_current: dict[str, dict[str, Any]] = {}

        for lane in LANES:
            selected = selections[lane]
            if selected is None:
                continue

            action = headline_actionability(lane, selected)
            material = dict(selected)
            material.update(
                {
                    "season": season,
                    "block": block,
                    "lane": lane,
                    "candidate_id": candidate_id(selected),
                    "offer_key": offer_key(selected),
                    "published": action.published,
                    "headline_action": action.primary_action,
                    "current_units": action.current_units,
                    "action_units": action.action_units,
                    "value_at_price_american": action.value_at_price_american,
                    "value_at_break_even_improvement_pp": None
                    if action.value_at_break_even_improvement is None
                    else action.value_at_break_even_improvement * 100.0,
                    "heavily_juiced": action.heavily_juiced,
                }
            )
            headline_rows.append(material)

            # Bankroll simulation only places recommendations actionable at the
            # actual historical current offer. A Value-at target is an
            # instruction for a future/better price and is not fabricated as a
            # historical fill.
            if not action.published or action.current_units <= 0.0:
                continue

            key = material["offer_key"]
            prior = unique_current.get(key)
            if prior is None:
                unique_current[key] = dict(material)
            elif abs(float(prior["current_units"]) - float(material["current_units"])) > 1e-12:
                duplicate_conflicts.append(
                    {
                        "block": block,
                        "offer_key": key,
                        "prior_lane": prior["lane"],
                        "prior_units": prior["current_units"],
                        "new_lane": lane,
                        "new_units": material["current_units"],
                    }
                )
                if float(material["current_units"]) > float(prior["current_units"]):
                    unique_current[key] = dict(material)

        current_bets_by_block[block] = list(unique_current.values())
        state = advance_value_state(state, block_rows)

    counts = Counter(row["lane"] for row in headline_rows)
    if dict(counts) != EXPECTED_COUNTS:
        raise RuntimeError(f"frozen selector counts changed: {dict(counts)}")
    if any(int(row["season"]) == SEALED for row in headline_rows):
        raise RuntimeError("2025 entered headline outputs")

    season_lane_rows: list[dict[str, Any]] = []
    for season in sorted(ALL):
        for lane in LANES:
            selected_rows = [
                row
                for row in headline_rows
                if int(row["season"]) == season and row["lane"] == lane
            ]
            current_rows = [row for row in selected_rows if float(row["current_units"]) > 0.0]
            current_summary = summarize_current_bets(current_rows)
            season_lane_rows.append(
                {
                    "season": season,
                    "lane": lane,
                    "selected": len(selected_rows),
                    "published": sum(bool(row["published"]) for row in selected_rows),
                    "current_bets": current_summary["current_bets"],
                    "value_at_target_only": sum(
                        row["headline_action"] == "VALUE_AT" for row in selected_rows
                    ),
                    "suppressed": sum(not bool(row["published"]) for row in selected_rows),
                    "wins_current_bets": current_summary["wins"],
                    "losses_current_bets": current_summary["losses"],
                    "pushes_current_bets": current_summary["pushes"],
                    "hit_rate_current_nonpush": current_summary["hit_rate_nonpush"],
                    "current_units_staked": current_summary["units_staked"],
                    "current_weighted_profit_units": current_summary["weighted_profit_units"],
                }
            )

    season_combined_rows: list[dict[str, Any]] = []
    for season in sorted(ALL):
        rows = [
            row
            for block, block_rows in current_bets_by_block.items()
            if block_key(block)[0] == season
            for row in block_rows
        ]
        summary = summarize_current_bets(rows)
        season_combined_rows.append(
            {
                "season": season,
                "unique_current_recommended_wagers": len(rows),
                **summary,
            }
        )

    scenarios: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    for starting_bankroll in STARTS:
        for profile in PROFILES:
            bankroll = starting_bankroll
            peak = bankroll
            total_staked = 0.0
            total_profit = 0.0
            wagers_bet = 0
            min_stake_suppressed = 0
            slate_cap_binding_blocks = 0
            max_drawdown = 0.0

            for block in sorted(current_bets_by_block, key=block_key):
                rows = current_bets_by_block[block]
                proposed: list[tuple[str, float]] = []
                for row in rows:
                    stake = dollar_stake(bankroll, profile, float(row["current_units"]))
                    if stake == 0.0 and float(row["current_units"]) > 0.0:
                        min_stake_suppressed += 1
                    proposed.append((row["offer_key"], stake))

                capped = cap_slate_stakes(bankroll, proposed)
                if any(capped.get(key, 0.0) + 1e-12 < stake for key, stake in proposed):
                    slate_cap_binding_blocks += 1

                block_profit = 0.0
                block_staked = 0.0
                for row in rows:
                    stake = float(capped.get(row["offer_key"], 0.0))
                    if stake <= 0.0:
                        continue
                    pnl = stake * profit_per_unit(row)
                    block_staked += stake
                    block_profit += pnl
                    wagers_bet += 1
                    ledger.append(
                        {
                            "starting_bankroll": starting_bankroll,
                            "profile": profile,
                            "block": block,
                            "season": block_key(block)[0],
                            "lane_source": row["lane"],
                            "offer_key": row["offer_key"],
                            "units": row["current_units"],
                            "stake": stake,
                            "settlement": settlement(row),
                            "profit": pnl,
                        }
                    )

                total_staked += block_staked
                total_profit += block_profit
                bankroll += block_profit
                peak = max(peak, bankroll)
                if peak > 0:
                    max_drawdown = max(max_drawdown, (peak - bankroll) / peak)

            scenarios.append(
                {
                    "starting_bankroll": starting_bankroll,
                    "profile": profile,
                    "ending_bankroll": bankroll,
                    "profit": total_profit,
                    "return_pct": total_profit / starting_bankroll,
                    "total_staked": total_staked,
                    "wagers_bet": wagers_bet,
                    "min_stake_suppressed": min_stake_suppressed,
                    "slate_cap_binding_blocks": slate_cap_binding_blocks,
                    "max_drawdown_pct": max_drawdown,
                }
            )

    published_zero_action = [
        row
        for row in headline_rows
        if bool(row["published"]) and float(row["action_units"]) <= 0.0
    ]
    value_rows = [row for row in headline_rows if row["lane"] == "value"]
    value_at_rows = [row for row in value_rows if row["headline_action"] == "VALUE_AT"]

    invariants = {
        "selectors_unchanged": dict(counts) == EXPECTED_COUNTS,
        "all_hhr_selected_published_positive_current_bet": all(
            bool(row["published"]) and float(row["current_units"]) > 0.0
            for row in headline_rows
            if row["lane"] == "hit_rate"
        ),
        "all_balanced_selected_published_positive_current_bet": all(
            bool(row["published"]) and float(row["current_units"]) > 0.0
            for row in headline_rows
            if row["lane"] == "balanced"
        ),
        "all_published_headlines_have_positive_action_units": not published_zero_action,
        "all_value_target_only_cards_are_within_1_5pp": all(
            float(row["value_at_break_even_improvement_pp"]) <= 1.5 + 1e-12
            for row in value_at_rows
        ),
        "no_audit_staking_imports": True,
        "no_2025": True,
    }
    if not all(invariants.values()):
        raise RuntimeError(f"canonical replay invariant failure: {invariants}")

    out.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(headline_rows).write_csv(out / "headline_cards.csv")
    pl.DataFrame(season_lane_rows).write_csv(out / "season_lane_summary.csv")
    pl.DataFrame(season_combined_rows).write_csv(out / "season_combined_summary.csv")
    pl.DataFrame(scenarios).write_csv(out / "all_cards_bankroll_scenarios.csv")
    pl.DataFrame(ledger).write_csv(out / "scenario_ledger.csv")
    if duplicate_conflicts:
        pl.DataFrame(duplicate_conflicts).write_csv(out / "duplicate_unit_conflicts.csv")
    else:
        (out / "duplicate_unit_conflicts.csv").write_text(
            "block,offer_key,prior_lane,prior_units,new_lane,new_units\n"
        )

    scorecard = {
        "seasons": sorted(ALL),
        "sealed_not_run": [SEALED],
        "headline_counts": dict(counts),
        "published_headline_counts": dict(
            Counter(row["lane"] for row in headline_rows if bool(row["published"]))
        ),
        "positive_current_bet_headline_counts": dict(
            Counter(row["lane"] for row in headline_rows if float(row["current_units"]) > 0.0)
        ),
        "value_at_target_only_cards": len(value_at_rows),
        "value_suppressed_cards": sum(
            row["lane"] == "value" and not bool(row["published"]) for row in headline_rows
        ),
        "hhr_heavily_juiced_count": sum(
            row["lane"] == "hit_rate" and bool(row["heavily_juiced"])
            for row in headline_rows
        ),
        "combined_unique_current_recommended_wagers": sum(
            len(rows) for rows in current_bets_by_block.values()
        ),
        "duplicate_unit_conflict_count": len(duplicate_conflicts),
        "scenario_count": len(scenarios),
        "invariants": invariants,
    }
    (out / "scorecard.json").write_text(json.dumps(scorecard, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
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
    run(args.v3_candidates, args.discovery, args.confirmation, args.out)
