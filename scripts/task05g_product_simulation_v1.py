#!/usr/bin/env python3
"""Task05G 2020-24 end-to-end product/staking simulation.

2025 is intentionally prohibited.  This runner consumes the frozen V3 candidate
board plus frozen Task05G selector provenance, recreates the three weekly
headlines, applies canonical units and all five risk profiles, and measures the
product effect of Play Through without tuning any threshold from outcomes.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Mapping

import polars as pl

from nfl_edge.recommendation.final_selectors_v1 import (
    ValueSelectorState,
    advance_value_state,
    select_balanced,
    select_hit_rate,
    select_value,
)
from nfl_edge.recommendation.policy import NO_BALANCED_PLAY, NO_HIT_RATE_PLAY, NO_VALUE_PLAY, shop_exact_offers
from nfl_edge.recommendation.remediation_provenance_v1 import build_candidate_registry, enrich_board_rows
from nfl_edge.recommendation.staking_v1 import (
    RISK_PROFILES,
    ULTRA_CAUTION,
    cap_slate_stakes,
    dollar_stake,
    recommended_units,
    unit_dollars,
    user_wager_view,
)

ALL = {2020, 2021, 2022, 2023, 2024}
SEALED = 2025
LANES = ("hit_rate", "balanced", "value")
STATUSES = ("VALUE", "PLAYABLE", "LEAN", "PASS", "UNSUPPORTED")
INITIAL_BANKROLL = 1000.0
DISPLAY_BANKROLL = 250.0


def block_key(block: str) -> tuple[int, int]:
    season, week = str(block).split("-", 1)
    return int(season), int(week)


def group_blocks(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        out[str(row["block"])].append(dict(row))
    return dict(out)


def cid(row: Mapping[str, Any]) -> str:
    return str(row.get("candidate_id") or "|".join([str(row.get("game_id", "")), str(row.get("market_type", "")), str(row.get("selected_side", ""))]))


def offer_key(row: Mapping[str, Any]) -> str:
    return "|".join(
        [
            cid(row),
            str(row.get("sportsbook") or row.get("actionable_book") or ""),
            str(row.get("line") if row.get("line") is not None else row.get("actionable_line")),
            str(row.get("american_odds") if row.get("american_odds") is not None else row.get("actionable_price_american")),
        ]
    )


def status(row: Mapping[str, Any]) -> str:
    return str(row.get("price_status") or "UNSUPPORTED").upper()


def settlement(row: Mapping[str, Any]) -> str:
    return str(row.get("settlement") or "").upper()


def profit_per_unit(row: Mapping[str, Any]) -> float:
    value = row.get("realized_profit")
    return 0.0 if value is None else float(value)


def select_all(block_rows: list[dict[str, Any]], state: ValueSelectorState) -> dict[str, dict[str, Any] | None]:
    h = select_hit_rate(block_rows)
    b = select_balanced(block_rows)
    v = select_value(block_rows, state)
    return {
        "hit_rate": None if h == NO_HIT_RATE_PLAY else dict(h),
        "balanced": None if b == NO_BALANCED_PLAY else dict(b),
        "value": None if v == NO_VALUE_PLAY else dict(v),
    }


def summarize_rows(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    wins = sum(settlement(r) == "WIN" for r in rows)
    losses = sum(settlement(r) == "LOSS" for r in rows)
    pushes = sum(settlement(r) == "PUSH" for r in rows)
    denom = wins + losses
    profits = [profit_per_unit(r) for r in rows if r.get("realized_profit") is not None]
    return {
        "count": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if denom == 0 else wins / denom,
        "flat_units": float(sum(profits)),
        "flat_roi": None if not profits else float(mean(profits)),
    }


def simulate_profile(
    selected_by_block: Mapping[str, Mapping[str, Mapping[str, Any] | None]],
    profile_name: str,
    *,
    include_playable: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    bankroll = INITIAL_BANKROLL
    peak = bankroll
    max_drawdown = 0.0
    total_staked = 0.0
    total_profit = 0.0
    unique_wagers = 0
    zero_stake_headlines = 0
    playable_wagers = 0
    value_wagers = 0
    min_rounding_suppressed = 0
    slate_cap_binding_blocks = 0
    ledger: list[dict[str, Any]] = []

    for block in sorted(selected_by_block, key=block_key):
        picks = selected_by_block[block]
        by_offer: dict[str, dict[str, Any]] = {}
        lanes_by_offer: dict[str, list[str]] = defaultdict(list)
        for lane in LANES:
            row = picks.get(lane)
            if row is None:
                continue
            lanes_by_offer[offer_key(row)].append(lane)
            units = recommended_units(row)
            if not include_playable and status(row) == "PLAYABLE":
                units = 0.0
            if units <= 0:
                zero_stake_headlines += 1
                continue
            key = offer_key(row)
            prior = by_offer.get(key)
            if prior is not None:
                if float(prior["units"]) != float(units):
                    raise RuntimeError(f"same offer received different units across lanes: {key}")
                continue
            raw_stake = dollar_stake(bankroll, profile_name, units)
            if raw_stake == 0.0 and bankroll > 0:
                min_rounding_suppressed += 1
            by_offer[key] = {"row": row, "units": units, "raw_stake": raw_stake}

        proposed = [(key, float(by_offer[key]["raw_stake"])) for key in sorted(by_offer)]
        capped = cap_slate_stakes(bankroll, proposed)
        if any(capped.get(key, 0.0) + 1e-12 < stake for key, stake in proposed):
            slate_cap_binding_blocks += 1

        block_profit = 0.0
        block_staked = 0.0
        for key in sorted(by_offer):
            item = by_offer[key]
            row = item["row"]
            stake = float(capped.get(key, 0.0))
            if stake <= 0:
                continue
            pnl = stake * profit_per_unit(row)
            block_staked += stake
            block_profit += pnl
            unique_wagers += 1
            if status(row) == "PLAYABLE":
                playable_wagers += 1
            elif status(row) == "VALUE":
                value_wagers += 1
            ledger.append(
                {
                    "profile": profile_name,
                    "policy": "WITH_PLAY_THROUGH" if include_playable else "STRICT_VALUE_ONLY_STAKING",
                    "block": block,
                    "offer_key": key,
                    "lanes": ";".join(sorted(lanes_by_offer[key])),
                    "candidate_id": cid(row),
                    "market_type": row.get("market_type"),
                    "selected_side": row.get("selected_side"),
                    "sportsbook": row.get("sportsbook"),
                    "line": row.get("line"),
                    "american_odds": row.get("american_odds"),
                    "price_status": status(row),
                    "recommended_units": item["units"],
                    "stake": stake,
                    "settlement": settlement(row),
                    "profit": pnl,
                    "bankroll_before_block": bankroll,
                }
            )

        total_staked += block_staked
        total_profit += block_profit
        bankroll += block_profit
        peak = max(peak, bankroll)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - bankroll) / peak)

    return (
        {
            "profile": profile_name,
            "include_playable": include_playable,
            "initial_bankroll": INITIAL_BANKROLL,
            "ending_bankroll": bankroll,
            "profit": total_profit,
            "return_on_initial_bankroll": total_profit / INITIAL_BANKROLL,
            "total_staked": total_staked,
            "unique_wagers": unique_wagers,
            "value_wagers": value_wagers,
            "playable_wagers": playable_wagers,
            "zero_stake_headline_instances": zero_stake_headlines,
            "minimum_rounding_suppressed": min_rounding_suppressed,
            "slate_cap_binding_blocks": slate_cap_binding_blocks,
            "max_drawdown_pct": max_drawdown,
        },
        ledger,
    )


def concession_summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    vals = [float(r["play_through_break_even_concession"]) for r in rows if r.get("play_through_break_even_concession") is not None]
    mults = [float(r["play_through_confidence_multiplier"]) for r in rows if r.get("play_through_confidence_multiplier") is not None]
    if not vals:
        return {"n": 0, "min_pp": None, "median_pp": None, "mean_pp": None, "max_pp": None, "confidence_multiplier_min": None, "confidence_multiplier_median": None, "confidence_multiplier_max": None}
    return {
        "n": len(vals),
        "min_pp": min(vals) * 100.0,
        "median_pp": median(vals) * 100.0,
        "mean_pp": mean(vals) * 100.0,
        "max_pp": max(vals) * 100.0,
        "confidence_multiplier_min": None if not mults else min(mults),
        "confidence_multiplier_median": None if not mults else median(mults),
        "confidence_multiplier_max": None if not mults else max(mults),
    }


def run(v3_path: Path, discovery: Path, confirmation: Path, out: Path) -> None:
    rows = pl.read_parquet(v3_path).to_dicts()
    seasons = {int(r["season"]) for r in rows}
    if seasons != ALL or SEALED in seasons:
        raise RuntimeError(f"2025 firewall / unexpected V3 seasons: {sorted(seasons)}")

    provenance = pl.concat(
        [pl.read_csv(discovery, infer_schema_length=10000), pl.read_csv(confirmation, infer_schema_length=10000)],
        how="vertical_relaxed",
    ).to_dicts()
    prov_seasons = {int(r["season"]) for r in provenance}
    if prov_seasons != ALL or SEALED in prov_seasons:
        raise RuntimeError(f"2025 firewall / unexpected provenance seasons: {sorted(prov_seasons)}")

    enriched = enrich_board_rows(rows, build_candidate_registry(provenance))
    blocks = group_blocks(enriched)

    selected_by_block: dict[str, dict[str, dict[str, Any] | None]] = {}
    headline_rows: list[dict[str, Any]] = []
    shopped_rows: list[dict[str, Any]] = []
    state = ValueSelectorState()
    season_now: int | None = None

    for block in sorted(blocks, key=block_key):
        season, _ = block_key(block)
        if season_now != season:
            state = ValueSelectorState()
            season_now = season
        block_rows = blocks[block]
        selections = select_all(block_rows, state)
        selected_by_block[block] = selections
        for lane, row in selections.items():
            if row is None:
                continue
            material = dict(row)
            material["lane"] = lane
            material["block"] = block
            material["offer_key"] = offer_key(row)
            material["recommended_units"] = recommended_units(row)
            headline_rows.append(material)
        for row in shop_exact_offers(block_rows):
            material = dict(row)
            material["block"] = block
            material["offer_key"] = offer_key(row)
            shopped_rows.append(material)
        state = advance_value_state(state, block_rows)

    if any(int(r["season"]) == SEALED for r in enriched):
        raise RuntimeError("2025 entered enriched development rows")

    board_status = Counter(status(r) for r in shopped_rows)
    headline_status_by_lane = {
        lane: {s: sum(r["lane"] == lane and status(r) == s for r in headline_rows) for s in STATUSES}
        for lane in LANES
    }
    headline_unit_distribution = {
        lane: dict(sorted(Counter(float(r["recommended_units"]) for r in headline_rows if r["lane"] == lane).items()))
        for lane in LANES
    }

    playable_board = [r for r in shopped_rows if status(r) == "PLAYABLE"]
    value_board = [r for r in shopped_rows if status(r) == "VALUE"]
    playable_headlines = [r for r in headline_rows if status(r) == "PLAYABLE"]
    value_headlines = [r for r in headline_rows if status(r) == "VALUE"]
    zero_unit_headlines = [r for r in headline_rows if float(r["recommended_units"]) == 0.0]

    by_block_status: dict[str, set[str]] = defaultdict(set)
    for r in shopped_rows:
        by_block_status[str(r["block"])].add(status(r))
    value_blocks = sum("VALUE" in s for s in by_block_status.values())
    playable_blocks = sum("PLAYABLE" in s for s in by_block_status.values())
    playable_only_blocks = sum("PLAYABLE" in s and "VALUE" not in s for s in by_block_status.values())
    value_or_playable_blocks = sum(bool({"VALUE", "PLAYABLE"}.intersection(s)) for s in by_block_status.values())

    profile_results = []
    bankroll_ledgers: list[dict[str, Any]] = []
    strict_results = []
    strict_ledgers: list[dict[str, Any]] = []
    for profile in RISK_PROFILES:
        result, ledger_rows = simulate_profile(selected_by_block, profile.name, include_playable=True)
        profile_results.append(result)
        bankroll_ledgers.extend(ledger_rows)
        strict_result, strict_ledger_rows = simulate_profile(selected_by_block, profile.name, include_playable=False)
        strict_results.append(strict_result)
        strict_ledgers.extend(strict_ledger_rows)

    pt_effect_by_profile = []
    strict_map = {r["profile"]: r for r in strict_results}
    for current in profile_results:
        strict = strict_map[current["profile"]]
        pt_effect_by_profile.append(
            {
                "profile": current["profile"],
                "additional_wagers_from_play_through": current["unique_wagers"] - strict["unique_wagers"],
                "ending_bankroll_with_play_through": current["ending_bankroll"],
                "ending_bankroll_strict_value_only_staking": strict["ending_bankroll"],
                "ending_bankroll_difference": current["ending_bankroll"] - strict["ending_bankroll"],
                "max_drawdown_with_play_through": current["max_drawdown_pct"],
                "max_drawdown_strict_value_only_staking": strict["max_drawdown_pct"],
            }
        )

    profile_stake_examples = []
    for profile in RISK_PROFILES:
        for units in (0.5, 0.75, 1.0, 1.25, 1.5):
            profile_stake_examples.append(
                {
                    "bankroll": DISPLAY_BANKROLL,
                    "profile": profile.name,
                    "unit_bankroll_pct": profile.unit_bankroll_pct,
                    "one_unit_dollars": unit_dollars(DISPLAY_BANKROLL, profile),
                    "recommended_units": units,
                    "recommended_stake": dollar_stake(DISPLAY_BANKROLL, profile, units),
                    "caution": profile.caution,
                }
            )

    examples = []
    example_kinds = {
        "VALUE_HEADLINE": next((r for r in headline_rows if status(r) == "VALUE" and float(r["recommended_units"]) > 0), None),
        "PLAYABLE_HEADLINE": next((r for r in headline_rows if status(r) == "PLAYABLE" and float(r["recommended_units"]) > 0), None),
        "ZERO_STAKE_HEADLINE": next((r for r in headline_rows if float(r["recommended_units"]) == 0.0), None),
    }
    for kind, row in example_kinds.items():
        if row is None:
            continue
        view = user_wager_view(row, bankroll=DISPLAY_BANKROLL, profile="Normal", lane=str(row["lane"]))
        view["example_kind"] = kind
        view["block"] = row["block"]
        examples.append(view)

    scorecard = {
        "version": "task05g_product_simulation_v1",
        "seasons": sorted(ALL),
        "sealed": [SEALED],
        "total_blocks": len(blocks),
        "initial_simulation_bankroll": INITIAL_BANKROLL,
        "display_example_bankroll": DISPLAY_BANKROLL,
        "risk_profiles": [
            {"name": p.name, "unit_bankroll_pct": p.unit_bankroll_pct, "caution": p.caution} for p in RISK_PROFILES
        ],
        "ultra_caution": ULTRA_CAUTION,
        "board": {
            "shopped_exact_offer_count": len(shopped_rows),
            "status_counts": {s: board_status.get(s, 0) for s in STATUSES},
            "blocks_with_value": value_blocks,
            "blocks_with_playable": playable_blocks,
            "blocks_with_value_or_playable": value_or_playable_blocks,
            "blocks_with_playable_but_no_value": playable_only_blocks,
            "value_outcomes": summarize_rows(value_board),
            "playable_outcomes": summarize_rows(playable_board),
            "playable_concession": concession_summary(playable_board),
        },
        "headlines": {
            "total_selected": len(headline_rows),
            "status_by_lane": headline_status_by_lane,
            "unit_distribution_by_lane": headline_unit_distribution,
            "value_headlines": summarize_rows(value_headlines),
            "playable_headlines": summarize_rows(playable_headlines),
            "zero_unit_headline_count": len(zero_unit_headlines),
            "zero_unit_status_counts": dict(sorted(Counter(status(r) for r in zero_unit_headlines).items())),
            "playable_concession": concession_summary(playable_headlines),
        },
        "profile_results_with_play_through": profile_results,
        "profile_results_strict_value_only_staking": strict_results,
        "play_through_effect_by_profile": pt_effect_by_profile,
        "invariants": {
            "no_2025": True,
            "five_profiles": [p.name for p in RISK_PROFILES] == ["Cautious", "Conservative", "Normal", "Aggressive", "Ultra"],
            "profiles_monotonic": [p.unit_bankroll_pct for p in RISK_PROFILES] == sorted(p.unit_bankroll_pct for p in RISK_PROFILES),
            "ultra_performance_independence_warning_present": "does not imply higher expected performance" in ULTRA_CAUTION,
            "value_headlines_never_playable": all(status(r) == "VALUE" for r in headline_rows if r["lane"] == "value"),
            "playable_units_lte_0_75": all(float(r["recommended_units"]) <= 0.75 for r in playable_headlines),
            "lean_pass_unsupported_zero_units": all(float(r["recommended_units"]) == 0.0 for r in headline_rows if status(r) in {"LEAN", "PASS", "UNSUPPORTED"}),
            "play_through_never_relabels_value": all(status(r) != "VALUE" for r in playable_board),
            "max_play_through_concession_lte_1_5pp": all(float(r.get("play_through_break_even_concession") or 0.0) <= 0.015 + 1e-12 for r in playable_board),
        },
    }

    out.mkdir(parents=True, exist_ok=True)
    (out / "scorecard.json").write_text(json.dumps(scorecard, indent=2, sort_keys=True, allow_nan=False) + "\n")
    pl.DataFrame(headline_rows).sort(["block", "lane", "candidate_id"]).write_csv(out / "headline_rows.csv")
    pl.DataFrame(playable_headlines).sort(["block", "lane", "candidate_id"]).write_csv(out / "playable_headlines.csv")
    pl.DataFrame(zero_unit_headlines).sort(["block", "lane", "candidate_id"]).write_csv(out / "zero_unit_headlines.csv")
    pl.DataFrame(profile_results).write_csv(out / "profile_bankroll_summary.csv")
    pl.DataFrame(pt_effect_by_profile).write_csv(out / "play_through_profile_effect.csv")
    pl.DataFrame(profile_stake_examples).write_csv(out / "profile_stake_examples_250_bankroll.csv")
    pl.DataFrame(examples).write_csv(out / "user_view_examples_normal_250.csv")
    if playable_board:
        pl.DataFrame(playable_board).sort(["block", "candidate_id"]).write_csv(out / "playable_board_offers.csv")
    if bankroll_ledgers:
        pl.DataFrame(bankroll_ledgers).sort(["profile", "block", "offer_key"]).write_csv(out / "bankroll_ledger_with_play_through.csv")
    if strict_ledgers:
        pl.DataFrame(strict_ledgers).sort(["profile", "block", "offer_key"]).write_csv(out / "bankroll_ledger_strict_value_only_staking.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--v3-candidates", type=Path, required=True)
    parser.add_argument("--discovery", type=Path, default=Path("reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv"))
    parser.add_argument("--confirmation", type=Path, default=Path("reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.v3_candidates, args.discovery, args.confirmation, args.out)
