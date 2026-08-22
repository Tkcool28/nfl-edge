#!/usr/bin/env python3
"""Task05F 2020-2024 diagnostic product simulation V2.

Uses Selector V3.1 + evaluator-unit Staking V2. This is post-hoc diagnostic
product/risk evidence only; it cannot promote or tune the selector or staking
policy. Season 2025 remains sealed.

Selections and evaluator units are frozen before the historical outcome sidecar
is exposed. All wagers on a slate use the same start-of-slate bankroll.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

import polars as pl
import yaml

from nfl_edge.user.staking_profile_v2 import RiskStyle, UserRiskProfile
from nfl_edge.value.candidate_table import OUTCOME_FIELDS
from nfl_edge.value.selectors_v3_1 import PRIMARY_CARDS, select_primary_cards_v3_1
from nfl_edge.value.staking_v2 import evaluator_units, recommend_stake_v2


ROOT = Path(__file__).resolve().parents[1]
DEV = [2020, 2021, 2022, 2023, 2024]
SEALED = {2025}
VERSION = "task05f_product_simulation_v2"
CONFIG = ROOT / "config/task05f_product_simulation_v2.yaml"
CANDIDATE_CONFIG = ROOT / "config/task05f_candidate_table_v1.yaml"
CANDIDATE_RUNNER = ROOT / "scripts/task05f_candidate_table_v1_runner.py"
SELECTOR_CONFIG = ROOT / "config/task05f_selectors_v3_1_product_prereg.yaml"
STAKING_CONFIG = ROOT / "config/task05f_staking_v2_units_prereg.yaml"


class ProductSimulationV2Error(RuntimeError):
    pass


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


def _logical_hash(rows: list[dict[str, Any]]) -> str:
    ordered = sorted(rows, key=lambda row: str(row["candidate_id"]))
    raw = json.dumps(ordered, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _normalize_settlement(value: Any) -> str:
    text = str(value).strip().upper()
    if text.endswith(".WIN") or text == "WIN":
        return "WIN"
    if text.endswith(".PUSH") or text == "PUSH":
        return "PUSH"
    if text.endswith(".LOSS") or text == "LOSS":
        return "LOSS"
    raise ProductSimulationV2Error(f"unknown settlement {value!r}")


def _track(initial: float) -> dict[str, Any]:
    return {
        "initial": float(initial),
        "bankroll": float(initial),
        "peak": float(initial),
        "minimum": float(initial),
        "max_drawdown_pct": 0.0,
        "recommended_card_count": 0,
        "positive_stake_count": 0,
        "total_amount_staked": 0.0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
    }


def _settle_track(track: dict[str, Any], profit: float) -> None:
    track["bankroll"] = max(0.0, float(track["bankroll"]) + float(profit))
    track["peak"] = max(float(track["peak"]), float(track["bankroll"]))
    track["minimum"] = min(float(track["minimum"]), float(track["bankroll"]))
    peak = float(track["peak"])
    dd = 0.0 if peak <= 0.0 else (peak - float(track["bankroll"])) / peak
    track["max_drawdown_pct"] = max(float(track["max_drawdown_pct"]), float(dd))


def _final_track(track: dict[str, Any]) -> dict[str, Any]:
    initial = float(track["initial"])
    ending = float(track["bankroll"])
    return {
        "starting_bankroll": initial,
        "ending_bankroll": ending,
        "return_pct": None if initial <= 0.0 else ending / initial - 1.0,
        "recommended_card_count": int(track["recommended_card_count"]),
        "positive_stake_count": int(track["positive_stake_count"]),
        "total_amount_staked": float(track["total_amount_staked"]),
        "max_drawdown_pct": float(track["max_drawdown_pct"]),
        "minimum_bankroll": float(track["minimum"]),
        "wins": int(track["wins"]),
        "losses": int(track["losses"]),
        "pushes": int(track["pushes"]),
    }


def _summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "min": None, "mean": None, "max": None}
    return {
        "n": len(values),
        "min": float(min(values)),
        "mean": float(sum(values) / len(values)),
        "max": float(max(values)),
    }


def _count_mix(records: list[dict[str, Any]], field: str) -> dict[str, int]:
    values = sorted({str(record[field]) for record in records})
    return {value: sum(str(record[field]) == value for record in records) for value in values}


def run(root: Path, config_path: Path, out: Path) -> None:
    root = root.resolve()
    if not config_path.is_absolute():
        config_path = (root / config_path).resolve()
    cfg, config_sha = _read_yaml(config_path)
    _, selector_sha = _read_yaml(SELECTOR_CONFIG)
    _, staking_sha = _read_yaml(STAKING_CONFIG)
    _, candidate_sha = _read_yaml(CANDIDATE_CONFIG)

    if cfg["status"] != "PREREGISTERED_BEFORE_V3_1_STAKING_V2_2020_2024_PRODUCT_SIMULATION":
        raise ProductSimulationV2Error("product simulation V2 preregistration status mismatch")
    if cfg["results_label"] != "OBSERVATIONAL_ONLY_NOT_TUNED":
        raise ProductSimulationV2Error("diagnostic result label mismatch")
    if [int(x) for x in cfg["development_seasons"]] != DEV:
        raise ProductSimulationV2Error("development-season contract mismatch")
    if set(int(x) for x in cfg["sealed_seasons"]) != SEALED:
        raise ProductSimulationV2Error("sealed-season contract mismatch")

    candidate_runner = _load_script("task05f_product_v2_candidate_runtime", CANDIDATE_RUNNER)
    with tempfile.TemporaryDirectory(prefix="task05f_product_v2_candidate_") as tmp:
        candidate_out = Path(tmp) / "candidate"
        candidate_runner.run(root, CANDIDATE_CONFIG, candidate_out)
        candidate_df = pl.read_parquet(candidate_out / "candidate_table.parquet")
        outcome_df = pl.read_parquet(candidate_out / "historical_outcomes.parquet")

        if OUTCOME_FIELDS.intersection(candidate_df.columns):
            raise ProductSimulationV2Error("outcome field entered production candidate table")
        seasons = sorted(int(x) for x in candidate_df["season"].unique().to_list())
        if seasons != DEV or set(seasons).intersection(SEALED):
            raise ProductSimulationV2Error(f"unexpected candidate seasons {seasons}")
        if candidate_df.height != 8448 or outcome_df.height != 8448:
            raise ProductSimulationV2Error("candidate/outcome fixture row count mismatch")

        candidate_rows = candidate_df.to_dicts()
        candidate_hash_before = _logical_hash(candidate_rows)
        blocks = sorted({str(row["block"]) for row in candidate_rows})
        if len(blocks) != int(cfg["expected_slates"]):
            raise ProductSimulationV2Error(
                f"expected {cfg['expected_slates']} slates, found {len(blocks)}"
            )

        # Freeze featured selections AND evaluator-owned unit ratings before
        # constructing any historical outcome lookup.
        picks_by_block: dict[str, dict[str, dict[str, Any] | None]] = {}
        selected_records: list[dict[str, Any]] = []
        unit_records: list[dict[str, Any]] = []
        no_play_counts = {card: 0 for card in PRIMARY_CARDS}
        for block in blocks:
            slate = [row for row in candidate_rows if str(row["block"]) == block]
            slate_seasons = {int(row["season"]) for row in slate}
            slate_weeks = {str(row["week"]) for row in slate}
            if len(slate_seasons) != 1 or len(slate_weeks) != 1:
                raise ProductSimulationV2Error(f"block {block} is not one season-week slate")
            season = next(iter(slate_seasons))
            week = next(iter(slate_weeks))
            picks = select_primary_cards_v3_1(slate)
            ids = [str(pick["candidate_id"]) for pick in picks.values() if pick is not None]
            if len(ids) != len(set(ids)):
                raise ProductSimulationV2Error(f"duplicate featured candidate identity in {block}")
            picks_by_block[block] = picks
            for card in PRIMARY_CARDS:
                pick = picks[card]
                if pick is None:
                    no_play_counts[card] += 1
                    selected_records.append(
                        {
                            "block": block,
                            "season": season,
                            "week": week,
                            "card": card,
                            "candidate_id": None,
                            "candidate": None,
                        }
                    )
                    continue
                units, unit_reason = evaluator_units(pick)
                if units <= 0.0:
                    raise ProductSimulationV2Error(
                        f"featured actionable card {card} in {block} received zero units: {unit_reason}"
                    )
                selected_records.append(
                    {
                        "block": block,
                        "season": season,
                        "week": week,
                        "card": card,
                        "candidate_id": str(pick["candidate_id"]),
                        "candidate": pick,
                    }
                )
                unit_records.append(
                    {
                        "block": block,
                        "season": season,
                        "week": week,
                        "card": card,
                        "candidate_id": str(pick["candidate_id"]),
                        "market_type": str(pick["market_type"]),
                        "price_status": str(pick["price_status"]),
                        "reliability": str(pick["reliability"]),
                        "recommended_units": float(units),
                        "unit_reason": unit_reason,
                    }
                )

        candidate_hash_after = _logical_hash(candidate_rows)
        if candidate_hash_before != candidate_hash_after:
            raise ProductSimulationV2Error("selector/staking mutated candidate table")

        # Outcomes become available only after selections and unit ratings are frozen.
        outcome_map: dict[str, dict[str, Any]] = {}
        for row in outcome_df.to_dicts():
            cid = str(row["candidate_id"])
            if cid in outcome_map:
                raise ProductSimulationV2Error(f"duplicate outcome row {cid}")
            outcome_map[cid] = row

        profile_cfgs = {str(item["id"]): dict(item) for item in cfg["simulated_profiles"]}
        per_card_tracks = {
            profile_id: {
                card: _track(float(item["initial_bankroll"])) for card in PRIMARY_CARDS
            }
            for profile_id, item in profile_cfgs.items()
        }
        portfolio_tracks = {
            profile_id: {
                **_track(float(item["initial_bankroll"])),
                "maximum_single_slate_exposure_pct": 0.0,
                "configured_exposure_cap_pct": None,
            }
            for profile_id, item in profile_cfgs.items()
        }

        stake_ledger: list[dict[str, Any]] = []
        for block in blocks:
            picks = picks_by_block[block]
            for profile_id, item in profile_cfgs.items():
                style = RiskStyle(str(item["risk_style"]))

                # Independent per-card tracks.
                for card in PRIMARY_CARDS:
                    pick = picks[card]
                    track = per_card_tracks[profile_id][card]
                    if pick is None:
                        continue
                    track["recommended_card_count"] += 1
                    start_bankroll = float(track["bankroll"])
                    if start_bankroll <= 0.0:
                        continue
                    profile = UserRiskProfile(start_bankroll, style)
                    rec = recommend_stake_v2(pick, profile)
                    stake = float(rec.recommended_stake)
                    if stake <= 0.0:
                        raise ProductSimulationV2Error(
                            f"featured wager unexpectedly received zero stake: {block} {profile_id} {card}"
                        )
                    outcome = outcome_map[str(pick["candidate_id"])]
                    settlement = _normalize_settlement(outcome["settlement"])
                    unit_profit = float(outcome["realized_profit"])
                    dollar_profit = stake * unit_profit
                    track["positive_stake_count"] += 1
                    track["total_amount_staked"] += stake
                    track[{"WIN": "wins", "LOSS": "losses", "PUSH": "pushes"}[settlement]] += 1
                    _settle_track(track, dollar_profit)
                    stake_ledger.append(
                        {
                            "block": block,
                            "profile": profile_id,
                            "track": card,
                            "candidate_id": str(pick["candidate_id"]),
                            "price_status": str(pick["price_status"]),
                            "recommended_units": float(rec.recommended_units),
                            "start_bankroll": start_bankroll,
                            "recommended_stake": stake,
                            "stake_fraction": float(rec.recommended_stake_fraction),
                            "settlement": settlement,
                            "realized_profit_per_unit": unit_profit,
                            "dollar_profit": dollar_profit,
                            "end_bankroll": float(track["bankroll"]),
                        }
                    )

                # Combined featured portfolio. Every wager uses the same start-of-slate
                # bankroll. Exposure capacity is consumed in the selector's duplicate-
                # resolution order only if rounding would otherwise touch the style cap.
                portfolio = portfolio_tracks[profile_id]
                start_bankroll = float(portfolio["bankroll"])
                if start_bankroll <= 0.0:
                    continue
                profile = UserRiskProfile(start_bankroll, style)
                portfolio["configured_exposure_cap_pct"] = profile.open_slate_exposure_cap_fraction
                open_exposure = 0.0
                frozen_wagers: list[tuple[str, dict[str, Any], Any]] = []
                for card in ("VALUE", "HIGH_HIT_RATE", "BALANCED"):
                    pick = picks[card]
                    if pick is None:
                        continue
                    rec = recommend_stake_v2(
                        pick,
                        profile,
                        current_open_exposure_amount=open_exposure,
                    )
                    if rec.recommended_stake <= 0.0:
                        raise ProductSimulationV2Error(
                            f"featured portfolio wager unexpectedly capped to zero: {block} {profile_id} {card}"
                        )
                    frozen_wagers.append((card, pick, rec))
                    open_exposure += float(rec.recommended_stake)

                exposure_fraction = 0.0 if start_bankroll <= 0.0 else open_exposure / start_bankroll
                if exposure_fraction > profile.open_slate_exposure_cap_fraction + 1e-12:
                    raise ProductSimulationV2Error(
                        f"style exposure cap exceeded: {block} {profile_id} {exposure_fraction}"
                    )
                portfolio["maximum_single_slate_exposure_pct"] = max(
                    float(portfolio["maximum_single_slate_exposure_pct"]), exposure_fraction
                )
                portfolio["total_amount_staked"] += open_exposure

                slate_profit = 0.0
                for card, pick, rec in frozen_wagers:
                    outcome = outcome_map[str(pick["candidate_id"])]
                    settlement = _normalize_settlement(outcome["settlement"])
                    unit_profit = float(outcome["realized_profit"])
                    dollar_profit = float(rec.recommended_stake) * unit_profit
                    slate_profit += dollar_profit
                    portfolio["positive_stake_count"] += 1
                    portfolio[{"WIN": "wins", "LOSS": "losses", "PUSH": "pushes"}[settlement]] += 1
                    stake_ledger.append(
                        {
                            "block": block,
                            "profile": profile_id,
                            "track": "COMBINED_FEATURED",
                            "card": card,
                            "candidate_id": str(pick["candidate_id"]),
                            "price_status": str(pick["price_status"]),
                            "recommended_units": float(rec.recommended_units),
                            "start_bankroll": start_bankroll,
                            "recommended_stake": float(rec.recommended_stake),
                            "stake_fraction": float(rec.recommended_stake_fraction),
                            "settlement": settlement,
                            "realized_profit_per_unit": unit_profit,
                            "dollar_profit": dollar_profit,
                            "end_bankroll": None,
                        }
                    )
                _settle_track(portfolio, slate_profit)

        per_card_summary = {
            profile_id: {card: _final_track(track) for card, track in card_tracks.items()}
            for profile_id, card_tracks in per_card_tracks.items()
        }
        portfolio_summary: dict[str, Any] = {}
        for profile_id, track in portfolio_tracks.items():
            base = _final_track(track)
            base["maximum_single_slate_exposure_pct"] = float(
                track["maximum_single_slate_exposure_pct"]
            )
            base["configured_exposure_cap_pct"] = float(track["configured_exposure_cap_pct"])
            portfolio_summary[profile_id] = base

        selector_records = [
            record["candidate"]
            for record in selected_records
            if record["candidate"] is not None
        ]
        selector_diagnostics: dict[str, Any] = {}
        units_diagnostics: dict[str, Any] = {}
        for card in PRIMARY_CARDS:
            card_candidates = [
                record["candidate"]
                for record in selected_records
                if record["card"] == card and record["candidate"] is not None
            ]
            card_units = [
                float(record["recommended_units"])
                for record in unit_records
                if record["card"] == card
            ]
            selector_diagnostics[card] = {
                "plays": len(card_candidates),
                "no_play_count": int(no_play_counts[card]),
                "market_mix": _count_mix(card_candidates, "market_type") if card_candidates else {},
                "price_status_mix": _count_mix(card_candidates, "price_status") if card_candidates else {},
                "reliability_mix": _count_mix(card_candidates, "reliability") if card_candidates else {},
            }
            units_diagnostics[card] = _summary(card_units)

        playable_units_values = [
            float(record["recommended_units"])
            for record in unit_records
            if record["price_status"] == "PLAYABLE"
        ]
        value_units_values = [
            float(record["recommended_units"])
            for record in unit_records
            if record["price_status"] == "VALUE"
        ]

        out.mkdir(parents=True, exist_ok=True)
        _json_write(out / "selector_picks.json", selected_records)
        pl.DataFrame(unit_records, infer_schema_length=None).write_csv(out / "unit_assignments.csv")
        pl.DataFrame(stake_ledger, infer_schema_length=None).write_csv(out / "stake_ledger.csv")
        _json_write(out / "per_card_bankroll.json", per_card_summary)
        _json_write(out / "portfolio_bankroll.json", portfolio_summary)
        _json_write(
            out / "diagnostics.json",
            {
                "label": "OBSERVATIONAL_ONLY_NOT_TUNED",
                "selector": selector_diagnostics,
                "units_by_card": units_diagnostics,
                "playable_units": _summary(playable_units_values),
                "value_units": _summary(value_units_values),
                "all_non_null_featured_candidate_ids_distinct": True,
                "selector_records": len(selector_records),
            },
        )
        _json_write(
            out / "candidate_reproduction.json",
            {
                "candidate_rows": len(candidate_rows),
                "candidate_logical_sha256_before": candidate_hash_before,
                "candidate_logical_sha256_after": candidate_hash_after,
                "candidate_rows_immutable": candidate_hash_before == candidate_hash_after,
                "outcome_fields_in_candidate_table": sorted(OUTCOME_FIELDS.intersection(candidate_df.columns)),
                "selection_and_units_frozen_before_outcome_join": True,
            },
        )
        _json_write(
            out / "scorecard.json",
            {
                "version": VERSION,
                "label": "OBSERVATIONAL_ONLY_NOT_TUNED",
                "development_seasons": DEV,
                "sealed_seasons": [2025],
                "total_slates": len(blocks),
                "selector": selector_diagnostics,
                "units": {
                    "by_card": units_diagnostics,
                    "playable": _summary(playable_units_values),
                    "value": _summary(value_units_values),
                },
                "per_card_bankroll": per_card_summary,
                "combined_featured_portfolio": portfolio_summary,
                "historical_roi_is_acceptance_gate": False,
                "historical_hit_rate_is_acceptance_gate": False,
                "may_tune_from_results": False,
                "production_promotion": False,
            },
        )
        _json_write(
            out / "provenance.json",
            {
                "version": VERSION,
                "github_sha": os.environ.get("GITHUB_SHA"),
                "config_path": str(config_path.relative_to(root)),
                "config_sha256": config_sha,
                "candidate_config_sha256": candidate_sha,
                "selector_v3_1_config_sha256": selector_sha,
                "staking_v2_config_sha256": staking_sha,
                "development_seasons": DEV,
                "sealed_seasons": [2025],
                "results_label": "OBSERVATIONAL_ONLY_NOT_TUNED",
                "outcome_join_after_selection_and_units": True,
                "product_simulation_v1": "SUPERSEDED_NOT_EVIDENCE",
            },
        )

        # Stable textual summary for CI logs without changing evidence semantics.
        print(
            json.dumps(
                {
                    "total_slates": len(blocks),
                    "selector": selector_diagnostics,
                    "units": {
                        "playable": _summary(playable_units_values),
                        "value": _summary(value_units_values),
                    },
                    "portfolio": portfolio_summary,
                },
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--out", default=str(ROOT / "artifacts/task05f/product_simulation_v2"))
    args = parser.parse_args()
    run(ROOT, Path(args.config), Path(args.out))
