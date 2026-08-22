#!/usr/bin/env python3
"""Task05F Phase F: candidate uncertainty and conservative staking probability.

This runner is strictly downstream of the locked evaluator.  It first produces
the locked ML V4 + Spread/Total V3 board, then enriches each chronological block
using ONLY strictly prior locked out-of-sample predictions.

It hard-fails if any frozen evaluator probability/value/support field changes.
2025 remains sealed.
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

from nfl_edge.value.locked_reliability import (
    cap_reliability,
    conditional_nonpush_probability,
    conservative_staking_probability,
    expected_value_from_decimal,
    fit_candidate_uncertainty,
    staking_outcome_probabilities,
)

ROOT = Path(__file__).resolve().parents[1]
DEV = [2020, 2021, 2022, 2023, 2024]
SEALED = {2025}
VERSION = "task05f_reliability_uncertainty_v1"
PREREG = ROOT / "config" / "task05f_reliability_uncertainty_v1_prereg.yaml"
LOCKED_RUNNER = ROOT / "scripts" / "task05f_evaluator_locked_runner.py"
LOCKED_CONFIG = ROOT / "config" / "task05f_evaluator_locked_v1.yaml"

IMMUTABLE_FIELDS = [
    "p_win",
    "p_push",
    "p_loss",
    "actionable_probability",
    "fair_price_american",
    "expected_value",
    "strict_positive_value",
    "supported",
]
IDENTITY_FIELDS = [
    "game_id",
    "season",
    "week",
    "block",
    "market_type",
    "selected_side",
    "sportsbook",
    "line",
    "american_odds",
]
CANONICAL_SIDE = {"moneyline": "home", "spread": "home", "total": "over"}


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


def _american_break_even(decimal_odds: float) -> float:
    dec = float(decimal_odds)
    if dec <= 1.0:
        raise ValueError("decimal odds must exceed 1")
    return 1.0 / dec


def _market_anchor(row: dict[str, Any]) -> float | None:
    market = row["market_type"]
    side = str(row["selected_side"]).lower()
    if market == "moneyline":
        value = row.get("calibrated_market_probability")
        return None if value is None else float(value)
    value = row.get("pinnacle_anchor_probability")
    if value is None:
        return None
    p = float(value)
    if market == "spread":
        return p if side == "home" else 1.0 - p
    if market == "total":
        return p if side == "over" else 1.0 - p
    raise ValueError(f"unknown market {market}")


def _identity_key(row: dict[str, Any]) -> tuple:
    return (
        str(row.get("block")),
        str(row.get("game_id")),
        str(row.get("market_type")),
        str(row.get("selected_side")),
        str(row.get("sportsbook")),
        -9999.0 if row.get("line") is None else float(row["line"]),
        int(row.get("american_odds")),
    )


def _immutable_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = [
        {field: row.get(field) for field in IDENTITY_FIELDS + IMMUTABLE_FIELDS}
        for row in rows
    ]
    return sorted(out, key=_identity_key)


def _payload_hash(payload: list[dict[str, Any]]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _same_field_by_identity(
    before: list[dict[str, Any]], after: list[dict[str, Any]], field: str
) -> bool:
    a = {_identity_key(row): row.get(field) for row in before}
    b = {_identity_key(row): row.get(field) for row in after}
    return a == b


def _history_row(row: dict[str, Any]) -> tuple[str, float, int] | None:
    if not row.get("supported"):
        return None
    if str(row["selected_side"]).lower() != CANONICAL_SIDE[row["market_type"]]:
        return None
    settlement = row.get("settlement")
    if settlement not in {"WIN", "LOSS"}:
        return None
    q = conditional_nonpush_probability(
        float(row["p_win"]), float(row["p_push"]), float(row["p_loss"])
    )
    return str(row["block"]), q, 1 if settlement == "WIN" else 0


def _tier_counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return {
        tier: sum(str(r.get(key)) == tier for r in rows)
        for tier in ("HIGH", "MEDIUM", "LOW", "UNSUPPORTED")
    }


def _mean_or_none(values: list[float]) -> float | None:
    return None if not values else float(sum(values) / len(values))


def _roi(rows: list[dict[str, Any]]) -> float | None:
    if not rows:
        return None
    return float(sum(float(r["realized_profit"]) for r in rows) / len(rows))


def run(root: Path, config_path: Path, out: Path) -> None:
    cfg, config_sha = _read_yaml(config_path)
    _assert_unsealed(cfg["development_seasons"])
    locked = _load_script("task05f_phase_f_locked_runtime", LOCKED_RUNNER)

    with tempfile.TemporaryDirectory(prefix="task05f_phase_f_base_") as tmp:
        base_out = Path(tmp) / "locked"
        locked.run(root, LOCKED_CONFIG, base_out)
        base_df = pl.read_parquet(base_out / "full_board.parquet")
        if set(int(x) for x in base_df["season"].unique().to_list()).intersection(SEALED):
            raise RuntimeError("SEALED 2025 row entered locked Phase F board")
        base_rows = base_df.to_dicts()
        before_payload = _immutable_payload(base_rows)
        before_hash = _payload_hash(before_payload)

        histories: dict[str, list[tuple[str, float, int]]] = {
            "moneyline": [],
            "spread": [],
            "total": [],
        }
        enriched: list[dict[str, Any]] = []
        states_by_block: list[dict[str, Any]] = []
        blocks = sorted({str(r["block"]) for r in base_rows})

        for block in blocks:
            current = [r for r in base_rows if str(r["block"]) == block]
            market_states = {
                market: fit_candidate_uncertainty(histories[market])
                for market in ("moneyline", "spread", "total")
            }
            states_by_block.append(
                {
                    "block": block,
                    **{
                        market: {
                            "radius": market_states[market].radius,
                            "support_n": market_states[market].support_n,
                            "block_count": market_states[market].block_count,
                            "tier": market_states[market].tier,
                            "stable": market_states[market].stable,
                        }
                        for market in ("moneyline", "spread", "total")
                    },
                }
            )

            for base in current:
                row = dict(base)
                market = row["market_type"]
                state = market_states[market]
                base_rel = str(row["reliability"])
                row["base_reliability"] = base_rel
                row["break_even_probability"] = _american_break_even(row["decimal_odds"])

                if not row.get("supported"):
                    row.update(
                        {
                            "uncertainty": None,
                            "uncertainty_support_n": None,
                            "uncertainty_block_count": None,
                            "candidate_uncertainty_tier": "UNSUPPORTED",
                            "reliability": "UNSUPPORTED",
                            "conditional_nonpush_probability": None,
                            "staking_anchor_probability": None,
                            "staking_probability": None,
                            "staking_p_win": None,
                            "staking_p_push": None,
                            "staking_p_loss": None,
                            "staking_expected_value": None,
                            "evaluated_edge_probability": None,
                            "staking_edge_probability": None,
                        }
                    )
                    enriched.append(row)
                    continue

                q_eval = conditional_nonpush_probability(
                    row["p_win"], row["p_push"], row["p_loss"]
                )
                final_rel = cap_reliability(base_rel, state.tier)
                anchor = _market_anchor(row)
                q_stake = None
                stake_win = stake_push = stake_loss = stake_ev = None
                if anchor is not None:
                    q_stake = conservative_staking_probability(
                        q_eval, anchor, final_rel, state.radius
                    )
                    stake_win, stake_push, stake_loss = staking_outcome_probabilities(
                        q_stake, float(row["p_push"])
                    )
                    stake_ev = expected_value_from_decimal(
                        stake_win, stake_loss, float(row["decimal_odds"])
                    )

                be = float(row["break_even_probability"])
                row.update(
                    {
                        "uncertainty": state.radius,
                        "uncertainty_support_n": state.support_n,
                        "uncertainty_block_count": state.block_count,
                        "candidate_uncertainty_tier": state.tier,
                        "reliability": final_rel,
                        "conditional_nonpush_probability": q_eval,
                        "staking_anchor_probability": anchor,
                        "staking_probability": q_stake,
                        "staking_p_win": stake_win,
                        "staking_p_push": stake_push,
                        "staking_p_loss": stake_loss,
                        "staking_expected_value": stake_ev,
                        "evaluated_edge_probability": q_eval - be,
                        "staking_edge_probability": None if q_stake is None else q_stake - be,
                    }
                )
                enriched.append(row)

            # Only after the entire current block has been enriched do its outcomes
            # become eligible uncertainty history for later blocks.
            seen: set[tuple[str, str]] = set()
            for base in current:
                key = (base["market_type"], base["game_id"])
                if key in seen:
                    continue
                history = _history_row(base)
                if history is not None:
                    histories[base["market_type"]].append(history)
                    seen.add(key)

        after_payload = _immutable_payload(enriched)
        after_hash = _payload_hash(after_payload)
        immutable_equal = before_payload == after_payload
        strict_labels_unchanged = _same_field_by_identity(
            base_rows, enriched, "strict_positive_value"
        )
        support_flags_unchanged = _same_field_by_identity(
            base_rows, enriched, "supported"
        )
        if not immutable_equal or before_hash != after_hash:
            raise RuntimeError("Phase F modified locked evaluator probability/value/support fields")

        out.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(enriched, infer_schema_length=None).write_parquet(
            out / "full_board.parquet", compression="zstd"
        )
        with (out / "uncertainty_state_by_block.ndjson").open("w") as fh:
            for state in states_by_block:
                fh.write(json.dumps(state, sort_keys=True, allow_nan=False) + "\n")

        diagnostics: list[dict[str, Any]] = []
        score_markets: dict[str, dict[str, Any]] = {}
        for market in ("moneyline", "spread", "total"):
            rr = [r for r in enriched if r["market_type"] == market]
            supported = [r for r in rr if r["supported"]]
            with_stake = [r for r in supported if r["staking_expected_value"] is not None]
            stake_pos = [r for r in with_stake if float(r["staking_expected_value"]) > 0.0]
            stake_nonpos = [r for r in with_stake if float(r["staking_expected_value"]) <= 0.0]
            radii = [float(r["uncertainty"]) for r in supported if r["uncertainty"] is not None]
            score_markets[market] = {
                "rows": len(rr),
                "supported": len(supported),
                "base_reliability": _tier_counts(rr, "base_reliability"),
                "final_reliability": _tier_counts(rr, "reliability"),
                "candidate_uncertainty_tier": _tier_counts(rr, "candidate_uncertainty_tier"),
                "mean_uncertainty_radius": _mean_or_none(radii),
                "staking_probability_n": sum(r["staking_probability"] is not None for r in supported),
                "staking_positive_ev_n": len(stake_pos),
                "staking_nonpositive_ev_n": len(stake_nonpos),
                "staking_positive_ev_realized_roi": _roi(stake_pos),
                "staking_nonpositive_ev_realized_roi": _roi(stake_nonpos),
            }
            for season in DEV:
                season_rows = [r for r in rr if int(r["season"]) == season]
                diagnostics.append(
                    {
                        "market_type": market,
                        "season": season,
                        "rows": len(season_rows),
                        "supported": sum(bool(r["supported"]) for r in season_rows),
                        "high": sum(r["reliability"] == "HIGH" for r in season_rows),
                        "medium": sum(r["reliability"] == "MEDIUM" for r in season_rows),
                        "low": sum(r["reliability"] == "LOW" for r in season_rows),
                        "unsupported": sum(r["reliability"] == "UNSUPPORTED" for r in season_rows),
                    }
                )
        pl.DataFrame(diagnostics).write_csv(out / "per_season_reliability_mix.csv")

        reproduction = {
            "base_locked_version": "task05f_evaluator_locked_v1",
            "locked_rows": len(base_rows),
            "phase_f_rows": len(enriched),
            "immutable_fields": IMMUTABLE_FIELDS,
            "immutable_payload_sha256_before": before_hash,
            "immutable_payload_sha256_after": after_hash,
            "immutable_rows_equal": immutable_equal,
            "strict_value_labels_unchanged": strict_labels_unchanged,
            "support_flags_unchanged": support_flags_unchanged,
        }
        _json_write(out / "base_reproduction.json", reproduction)

        for name in (
            "frozen_edge_preservation.json",
            "ev_calibration.csv",
            "component_reproduction.json",
        ):
            shutil.copy2(base_out / name, out / name)

        _json_write(
            out / "scorecard.json",
            {
                "version": VERSION,
                "prereg_config_sha256": config_sha,
                "development_seasons": DEV,
                "sealed_seasons": [2025],
                "chronology": "strictly prior locked OOS season-week blocks",
                "locked_probability_architecture": {
                    "moneyline": "ml_v4",
                    "spread": "spread_v3",
                    "total": "total_v3",
                },
                "markets": score_markets,
                "base_reproduction": reproduction,
                "play_through": "NOT_SCORED_IN_PHASE_F",
                "selector_scoring": "NOT_SCORED_IN_PHASE_F",
                "acceptance_status": "EVIDENCE_PENDING_MASTER_REVIEW",
            },
        )
        _json_write(
            out / "provenance.json",
            {
                "version": VERSION,
                "github_sha": os.environ.get("GITHUB_SHA"),
                "scope": "evaluator_only_post_probability_reliability",
                "prereg_path": str(config_path.relative_to(root)),
                "prereg_config_sha256": config_sha,
                "locked_config_path": str(LOCKED_CONFIG.relative_to(root)),
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
                "note": "Phase F does not alter its preregistered uncertainty/reliability/staking formula from historical diagnostics.",
            },
        )

    print(
        json.dumps(
            {
                "version": VERSION,
                "rows": reproduction["phase_f_rows"],
                "immutable_rows_equal": reproduction["immutable_rows_equal"],
                "strict_value_labels_unchanged": reproduction["strict_value_labels_unchanged"],
                "support_flags_unchanged": reproduction["support_flags_unchanged"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(PREREG))
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "task05f" / "reliability_v1"))
    args = parser.parse_args()
    run(ROOT, Path(args.config), Path(args.out))
