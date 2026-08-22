#!/usr/bin/env python3
"""Task05F evaluator-only V2 chronological validation runner.

V2 implements only the globally preregistered calibration formulas in
config/task05f_evaluator_rebuild_v2_prereg.yaml. It consumes frozen football
outputs and frozen T-60 market data; it does not tune or alter football models
and does not search betting buckets or price regions.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import yaml

from nfl_edge.value.calibration_v2 import (
    calibrated_point_mean,
    calibrated_probability,
    fit_anchor_slope_calibration,
    fit_monotone_logit_calibration,
)
from nfl_edge.value.contracts import GameState, NormalizedOffer
from nfl_edge.value.evaluators import evaluate_offer, exact_avg
from nfl_edge.value.fitting import fit_ml_states, fit_point_states
from nfl_edge.value.market_math import proportional_no_vig
from nfl_edge.value.wager_economics import (
    Settlement,
    empirical_spread_probabilities,
    empirical_total_probabilities,
    moneyline_outcome_probabilities,
    moneyline_settlement,
)

ROOT = Path(__file__).resolve().parents[1]
DEV = [2020, 2021, 2022, 2023, 2024]
SEALED = {2025}
MIN_PRIOR = 128
VERSION = "task05f_evaluator_rebuild_v2"
V1_PATH = ROOT / "scripts" / "task05f_evaluator_rebuild_runner.py"


def _load_v1():
    spec = importlib.util.spec_from_file_location("task05f_rebuild_v1_runtime", V1_PATH)
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


def _unique_pinnacle_line(
    idx: dict[tuple[str, str, str, str], list[NormalizedOffer]],
    gid: str,
    market_type: str,
    side: str,
) -> float | None:
    offers = idx.get((gid, market_type, side, "pinnacle"), [])
    lines = sorted({round(float(o.line), 6) for o in offers if o.line is not None})
    return float(lines[0]) if len(lines) == 1 else None


def _pinnacle_total_line(
    idx: dict[tuple[str, str, str, str], list[NormalizedOffer]], gid: str
) -> float | None:
    over = {
        round(float(o.line), 6)
        for o in idx.get((gid, "total", "over", "pinnacle"), [])
        if o.line is not None
    }
    under = {
        round(float(o.line), 6)
        for o in idx.get((gid, "total", "under", "pinnacle"), [])
        if o.line is not None
    }
    common = sorted(over.intersection(under))
    return float(common[0]) if len(common) == 1 else None


def _v2_fit_material(games, idx, prior_gids):
    ml_rows: list[tuple[float, int]] = []
    spread_rows: list[tuple[float, float, float]] = []
    total_rows: list[tuple[float, float, float]] = []
    ties = 0
    completed = 0
    for gid in prior_gids:
        g = games[gid]
        hs, aw = int(g["home_score"]), int(g["away_score"])
        completed += 1
        if hs == aw:
            ties += 1
        q, x = g.get("qbelo_home"), g.get("xgb_home")
        if q is not None and x is not None and hs != aw:
            ml_rows.append(((float(q) + float(x)) / 2.0, int(hs > aw)))

        expected = g.get("expected_home_margin")
        pin_spread = _unique_pinnacle_line(idx, gid, "spread", "home")
        if expected is not None and pin_spread is not None:
            market_home_margin = -float(pin_spread)
            spread_rows.append(
                (float(expected), market_home_margin, float(hs - aw))
            )

        predicted = g.get("predicted_total")
        pin_total = _pinnacle_total_line(idx, gid)
        if predicted is not None and pin_total is not None:
            total_rows.append(
                (float(predicted), float(pin_total), float(hs + aw))
            )
    return ml_rows, spread_rows, total_rows, ties, completed


def _state_dict(state) -> dict:
    return {
        key: value
        for key, value in state.__dict__.items()
        if key != "residuals"
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
        "moneyline_pinnacle_no_vig": [],
        "moneyline_raw_exact_avg": [],
        "moneyline_raw_qbelo": [],
        "moneyline_raw_xgb": [],
        "spread_incumbent_calibrated_normal": [],
        "total_incumbent_calibrated_normal": [],
    }

    for block in ordered_blocks:
        current = [gid for b, gid in game_blocks if b == block]
        prior = [gid for b, gid in game_blocks if b < block]

        # Existing Task05F states are retained only for support/OOD parity and
        # incumbent benchmarks. They do not define V2 candidate probabilities.
        ml_train, spread_train, total_train, _, _, _, _ = V1._training_material(games, idx, prior)
        ml_gate_states = fit_ml_states(ml_train, VERSION, config_sha)
        spread_gate_states = fit_point_states(spread_train, "spread", VERSION, config_sha)
        total_gate_states = fit_point_states(total_train, "total", VERSION, config_sha)

        ml_material, spread_material, total_material, prior_ties, prior_games = _v2_fit_material(
            games, idx, prior
        )
        ml_cal = fit_monotone_logit_calibration(
            ml_material, minimum_prior=MIN_PRIOR, C=1.0
        )
        spread_cal = fit_anchor_slope_calibration(
            spread_material, minimum_prior=MIN_PRIOR
        )
        total_cal = fit_anchor_slope_calibration(
            total_material, minimum_prior=MIN_PRIOR
        )
        calibration_states.append(
            {
                "block": block,
                "current_games": len(current),
                "prior_games": len(prior),
                "moneyline": _state_dict(ml_cal),
                "spread": _state_dict(spread_cal),
                "total": _state_dict(total_cal),
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

            ph = V1._pin(idx, gid, "moneyline", "home")
            pa = V1._pin(idx, gid, "moneyline", "away")
            pin_probs = None
            if ph and pa:
                pin_probs = proportional_no_vig(ph.price_american, pa.price_american)

            raw_home = None
            if g["qbelo_home"] is not None and g["xgb_home"] is not None:
                raw_home = (float(g["qbelo_home"]) + float(g["xgb_home"])) / 2.0

            for side in ("home", "away"):
                offer = V1._best(idx, gid, "moneyline", side)
                if offer is None:
                    continue
                settlement = moneyline_settlement(side, hs, aw)
                pin_selected = None if pin_probs is None else (pin_probs[0] if side == "home" else pin_probs[1])
                raw_selected = None if raw_home is None else (raw_home if side == "home" else 1.0 - raw_home)

                reason = None
                gate = None
                if pin_selected is None:
                    reason = "missing_pinnacle_benchmark"
                elif raw_selected is None:
                    reason = "exact_avg_requires_both_models"
                elif not ml_cal.supported:
                    reason = ml_cal.reason
                else:
                    gate = evaluate_offer(
                        gs,
                        offer,
                        ml_gate_states["exact_avg"],
                        pinnacle_no_vig_selected=float(pin_selected),
                    )
                    if not gate.supported:
                        reason = gate.reason

                if reason is not None:
                    board_rows.append(
                        V1._unsupported_row(
                            gid=gid,
                            g=g,
                            block=block,
                            offer=offer,
                            market_type="moneyline",
                            raw_model_output=raw_selected,
                            pinnacle_probability=pin_selected,
                            support_n=0 if gate is None else gate.support_n,
                            reason=reason,
                            reliability="UNSUPPORTED" if gate is None else gate.reliability,
                            settlement=settlement,
                            benchmark_probability=pin_selected,
                        )
                    )
                    continue

                calibrated_home = calibrated_probability(raw_home, ml_cal)
                calibrated_selected = calibrated_home if side == "home" else 1.0 - calibrated_home
                prob = moneyline_outcome_probabilities(
                    calibrated_selected,
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
                    pinnacle_probability=float(pin_selected),
                    benchmark_probability=float(pin_selected),
                    prob=prob,
                    reliability=gate.reliability,
                    uncertainty=None,
                    support_n=gate.support_n,
                    staking_probability=None,
                    settlement=settlement,
                )
                row.update(
                    {
                        "calibrated_model_output": float(calibrated_selected),
                        "calibration_beta": None,
                        "calibration_slope": float(ml_cal.slope),
                        "pinnacle_anchor": float(pin_selected),
                    }
                )
                board_rows.append(row)

                actual = settlement.value
                q = float(g["qbelo_home"]) if side == "home" else 1.0 - float(g["qbelo_home"])
                x = float(g["xgb_home"]) if side == "home" else 1.0 - float(g["xgb_home"])
                for name, p in (
                    ("moneyline_pinnacle_no_vig", float(pin_selected)),
                    ("moneyline_raw_exact_avg", float(raw_selected)),
                    ("moneyline_raw_qbelo", q),
                    ("moneyline_raw_xgb", x),
                ):
                    benchmark_rows[name].append({"settlement": actual, "p": p})

            pin_spread_line = _unique_pinnacle_line(idx, gid, "spread", "home")
            expected = g.get("expected_home_margin")
            market_home_margin = None if pin_spread_line is None else -float(pin_spread_line)
            calibrated_margin = None
            if expected is not None and market_home_margin is not None and spread_cal.supported:
                calibrated_margin = calibrated_point_mean(float(expected), market_home_margin, spread_cal)

            for side in ("home", "away"):
                offer = V1._best(idx, gid, "spread", side)
                if offer is None:
                    continue
                settlement = V1._spread_settlement(side, float(offer.line), hs, aw)
                gate = evaluate_offer(gs, offer, spread_gate_states["normal_cdf"])
                incumbent = None
                if "calibrated_normal" in spread_gate_states:
                    incumbent_result = evaluate_offer(gs, offer, spread_gate_states["calibrated_normal"])
                    if incumbent_result.supported and incumbent_result.actionable_probability is not None:
                        incumbent = float(incumbent_result.actionable_probability)
                        benchmark_rows["spread_incumbent_calibrated_normal"].append(
                            {"settlement": settlement.value, "p": incumbent}
                        )
                reason = None
                if expected is None:
                    reason = "missing_expected_margin"
                elif pin_spread_line is None:
                    reason = "missing_or_ambiguous_pinnacle_spread_anchor"
                elif not spread_cal.supported:
                    reason = spread_cal.reason
                elif not gate.supported:
                    reason = gate.reason
                if reason is not None:
                    board_rows.append(
                        V1._unsupported_row(
                            gid=gid,
                            g=g,
                            block=block,
                            offer=offer,
                            market_type="spread",
                            raw_model_output=expected,
                            pinnacle_probability=None,
                            support_n=gate.support_n,
                            reason=reason,
                            reliability=gate.reliability,
                            settlement=settlement,
                            benchmark_probability=incumbent,
                        )
                    )
                    continue
                prob = empirical_spread_probabilities(
                    spread_cal.residuals,
                    float(calibrated_margin),
                    side,
                    float(offer.line),
                )
                row = V1._supported_row(
                    gid=gid,
                    g=g,
                    block=block,
                    offer=offer,
                    market_type="spread",
                    raw_model_output=float(expected),
                    pinnacle_probability=None,
                    benchmark_probability=incumbent,
                    prob=prob,
                    reliability=gate.reliability,
                    uncertainty=None,
                    support_n=gate.support_n,
                    staking_probability=None,
                    settlement=settlement,
                )
                row.update(
                    {
                        "calibrated_model_output": float(calibrated_margin),
                        "calibration_beta": float(spread_cal.beta),
                        "calibration_slope": None,
                        "pinnacle_anchor": float(market_home_margin),
                    }
                )
                board_rows.append(row)

            pin_total = _pinnacle_total_line(idx, gid)
            predicted = g.get("predicted_total")
            calibrated_total = None
            if predicted is not None and pin_total is not None and total_cal.supported:
                calibrated_total = calibrated_point_mean(float(predicted), float(pin_total), total_cal)

            for side in ("over", "under"):
                offer = V1._best(idx, gid, "total", side)
                if offer is None:
                    continue
                settlement = V1._total_settlement(side, float(offer.line), hs, aw)
                gate = evaluate_offer(gs, offer, total_gate_states["normal_cdf"])
                incumbent = None
                if "calibrated_normal" in total_gate_states:
                    incumbent_result = evaluate_offer(gs, offer, total_gate_states["calibrated_normal"])
                    if incumbent_result.supported and incumbent_result.actionable_probability is not None:
                        incumbent = float(incumbent_result.actionable_probability)
                        benchmark_rows["total_incumbent_calibrated_normal"].append(
                            {"settlement": settlement.value, "p": incumbent}
                        )
                reason = None
                if predicted is None:
                    reason = "missing_r4_total"
                elif pin_total is None:
                    reason = "missing_or_ambiguous_pinnacle_total_anchor"
                elif not total_cal.supported:
                    reason = total_cal.reason
                elif not gate.supported:
                    reason = gate.reason
                if reason is not None:
                    board_rows.append(
                        V1._unsupported_row(
                            gid=gid,
                            g=g,
                            block=block,
                            offer=offer,
                            market_type="total",
                            raw_model_output=predicted,
                            pinnacle_probability=None,
                            support_n=gate.support_n,
                            reason=reason,
                            reliability=gate.reliability,
                            settlement=settlement,
                            benchmark_probability=incumbent,
                        )
                    )
                    continue
                prob = empirical_total_probabilities(
                    total_cal.residuals,
                    float(calibrated_total),
                    side,
                    float(offer.line),
                )
                row = V1._supported_row(
                    gid=gid,
                    g=g,
                    block=block,
                    offer=offer,
                    market_type="total",
                    raw_model_output=float(predicted),
                    pinnacle_probability=None,
                    benchmark_probability=incumbent,
                    prob=prob,
                    reliability=gate.reliability,
                    uncertainty=None,
                    support_n=gate.support_n,
                    staking_probability=None,
                    settlement=settlement,
                )
                row.update(
                    {
                        "calibrated_model_output": float(calibrated_total),
                        "calibration_beta": float(total_cal.beta),
                        "calibration_slope": None,
                        "pinnacle_anchor": float(pin_total),
                    }
                )
                board_rows.append(row)

    board_rows.sort(
        key=lambda r: (
            int(r["season"]),
            str(r["week"]),
            r["game_id"],
            r["market_type"],
            r["selected_side"],
            r["sportsbook"],
            -9999.0 if r["line"] is None else float(r["line"]),
        )
    )
    out.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(board_rows, infer_schema_length=None).write_parquet(
        out / "full_board.parquet", compression="zstd"
    )
    pl.DataFrame(calibration_states, infer_schema_length=None).write_ndjson(
        out / "calibration_state_by_block.ndjson"
    )

    markets: dict[str, dict] = {}
    for market in ("moneyline", "spread", "total"):
        rr = [r for r in board_rows if r["market_type"] == market]
        supported = [r for r in rr if r["supported"]]
        positive = [r for r in supported if r["expected_value"] is not None and float(r["expected_value"]) > 0]
        nonpositive = [r for r in supported if r["expected_value"] is not None and float(r["expected_value"]) <= 0]
        markets[market] = {
            "rows": len(rr),
            "supported": len(supported),
            "unsupported": len(rr) - len(supported),
            "positive_ev_n": len(positive),
            "nonpositive_ev_n": len(nonpositive),
            "positive_ev_realized_roi": V1._roi(positive),
            "nonpositive_ev_realized_roi": V1._roi(nonpositive),
            "probability_metrics": V1._candidate_probability_metrics(rr),
            "reliability": {
                tier: sum(r["reliability"] == tier for r in rr)
                for tier in ("HIGH", "MEDIUM", "LOW", "UNSUPPORTED")
            },
            "unsupported_reasons": {
                reason: sum((not r["supported"]) and r.get("reason") == reason for r in rr)
                for reason in sorted({r.get("reason") for r in rr if not r["supported"] and r.get("reason")})
            },
        }

    benchmark_metrics = {name: V1._binary_metrics(rows, "p") for name, rows in benchmark_rows.items()}
    ev_rows = V1._ev_calibration(board_rows)
    pl.DataFrame(ev_rows, infer_schema_length=None).write_csv(out / "ev_calibration.csv")
    frozen = V1._frozen_preservation(root, board_rows)
    _json_write(out / "frozen_edge_preservation.json", frozen)

    scorecard = {
        "version": VERSION,
        "prereg_config_sha256": config_sha,
        "development_seasons": DEV,
        "sealed_seasons": [2025],
        "chronology": "expanding prior season-week blocks only",
        "candidate_families": {
            "moneyline": cfg["candidates"]["moneyline"]["name"],
            "spread": cfg["candidates"]["spread"]["name"],
            "total": cfg["candidates"]["total"]["name"],
        },
        "value_semantics": "strict expected_value > 0",
        "play_through": "deferred until core probability acceptance",
        "markets": markets,
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
            "scope": "evaluator_only",
            "new_observation_policy": "OBSERVATIONAL_ONLY_NOT_TUNED",
        },
    )
    _json_write(
        out / "observations.json",
        {
            "label": "OBSERVATIONAL_ONLY_NOT_TUNED",
            "items": [],
            "note": "V2 performs no wagering bucket, price region, or disagreement threshold search.",
        },
    )
    print(json.dumps({"markets": markets, "calibration_blocks": len(calibration_states)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default=str(ROOT / "config/task05f_evaluator_rebuild_v2_prereg.yaml"),
    )
    parser.add_argument("--out", default=str(ROOT / "artifacts/task05f/rebuild_v2"))
    args = parser.parse_args()
    run(ROOT, Path(args.config), Path(args.out))
