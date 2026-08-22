#!/usr/bin/env python3
"""Task05F 2020-2024 diagnostic product/bankroll simulation.

This runner is intentionally post-hoc diagnostic evidence, not Selector V3
acceptance evidence. Selector V3 was designed after V1/V2 development outcomes
were observed. The clean selector/staking outcome test remains sealed 2025.

Selections and stakes are frozen before the historical outcome sidecar is read
into a lookup. All wagers on one slate use the same start-of-slate bankroll.
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

from nfl_edge.user.staking_profile import FlatStakeMode, StakingStrategy, UserStakingProfile
from nfl_edge.value.candidate_table import OUTCOME_FIELDS
from nfl_edge.value.selectors import PRIMARY_CARDS
from nfl_edge.value.selectors_v3 import select_primary_cards_v3
from nfl_edge.value.staking import recommend_stake


ROOT = Path(__file__).resolve().parents[1]
DEV = [2020, 2021, 2022, 2023, 2024]
SEALED = {2025}
VERSION = "task05f_product_simulation_v1"
CONFIG = ROOT / "config/task05f_product_simulation_v1.yaml"
CANDIDATE_CONFIG = ROOT / "config/task05f_candidate_table_v1.yaml"
CANDIDATE_RUNNER = ROOT / "scripts/task05f_candidate_table_v1_runner.py"
SELECTOR_CONFIG = ROOT / "config/task05f_selectors_v3_capability_prereg.yaml"
STAKING_CONFIG = ROOT / "config/task05f_staking_v1.yaml"
PRODUCT_CONFIG = ROOT / "config/task05f_product_interface_v1.yaml"


class ProductSimulationError(RuntimeError):
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
    raise ProductSimulationError(f"unknown settlement {value!r}")


def _profile_from_config(item: dict[str, Any], bankroll: float) -> UserStakingProfile:
    strategy = StakingStrategy(str(item["staking_strategy"]))
    mode = FlatStakeMode(str(item.get("flat_stake_mode", "BANKROLL_DERIVED")))
    return UserStakingProfile(
        bankroll=float(bankroll),
        staking_strategy=strategy,
        flat_stake_mode=mode,
    )


def _track(initial: float) -> dict[str, Any]:
    return {
        "initial": float(initial),
        "bankroll": float(initial),
        "peak": float(initial),
        "minimum": float(initial),
        "max_drawdown_pct": 0.0,
        "recommended_card_count": 0,
        "positive_stake_count": 0,
        "zero_stake_actionable_count": 0,
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
    dd = 0.0 if peak <= 0 else (peak - float(track["bankroll"])) / peak
    track["max_drawdown_pct"] = max(float(track["max_drawdown_pct"]), float(dd))


def _final_track(track: dict[str, Any]) -> dict[str, Any]:
    initial = float(track["initial"])
    ending = float(track["bankroll"])
    return {
        "starting_bankroll": initial,
        "ending_bankroll": ending,
        "return_pct": (ending / initial - 1.0) if initial > 0 else None,
        "recommended_card_count": int(track["recommended_card_count"]),
        "positive_stake_count": int(track["positive_stake_count"]),
        "zero_stake_actionable_count": int(track["zero_stake_actionable_count"]),
        "total_amount_staked": float(track["total_amount_staked"]),
        "max_drawdown_pct": float(track["max_drawdown_pct"]),
        "minimum_bankroll": float(track["minimum"]),
        "wins": int(track["wins"]),
        "losses": int(track["losses"]),
        "pushes": int(track["pushes"]),
    }


def run(root: Path, config_path: Path, out: Path) -> None:
    root = root.resolve()
    if not config_path.is_absolute():
        config_path = (root / config_path).resolve()
    cfg, config_sha = _read_yaml(config_path)
    if cfg["status"] != "PREREGISTERED_BEFORE_V3_STAKING_2020_2024_PRODUCT_SIMULATION":
        raise ProductSimulationError("product simulation preregistration status mismatch")
    if [int(x) for x in cfg["development_seasons"]] != DEV:
        raise ProductSimulationError("development-season contract mismatch")
    if set(int(x) for x in cfg["sealed_seasons"]) != SEALED:
        raise ProductSimulationError("sealed-season contract mismatch")
    if cfg["results_label"] != "OBSERVATIONAL_ONLY_NOT_TUNED":
        raise ProductSimulationError("diagnostic result label mismatch")

    candidate_runner = _load_script("task05f_product_candidate_runtime", CANDIDATE_RUNNER)
    with tempfile.TemporaryDirectory(prefix="task05f_product_candidate_") as tmp:
        candidate_out = Path(tmp) / "candidate"
        candidate_runner.run(root, CANDIDATE_CONFIG, candidate_out)
        candidate_df = pl.read_parquet(candidate_out / "candidate_table.parquet")
        outcome_df = pl.read_parquet(candidate_out / "historical_outcomes.parquet")

        if OUTCOME_FIELDS.intersection(candidate_df.columns):
            raise ProductSimulationError("outcome field entered production candidate table")
        seasons = sorted(int(x) for x in candidate_df["season"].unique().to_list())
        if seasons != DEV or set(seasons).intersection(SEALED):
            raise ProductSimulationError(f"unexpected candidate seasons {seasons}")
        if candidate_df.height != 8448 or outcome_df.height != 8448:
            raise ProductSimulationError("candidate/outcome fixture row count mismatch")

        candidate_rows = candidate_df.to_dicts()
        candidate_hash_before = _logical_hash(candidate_rows)
        blocks = sorted({str(row["block"]) for row in candidate_rows})
        if len(blocks) != int(cfg["expected_slates"]):
            raise ProductSimulationError(f"expected {cfg['expected_slates']} slates, found {len(blocks)}")

        # Freeze every V3 card selection before constructing an outcome lookup.
        picks_by_block: dict[str, dict[str, dict[str, Any] | None]] = {}
        selected_records: list[dict[str, Any]] = []
        for block in blocks:
            slate = [row for row in candidate_rows if str(row["block"]) == block]
            slate_seasons = {int(row["season"]) for row in slate}
            slate_weeks = {str(row["week"]) for row in slate}
            if len(slate_seasons) != 1 or len(slate_weeks) != 1:
                raise ProductSimulationError(f"block {block} is not one season-week slate")
            picks = select_primary_cards_v3(slate)
            picks_by_block[block] = picks
            for card in PRIMARY_CARDS:
                pick = picks[card]
                selected_records.append(
                    {
                        "block": block,
                        "season": next(iter(slate_seasons)),
                        "week": next(iter(slate_weeks)),
                        "card": card,
                        "candidate_id": None if pick is None else str(pick["candidate_id"]),
                        "candidate": None if pick is None else pick,
                    }
                )

        candidate_hash_after = _logical_hash(candidate_rows)
        if candidate_hash_before != candidate_hash_after:
            raise ProductSimulationError("selector mutated candidate table")

        # Only now expose outcomes for settlement diagnostics.
        outcome_map: dict[str, dict[str, Any]] = {}
        for row in outcome_df.to_dicts():
            cid = str(row["candidate_id"])
            if cid in outcome_map:
                raise ProductSimulationError(f"duplicate outcome row {cid}")
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
                "unique_positive_stake_wagers": 0,
                "maximum_single_slate_exposure_pct": 0.0,
            }
            for profile_id, item in profile_cfgs.items()
        }

        stake_ledger: list[dict[str, Any]] = []
        no_play_counts = {card: 0 for card in PRIMARY_CARDS}
        duplicate_card_slates = 0
        hhr_status_mix = {"VALUE": 0, "PLAYABLE": 0}
        zero_kelly_stake_on_playable = 0

        for block in blocks:
            picks = picks_by_block[block]
            selected_ids = [str(picks[card]["candidate_id"]) for card in PRIMARY_CARDS if picks[card] is not None]
            if len(selected_ids) != len(set(selected_ids)):
                duplicate_card_slates += 1
            for card in PRIMARY_CARDS:
                if picks[card] is None:
                    no_play_counts[card] += 1
            if picks["HIGH_HIT_RATE"] is not None:
                status = str(picks["HIGH_HIT_RATE"]["price_status"])
                if status in hhr_status_mix:
                    hhr_status_mix[status] += 1

            for profile_id, item in profile_cfgs.items():
                # Independent per-card bankroll tracks.
                for card in PRIMARY_CARDS:
                    track = per_card_tracks[profile_id][card]
                    pick = picks[card]
                    if pick is None:
                        continue
                    track["recommended_card_count"] += 1
                    start_bankroll = float(track["bankroll"])
                    if start_bankroll <= 0.0:
                        continue
                    profile = _profile_from_config(item, start_bankroll)
                    rec = recommend_stake(pick, profile)
                    stake = float(rec.recommended_stake)
                    if stake <= 0.0:
                        track["zero_stake_actionable_count"] += 1
                        if (
                            item["staking_strategy"] in {"HALF_KELLY", "QUARTER_KELLY"}
                            and str(pick["price_status"]) == "PLAYABLE"
                        ):
                            zero_kelly_stake_on_playable += 1
                        stake_ledger.append(
                            {
                                "block": block,
                                "profile": profile_id,
                                "track": card,
                                "candidate_id": str(pick["candidate_id"]),
                                "start_bankroll": start_bankroll,
                                "recommended_stake": 0.0,
                                "stake_reason": rec.reason,
                                "settlement": None,
                                "realized_profit_per_unit": None,
                                "dollar_profit": 0.0,
                                "end_bankroll": start_bankroll,
                            }
                        )
                        continue
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
                            "start_bankroll": start_bankroll,
                            "recommended_stake": stake,
                            "stake_reason": rec.reason,
                            "settlement": settlement,
                            "realized_profit_per_unit": unit_profit,
                            "dollar_profit": dollar_profit,
                            "end_bankroll": float(track["bankroll"]),
                        }
                    )

                # Combined unique top-card portfolio. All stake sizes use one
                # shared start-of-slate bankroll and settle simultaneously.
                portfolio = portfolio_tracks[profile_id]
                start_bankroll = float(portfolio["bankroll"])
                if start_bankroll <= 0.0:
                    continue
                unique_picks: dict[str, dict[str, Any]] = {}
                for card in PRIMARY_CARDS:
                    pick = picks[card]
                    if pick is not None:
                        unique_picks.setdefault(str(pick["candidate_id"]), pick)
                profile = _profile_from_config(item, start_bankroll)
                frozen_wagers: list[tuple[dict[str, Any], float, str]] = []
                for cid in sorted(unique_picks):
                    pick = unique_picks[cid]
                    rec = recommend_stake(pick, profile)
                    frozen_wagers.append((pick, float(rec.recommended_stake), rec.reason))
                slate_exposure = sum(stake for _, stake, _ in frozen_wagers)
                if start_bankroll > 0:
                    portfolio["maximum_single_slate_exposure_pct"] = max(
                        float(portfolio["maximum_single_slate_exposure_pct"]),
                        slate_exposure / start_bankroll,
                    )
                portfolio["total_amount_staked"] += slate_exposure
                slate_profit = 0.0
                for pick, stake, reason in frozen_wagers:
                    if stake <= 0.0:
                        continue
                    outcome = outcome_map[str(pick["candidate_id"])]
                    settlement = _normalize_settlement(outcome["settlement"])
                    unit_profit = float(outcome["realized_profit"])
                    slate_profit += stake * unit_profit
                    portfolio["unique_positive_stake_wagers"] += 1
                    portfolio["positive_stake_count"] += 1
                    portfolio[{"WIN": "wins", "LOSS": "losses", "PUSH": "pushes"}[settlement]] += 1
                _settle_track(portfolio, slate_profit)

        per_card_summary = {
            profile_id: {
                card: _final_track(track) for card, track in card_tracks.items()
            }
            for profile_id, card_tracks in per_card_tracks.items()
        }
        portfolio_summary: dict[str, Any] = {}
        for profile_id, track in portfolio_tracks.items():
            base = _final_track(track)
            base["unique_positive_stake_wagers"] = int(track["unique_positive_stake_wagers"])
            base["maximum_single_slate_exposure_pct"] = float(track["maximum_single_slate_exposure_pct"])
            portfolio_summary[profile_id] = base

        out.mkdir(parents=True, exist_ok=True)
        _json_write(out / "selected_cards.json", selected_records)
        pl.DataFrame(stake_ledger, infer_schema_length=None).write_csv(out / "stake_ledger.csv")
        scorecard = {
            "version": VERSION,
            "label": "OBSERVATIONAL_ONLY_NOT_TUNED",
            "development_seasons": DEV,
            "sealed_seasons": [2025],
            "total_slates": len(blocks),
            "methodology_warning": cfg["methodology_warning"],
            "per_profile_card": per_card_summary,
            "combined_unique_top_cards": portfolio_summary,
            "product": {
                "no_play_counts_by_card": no_play_counts,
                "duplicate_card_slates": duplicate_card_slates,
                "high_hit_value_vs_playable_mix": hhr_status_mix,
                "zero_kelly_stake_on_playable_count": zero_kelly_stake_on_playable,
            },
            "historical_roi_is_acceptance_gate": False,
            "historical_hit_rate_is_acceptance_gate": False,
            "staking_parameters_may_change_after_simulation": False,
            "selector_v3_may_change_after_simulation": False,
            "production_promotion": False,
        }
        _json_write(out / "scorecard.json", scorecard)
        _json_write(
            out / "reproduction.json",
            {
                "candidate_rows": len(candidate_rows),
                "candidate_logical_sha256_before_selection": candidate_hash_before,
                "candidate_logical_sha256_after_selection": candidate_hash_after,
                "candidate_rows_immutable": candidate_hash_before == candidate_hash_after,
                "candidate_table_outcome_fields": sorted(OUTCOME_FIELDS.intersection(candidate_df.columns)),
                "outcome_join_occurred_after_selection": True,
                "same_start_of_slate_bankroll_for_combined_wagers": True,
                "duplicate_candidate_dedup_in_combined_portfolio": True,
                "sealed_2025_loaded": False,
            },
        )
        _json_write(
            out / "provenance.json",
            {
                "version": VERSION,
                "github_sha": os.environ.get("GITHUB_SHA"),
                "config_path": str(config_path.relative_to(root)),
                "config_sha256": config_sha,
                "candidate_config_sha256": hashlib.sha256(CANDIDATE_CONFIG.read_bytes()).hexdigest(),
                "selector_v3_config_sha256": hashlib.sha256(SELECTOR_CONFIG.read_bytes()).hexdigest(),
                "staking_v1_config_sha256": hashlib.sha256(STAKING_CONFIG.read_bytes()).hexdigest(),
                "product_interface_config_sha256": hashlib.sha256(PRODUCT_CONFIG.read_bytes()).hexdigest(),
                "results_label": "OBSERVATIONAL_ONLY_NOT_TUNED",
                "development_seasons": DEV,
                "sealed_seasons": [2025],
            },
        )

    print(json.dumps(scorecard, indent=2, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--out", default=str(ROOT / "artifacts/task05f/product_simulation_v1"))
    args = parser.parse_args()
    run(ROOT, Path(args.config), Path(args.out))
