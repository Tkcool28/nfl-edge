#!/usr/bin/env python3
"""Descriptive 2020-24 replay for the post-V5 Balanced V2 successor.

This runner is intentionally diagnostic-only. The -130 ML cap, true-favorite
Pinnacle gate, spread 0-4 provenance, neutral spread confidence floor and
cross-market ranking are already fixed in ``final_selectors_v2`` before this
output is generated. Results must not be used to retune those constants.

2025 is hard-forbidden.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Mapping

import polars as pl

from nfl_edge.recommendation.final_selectors_v2 import select_balanced
from nfl_edge.recommendation.policy import NO_BALANCED_PLAY
from nfl_edge.recommendation.remediation_provenance_v1 import (
    build_candidate_registry,
    enrich_board_rows,
)

ALLOWED_SEASONS = {2020, 2021, 2022, 2023, 2024}
SEALED_SEASON = 2025


def _block_key(block: str) -> tuple[int, int]:
    season, week = str(block).split("-", 1)
    return int(season), int(week)


def _candidate_id(row: Mapping[str, Any]) -> str:
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


def _profit_per_unit(row: Mapping[str, Any]) -> float:
    value = row.get("realized_profit")
    return 0.0 if value is None else float(value)


def _settlement(row: Mapping[str, Any]) -> str:
    return str(row.get("settlement") or "").upper()


def _summary(rows: list[dict[str, Any]], *, block_count: int) -> dict[str, Any]:
    wins = sum(_settlement(row) == "WIN" for row in rows)
    losses = sum(_settlement(row) == "LOSS" for row in rows)
    pushes = sum(_settlement(row) == "PUSH" for row in rows)
    denom = wins + losses
    odds = [int(row["american_odds"]) for row in rows if row.get("american_odds") is not None]
    market_mix = Counter(str(row.get("market_type") or "").lower() for row in rows)
    flat_profit = sum(_profit_per_unit(row) for row in rows)
    return {
        "plays": len(rows),
        "blocks": block_count,
        "coverage": 0.0 if block_count == 0 else len(rows) / block_count,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if denom == 0 else wins / denom,
        "flat_profit_units": flat_profit,
        "flat_roi": None if not rows else flat_profit / len(rows),
        "average_american_odds": None if not odds else mean(odds),
        "market_mix": dict(sorted(market_mix.items())),
        "minus_130_or_shorter_count": sum(int(row["american_odds"]) <= -130 for row in rows),
        "plus_money_ml_count": sum(
            str(row.get("market_type") or "").lower() == "moneyline"
            and int(row["american_odds"]) > 0
            for row in rows
            if row.get("american_odds") is not None
        ),
        "ml_sharp_market_dog_count": sum(
            str(row.get("market_type") or "").lower() == "moneyline"
            and float(row.get("pinnacle_anchor_probability") or 0.0) < 0.50
            for row in rows
        ),
    }


def run(v3_path: Path, discovery: Path, confirmation: Path, out: Path) -> None:
    board = pl.read_parquet(v3_path).to_dicts()
    seasons = {int(row["season"]) for row in board}
    if seasons != ALLOWED_SEASONS or SEALED_SEASON in seasons:
        raise RuntimeError(f"2025 firewall / unexpected board seasons: {sorted(seasons)}")

    provenance = pl.concat(
        [
            pl.read_csv(discovery, infer_schema_length=10000),
            pl.read_csv(confirmation, infer_schema_length=10000),
        ],
        how="vertical_relaxed",
    ).to_dicts()
    provenance_seasons = {int(row["season"]) for row in provenance}
    if provenance_seasons != ALLOWED_SEASONS or SEALED_SEASON in provenance_seasons:
        raise RuntimeError(
            f"2025 firewall / unexpected provenance seasons: {sorted(provenance_seasons)}"
        )

    enriched = enrich_board_rows(board, build_candidate_registry(provenance))
    blocks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        blocks[str(row["block"])].append(row)

    selections: list[dict[str, Any]] = []
    no_play_blocks: list[str] = []
    for block in sorted(blocks, key=_block_key):
        selected = select_balanced(blocks[block])
        if selected == NO_BALANCED_PLAY:
            no_play_blocks.append(block)
            continue
        material = dict(selected)
        material["block"] = block
        material["candidate_id"] = _candidate_id(material)
        selections.append(material)

    # Product-definition invariants, not performance gates.
    for row in selections:
        market = str(row.get("market_type") or "").lower()
        odds = int(row["american_odds"])
        if market == "moneyline":
            if not (-130 <= odds <= -100):
                raise RuntimeError(f"Balanced V2 ML price-band violation: {row}")
            if float(row.get("pinnacle_anchor_probability") or 0.0) < 0.50:
                raise RuntimeError(f"Balanced V2 ML true-favorite violation: {row}")
        elif market == "spread":
            tags = set(str(row.get("model_candidate_regions") or "").split(";"))
            if "SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4" not in tags:
                raise RuntimeError(f"Balanced V2 spread provenance violation: {row}")
            if float(row.get("model_confidence_probability") or 0.0) < 0.50:
                raise RuntimeError(f"Balanced V2 spread confidence-floor violation: {row}")
            if float(row.get("model_cover_margin_v3") or 0.0) <= 0.0:
                raise RuntimeError(f"Balanced V2 spread direction violation: {row}")
        else:
            raise RuntimeError(f"unexpected Balanced V2 market: {market}")

    by_season: dict[str, Any] = {}
    for season in sorted(ALLOWED_SEASONS):
        season_blocks = [b for b in blocks if _block_key(b)[0] == season]
        season_rows = [row for row in selections if int(row["season"]) == season]
        by_season[str(season)] = _summary(season_rows, block_count=len(season_blocks))

    scorecard = {
        "status": "DESCRIPTIVE_EXPOSED_2020_2024__NO_RETUNING_AUTHORIZED",
        "seasons": sorted(ALLOWED_SEASONS),
        "sealed_not_read": [SEALED_SEASON],
        "overall": _summary(selections, block_count=len(blocks)),
        "by_season": by_season,
        "no_play_blocks": no_play_blocks,
        "invariants": {
            "no_plus_money_ml": all(
                not (
                    str(row.get("market_type") or "").lower() == "moneyline"
                    and int(row["american_odds"]) > 0
                )
                for row in selections
            ),
            "all_ml_at_or_better_than_minus_130": all(
                str(row.get("market_type") or "").lower() != "moneyline"
                or int(row["american_odds"]) >= -130
                for row in selections
            ),
            "all_ml_sharp_market_favorites": all(
                str(row.get("market_type") or "").lower() != "moneyline"
                or float(row.get("pinnacle_anchor_probability") or 0.0) >= 0.50
                for row in selections
            ),
            "all_spreads_from_expected_margin_0_4": all(
                str(row.get("market_type") or "").lower() != "spread"
                or "SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4"
                in set(str(row.get("model_candidate_regions") or "").split(";"))
                for row in selections
            ),
            "2025_absent": all(int(row["season"]) != SEALED_SEASON for row in selections),
        },
    }
    if not all(scorecard["invariants"].values()):
        raise RuntimeError(f"Balanced V2 product invariant failure: {scorecard['invariants']}")

    out.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(selections).write_csv(out / "balanced_v2_selections.csv")
    (out / "balanced_v2_scorecard.json").write_text(
        json.dumps(scorecard, indent=2, sort_keys=True) + "\n"
    )


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
