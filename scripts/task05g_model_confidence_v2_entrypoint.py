#!/usr/bin/env python3
"""Stable CLI entrypoint for the preregistered Task05G V2 experiment.

The core runner's V2 summaries contain model-confidence fields. Historical V1
baseline rows predate those fields, so this adapter makes summary aggregation
field-optional without changing any selector/calibration/threshold semantics.

It also makes Polars dict-row artifact serialization scan the complete V2 row
set for optional-column schema inference. That affects serialization only.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from statistics import mean
from typing import Any


def _load_core():
    path = Path(__file__).with_name("task05g_model_confidence_v2_runner.py")
    spec = importlib.util.spec_from_file_location("task05g_model_confidence_v2_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load V2 core runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _safe_summary_factory(core):
    def safe_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        wins = sum(str(r.get("settlement")) == "WIN" for r in rows)
        losses = sum(str(r.get("settlement")) == "LOSS" for r in rows)
        pushes = sum(str(r.get("settlement")) == "PUSH" for r in rows)
        nonpush = wins + losses
        q_values = [float(r["model_confidence_probability"]) for r in rows if r.get("model_confidence_probability") is not None]
        gap_values = [float(r["model_price_gap"]) for r in rows if r.get("model_price_gap") is not None]
        return {
            "plays": len(rows),
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "hit_rate_nonpush": None if nonpush == 0 else wins / nonpush,
            "roi": None if not rows else float(mean(float(r["realized_profit"]) for r in rows)),
            "avg_odds": None if not rows else float(mean(int(r["american_odds"]) for r in rows)),
            "avg_model_confidence_probability": None if not q_values else float(mean(q_values)),
            "avg_model_price_gap": None if not gap_values else float(mean(gap_values)),
            "max_losing_streak": core._longest_losing_streak(rows),
            "by_market": {
                market: {
                    "plays": sum(str(r.get("market_type")) == market for r in rows),
                    "roi": None
                    if not [r for r in rows if str(r.get("market_type")) == market]
                    else float(mean(float(r["realized_profit"]) for r in rows if str(r.get("market_type")) == market)),
                }
                for market in ("moneyline", "spread", "total")
            },
            "by_reliability": {
                tier: sum(str(r.get("reliability")) == tier for r in rows)
                for tier in ("HIGH", "MEDIUM", "LOW", "UNSUPPORTED")
            },
        }
    return safe_summary


def _enable_full_dict_schema_inference(core) -> None:
    original_dataframe = core.pl.DataFrame

    def dataframe(data=None, *args, **kwargs):
        if isinstance(data, list) and (not data or isinstance(data[0], dict)) and "infer_schema_length" not in kwargs:
            return core.pl.from_dicts(data, infer_schema_length=None)
        return original_dataframe(data, *args, **kwargs)

    core.pl.DataFrame = dataframe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--board", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--prereg", default="docs/task05g_model_confidence_v2_preregistration.md")
    args = parser.parse_args()

    core = _load_core()
    core._summary = _safe_summary_factory(core)
    _enable_full_dict_schema_inference(core)
    core.run(Path(args.root), Path(args.board), Path(args.out), Path(args.prereg))


if __name__ == "__main__":
    main()
