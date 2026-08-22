#!/usr/bin/env python3
"""Task05F Phase G: preregistered global Play Through policy.

Phase G is a pure downstream product-policy enrichment of accepted Phase F V1.1.
It may populate a small confidence-scaled price tolerance and presentation status,
but it may not change evaluator probability, strict EV/Value, reliability,
uncertainty, staking probability, or any football-model output. 2025 is sealed.

The maximum Play Through concession is read from the preregistered config. This
keeps completed V1 (1.0pp) reproducible while allowing the separately
preregistered V1.1 product policy (1.5pp) to use the exact same implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

import polars as pl
import yaml

from nfl_edge.value.play_through import assess_play_through


ROOT = Path(__file__).resolve().parents[1]
DEV = [2020, 2021, 2022, 2023, 2024]
SEALED = {2025}
VERSION = "task05f_play_through_v1"
PREREG = ROOT / "config" / "task05f_play_through_v1_prereg.yaml"
PHASE_F_RUNNER = ROOT / "scripts" / "task05f_reliability_uncertainty_v1_1_runner.py"
PHASE_F_CONFIG = ROOT / "config" / "task05f_reliability_uncertainty_v1_1_prereg.yaml"

IDENTITY_FIELDS = [
    "game_id", "season", "week", "block", "market_type", "selected_side",
    "sportsbook", "line", "american_odds",
]
PRESERVED_FIELDS = [
    "p_win", "p_push", "p_loss", "actionable_probability",
    "fair_price_american", "expected_value", "strict_positive_value", "supported",
    "uncertainty", "uncertainty_support_n", "uncertainty_block_count",
    "candidate_uncertainty_tier", "base_reliability", "reliability",
    "conditional_nonpush_probability", "staking_anchor_probability",
    "staking_probability", "staking_p_win", "staking_p_push", "staking_p_loss",
    "staking_expected_value", "break_even_probability",
    "evaluated_edge_probability", "staking_edge_probability",
]
STATUSES = ("VALUE", "PLAYABLE", "LEAN", "PASS")


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


def _assert_unsealed(seasons) -> None:
    bad = SEALED.intersection({int(x) for x in seasons})
    if bad:
        raise RuntimeError(f"SEALED season requested: {sorted(bad)}")


def _preserved_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = IDENTITY_FIELDS + PRESERVED_FIELDS
    payload = [{field: row.get(field) for field in fields} for row in rows]
    payload.sort(
        key=lambda item: json.dumps(
            {field: item.get(field) for field in IDENTITY_FIELDS},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return payload


def _payload_hash(payload: list[dict[str, Any]]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _roi(rows: list[dict[str, Any]]) -> float | None:
    if not rows:
        return None
    return float(sum(float(row["realized_profit"]) for row in rows) / len(rows))


def _counts(rows: list[dict[str, Any]], key: str, values) -> dict[str, int]:
    return {str(value): sum(str(row.get(key)) == str(value) for row in rows) for value in values}


def _runtime_version(cfg: dict[str, Any]) -> str:
    value = str(cfg.get("version", VERSION))
    return value[:-7] if value.endswith("_prereg") else value


def run(root: Path, config_path: Path, out: Path) -> None:
    cfg, config_sha = _read_yaml(config_path)
    _assert_unsealed(cfg["development_seasons"])
    runtime_version = _runtime_version(cfg)
    maximum_concession = float(cfg["play_through_policy"]["maximum_break_even_concession"])
    if not 0.0 <= maximum_concession <= 0.05:
        raise RuntimeError("Play Through maximum concession is outside the bounded product-policy range")

    phase_f = _load_script("task05f_phase_g_phase_f_runtime", PHASE_F_RUNNER)

    with tempfile.TemporaryDirectory(prefix="task05f_phase_g_base_") as tmp:
        base_out = Path(tmp) / "phase_f"
        phase_f.run(root, PHASE_F_CONFIG, base_out)
        base_df = pl.read_parquet(base_out / "full_board.parquet")
        if set(int(x) for x in base_df["season"].unique().to_list()).intersection(SEALED):
            raise RuntimeError("SEALED 2025 row entered Phase G board")
        base_rows = base_df.to_dicts()
        before_payload = _preserved_payload(base_rows)
        before_hash = _payload_hash(before_payload)

        enriched: list[dict[str, Any]] = []
        for base in base_rows:
            row = dict(base)
            assessment = assess_play_through(
                supported=bool(row.get("supported")),
                strict_expected_value=row.get("expected_value"),
                conditional_nonpush_probability=row.get("conditional_nonpush_probability"),
                current_break_even_probability=row.get("break_even_probability"),
                reliability=str(row.get("reliability")),
                uncertainty_radius=row.get("uncertainty"),
                maximum_concession=maximum_concession,
            )
            row.update(
                {
                    "play_through_confidence_multiplier": assessment.confidence_multiplier,
                    "play_through_break_even_concession": assessment.break_even_concession,
                    "play_through_break_even_probability": assessment.play_through_break_even_probability,
                    "play_through_decimal_price": assessment.play_through_decimal_price,
                    "play_through_price_american": assessment.play_through_price_american,
                    "price_status": assessment.status,
                }
            )
            enriched.append(row)

        after_payload = _preserved_payload(enriched)
        after_hash = _payload_hash(after_payload)
        preserved_equal = before_payload == after_payload
        if not preserved_equal or before_hash != after_hash:
            raise RuntimeError("Phase G modified evaluator/Phase-F preserved fields")

        strict_value_unchanged = all(
            bool(base.get("strict_positive_value")) == bool(row.get("strict_positive_value"))
            for base, row in zip(base_rows, enriched)
        )
        negative_never_value = all(
            not (
                row.get("expected_value") is not None
                and float(row["expected_value"]) <= 0.0
                and row["price_status"] == "VALUE"
            )
            for row in enriched
        )
        playable_within_limit = all(
            row["price_status"] != "PLAYABLE"
            or (
                row.get("break_even_probability") is not None
                and row.get("play_through_break_even_probability") is not None
                and float(row["break_even_probability"])
                <= float(row["play_through_break_even_probability"]) + 1e-12
            )
            for row in enriched
        )
        if not strict_value_unchanged or not negative_never_value or not playable_within_limit:
            raise RuntimeError("Phase G violated strict Value or Play Through status contract")

        out.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(enriched, infer_schema_length=None).write_parquet(
            out / "full_board.parquet", compression="zstd"
        )

        status_rows: list[dict[str, Any]] = []
        season_rows: list[dict[str, Any]] = []
        concession_rows: list[dict[str, Any]] = []
        score_markets: dict[str, Any] = {}
        for market in ("moneyline", "spread", "total"):
            rr = [row for row in enriched if row["market_type"] == market]
            score_markets[market] = {
                "rows": len(rr),
                "status_counts": _counts(rr, "price_status", STATUSES),
                "reliability_counts": _counts(
                    rr, "reliability", ("HIGH", "MEDIUM", "LOW", "UNSUPPORTED")
                ),
            }
            for status in STATUSES:
                xs = [row for row in rr if row["price_status"] == status]
                ev_material = [
                    float(row["expected_value"])
                    for row in xs
                    if row.get("expected_value") is not None
                ]
                status_rows.append(
                    {
                        "market_type": market,
                        "status": status,
                        "n": len(xs),
                        "realized_roi": _roi(xs),
                        "mean_strict_ev": (
                            None if not ev_material else float(sum(ev_material) / len(ev_material))
                        ),
                    }
                )
            for season in DEV:
                xs = [row for row in rr if int(row["season"]) == season]
                season_rows.append(
                    {
                        "market_type": market,
                        "season": season,
                        **{
                            status.lower(): sum(row["price_status"] == status for row in xs)
                            for status in STATUSES
                        },
                    }
                )
            supported = [row for row in rr if row.get("supported")]
            concessions = [
                float(row["play_through_break_even_concession"]) for row in supported
            ]
            confidences = [
                float(row["play_through_confidence_multiplier"]) for row in supported
            ]
            concession_rows.append(
                {
                    "market_type": market,
                    "supported": len(supported),
                    "mean_confidence": (
                        None if not confidences else float(sum(confidences) / len(confidences))
                    ),
                    "max_confidence": None if not confidences else max(confidences),
                    "mean_break_even_concession": (
                        None if not concessions else float(sum(concessions) / len(concessions))
                    ),
                    "max_break_even_concession": None if not concessions else max(concessions),
                }
            )

        pl.DataFrame(status_rows, infer_schema_length=None).write_csv(out / "status_diagnostics.csv")
        pl.DataFrame(season_rows, infer_schema_length=None).write_csv(out / "per_season_status_mix.csv")
        pl.DataFrame(concession_rows, infer_schema_length=None).write_csv(
            out / "play_through_concession_summary.csv"
        )

        reproduction = {
            "phase_f_version": "task05f_reliability_uncertainty_v1_1",
            "phase_f_rows": len(base_rows),
            "phase_g_rows": len(enriched),
            "preserved_fields": PRESERVED_FIELDS,
            "preserved_payload_sha256_before": before_hash,
            "preserved_payload_sha256_after": after_hash,
            "preserved_rows_equal": preserved_equal,
            "strict_value_labels_unchanged": strict_value_unchanged,
            "negative_ev_never_value": negative_never_value,
            "playable_within_preregistered_limit": playable_within_limit,
            "maximum_break_even_concession": maximum_concession,
        }
        _json_write(out / "phase_f_reproduction.json", reproduction)

        for name in (
            "base_reproduction.json",
            "component_reproduction.json",
            "frozen_edge_preservation.json",
            "ev_calibration.csv",
            "uncertainty_state_by_block.ndjson",
            "per_season_reliability_mix.csv",
        ):
            shutil.copy2(base_out / name, out / name)

        _json_write(
            out / "scorecard.json",
            {
                "version": runtime_version,
                "prereg_config_sha256": config_sha,
                "development_seasons": DEV,
                "sealed_seasons": [2025],
                "maximum_break_even_concession": maximum_concession,
                "policy": (
                    f"max {maximum_concession * 100:.1f}pp break-even concession "
                    "scaled by Phase F confidence"
                ),
                "markets": score_markets,
                "phase_f_reproduction": reproduction,
                "selector_scoring": "NOT_SCORED_IN_PHASE_G",
                "acceptance_status": "EVIDENCE_PENDING_MASTER_REVIEW",
            },
        )
        _json_write(
            out / "provenance.json",
            {
                "version": runtime_version,
                "github_sha": os.environ.get("GITHUB_SHA"),
                "scope": "evaluator_only_play_through_product_policy",
                "prereg_path": str(config_path.relative_to(root)),
                "prereg_config_sha256": config_sha,
                "phase_f_config": str(PHASE_F_CONFIG.relative_to(root)),
                "maximum_break_even_concession": maximum_concession,
                "development_seasons": DEV,
                "sealed_seasons": [2025],
                "new_observation_policy": "OBSERVATIONAL_ONLY_NOT_TUNED",
            },
        )
        _json_write(
            out / "observations.json",
            {
                "label": "OBSERVATIONAL_ONLY_NOT_TUNED",
                "items": [],
                "note": (
                    "Play Through does not alter its preregistered formula from "
                    "historical status/ROI diagnostics."
                ),
            },
        )

    print(
        json.dumps(
            {
                "version": runtime_version,
                "rows": len(enriched),
                "maximum_break_even_concession": maximum_concession,
                "markets": score_markets,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(PREREG))
    parser.add_argument(
        "--out", default=str(ROOT / "artifacts" / "task05f" / "play_through_v1")
    )
    args = parser.parse_args()
    run(ROOT, Path(args.config), Path(args.out))
