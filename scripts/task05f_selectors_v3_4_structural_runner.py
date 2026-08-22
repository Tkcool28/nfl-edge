#!/usr/bin/env python3
"""Task05F V3.4 structural replay with no outcome scoring.

Materializes the accepted 2020-2024 candidate board, enriches it with the
account-independent evaluated-wager board, and runs the thin selector. The
historical outcome sidecar is deliberately never opened.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
import tempfile
from typing import Any

import polars as pl

from nfl_edge.value.candidate_table import OUTCOME_FIELDS
from nfl_edge.value.evaluated_wager_board import (
    assert_candidate_fields_preserved,
    build_evaluated_wager_board,
)
from nfl_edge.value.selectors_v3_4 import select_primary_cards_v3_4

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_CONFIG = ROOT / "config/task05f_candidate_table_v1.yaml"
CANDIDATE_RUNNER = ROOT / "scripts/task05f_candidate_table_v1_runner.py"
DEV = [2020, 2021, 2022, 2023, 2024]
SEALED = {2025}
CARDS = ("HIGH_HIT_RATE", "BALANCED", "VALUE")


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _inc(bucket: dict[str, int], value: Any) -> None:
    key = str(value)
    bucket[key] = bucket.get(key, 0) + 1


def _finite(value: Any) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _card_counter() -> dict[str, Any]:
    return {
        "plays": 0,
        "no_play": 0,
        "market_mix": {},
        "price_status_mix": {},
        "reliability_mix": {},
        "unit_reason_mix": {},
        "units": [],
        "football_confidence_proxy": [],
    }


def run(root: Path, out: Path) -> None:
    root = root.resolve()
    candidate_runner = _load_script("task05f_v34_candidate_runtime", CANDIDATE_RUNNER)

    with tempfile.TemporaryDirectory(prefix="task05f_v34_structural_") as tmp:
        candidate_out = Path(tmp) / "candidate"
        candidate_runner.run(root, CANDIDATE_CONFIG, candidate_out)

        # Historical sidecar may be emitted by the shared candidate runner, but
        # this structural runner deliberately never opens or joins it.
        candidates_df = pl.read_parquet(candidate_out / "candidate_table.parquet")
        if candidates_df.height != 8448:
            raise RuntimeError(f"expected 8448 candidate rows, found {candidates_df.height}")
        if OUTCOME_FIELDS.intersection(candidates_df.columns):
            raise RuntimeError("outcome fields entered structural candidate table")

        seasons = sorted(int(x) for x in candidates_df["season"].unique().to_list())
        if seasons != DEV or set(seasons).intersection(SEALED):
            raise RuntimeError(f"unexpected seasons {seasons}")

        candidates = candidates_df.to_dicts()
        board = build_evaluated_wager_board(candidates)
        assert_candidate_fields_preserved(candidates, board)
        if any(OUTCOME_FIELDS.intersection(row) for row in board):
            raise RuntimeError("outcome fields entered evaluated wager board")

        blocks = sorted({str(row["block"]) for row in board})
        if len(blocks) != 109:
            raise RuntimeError(f"expected 109 slates, found {len(blocks)}")

        actionable_summary: dict[str, Any] = {
            "rows": len(board),
            "actionable": 0,
            "nonactionable": 0,
            "market_mix": {},
            "price_status_mix": {},
            "reliability_mix": {},
            "unit_reason_mix": {},
            "low_reliability_actionable": 0,
        }
        for row in board:
            if row["evaluator_actionable"]:
                actionable_summary["actionable"] += 1
                _inc(actionable_summary["market_mix"], row.get("market_type"))
                _inc(actionable_summary["price_status_mix"], row.get("price_status"))
                _inc(actionable_summary["reliability_mix"], row.get("reliability"))
                _inc(actionable_summary["unit_reason_mix"], row.get("evaluator_unit_reason"))
                if str(row.get("reliability")) == "LOW":
                    actionable_summary["low_reliability_actionable"] += 1
            else:
                actionable_summary["nonactionable"] += 1

        cards = {card: _card_counter() for card in CARDS}
        slate_card_counts = {0: 0, 1: 0, 2: 0, 3: 0}
        picks_out: list[dict[str, Any]] = []

        raw_top = {
            "slates_with_finite_above_half_confidence": 0,
            "evaluator_actionable": 0,
            "blocked": 0,
            "blocked_price_status_mix": {},
            "blocked_reliability_mix": {},
            "blocked_support_mix": {},
            "blocked_unit_reason_mix": {},
        }

        for block in blocks:
            slate = [row for row in board if str(row["block"]) == block]

            confidence_rows = [
                row
                for row in slate
                if _finite(row.get("football_confidence_z"))
                and _finite(row.get("football_cash_confidence_proxy"))
                and float(row["football_cash_confidence_proxy"]) > 0.5
            ]
            if confidence_rows:
                confidence_rows.sort(
                    key=lambda row: (-float(row["football_confidence_z"]), str(row["candidate_id"]))
                )
                top = confidence_rows[0]
                raw_top["slates_with_finite_above_half_confidence"] += 1
                if top["evaluator_actionable"]:
                    raw_top["evaluator_actionable"] += 1
                else:
                    raw_top["blocked"] += 1
                    _inc(raw_top["blocked_price_status_mix"], top.get("price_status"))
                    _inc(raw_top["blocked_reliability_mix"], top.get("reliability"))
                    _inc(raw_top["blocked_support_mix"], bool(top.get("supported")))
                    _inc(raw_top["blocked_unit_reason_mix"], top.get("evaluator_unit_reason"))

            picks = select_primary_cards_v3_4(slate)
            non_null = sum(pick is not None for pick in picks.values())
            slate_card_counts[non_null] += 1
            ids = [str(pick["candidate_id"]) for pick in picks.values() if pick is not None]
            if len(ids) != len(set(ids)):
                raise RuntimeError(f"duplicate featured candidate in block {block}")

            for card, pick in picks.items():
                counter = cards[card]
                if pick is None:
                    counter["no_play"] += 1
                    picks_out.append({"block": block, "card": card, "candidate": None})
                    continue
                counter["plays"] += 1
                _inc(counter["market_mix"], pick.get("market_type"))
                _inc(counter["price_status_mix"], pick.get("price_status"))
                _inc(counter["reliability_mix"], pick.get("reliability"))
                _inc(counter["unit_reason_mix"], pick.get("evaluator_unit_reason"))
                counter["units"].append(float(pick["evaluator_recommended_units"]))
                if _finite(pick.get("football_cash_confidence_proxy")):
                    counter["football_confidence_proxy"].append(
                        float(pick["football_cash_confidence_proxy"])
                    )
                picks_out.append(
                    {
                        "block": block,
                        "card": card,
                        "candidate_id": pick["candidate_id"],
                        "market_type": pick.get("market_type"),
                        "selection": pick.get("selection"),
                        "actionable_book": pick.get("actionable_book"),
                        "actionable_line": pick.get("actionable_line"),
                        "actionable_price_american": pick.get("actionable_price_american"),
                        "football_confidence_z": pick.get("football_confidence_z"),
                        "football_cash_confidence_proxy": pick.get("football_cash_confidence_proxy"),
                        "price_status": pick.get("price_status"),
                        "reliability": pick.get("reliability"),
                        "expected_value": pick.get("expected_value"),
                        "evaluator_recommended_units": pick.get("evaluator_recommended_units"),
                    }
                )

        for counter in cards.values():
            units = counter.pop("units")
            conf = counter.pop("football_confidence_proxy")
            counter["mean_units"] = None if not units else sum(units) / len(units)
            counter["min_units"] = None if not units else min(units)
            counter["max_units"] = None if not units else max(units)
            counter["mean_football_confidence_proxy"] = None if not conf else sum(conf) / len(conf)
            counter["min_football_confidence_proxy"] = None if not conf else min(conf)
            counter["max_football_confidence_proxy"] = None if not conf else max(conf)

        summary = {
            "version": "task05f_selector_v3_4_structural_replay",
            "candidate_rows": len(candidates),
            "evaluated_wager_rows": len(board),
            "slates": len(blocks),
            "development_seasons": DEV,
            "sealed_seasons": sorted(SEALED),
            "outcome_sidecar_opened": False,
            "historical_outcomes_scored": False,
            "bankroll_simulated": False,
            "actionability": actionable_summary,
            "raw_top_football_confidence": raw_top,
            "cards": cards,
            "slates_by_featured_card_count": {str(k): v for k, v in sorted(slate_card_counts.items())},
        }

        out.mkdir(parents=True, exist_ok=True)
        _write_json(out / "structural_summary.json", summary)
        _write_json(out / "selector_picks_no_outcomes.json", picks_out)
        _write_json(
            out / "provenance.json",
            {
                "outcome_sidecar_opened": False,
                "sealed_2025_loaded": False,
                "selector_version": "task05f_selectors_v3_4_thin",
                "wager_board_version": "task05f_evaluated_wager_board_v1",
                "staking_units_version": "task05f_staking_v2_1_units",
            },
        )
        print(json.dumps(summary, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.root, args.out)


if __name__ == "__main__":
    main()
