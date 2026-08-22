#!/usr/bin/env python3
"""Task05F Selector V3.2 structural replay with no outcome scoring.

The candidate table is materialized from the accepted frozen stack. This runner
never opens historical_outcomes.parquet and reports only card coverage/composition.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
from typing import Any

import polars as pl

from nfl_edge.value.candidate_table import OUTCOME_FIELDS
from nfl_edge.value.selectors_v3_2 import select_primary_cards_v3_2

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_CONFIG = ROOT / "config/task05f_candidate_table_v1.yaml"
CANDIDATE_RUNNER = ROOT / "scripts/task05f_candidate_table_v1_runner.py"
DEV = [2020, 2021, 2022, 2023, 2024]
SEALED = {2025}


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json_write(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


def run(root: Path, out: Path) -> None:
    root = root.resolve()
    candidate_runner = _load_script("task05f_v32_candidate_runtime", CANDIDATE_RUNNER)
    with tempfile.TemporaryDirectory(prefix="task05f_v32_structural_") as tmp:
        candidate_out = Path(tmp) / "candidate"
        candidate_runner.run(root, CANDIDATE_CONFIG, candidate_out)
        # Deliberately do not open candidate_out / historical_outcomes.parquet.
        df = pl.read_parquet(candidate_out / "candidate_table.parquet")

        if df.height != 8448:
            raise RuntimeError(f"expected 8448 candidate rows, found {df.height}")
        if OUTCOME_FIELDS.intersection(df.columns):
            raise RuntimeError("outcome fields entered structural candidate table")
        seasons = sorted(int(x) for x in df["season"].unique().to_list())
        if seasons != DEV or set(seasons).intersection(SEALED):
            raise RuntimeError(f"unexpected seasons {seasons}")

        rows = df.to_dicts()
        blocks = sorted({str(row["block"]) for row in rows})
        if len(blocks) != 109:
            raise RuntimeError(f"expected 109 slates, found {len(blocks)}")

        picks_out: list[dict[str, Any]] = []
        counts: dict[str, dict[str, Any]] = {
            card: {
                "plays": 0,
                "no_play": 0,
                "market_mix": {},
                "price_status_mix": {},
                "reliability_mix": {},
            }
            for card in ("HIGH_HIT_RATE", "BALANCED", "VALUE")
        }
        slate_card_counts = {0: 0, 1: 0, 2: 0, 3: 0}

        for block in blocks:
            slate = [row for row in rows if str(row["block"]) == block]
            picks = select_primary_cards_v3_2(slate)
            non_null = sum(pick is not None for pick in picks.values())
            slate_card_counts[non_null] += 1
            ids = [str(pick["candidate_id"]) for pick in picks.values() if pick is not None]
            if len(ids) != len(set(ids)):
                raise RuntimeError(f"duplicate featured candidate in block {block}")

            for card, pick in picks.items():
                if pick is None:
                    counts[card]["no_play"] += 1
                    picks_out.append({"block": block, "card": card, "candidate": None})
                    continue
                counts[card]["plays"] += 1
                for field, key in (
                    ("market_type", "market_mix"),
                    ("price_status", "price_status_mix"),
                    ("reliability", "reliability_mix"),
                ):
                    value = str(pick.get(field))
                    counts[card][key][value] = counts[card][key].get(value, 0) + 1
                record = {
                    "block": block,
                    "card": card,
                    "candidate_id": pick["candidate_id"],
                    "market_type": pick["market_type"],
                    "selection": pick["selection"],
                    "raw_football_output": pick.get("raw_football_output"),
                    "actionable_probability": pick.get("actionable_probability"),
                    "price_status": pick.get("price_status"),
                    "reliability": pick.get("reliability"),
                    "expected_value": pick.get("expected_value"),
                }
                if card == "HIGH_HIT_RATE":
                    record["model_native_hit_probability"] = pick["model_native_hit_probability"]
                    record["hhr_price_actionable"] = pick["hhr_price_actionable"]
                if card == "BALANCED":
                    record["model_native_strength"] = pick["model_native_strength"]
                    record["balanced_native_hit_rank_within_market"] = pick["balanced_native_hit_rank_within_market"]
                    record["balanced_price_quality_rank"] = pick["balanced_price_quality_rank"]
                picks_out.append(record)

        summary = {
            "version": "task05f_selectors_v3_2_structural_replay",
            "outcomes_opened": False,
            "candidate_rows": len(rows),
            "development_seasons": DEV,
            "sealed_seasons": sorted(SEALED),
            "slates": len(blocks),
            "cards": counts,
            "slates_by_featured_card_count": {str(k): v for k, v in sorted(slate_card_counts.items())},
        }
        out.mkdir(parents=True, exist_ok=True)
        _json_write(out / "structural_summary.json", summary)
        _json_write(out / "selector_picks_no_outcomes.json", picks_out)
        print(json.dumps(summary, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.root, args.out)


if __name__ == "__main__":
    main()
