#!/usr/bin/env python3
"""Task05F ML-only V4 chronological evaluator validation.

Spread and totals remain frozen at V3.  V4 calibrates Pinnacle moneyline
no-vig probability first, then optionally pools in frozen exact AVG only when
prior proper scoring assigns nonzero weight.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from nfl_edge.value.calibration_v4 import (
    calibrated_market_probability,
    final_ml_probability,
    fit_ml_v4_calibration,
)
from nfl_edge.value.contracts import GameState
from nfl_edge.value.evaluators import evaluate_offer
from nfl_edge.value.fitting import fit_ml_states
from nfl_edge.value.market_math import proportional_no_vig
from nfl_edge.value.wager_economics import moneyline_outcome_probabilities, moneyline_settlement

ROOT = Path(__file__).resolve().parents[1]
DEV = [2020, 2021, 2022, 2023, 2024]
SEALED = {2025}
MIN_PRIOR = 128
VERSION = "task05f_ml_v4"
V1_PATH = ROOT / "scripts" / "task05f_evaluator_rebuild_runner.py"


def _load_v1():
    spec = importlib.util.spec_from_file_location("task05f_rebuild_v1_runtime_ml_v4", V1_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load V1 evaluator helper module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = _load_v1()


def _json_write(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _config(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    return yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()


def _assert_unsealed(seasons) -> None:
    bad = SEALED.intersection({int(x) for x in seasons})
    if bad:
        raise RuntimeError(f"SEALED season requested: {sorted(bad)}")


def _pinnacle_home_probability(idx, gid: str) -> float | None:
    ph = V1._pin(idx, gid, "moneyline", "home")
    pa = V1._pin(idx, gid, "moneyline", "away")
    if ph is None or pa is None:
        return None
    p_home, _ = proportional_no_vig(ph.price_american, pa.price_american)
    return float(p_home)


def _fit_material(games, idx, prior_gids):
    rows: list[tuple[float, float, int]] = []
    ties = 0
    completed = 0
    for gid in prior_gids:
        g = games[gid]
        hs, aw = int(g["home_score"]), int(g["away_score"])
        completed += 1
        if hs == aw:
            ties += 1
            continue
        q, x = g.get("qbelo_home"), g.get("xgb_home")
        p_market = _pinnacle_home_probability(idx, gid)
        if q is None or x is None or p_market is None:
            continue
        p_model = (float(q) + float(x)) / 2.0
        rows.append((p_model, p_market, int(hs > aw)))
    return rows, ties, completed


def _state_dict(state) -> dict:
    return {
        "supported": state.supported,
        "reason": state.reason,
        "support_n": state.support_n,
        "market_intercept": state.market.intercept,
        "market_slope": state.market.slope,
        "market_support_n": state.market.support_n,
        "model_pool_weight": state.pool.weight,
        "pool_support_n": state.pool.support_n,
    }


def run(root: Path, config_path: Path, out: Path) -> None:
    cfg, config_sha = _config(config_path)
    _assert_unsealed(cfg["development_seasons"])
    games = V1.build_inputs(root)
    idx = V1.build_market(root, games)
    game_blocks = sorted((V1._block_key(g["season"], g["week"]), gid) for gid, g in games.items())
    ordered_blocks = sorted({block for block, _ in game_blocks})

    board_rows: list[dict] = []
    calibration_states: list[dict] = []
    benchmark_rows: dict[str, list[dict]] = {
        "pinnacle_raw_no_vig": [],
        "pinnacle_calibrated": [],
        "raw_exact_avg": [],
        "raw_qbelo": [],
        "raw_xgb": [],
    }

    for block in ordered_blocks:
        current = [gid for b, gid in game_blocks if b == block]
        prior = [gid for b, gid in game_blocks if b < block]
        ml_train, _, _, _, _, _, _ = V1._training_material(games, idx, prior)
        gate_states = fit_ml_states(ml_train, VERSION, config_sha)
        material, prior_ties, prior_games = _fit_material(games, idx, prior)
        cal = fit_ml_v4_calibration(material, minimum_prior=MIN_PRIOR)
        calibration_states.append(
            {
                "block": block,
                "current_games": len(current),
                "prior_games": len(prior),
                **_state_dict(cal),
            }
        )

        for gid in current:
            g = games[gid]
            hs, aw = int(g["home_score"]), int(g["away_score"])
            gs = GameState(
                game_id=gid,
                season=int(g["season"]),
                week=str(g["week"]),
                kickoff_utc=None,
                qbelo_home=g["qbelo_home"],
                xgb_home=g["xgb_home"],
                expected_home_margin=g["expected_home_margin"],
                predicted_total_r4=g["predicted_total"],
            )
            p_market_home = _pinnacle_home_probability(idx, gid)
            raw_home = None
            if g["qbelo_home"] is not None and g["xgb_home"] is not None:
                raw_home = (float(g["qbelo_home"]) + float(g["xgb_home"])) / 2.0

            p_market_cal_home = None
            p_final_home = None
            if cal.supported and p_market_home is not None and raw_home is not None:
                p_market_cal_home = calibrated_market_probability(p_market_home, cal)
                p_final_home = final_ml_probability(raw_home, p_market_home, cal)

            for side in ("home", "away"):
                offer = V1._best(idx, gid, "moneyline", side)
                if offer is None:
                    continue
                settlement = moneyline_settlement(side, hs, aw)
                p_market_selected = None if p_market_home is None else (p_market_home if side == "home" else 1.0 - p_market_home)
                raw_selected = None if raw_home is None else (raw_home if side == "home" else 1.0 - raw_home)
                market_cal_selected = None if p_market_cal_home is None else (p_market_cal_home if side == "home" else 1.0 - p_market_cal_home)
                final_selected = None if p_final_home is None else (p_final_home if side == "home" else 1.0 - p_final_home)

                gate = None
                reason = None
                if p_market_selected is None:
                    reason = "missing_pinnacle_benchmark"
                elif raw_selected is None:
                    reason = "exact_avg_requires_both_models"
                else:
                    gate = evaluate_offer(
                        gs,
                        offer,
                        gate_states["exact_avg"],
                        pinnacle_no_vig_selected=float(p_market_selected),
                    )
                    if not gate.supported:
                        reason = gate.reason
                    elif not cal.supported:
                        reason = cal.reason

                if reason is not None:
                    board_rows.append(
                        V1._unsupported_row(
                            gid=gid,
                            g=g,
                            block=block,
                            offer=offer,
                            market_type="moneyline",
                            raw_model_output=raw_selected,
                            pinnacle_probability=p_market_selected,
                            support_n=0 if gate is None else gate.support_n,
                            reason=reason,
                            reliability="UNSUPPORTED" if gate is None else gate.reliability,
                            settlement=settlement,
                            benchmark_probability=market_cal_selected,
                        )
                    )
                    continue

                prob = moneyline_outcome_probabilities(
                    float(final_selected),
                    prior_ties=prior_ties,
                    prior_games=prior_games,
                )
                row = V1._supported_row(
                    gid=gid,
                    g=g,
                    block=block,
                    offer=offer,
                    market_type="moneyline",
                    raw_model_output=float(raw_selected),
                    pinnacle_probability=float(p_market_selected),
                    benchmark_probability=float(market_cal_selected),
                    prob=prob,
                    reliability=gate.reliability,
                    uncertainty=None,
                    support_n=gate.support_n,
                    staking_probability=None,
                    settlement=settlement,
                )
                row.update(
                    {
                        "raw_pinnacle_no_vig_probability": float(p_market_selected),
                        "calibrated_market_probability": float(market_cal_selected),
                        "model_market_disagreement": float(raw_selected - market_cal_selected),
                        "calibration_market_intercept": float(cal.market.intercept),
                        "calibration_market_slope": float(cal.market.slope),
                        "calibration_model_weight": float(cal.pool.weight),
                    }
                )
                board_rows.append(row)

                actual = settlement.value
                q = float(g["qbelo_home"]) if side == "home" else 1.0 - float(g["qbelo_home"])
                x = float(g["xgb_home"]) if side == "home" else 1.0 - float(g["xgb_home"])
                for name, p in (
                    ("pinnacle_raw_no_vig", float(p_market_selected)),
                    ("pinnacle_calibrated", float(market_cal_selected)),
                    ("raw_exact_avg", float(raw_selected)),
                    ("raw_qbelo", q),
                    ("raw_xgb", x),
                ):
                    benchmark_rows[name].append({"settlement": actual, "p": p})

    board_rows.sort(
        key=lambda r: (
            int(r["season"]), str(r["week"]), r["game_id"], r["selected_side"],
            r["sportsbook"],
        )
    )
    out.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(board_rows, infer_schema_length=None).write_parquet(out / "full_board.parquet", compression="zstd")
    pl.DataFrame(calibration_states, infer_schema_length=None).write_ndjson(out / "calibration_state_by_block.ndjson")

    supported = [r for r in board_rows if r["supported"]]
    positive = [r for r in supported if r["expected_value"] is not None and float(r["expected_value"]) > 0]
    nonpositive = [r for r in supported if r["expected_value"] is not None and float(r["expected_value"]) <= 0]
    market_summary = {
        "rows": len(board_rows),
        "supported": len(supported),
        "unsupported": len(board_rows) - len(supported),
        "positive_ev_n": len(positive),
        "nonpositive_ev_n": len(nonpositive),
        "positive_ev_realized_roi": V1._roi(positive),
        "nonpositive_ev_realized_roi": V1._roi(nonpositive),
        "probability_metrics": V1._candidate_probability_metrics(board_rows),
        "reliability": {
            tier: sum(r["reliability"] == tier for r in board_rows)
            for tier in ("HIGH", "MEDIUM", "LOW", "UNSUPPORTED")
        },
        "unsupported_reasons": {
            reason: sum((not r["supported"]) and r.get("reason") == reason for r in board_rows)
            for reason in sorted({r.get("reason") for r in board_rows if not r["supported"] and r.get("reason")})
        },
    }

    benchmark_metrics = {name: V1._binary_metrics(rows, "p") for name, rows in benchmark_rows.items()}
    ev_rows = [r for r in V1._ev_calibration(board_rows) if r["market_type"] == "moneyline"]
    pl.DataFrame(ev_rows, infer_schema_length=None).write_csv(out / "ev_calibration.csv")
    frozen_all = V1._frozen_preservation(root, board_rows)
    frozen_ml = {k: v for k, v in frozen_all.items() if k.startswith("ML_")}
    _json_write(out / "frozen_ml_edge_preservation.json", frozen_ml)

    scorecard = {
        "version": VERSION,
        "prereg_config_sha256": config_sha,
        "development_seasons": DEV,
        "sealed_seasons": [2025],
        "chronology": "expanding prior season-week blocks only",
        "candidate_family": cfg["candidate"]["name"],
        "value_semantics": "strict expected_value > 0",
        "play_through": "deferred until ML core probability acceptance",
        "moneyline": market_summary,
        "benchmark_probability_metrics": benchmark_metrics,
        "acceptance_status": "EVIDENCE_PENDING_MASTER_REVIEW",
    }
    _json_write(out / "scorecard.json", scorecard)
    _json_write(
        out / "provenance.json",
        {
            "version": VERSION,
            "prereg_config_sha256": config_sha,
            "prereg_path": str(config_path.relative_to(root)),
            "github_sha": os.environ.get("GITHUB_SHA"),
            "development_seasons": DEV,
            "sealed_seasons": [2025],
            "scope": "evaluator_only_moneyline",
            "spread_architecture": "frozen_at_v3",
            "totals_architecture": "frozen_at_v3",
            "new_observation_policy": "OBSERVATIONAL_ONLY_NOT_TUNED",
        },
    )
    _json_write(
        out / "observations.json",
        {
            "label": "OBSERVATIONAL_ONLY_NOT_TUNED",
            "items": [],
            "note": "ML V4 performs no odds, dog/favorite, disagreement, ROI, or EV-threshold search.",
        },
    )
    print(json.dumps({"moneyline": market_summary, "calibration_blocks": len(calibration_states)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config/task05f_ml_v4_prereg.yaml"))
    parser.add_argument("--out", default=str(ROOT / "artifacts/task05f/ml_v4"))
    args = parser.parse_args()
    run(ROOT, Path(args.config), Path(args.out))
