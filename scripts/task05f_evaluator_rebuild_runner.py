#!/usr/bin/env python3
"""Chronological Task05F evaluator-only rebuild runner.

This runner consumes frozen football-model outputs and frozen market evidence.
It does not fit or tune any football model and does not search betting buckets.

Candidate families are preregistered in config/task05f_evaluator_rebuild_v1.yaml:
- moneyline: exact AVG of frozen QB-Elo + XGB
- spread: prior-only empirical Expected Margin residual distribution
- total: prior-only empirical Ridge R4 residual distribution

Every actionable wager is evaluated at its own shopped line/price. Point markets
use explicit WIN/PUSH/LOSS probability mass and three-way EV economics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import yaml
from sklearn.metrics import roc_auc_score

from nfl_edge.market_data.matching import _NAME_TO_ABBR
from nfl_edge.value.contracts import GameState, NormalizedOffer
from nfl_edge.value.evaluators import evaluate_offer, exact_avg
from nfl_edge.value.fitting import fit_ml_states, fit_point_states
from nfl_edge.value.market_math import (
    american_to_decimal,
    proportional_no_vig,
    shop_moneyline,
    shop_spread,
    shop_total,
)
from nfl_edge.value.wager_economics import (
    OutcomeProbabilities,
    PriceStatus,
    Settlement,
    classify_price,
    empirical_spread_probabilities,
    empirical_total_probabilities,
    fair_american_three_way,
    moneyline_outcome_probabilities,
    moneyline_settlement,
)

ROOT = Path(__file__).resolve().parents[1]
DEV = [2020, 2021, 2022, 2023, 2024]
SEALED = {2025}
VERSION = "task05f_evaluator_rebuild_v1"
MIN_PRIOR = 128


def _json_write(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _config(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    cfg = yaml.safe_load(raw)
    return cfg, hashlib.sha256(raw).hexdigest()


def _block_key(season: int, week: Any) -> str:
    return f"{int(season):04d}-{str(week).zfill(2)}"


def _assert_unsealed(seasons: list[int]) -> None:
    bad = SEALED.intersection({int(x) for x in seasons})
    if bad:
        raise RuntimeError(f"SEALED season requested before materialization: {sorted(bad)}")


def _safe_scan(path: Path, cols: list[str]) -> pl.LazyFrame:
    return pl.scan_parquet(path).select(cols).filter(pl.col("season").is_in(DEV))


def build_inputs(root: Path) -> dict[str, dict]:
    qe = _safe_scan(
        root / "data/modeling/development_v1/qb_elo_predictions_2018_2024.parquet",
        ["game_id", "season", "week", "predicted_home_win_probability"],
    ).rename({"predicted_home_win_probability": "qbelo_home"})
    xb = (
        _safe_scan(
            root / "data/modeling/development_v1/chronology_corrected/xgboost_candidate_predictions_2018_2024.parquet",
            ["candidate_id", "game_id", "season", "week", "warmup", "prediction_probability"],
        )
        .filter(pl.col("candidate_id") == "conservative")
        .with_columns(
            pl.when(pl.col("warmup"))
            .then(None)
            .otherwise(pl.col("prediction_probability"))
            .alias("xgb_home")
        )
        .select(["game_id", "xgb_home"])
    )
    em = (
        _safe_scan(
            root / "data/modeling/development_v1/expected_margin_predictions_2018_2024.parquet",
            ["candidate_id", "game_id", "season", "week", "expected_home_margin"],
        )
        .filter(pl.col("candidate_id") == "stable")
        .select(["game_id", "expected_home_margin"])
    )
    r4 = (
        pl.scan_parquet(root / "reports/task05d/task05d_ridge_predictions.parquet")
        .select(["candidate_id", "game_id", "season", "week", "predicted_total"])
        .filter((pl.col("candidate_id") == "R4") & pl.col("season").is_in(DEV))
        .select(["game_id", "predicted_total"])
    )
    outcomes = _safe_scan(
        root / "data/frozen/games/games_2018_2025.parquet",
        ["game_id", "season", "home_score", "away_score"],
    )
    df = (
        qe.join(xb, on="game_id", how="left")
        .join(em, on="game_id", how="left")
        .join(r4, on="game_id", how="left")
        .join(outcomes, on=["game_id", "season"], how="inner")
        .collect()
    )
    _assert_unsealed(df["season"].unique().to_list())
    return {r["game_id"]: r for r in df.to_dicts()}


def build_market(root: Path, games: dict[str, dict]) -> dict[tuple[str, str, str, str], list[NormalizedOffer]]:
    cg = (
        pl.read_parquet(root / "data/market_data/canonical/canonical_games.parquet")
        .filter(pl.col("game_id").is_in(list(games)))
        .select(["game_id", "home_abbr", "away_abbr"])
    )
    team_sides = {r["game_id"]: (r["home_abbr"], r["away_abbr"]) for r in cg.to_dicts()}
    bm = pl.read_parquet(root / "data/market_data/canonical/canonical_book_market.parquet").filter(
        pl.col("game_id").is_in(list(games))
    )
    idx: dict[tuple[str, str, str, str], list[NormalizedOffer]] = {}
    for r in bm.to_dicts():
        book = r.get("bookmaker_key")
        mk = r.get("market_key")
        gid = r.get("game_id")
        if book not in {"draftkings", "fanduel", "pinnacle"} or mk not in {"h2h", "spreads", "totals"}:
            continue
        if mk == "totals":
            side = str(r.get("outcome_name", "")).strip().lower()
            if side not in {"over", "under"}:
                continue
        else:
            abbr = _NAME_TO_ABBR.get(str(r.get("outcome_name", "")).strip())
            home, away = team_sides.get(gid, (None, None))
            side = "home" if abbr == home else "away" if abbr == away else None
            if side is None:
                continue
        market_type = {"h2h": "moneyline", "spreads": "spread", "totals": "total"}[mk]
        try:
            offer = NormalizedOffer(
                market_type=market_type,
                side=side,
                book=book,
                price_american=int(r["american_price"]),
                line=None if market_type == "moneyline" else float(r["point"]),
                snapshot_utc=str(r.get("actual_snapshot_timestamp_utc") or r.get("requested_snapshot_timestamp_utc") or ""),
            )
        except Exception:
            continue
        idx.setdefault((gid, market_type, side, book), []).append(offer)
    return idx


def _best(
    idx: dict[tuple[str, str, str, str], list[NormalizedOffer]],
    gid: str,
    market_type: str,
    side: str,
    books: tuple[str, ...] = ("draftkings", "fanduel"),
) -> NormalizedOffer | None:
    offers = [o for book in books for o in idx.get((gid, market_type, side, book), [])]
    if market_type == "moneyline":
        return shop_moneyline(offers)
    if market_type == "spread":
        return shop_spread(offers)
    return shop_total(side, offers)


def _pin(
    idx: dict[tuple[str, str, str, str], list[NormalizedOffer]],
    gid: str,
    market_type: str,
    side: str,
) -> NormalizedOffer | None:
    offers = idx.get((gid, market_type, side, "pinnacle"), [])
    if not offers:
        return None
    if market_type == "moneyline":
        return shop_moneyline(offers)
    if market_type == "spread":
        return shop_spread(offers)
    return shop_total(side, offers)


def _spread_settlement(side: str, line: float, home_score: int, away_score: int) -> Settlement:
    margin = (home_score - away_score) if side == "home" else (away_score - home_score)
    value = float(margin) + float(line)
    if abs(value) < 1e-9:
        return Settlement.PUSH
    return Settlement.WIN if value > 0 else Settlement.LOSS


def _total_settlement(side: str, line: float, home_score: int, away_score: int) -> Settlement:
    total = float(home_score + away_score)
    value = total - float(line) if side == "over" else float(line) - total
    if abs(value) < 1e-9:
        return Settlement.PUSH
    return Settlement.WIN if value > 0 else Settlement.LOSS


def _profit(settlement: Settlement, price_american: int) -> float:
    if settlement is Settlement.PUSH:
        return 0.0
    if settlement is Settlement.LOSS:
        return -1.0
    return float(american_to_decimal(price_american) - 1.0)


def _training_material(
    games: dict[str, dict],
    idx: dict[tuple[str, str, str, str], list[NormalizedOffer]],
    prior_gids: list[str],
) -> tuple[list[dict], list[dict], list[dict], list[float], list[float], int, int]:
    ml_rows: list[dict] = []
    spread_rows: list[dict] = []
    total_rows: list[dict] = []
    spread_residuals: list[float] = []
    total_residuals: list[float] = []
    ties = 0
    completed = 0
    for gid in prior_gids:
        g = games[gid]
        hs, aw = int(g["home_score"]), int(g["away_score"])
        completed += 1
        if hs == aw:
            ties += 1
        block = _block_key(g["season"], g["week"])

        ph = _pin(idx, gid, "moneyline", "home")
        pa = _pin(idx, gid, "moneyline", "away")
        if ph and pa and g["qbelo_home"] is not None and g["xgb_home"] is not None and hs != aw:
            pin_home, _ = proportional_no_vig(ph.price_american, pa.price_american)
            ml_rows.append(
                {
                    "block": block,
                    "qb": float(g["qbelo_home"]),
                    "xgb": float(g["xgb_home"]),
                    "pin": float(pin_home),
                    "y": int(hs > aw),
                }
            )

        if g["expected_home_margin"] is not None:
            expected = float(g["expected_home_margin"])
            spread_residuals.append(float(hs - aw) - expected)
            offer = _best(idx, gid, "spread", "home")
            if offer is not None:
                settlement = _spread_settlement("home", float(offer.line), hs, aw)
                if settlement is not Settlement.PUSH:
                    spread_rows.append(
                        {
                            "block": block,
                            "delta": expected + float(offer.line),
                            "market_level": abs(float(offer.line)),
                            "residual": float(hs - aw) - expected,
                            "y": int(settlement is Settlement.WIN),
                        }
                    )

        if g["predicted_total"] is not None:
            predicted = float(g["predicted_total"])
            total_residuals.append(float(hs + aw) - predicted)
            offer = _best(idx, gid, "total", "over")
            if offer is not None:
                settlement = _total_settlement("over", float(offer.line), hs, aw)
                if settlement is not Settlement.PUSH:
                    total_rows.append(
                        {
                            "block": block,
                            "delta": predicted - float(offer.line),
                            "market_level": float(offer.line),
                            "residual": float(hs + aw) - predicted,
                            "y": int(settlement is Settlement.WIN),
                        }
                    )
    return ml_rows, spread_rows, total_rows, spread_residuals, total_residuals, ties, completed


def _unsupported_row(
    *,
    gid: str,
    g: dict,
    block: str,
    offer: NormalizedOffer,
    market_type: str,
    raw_model_output: float | None,
    pinnacle_probability: float | None,
    support_n: int,
    reason: str | None,
    reliability: str = "UNSUPPORTED",
    settlement: Settlement,
    benchmark_probability: float | None = None,
) -> dict:
    return {
        "game_id": gid,
        "season": int(g["season"]),
        "week": str(g["week"]),
        "block": block,
        "market_type": market_type,
        "selected_side": offer.side,
        "sportsbook": offer.book,
        "line": offer.line,
        "american_odds": int(offer.price_american),
        "decimal_odds": float(american_to_decimal(offer.price_american)),
        "market_snapshot_timestamp": offer.snapshot_utc,
        "raw_model_output": raw_model_output,
        "pinnacle_no_vig_probability": pinnacle_probability,
        "benchmark_probability": benchmark_probability,
        "p_win": None,
        "p_push": None,
        "p_loss": None,
        "actionable_probability": None,
        "staking_probability": None,
        "fair_price_american": None,
        "expected_value": None,
        "strict_positive_value": False,
        "play_through_price_american": None,
        "price_status": PriceStatus.PASS.value,
        "reliability": reliability,
        "uncertainty": None,
        "support_n": int(support_n),
        "supported": False,
        "reason": reason,
        "settlement": settlement.value,
        "realized_profit": _profit(settlement, offer.price_american),
    }


def _supported_row(
    *,
    gid: str,
    g: dict,
    block: str,
    offer: NormalizedOffer,
    market_type: str,
    raw_model_output: float,
    pinnacle_probability: float | None,
    benchmark_probability: float | None,
    prob: OutcomeProbabilities,
    reliability: str,
    uncertainty: float | None,
    support_n: int,
    staking_probability: float | None,
    settlement: Settlement,
) -> dict:
    assessment = classify_price(prob, offer.price_american, play_through_price_american=None)
    return {
        "game_id": gid,
        "season": int(g["season"]),
        "week": str(g["week"]),
        "block": block,
        "market_type": market_type,
        "selected_side": offer.side,
        "sportsbook": offer.book,
        "line": offer.line,
        "american_odds": int(offer.price_american),
        "decimal_odds": float(american_to_decimal(offer.price_american)),
        "market_snapshot_timestamp": offer.snapshot_utc,
        "raw_model_output": float(raw_model_output),
        "pinnacle_no_vig_probability": pinnacle_probability,
        "benchmark_probability": benchmark_probability,
        "p_win": float(prob.p_win),
        "p_push": float(prob.p_push),
        "p_loss": float(prob.p_loss),
        "actionable_probability": float(prob.p_win),
        "staking_probability": staking_probability,
        "fair_price_american": int(fair_american_three_way(prob)),
        "expected_value": float(assessment.expected_value),
        "strict_positive_value": bool(assessment.strict_positive_value),
        "play_through_price_american": None,
        "price_status": assessment.status.value,
        "reliability": reliability,
        "uncertainty": uncertainty,
        "support_n": int(support_n),
        "supported": True,
        "reason": None,
        "settlement": settlement.value,
        "realized_profit": _profit(settlement, offer.price_american),
    }


def _binary_metrics(rows: list[dict], probability_key: str) -> dict:
    rr = [
        r
        for r in rows
        if r.get(probability_key) is not None and r.get("settlement") in {Settlement.WIN.value, Settlement.LOSS.value}
    ]
    if not rr:
        return {"n": 0, "brier": None, "log_loss": None, "auc": None}
    p = np.clip(np.asarray([float(r[probability_key]) for r in rr]), 1e-9, 1 - 1e-9)
    y = np.asarray([1 if r["settlement"] == Settlement.WIN.value else 0 for r in rr], dtype=int)
    brier = float(np.mean((p - y) ** 2))
    log_loss = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    auc = float(roc_auc_score(y, p)) if len(set(y.tolist())) == 2 else None
    return {"n": len(rr), "brier": brier, "log_loss": log_loss, "auc": auc}


def _candidate_probability_metrics(rows: list[dict]) -> dict:
    rr = [r for r in rows if r.get("supported") and r.get("p_win") is not None]
    if not rr:
        return {
            "n": 0,
            "three_way_brier": None,
            "three_way_log_loss": None,
            "conditional_nonpush": {"n": 0, "brier": None, "log_loss": None, "auc": None},
        }
    briers: list[float] = []
    losses: list[float] = []
    conditional: list[dict] = []
    for r in rr:
        actual = r["settlement"]
        probs = {
            Settlement.WIN.value: float(r["p_win"]),
            Settlement.PUSH.value: float(r["p_push"]),
            Settlement.LOSS.value: float(r["p_loss"]),
        }
        target = {k: 1.0 if actual == k else 0.0 for k in probs}
        briers.append(sum((probs[k] - target[k]) ** 2 for k in probs))
        losses.append(-math.log(max(probs[actual], 1e-12)))
        if actual != Settlement.PUSH.value:
            den = probs[Settlement.WIN.value] + probs[Settlement.LOSS.value]
            conditional.append(
                {
                    **r,
                    "conditional_p": probs[Settlement.WIN.value] / den if den > 0 else None,
                }
            )
    cond = _binary_metrics(conditional, "conditional_p")
    return {
        "n": len(rr),
        "three_way_brier": float(np.mean(briers)),
        "three_way_log_loss": float(np.mean(losses)),
        "conditional_nonpush": cond,
        "mean_p_win": float(np.mean([r["p_win"] for r in rr])),
        "mean_p_push": float(np.mean([r["p_push"] for r in rr])),
        "std_p_win": float(np.std([r["p_win"] for r in rr])),
    }


def _roi(rows: list[dict]) -> float | None:
    return None if not rows else float(np.mean([float(r["realized_profit"]) for r in rows]))


def _ev_band(ev: float) -> str:
    if ev <= 0:
        return "<=0%"
    if ev <= 0.02:
        return "0-2%"
    if ev <= 0.05:
        return "2-5%"
    if ev <= 0.10:
        return "5-10%"
    return ">10%"


def _ev_calibration(rows: list[dict]) -> list[dict]:
    labels = ["<=0%", "0-2%", "2-5%", "5-10%", ">10%"]
    out: list[dict] = []
    supported = [r for r in rows if r.get("supported") and r.get("expected_value") is not None]
    for market in ("moneyline", "spread", "total"):
        market_rows = [r for r in supported if r["market_type"] == market]
        for label in labels:
            rr = [r for r in market_rows if _ev_band(float(r["expected_value"])) == label]
            out.append(
                {
                    "market_type": market,
                    "ev_band": label,
                    "n": len(rr),
                    "mean_predicted_ev": None if not rr else float(np.mean([r["expected_value"] for r in rr])),
                    "realized_roi": _roi(rr),
                    "wins": sum(r["settlement"] == Settlement.WIN.value for r in rr),
                    "pushes": sum(r["settlement"] == Settlement.PUSH.value for r in rr),
                    "losses": sum(r["settlement"] == Settlement.LOSS.value for r in rr),
                }
            )
    return out


def _group_profit_metrics(rows: list[dict]) -> dict:
    return {
        "n": len(rows),
        "profit": float(sum(float(r["profit"]) for r in rows)),
        "roi": None if not rows else float(np.mean([float(r["profit"]) for r in rows])),
        "wins": sum(int(r["w"]) for r in rows),
        "pushes": sum(int(r["p_push"]) for r in rows),
    }


def _frozen_candidate_rows(root: Path) -> dict[str, list[dict]]:
    discovery = pl.read_csv(root / "reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv")
    confirm = pl.read_csv(root / "reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv")
    ledger = pl.concat([discovery, confirm], how="vertical_relaxed")
    specs = {
        "ML_DOG_VALUE_ZONE_AVG": (
            (pl.col("family") == "ML_DOG_VALUE_ZONE") & (pl.col("model") == "AVG") & (pl.col("bucket") == "ZONE")
        ),
        "ML_CORROBORATED_DOG_VALUE_ZONE": (
            (pl.col("family") == "ML_DOG_VALUE_ZONE") & (pl.col("model") == "CORROB") & (pl.col("bucket") == "ZONE")
        ),
        "ML_AVG_0_2": (
            (pl.col("family") == "ML_AVG_DISAGREEMENT") & (pl.col("model") == "AVG") & (pl.col("bucket") == "0-2")
        ),
        "SPREAD_0_4_DISCOVERY_UNION": (
            (pl.col("family") == "SPREAD_DISAGREEMENT")
            & (pl.col("model") == "EXPECTED_MARGIN")
            & pl.col("bucket").is_in(["0-1", "1-2", "2-3", "3-4"])
        ),
    }
    return {name: ledger.filter(expr).to_dicts() for name, expr in specs.items()}


def _frozen_preservation(root: Path, board_rows: list[dict]) -> dict:
    frozen = _frozen_candidate_rows(root)
    ml_idx = {
        (r["game_id"], r["selected_side"], int(r["american_odds"])): r
        for r in board_rows
        if r["market_type"] == "moneyline"
    }
    spread_idx = {
        (r["game_id"], r["selected_side"], round(float(r["line"]), 6), int(r["american_odds"])): r
        for r in board_rows
        if r["market_type"] == "spread" and r["line"] is not None
    }
    out: dict[str, dict] = {}
    for name, baseline in frozen.items():
        matched: list[tuple[dict, dict]] = []
        missing = 0
        for b in baseline:
            if name.startswith("SPREAD"):
                if b.get("reconstructed_line") is None:
                    missing += 1
                    continue
                key = (
                    b["game_id"],
                    b["selected_side"],
                    round(float(b["reconstructed_line"]), 6),
                    int(b["price_american"]),
                )
                candidate = spread_idx.get(key)
            else:
                key = (b["game_id"], b["selected_side"], int(b["price_american"]))
                candidate = ml_idx.get(key)
            if candidate is None:
                missing += 1
            else:
                matched.append((b, candidate))

        def pack(pairs: list[tuple[dict, dict]]) -> dict:
            rows = [
                {
                    "profit": float(b["profit"]),
                    "w": int(b["w"]),
                    "p_push": int(b["p_push"]),
                    "season": int(b["season"]),
                }
                for b, _ in pairs
            ]
            base = _group_profit_metrics(rows)
            by_season = {
                str(season): _group_profit_metrics([r for r in rows if r["season"] == season])
                for season in DEV
                if any(r["season"] == season for r in rows)
            }
            return {**base, "per_season": by_season}

        supported = [(b, c) for b, c in matched if c.get("supported")]
        kept = [(b, c) for b, c in supported if float(c["expected_value"]) > 0.0]
        rejected = [(b, c) for b, c in supported if float(c["expected_value"]) <= 0.0]
        unsupported = [(b, c) for b, c in matched if not c.get("supported")]
        out[name] = {
            "baseline": pack([(b, {}) for b in baseline]),
            "exact_offer_joined_n": len(matched),
            "missing_exact_offer_n": missing,
            "supported": pack(supported),
            "positive_ev_kept": pack(kept),
            "nonpositive_ev_rejected": pack(rejected),
            "unsupported": pack(unsupported),
        }
    return out


def run(root: Path, config_path: Path, out: Path) -> None:
    cfg, config_sha = _config(config_path)
    _assert_unsealed(cfg.get("development_seasons", []))
    games = build_inputs(root)
    idx = build_market(root, games)
    game_blocks = sorted((_block_key(g["season"], g["week"]), gid) for gid, g in games.items())
    ordered_blocks = sorted({block for block, _ in game_blocks})

    board_rows: list[dict] = []
    benchmark_rows: dict[str, list[dict]] = {
        "moneyline_pinnacle_no_vig": [],
        "moneyline_raw_qbelo": [],
        "moneyline_raw_xgb": [],
        "spread_incumbent_calibrated_normal": [],
        "total_incumbent_calibrated_normal": [],
    }

    for block in ordered_blocks:
        current = [gid for b, gid in game_blocks if b == block]
        prior = [gid for b, gid in game_blocks if b < block]
        ml_train, spread_train, total_train, spread_resid, total_resid, prior_ties, prior_games = _training_material(
            games, idx, prior
        )
        ml_states = fit_ml_states(ml_train, VERSION, config_sha)
        spread_states = fit_point_states(spread_train, "spread", VERSION, config_sha)
        total_states = fit_point_states(total_train, "total", VERSION, config_sha)

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

            ph = _pin(idx, gid, "moneyline", "home")
            pa = _pin(idx, gid, "moneyline", "away")
            pin_probs = None
            if ph and pa:
                pin_probs = proportional_no_vig(ph.price_american, pa.price_american)

            for side in ("home", "away"):
                offer = _best(idx, gid, "moneyline", side)
                if offer is None:
                    continue
                settlement = moneyline_settlement(side, hs, aw)
                pin_selected = None if pin_probs is None else (pin_probs[0] if side == "home" else pin_probs[1])
                raw = exact_avg(gs, side)
                if pin_selected is None:
                    board_rows.append(
                        _unsupported_row(
                            gid=gid,
                            g=g,
                            block=block,
                            offer=offer,
                            market_type="moneyline",
                            raw_model_output=raw,
                            pinnacle_probability=None,
                            support_n=len(ml_train),
                            reason="missing_pinnacle_benchmark",
                            settlement=settlement,
                        )
                    )
                    continue
                gate = evaluate_offer(gs, offer, ml_states["exact_avg"], pinnacle_no_vig_selected=float(pin_selected))
                if not gate.supported or gate.actionable_probability is None:
                    board_rows.append(
                        _unsupported_row(
                            gid=gid,
                            g=g,
                            block=block,
                            offer=offer,
                            market_type="moneyline",
                            raw_model_output=raw,
                            pinnacle_probability=float(pin_selected),
                            support_n=gate.support_n,
                            reason=gate.reason,
                            reliability=gate.reliability,
                            settlement=settlement,
                        )
                    )
                    continue
                prob = moneyline_outcome_probabilities(
                    float(gate.actionable_probability), prior_ties=prior_ties, prior_games=prior_games
                )
                nonpush = 1.0 - prob.p_push
                staking = None if gate.staking_probability is None else float(gate.staking_probability) * nonpush
                board_rows.append(
                    _supported_row(
                        gid=gid,
                        g=g,
                        block=block,
                        offer=offer,
                        market_type="moneyline",
                        raw_model_output=float(gate.actionable_probability),
                        pinnacle_probability=float(pin_selected),
                        benchmark_probability=float(pin_selected),
                        prob=prob,
                        reliability=gate.reliability,
                        uncertainty=gate.uncertainty,
                        support_n=gate.support_n,
                        staking_probability=staking,
                        settlement=settlement,
                    )
                )
                conditional_actual = settlement.value
                q = None if g["qbelo_home"] is None else (float(g["qbelo_home"]) if side == "home" else 1.0 - float(g["qbelo_home"]))
                x = None if g["xgb_home"] is None else (float(g["xgb_home"]) if side == "home" else 1.0 - float(g["xgb_home"]))
                for name, p in (
                    ("moneyline_pinnacle_no_vig", float(pin_selected)),
                    ("moneyline_raw_qbelo", q),
                    ("moneyline_raw_xgb", x),
                ):
                    if p is not None:
                        benchmark_rows[name].append({"settlement": conditional_actual, "p": p})

            for side in ("home", "away"):
                offer = _best(idx, gid, "spread", side)
                if offer is None:
                    continue
                settlement = _spread_settlement(side, float(offer.line), hs, aw)
                raw = g["expected_home_margin"]
                gate_state = spread_states["normal_cdf"]
                gate = evaluate_offer(gs, offer, gate_state)
                incumbent = None
                if "calibrated_normal" in spread_states:
                    incumbent_result = evaluate_offer(gs, offer, spread_states["calibrated_normal"])
                    if incumbent_result.supported and incumbent_result.actionable_probability is not None:
                        incumbent = float(incumbent_result.actionable_probability)
                        benchmark_rows["spread_incumbent_calibrated_normal"].append(
                            {"settlement": settlement.value, "p": incumbent}
                        )
                if not gate.supported or raw is None or len(spread_resid) < MIN_PRIOR:
                    board_rows.append(
                        _unsupported_row(
                            gid=gid,
                            g=g,
                            block=block,
                            offer=offer,
                            market_type="spread",
                            raw_model_output=raw,
                            pinnacle_probability=None,
                            support_n=gate.support_n,
                            reason=gate.reason or "insufficient_prior_residual_support",
                            reliability=gate.reliability,
                            settlement=settlement,
                            benchmark_probability=incumbent,
                        )
                    )
                    continue
                prob = empirical_spread_probabilities(spread_resid, float(raw), side, float(offer.line))
                board_rows.append(
                    _supported_row(
                        gid=gid,
                        g=g,
                        block=block,
                        offer=offer,
                        market_type="spread",
                        raw_model_output=float(raw),
                        pinnacle_probability=None,
                        benchmark_probability=incumbent,
                        prob=prob,
                        reliability="LOW",
                        uncertainty=None,
                        support_n=gate.support_n,
                        staking_probability=None,
                        settlement=settlement,
                    )
                )

            for side in ("over", "under"):
                offer = _best(idx, gid, "total", side)
                if offer is None:
                    continue
                settlement = _total_settlement(side, float(offer.line), hs, aw)
                raw = g["predicted_total"]
                gate_state = total_states["normal_cdf"]
                gate = evaluate_offer(gs, offer, gate_state)
                incumbent = None
                if "calibrated_normal" in total_states:
                    incumbent_result = evaluate_offer(gs, offer, total_states["calibrated_normal"])
                    if incumbent_result.supported and incumbent_result.actionable_probability is not None:
                        incumbent = float(incumbent_result.actionable_probability)
                        benchmark_rows["total_incumbent_calibrated_normal"].append(
                            {"settlement": settlement.value, "p": incumbent}
                        )
                if not gate.supported or raw is None or len(total_resid) < MIN_PRIOR:
                    board_rows.append(
                        _unsupported_row(
                            gid=gid,
                            g=g,
                            block=block,
                            offer=offer,
                            market_type="total",
                            raw_model_output=raw,
                            pinnacle_probability=None,
                            support_n=gate.support_n,
                            reason=gate.reason or "insufficient_prior_residual_support",
                            reliability=gate.reliability,
                            settlement=settlement,
                            benchmark_probability=incumbent,
                        )
                    )
                    continue
                prob = empirical_total_probabilities(total_resid, float(raw), side, float(offer.line))
                board_rows.append(
                    _supported_row(
                        gid=gid,
                        g=g,
                        block=block,
                        offer=offer,
                        market_type="total",
                        raw_model_output=float(raw),
                        pinnacle_probability=None,
                        benchmark_probability=incumbent,
                        prob=prob,
                        reliability="LOW",
                        uncertainty=None,
                        support_n=gate.support_n,
                        staking_probability=None,
                        settlement=settlement,
                    )
                )

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
    pl.DataFrame(board_rows).write_parquet(out / "full_board.parquet", compression="zstd")

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
            "positive_ev_realized_roi": _roi(positive),
            "nonpositive_ev_realized_roi": _roi(nonpositive),
            "probability_metrics": _candidate_probability_metrics(rr),
            "reliability": {
                tier: sum(r["reliability"] == tier for r in rr)
                for tier in ("HIGH", "MEDIUM", "LOW", "UNSUPPORTED")
            },
            "unsupported_reasons": {
                reason: sum((not r["supported"]) and r.get("reason") == reason for r in rr)
                for reason in sorted({r.get("reason") for r in rr if not r["supported"] and r.get("reason")})
            },
        }

    benchmark_metrics = {name: _binary_metrics(rows, "p") for name, rows in benchmark_rows.items()}
    ev_rows = _ev_calibration(board_rows)
    pl.DataFrame(ev_rows).write_csv(out / "ev_calibration.csv")
    frozen = _frozen_preservation(root, board_rows)
    _json_write(out / "frozen_edge_preservation.json", frozen)

    scorecard = {
        "version": VERSION,
        "config_sha256": config_sha,
        "development_seasons": DEV,
        "sealed_seasons": [2025],
        "chronology": "expanding prior season-week blocks only",
        "candidate_families": cfg["candidate_probability_families"],
        "value_semantics": "strict expected_value > 0",
        "play_through": "output contract present; formula deferred until core probability acceptance",
        "markets": markets,
        "benchmark_probability_metrics": benchmark_metrics,
        "acceptance_status": "EVIDENCE_PENDING_MASTER_REVIEW",
    }
    _json_write(out / "scorecard.json", scorecard)
    _json_write(
        out / "provenance.json",
        {
            "version": VERSION,
            "config_sha256": config_sha,
            "base_commit": cfg["base_commit"],
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
            "note": "No new wagering buckets or thresholds are searched by this runner.",
        },
    )
    print(json.dumps({"markets": markets, "frozen_candidates": {k: v["baseline"]["n"] for k, v in frozen.items()}}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config/task05f_evaluator_rebuild_v1.yaml"))
    parser.add_argument("--out", default=str(ROOT / "artifacts/task05f/rebuild"))
    args = parser.parse_args()
    run(ROOT, Path(args.config), Path(args.out))
