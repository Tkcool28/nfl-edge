#!/usr/bin/env python3
"""Final Task05F evaluator validation/materialization runner.

Scope ends at the account-independent candidate table. It fits no football
model, contains no selector/unit/bankroll policy, and never loads sealed 2025
outcomes. Historical OOS rows are generated through the same public
``evaluate_offer`` function used for future stored/manual offers.
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
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from nfl_edge.market_data.matching import _NAME_TO_ABBR
from nfl_edge.value.accepted_calibration import (
    calibrated_market_probability,
    fit_ml_v4,
    fit_point_v3,
    market_implied_mean,
)
from nfl_edge.value.candidate_table import (
    BookOfferContext,
    CandidateOfferContext,
    build_candidate_table,
    make_candidate_id,
)
from nfl_edge.value.contracts import (
    GameState,
    MarketAnchor,
    MoneylineV4State,
    NormalizedOffer,
    PointV3State,
    ReliabilityState,
)
from nfl_edge.value.evaluators import evaluate_offer
from nfl_edge.value.market_math import american_to_decimal, proportional_no_vig, shop_moneyline, shop_spread, shop_total
from nfl_edge.value.play_through import assess_play_through
from nfl_edge.value.reliability import support_feature
from nfl_edge.value.state_io import load_frozen_state, write_frozen_state
from nfl_edge.value.uncertainty import fit_reliability_state
from nfl_edge.value.wager_economics import (
    Settlement,
    line_allows_push,
    moneyline_settlement,
    spread_settlement,
    total_settlement,
)

ROOT = Path(__file__).resolve().parents[1]
DEV = [2020, 2021, 2022, 2023, 2024]
SEALED = {2025}
CONFIG = ROOT / "config" / "task05f_evaluator_final_v1.yaml"
VERSION = "task05f_evaluator_final_v1"


def _json_write(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_config(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    return yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()


def _block_key(season: int, week: Any) -> str:
    return f"{int(season):04d}-{str(week).zfill(2)}"


def _safe_scan(path: Path, cols: list[str]) -> pl.LazyFrame:
    return pl.scan_parquet(path).select(cols).filter(pl.col("season").is_in(DEV))


def build_inputs(root: Path) -> dict[str, dict[str, Any]]:
    qbelo = _safe_scan(
        root / "data/modeling/development_v1/qb_elo_predictions_2018_2024.parquet",
        ["game_id", "season", "week", "predicted_home_win_probability"],
    ).rename({"predicted_home_win_probability": "qbelo_home"})
    xgb = (
        _safe_scan(
            root / "data/modeling/development_v1/chronology_corrected/xgboost_candidate_predictions_2018_2024.parquet",
            ["candidate_id", "game_id", "season", "week", "warmup", "prediction_probability"],
        )
        .filter(pl.col("candidate_id") == "conservative")
        .with_columns(
            pl.when(pl.col("warmup")).then(None).otherwise(pl.col("prediction_probability")).alias("xgb_home")
        )
        .select(["game_id", "xgb_home"])
    )
    expected_margin = (
        _safe_scan(
            root / "data/modeling/development_v1/expected_margin_predictions_2018_2024.parquet",
            ["candidate_id", "game_id", "season", "week", "expected_home_margin"],
        )
        .filter(pl.col("candidate_id") == "stable")
        .select(["game_id", "expected_home_margin"])
    )
    ridge = (
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
        qbelo.join(xgb, on="game_id", how="left")
        .join(expected_margin, on="game_id", how="left")
        .join(ridge, on="game_id", how="left")
        .join(outcomes, on=["game_id", "season"], how="inner")
        .collect()
    )
    seasons = set(int(x) for x in df["season"].unique().to_list())
    if seasons.intersection(SEALED):
        raise RuntimeError("sealed 2025 entered evaluator inputs")
    return {str(row["game_id"]): row for row in df.to_dicts()}


def build_market(root: Path, games: dict[str, Any]) -> dict[tuple[str, str, str, str], list[NormalizedOffer]]:
    canonical_games = (
        pl.read_parquet(root / "data/market_data/canonical/canonical_games.parquet")
        .filter(pl.col("game_id").is_in(list(games)))
        .select(["game_id", "home_abbr", "away_abbr"])
    )
    team_sides = {str(r["game_id"]): (r["home_abbr"], r["away_abbr"]) for r in canonical_games.to_dicts()}
    book_market = pl.read_parquet(root / "data/market_data/canonical/canonical_book_market.parquet").filter(
        pl.col("game_id").is_in(list(games))
    )
    idx: dict[tuple[str, str, str, str], list[NormalizedOffer]] = {}
    for row in book_market.to_dicts():
        book = str(row.get("bookmaker_key") or "")
        market_key = str(row.get("market_key") or "")
        gid = str(row.get("game_id"))
        if book not in {"draftkings", "fanduel", "pinnacle"} or market_key not in {"h2h", "spreads", "totals"}:
            continue
        if market_key == "totals":
            side = str(row.get("outcome_name", "")).strip().lower()
            if side not in {"over", "under"}:
                continue
        else:
            abbr = _NAME_TO_ABBR.get(str(row.get("outcome_name", "")).strip())
            home, away = team_sides.get(gid, (None, None))
            side = "home" if abbr == home else "away" if abbr == away else None
            if side is None:
                continue
        market_type = {"h2h": "moneyline", "spreads": "spread", "totals": "total"}[market_key]
        try:
            offer = NormalizedOffer(
                market_type=market_type,
                side=side,
                book=book,
                price_american=int(row["american_price"]),
                line=None if market_type == "moneyline" else float(row["point"]),
                snapshot_utc=str(
                    row.get("actual_snapshot_timestamp_utc")
                    or row.get("requested_snapshot_timestamp_utc")
                    or ""
                ),
            )
        except (TypeError, ValueError):
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
    offers = [offer for book in books for offer in idx.get((gid, market_type, side, book), [])]
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
    return _best(idx, gid, market_type, side, books=("pinnacle",))


def _best_same_line(offers: list[NormalizedOffer], line: float) -> NormalizedOffer | None:
    same = [offer for offer in offers if offer.line is not None and abs(float(offer.line) - float(line)) <= 1e-6]
    return max(same, key=lambda offer: (int(offer.price_american), str(offer.snapshot_utc or "")), default=None)


def _moneyline_anchor(idx, gid: str) -> MarketAnchor | None:
    home = _pin(idx, gid, "moneyline", "home")
    away = _pin(idx, gid, "moneyline", "away")
    if home is None or away is None:
        return None
    p_home, _ = proportional_no_vig(home.price_american, away.price_american)
    return MarketAnchor("moneyline", home_no_vig_probability=float(p_home))


def _spread_anchor(idx, gid: str) -> MarketAnchor | None:
    homes = idx.get((gid, "spread", "home", "pinnacle"), [])
    aways = idx.get((gid, "spread", "away", "pinnacle"), [])
    mirrored = sorted(
        {
            round(float(home.line), 6)
            for home in homes
            if home.line is not None
            and any(away.line is not None and abs(float(home.line) + float(away.line)) <= 1e-6 for away in aways)
        }
    )
    if len(mirrored) != 1:
        return None
    home_line = float(mirrored[0])
    home_offer = _best_same_line(homes, home_line)
    away_offer = _best_same_line(aways, -home_line)
    if home_offer is None or away_offer is None:
        return None
    p_home, _ = proportional_no_vig(home_offer.price_american, away_offer.price_american)
    return MarketAnchor(
        "spread",
        threshold=-home_line,
        probability_above_nonpush=float(p_home),
        push_possible=line_allows_push(home_line),
    )


def _total_anchor(idx, gid: str) -> MarketAnchor | None:
    overs = idx.get((gid, "total", "over", "pinnacle"), [])
    unders = idx.get((gid, "total", "under", "pinnacle"), [])
    common = sorted(
        {
            round(float(over.line), 6)
            for over in overs
            if over.line is not None
            and any(under.line is not None and abs(float(over.line) - float(under.line)) <= 1e-6 for under in unders)
        }
    )
    if len(common) != 1:
        return None
    line = float(common[0])
    over_offer = _best_same_line(overs, line)
    under_offer = _best_same_line(unders, line)
    if over_offer is None or under_offer is None:
        return None
    p_over, _ = proportional_no_vig(over_offer.price_american, under_offer.price_american)
    return MarketAnchor(
        "total",
        threshold=line,
        probability_above_nonpush=float(p_over),
        push_possible=line_allows_push(line),
    )


def _training_material(games, idx, prior_gids: list[str]) -> tuple[list[dict], list[dict], list[dict], int, int]:
    ml: list[dict] = []
    spread: list[dict] = []
    total: list[dict] = []
    ties = 0
    completed = 0
    for gid in prior_gids:
        game = games[gid]
        home_score = int(game["home_score"])
        away_score = int(game["away_score"])
        completed += 1
        if home_score == away_score:
            ties += 1
        ml_anchor = _moneyline_anchor(idx, gid)
        if (
            home_score != away_score
            and ml_anchor is not None
            and game.get("qbelo_home") is not None
            and game.get("xgb_home") is not None
        ):
            ml.append(
                {
                    "qb": float(game["qbelo_home"]),
                    "xgb": float(game["xgb_home"]),
                    "pin": float(ml_anchor.home_no_vig_probability),
                    "y": int(home_score > away_score),
                }
            )
        spread_anchor = _spread_anchor(idx, gid)
        if spread_anchor is not None and game.get("expected_home_margin") is not None:
            spread.append(
                {
                    "model": float(game["expected_home_margin"]),
                    "threshold": float(spread_anchor.threshold),
                    "q": float(spread_anchor.probability_above_nonpush),
                    "push": bool(spread_anchor.push_possible),
                    "actual": float(home_score - away_score),
                }
            )
        total_anchor = _total_anchor(idx, gid)
        if total_anchor is not None and game.get("predicted_total") is not None:
            total.append(
                {
                    "model": float(game["predicted_total"]),
                    "threshold": float(total_anchor.threshold),
                    "q": float(total_anchor.probability_above_nonpush),
                    "push": bool(total_anchor.push_possible),
                    "actual": float(home_score + away_score),
                }
            )
    return ml, spread, total, ties, completed


def _fit_states(games, idx, prior_gids: list[str], config_sha: str):
    ml_rows, spread_rows, total_rows, ties, completed = _training_material(games, idx, prior_gids)
    ml_fit = fit_ml_v4([(r["qb"] + r["xgb"]) / 2.0, r["pin"], r["y"]] for r in ml_rows)
    spread_fit = fit_point_v3(
        [(r["model"], r["threshold"], r["q"], r["push"], r["actual"]) for r in spread_rows]
    )
    total_fit = fit_point_v3(
        [(r["model"], r["threshold"], r["q"], r["push"], r["actual"]) for r in total_rows]
    )

    ml_state = None
    if ml_fit.supported:
        extremity: list[float] = []
        model_gap: list[float] = []
        constituent_gap: list[float] = []
        for row in ml_rows:
            p_model = (row["qb"] + row["xgb"]) / 2.0
            p_market = calibrated_market_probability(row["pin"], ml_fit)
            extremity.append(abs(p_market - 0.5))
            model_gap.append(abs(p_model - p_market))
            constituent_gap.append(abs(row["qb"] - row["xgb"]))
        ml_state = MoneylineV4State(
            market_intercept=float(ml_fit.market_intercept),
            market_slope=float(ml_fit.market_slope),
            model_weight=float(ml_fit.model_weight),
            training_n=int(ml_fit.support_n),
            prior_ties=int(ties),
            prior_games=int(completed),
            support_features=(
                support_feature("pinnacle_extremity", extremity),
                support_feature("model_market_gap", model_gap),
                support_feature("constituent_gap", constituent_gap),
            ),
            config_sha256=config_sha,
            version="ml_v4",
        )

    def point_state(market: str, rows: list[dict], fit) -> PointV3State | None:
        if not fit.supported:
            return None
        model_gap: list[float] = []
        threshold_mag: list[float] = []
        for row in rows:
            mu_market = market_implied_mean(
                row["threshold"],
                row["q"],
                float(fit.sigma),
                push_possible=row["push"],
            )
            model_gap.append(abs(row["model"] - mu_market))
            threshold_mag.append(abs(row["threshold"]))
        return PointV3State(
            market_type=market,
            sigma=float(fit.sigma),
            beta=float(fit.beta),
            residuals=tuple(float(value) for value in fit.residuals),
            training_n=int(fit.support_n),
            support_features=(
                support_feature("model_market_gap", model_gap),
                support_feature("anchor_threshold_magnitude", threshold_mag),
            ),
            config_sha256=config_sha,
            version=f"{market}_v3",
        )

    return ml_state, point_state("spread", spread_rows, spread_fit), point_state("total", total_rows, total_fit), {
        "moneyline": ml_fit,
        "spread": spread_fit,
        "total": total_fit,
    }


def _profit(settlement: Settlement, price: int) -> float:
    if settlement is Settlement.PUSH:
        return 0.0
    if settlement is Settlement.LOSS:
        return -1.0
    return american_to_decimal(price) - 1.0


def _unsupported_row(gid: str, game: dict, block: str, offer: NormalizedOffer, market: str, reason: str, settlement: Settlement) -> dict:
    return {
        "game_id": gid,
        "season": int(game["season"]),
        "week": str(game["week"]),
        "block": block,
        "market_type": market,
        "selected_side": offer.side,
        "sportsbook": offer.book,
        "line": offer.line,
        "american_odds": int(offer.price_american),
        "market_snapshot_timestamp": offer.snapshot_utc,
        "raw_model_output": None,
        "football_model_name": None,
        "model_market_disagreement": None,
        "pinnacle_anchor_probability": None,
        "pinnacle_anchor_threshold": None,
        "p_win": None,
        "p_push": None,
        "p_loss": None,
        "actionable_probability": None,
        "conditional_nonpush_probability": None,
        "staking_probability": None,
        "staking_anchor_probability": None,
        "fair_price_american": None,
        "break_even_probability": None,
        "expected_value": None,
        "strict_positive_value": False,
        "evaluated_edge_probability": None,
        "staking_edge_probability": None,
        "reliability": "UNSUPPORTED",
        "uncertainty": None,
        "support_n": 0,
        "support_distance": None,
        "evaluator_version": None,
        "supported": False,
        "reason": reason,
        "price_status": "PASS",
        "play_through_confidence_multiplier": 0.0,
        "play_through_break_even_concession": 0.0,
        "play_through_break_even_probability": None,
        "play_through_price_american": None,
        "settlement": settlement.value,
        "realized_profit": _profit(settlement, offer.price_american),
    }


def _result_row(
    gid: str,
    game: dict,
    block: str,
    offer: NormalizedOffer,
    anchor: MarketAnchor,
    result,
    settlement: Settlement,
) -> dict:
    market = offer.market_type
    evidence = dict(result.evidence)
    if market == "moneyline":
        raw_output = evidence.get("raw_exact_avg_probability")
        model_name = "QB_ELO_XGB_EXACT_AVG"
        anchor_prob = evidence.get("raw_pinnacle_no_vig_probability")
        anchor_threshold = None
    elif market == "spread":
        raw_output = evidence.get("raw_football_output")
        model_name = "EXPECTED_MARGIN_V1_STABLE"
        anchor_prob = anchor.probability_above_nonpush
        anchor_threshold = anchor.threshold
    else:
        raw_output = evidence.get("raw_football_output")
        model_name = "RIDGE_TOTALS_R4"
        anchor_prob = anchor.probability_above_nonpush
        anchor_threshold = anchor.threshold
    play = assess_play_through(
        supported=result.supported,
        strict_expected_value=result.expected_value,
        conditional_nonpush_probability=result.conditional_nonpush_probability,
        current_break_even_probability=result.break_even_probability,
        reliability=result.reliability,
        uncertainty_radius=result.uncertainty,
    )
    return {
        "game_id": gid,
        "season": int(game["season"]),
        "week": str(game["week"]),
        "block": block,
        "market_type": market,
        "selected_side": offer.side,
        "sportsbook": offer.book,
        "line": offer.line,
        "american_odds": int(offer.price_american),
        "market_snapshot_timestamp": offer.snapshot_utc,
        "raw_model_output": raw_output,
        "football_model_name": model_name,
        "model_market_disagreement": evidence.get("model_market_disagreement"),
        "pinnacle_anchor_probability": anchor_prob,
        "pinnacle_anchor_threshold": anchor_threshold,
        "p_win": result.p_win,
        "p_push": result.p_push,
        "p_loss": result.p_loss,
        "actionable_probability": result.actionable_probability,
        "conditional_nonpush_probability": result.conditional_nonpush_probability,
        "staking_probability": result.staking_probability,
        "staking_anchor_probability": result.staking_anchor_probability,
        "fair_price_american": result.fair_price_american,
        "break_even_probability": result.break_even_probability,
        "expected_value": result.expected_value,
        "strict_positive_value": result.strict_positive_value,
        "evaluated_edge_probability": result.evaluated_edge_probability,
        "staking_edge_probability": result.staking_edge_probability,
        "reliability": result.reliability,
        "uncertainty": result.uncertainty,
        "support_n": result.support_n,
        "support_distance": result.support_distance,
        "evaluator_version": result.evaluator_version,
        "supported": result.supported,
        "reason": result.reason,
        "price_status": play.status,
        "play_through_confidence_multiplier": play.confidence_multiplier,
        "play_through_break_even_concession": play.break_even_concession,
        "play_through_break_even_probability": play.play_through_break_even_probability,
        "play_through_price_american": play.play_through_price_american,
        "settlement": settlement.value,
        "realized_profit": _profit(settlement, offer.price_american),
    }


def _manual_parity(game_state, offer, state, anchor, reliability_state, expected) -> None:
    manual = NormalizedOffer(
        market_type=offer.market_type,
        side=offer.side,
        book="manual",
        price_american=offer.price_american,
        line=offer.line,
        snapshot_utc=offer.snapshot_utc,
        source="manual",
    )
    actual = evaluate_offer(game_state, manual, state, anchor, reliability_state)
    # Book/source identity never enters evaluator math.
    if actual != expected:
        raise RuntimeError(f"stored/manual evaluator parity failed for {game_state.game_id} {offer.market_type} {offer.side}")


def _history_append(histories: dict[str, list[tuple[str, float, int]]], rows: list[dict]) -> None:
    canonical = {"moneyline": "home", "spread": "home", "total": "over"}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        market = str(row["market_type"])
        key = (market, str(row["game_id"]))
        if key in seen or str(row["selected_side"]) != canonical[market]:
            continue
        seen.add(key)
        if not row.get("supported") or row.get("settlement") not in {"WIN", "LOSS"}:
            continue
        q = row.get("conditional_nonpush_probability")
        if q is None:
            continue
        histories[market].append((str(row["block"]), float(q), 1 if row["settlement"] == "WIN" else 0))


def _logit(p: float) -> float:
    q = min(1.0 - 1e-6, max(1e-6, float(p)))
    return math.log(q / (1.0 - q))


def _probability_metrics(rows: list[dict], probability_key: str) -> dict[str, Any]:
    material = [
        row for row in rows
        if row.get("supported") and row.get(probability_key) is not None and row.get("settlement") in {"WIN", "LOSS"}
    ]
    if not material:
        return {"n": 0, "brier": None, "log_loss": None, "auc": None, "calibration_intercept": None, "calibration_slope": None}
    p = np.clip(np.asarray([float(row[probability_key]) for row in material]), 1e-6, 1 - 1e-6)
    y = np.asarray([1 if row["settlement"] == "WIN" else 0 for row in material], dtype=int)
    brier = float(np.mean((p - y) ** 2))
    log_loss = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    auc = float(roc_auc_score(y, p)) if len(set(y.tolist())) == 2 else None
    calibration_intercept = calibration_slope = None
    if len(set(y.tolist())) == 2:
        model = LogisticRegression(C=1e6, max_iter=2000, solver="lbfgs").fit(
            np.asarray([[_logit(value)] for value in p]), y
        )
        calibration_intercept = float(model.intercept_[0])
        calibration_slope = float(model.coef_[0][0])
    return {
        "n": len(material),
        "brier": brier,
        "log_loss": log_loss,
        "auc": auc,
        "calibration_intercept": calibration_intercept,
        "calibration_slope": calibration_slope,
    }


def _reliability_rows(rows: list[dict]) -> list[dict]:
    output: list[dict] = []
    for market in ("moneyline", "spread", "total"):
        material = [
            row for row in rows
            if row["market_type"] == market and row.get("supported") and row.get("conditional_nonpush_probability") is not None and row.get("settlement") in {"WIN", "LOSS"}
        ]
        for lo in np.arange(0.0, 1.0, 0.1):
            hi = float(lo + 0.1)
            bucket = [
                row for row in material
                if float(lo) <= float(row["conditional_nonpush_probability"]) < (hi if hi < 1.0 else 1.000001)
            ]
            if not bucket:
                continue
            output.append(
                {
                    "market_type": market,
                    "bin_lo": float(lo),
                    "bin_hi": hi,
                    "n": len(bucket),
                    "mean_probability": float(np.mean([row["conditional_nonpush_probability"] for row in bucket])),
                    "hit_rate": float(np.mean([1.0 if row["settlement"] == "WIN" else 0.0 for row in bucket])),
                }
            )
    return output


def _roi(rows: list[dict]) -> float | None:
    return None if not rows else float(np.mean([float(row["realized_profit"]) for row in rows]))


def _market_summary(rows: list[dict], market: str) -> dict[str, Any]:
    rr = [row for row in rows if row["market_type"] == market]
    supported = [row for row in rr if row.get("supported")]
    positive = [row for row in supported if row.get("expected_value") is not None and float(row["expected_value"]) > 0.0]
    nonpositive = [row for row in supported if row.get("expected_value") is not None and float(row["expected_value"]) <= 0.0]
    return {
        "rows": len(rr),
        "supported": len(supported),
        "unsupported": len(rr) - len(supported),
        "probability_metrics": _probability_metrics(rr, "conditional_nonpush_probability"),
        "market_anchor_metrics": _probability_metrics(rr, "staking_anchor_probability"),
        "positive_ev_n": len(positive),
        "positive_ev_realized_roi": _roi(positive),
        "nonpositive_ev_n": len(nonpositive),
        "nonpositive_ev_realized_roi": _roi(nonpositive),
        "reliability": {
            tier: sum(row.get("reliability") == tier for row in rr)
            for tier in ("HIGH", "MEDIUM", "LOW", "UNSUPPORTED")
        },
        "price_status": {
            status: sum(row.get("price_status") == status for row in rr)
            for status in ("VALUE", "PLAYABLE", "LEAN", "PASS")
        },
        "unsupported_reasons": {
            reason: sum((not row.get("supported")) and row.get("reason") == reason for row in rr)
            for reason in sorted({str(row.get("reason")) for row in rr if not row.get("supported") and row.get("reason")})
        },
    }


def _frozen_candidate_rows(root: Path) -> dict[str, list[dict]]:
    discovery = pl.read_csv(root / "reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv")
    confirmation = pl.read_csv(root / "reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv")
    ledger = pl.concat([discovery, confirmation], how="vertical_relaxed")
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


def _frozen_preservation(root: Path, rows: list[dict]) -> dict[str, Any]:
    frozen = _frozen_candidate_rows(root)
    ml_idx = {
        (row["game_id"], row["selected_side"], int(row["american_odds"])): row
        for row in rows if row["market_type"] == "moneyline"
    }
    spread_idx = {
        (row["game_id"], row["selected_side"], round(float(row["line"]), 6), int(row["american_odds"])): row
        for row in rows if row["market_type"] == "spread" and row["line"] is not None
    }
    output: dict[str, Any] = {}
    for name, baseline in frozen.items():
        matched: list[tuple[dict, dict]] = []
        missing = 0
        for base in baseline:
            if name.startswith("SPREAD"):
                if base.get("reconstructed_line") is None:
                    missing += 1
                    continue
                key = (
                    base["game_id"],
                    base["selected_side"],
                    round(float(base["reconstructed_line"]), 6),
                    int(base["price_american"]),
                )
                candidate = spread_idx.get(key)
            else:
                key = (base["game_id"], base["selected_side"], int(base["price_american"]))
                candidate = ml_idx.get(key)
            if candidate is None:
                missing += 1
            else:
                matched.append((base, candidate))

        def pack(pairs: list[tuple[dict, dict]]) -> dict[str, Any]:
            profits = [float(base["profit"]) for base, _ in pairs]
            return {
                "n": len(pairs),
                "profit": float(sum(profits)),
                "roi": None if not pairs else float(np.mean(profits)),
                "wins": sum(int(base["w"]) for base, _ in pairs),
                "pushes": sum(int(base["p_push"]) for base, _ in pairs),
            }

        supported = [(base, candidate) for base, candidate in matched if candidate.get("supported")]
        kept = [(base, candidate) for base, candidate in supported if float(candidate["expected_value"]) > 0.0]
        rejected = [(base, candidate) for base, candidate in supported if float(candidate["expected_value"]) <= 0.0]
        output[name] = {
            "baseline": pack([(base, {}) for base in baseline]),
            "exact_offer_joined_n": len(matched),
            "missing_exact_offer_n": missing,
            "supported": pack(supported),
            "positive_ev_kept": pack(kept),
            "nonpositive_ev_rejected": pack(rejected),
        }
    return output


def _book_context(idx, gid: str, market: str, side: str) -> CandidateOfferContext:
    def convert(offer: NormalizedOffer | None) -> BookOfferContext | None:
        if offer is None:
            return None
        return BookOfferContext(None if offer.line is None else float(offer.line), int(offer.price_american))

    return CandidateOfferContext(
        draftkings=convert(_best(idx, gid, market, side, books=("draftkings",))),
        fanduel=convert(_best(idx, gid, market, side, books=("fanduel",))),
        pinnacle=convert(_pin(idx, gid, market, side)),
    )


def run(root: Path, config_path: Path, out: Path) -> None:
    config, config_sha = _read_config(config_path)
    if [int(x) for x in config["development_seasons"]] != DEV or int(config["sealed_season"]) != 2025:
        raise RuntimeError("unexpected evaluator season contract")

    games = build_inputs(root)
    market_idx = build_market(root, games)
    game_blocks = sorted((_block_key(game["season"], game["week"]), gid) for gid, game in games.items())
    blocks = sorted({block for block, _ in game_blocks})
    histories: dict[str, list[tuple[str, float, int]]] = {"moneyline": [], "spread": [], "total": []}
    board_rows: list[dict] = []
    states_by_block: list[dict] = []
    parity_checks = 0

    for block in blocks:
        current = [gid for current_block, gid in game_blocks if current_block == block]
        prior = [gid for prior_block, gid in game_blocks if prior_block < block]
        ml_state, spread_state, total_state, fit_diag = _fit_states(games, market_idx, prior, config_sha)
        states = {"moneyline": ml_state, "spread": spread_state, "total": total_state}
        rel_states = {market: fit_reliability_state(histories[market]) for market in histories}
        states_by_block.append(
            {
                "block": block,
                "prior_games": len(prior),
                "current_games": len(current),
                "ml_supported": ml_state is not None,
                "spread_supported": spread_state is not None,
                "total_supported": total_state is not None,
                "ml_model_weight": None if ml_state is None else ml_state.model_weight,
                "spread_beta": None if spread_state is None else spread_state.beta,
                "total_beta": None if total_state is None else total_state.beta,
                "reliability": {
                    market: {
                        "radius": rel_states[market].radius,
                        "support_n": rel_states[market].support_n,
                        "block_count": rel_states[market].block_count,
                        "stable": rel_states[market].stable,
                    }
                    for market in histories
                },
                "fit_support_n": {
                    market: int(fit_diag[market].support_n)
                    for market in ("moneyline", "spread", "total")
                },
            }
        )

        current_rows: list[dict] = []
        for gid in current:
            game = games[gid]
            home_score = int(game["home_score"])
            away_score = int(game["away_score"])
            game_state = GameState(
                gid,
                int(game["season"]),
                str(game["week"]),
                None,
                qbelo_home=game.get("qbelo_home"),
                xgb_home=game.get("xgb_home"),
                expected_home_margin=game.get("expected_home_margin"),
                predicted_total_r4=game.get("predicted_total"),
            )
            anchors = {
                "moneyline": _moneyline_anchor(market_idx, gid),
                "spread": _spread_anchor(market_idx, gid),
                "total": _total_anchor(market_idx, gid),
            }
            for market, sides in (("moneyline", ("home", "away")), ("spread", ("home", "away")), ("total", ("over", "under"))):
                for side in sides:
                    offer = _best(market_idx, gid, market, side)
                    if offer is None:
                        continue
                    if market == "moneyline":
                        settlement = moneyline_settlement(side, home_score, away_score)
                    elif market == "spread":
                        settlement = spread_settlement(side, float(offer.line), home_score, away_score)
                    else:
                        settlement = total_settlement(side, float(offer.line), home_score, away_score)
                    state = states[market]
                    anchor = anchors[market]
                    if state is None:
                        row = _unsupported_row(gid, game, block, offer, market, "accepted_family_cold_start", settlement)
                    elif anchor is None:
                        row = _unsupported_row(gid, game, block, offer, market, "missing_pinnacle_anchor", settlement)
                    else:
                        result = evaluate_offer(game_state, offer, state, anchor, rel_states[market])
                        _manual_parity(game_state, offer, state, anchor, rel_states[market], result)
                        parity_checks += 1
                        row = _result_row(gid, game, block, offer, anchor, result, settlement)
                    current_rows.append(row)
        board_rows.extend(current_rows)
        _history_append(histories, current_rows)

    board_rows.sort(key=lambda row: (int(row["season"]), str(row["block"]), row["game_id"], row["market_type"], row["selected_side"]))
    seasons = sorted({int(row["season"]) for row in board_rows})
    if seasons != DEV or set(seasons).intersection(SEALED):
        raise RuntimeError(f"unexpected scored seasons {seasons}")

    # Freeze production-replayable states using all development observations.
    all_gids = [gid for _, gid in game_blocks]
    final_ml, final_spread, final_total, final_fit = _fit_states(games, market_idx, all_gids, config_sha)
    if final_ml is None or final_spread is None or final_total is None:
        raise RuntimeError("final accepted evaluator state is unsupported")
    final_reliability = {market: fit_reliability_state(histories[market]) for market in histories}

    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "frozen_evaluator_state.json"
    write_frozen_state(
        state_path,
        moneyline=final_ml,
        spread=final_spread,
        total=final_total,
        reliability=final_reliability,
        metadata={
            "version": VERSION,
            "development_seasons": DEV,
            "sealed_season": 2025,
            "config_sha256": config_sha,
            "football_models_frozen": True,
            "play_through_max_break_even_concession": 0.015,
        },
    )
    reloaded = load_frozen_state(state_path)
    if reloaded["moneyline"] != final_ml or reloaded["spread"] != final_spread or reloaded["total"] != final_total:
        raise RuntimeError("frozen evaluator state round-trip failed")

    historical_df = pl.DataFrame(board_rows, infer_schema_length=None)
    historical_df.write_parquet(out / "historical_evaluator_board.parquet", compression="zstd")
    with (out / "state_by_block.ndjson").open("w") as handle:
        for state in states_by_block:
            handle.write(json.dumps(state, sort_keys=True, allow_nan=False) + "\n")

    contexts: dict[str, CandidateOfferContext] = {}
    for row in board_rows:
        cid = make_candidate_id(row["game_id"], row["market_type"], row["selected_side"])
        contexts[cid] = _book_context(market_idx, row["game_id"], row["market_type"], row["selected_side"])
    candidate_rows = build_candidate_table(board_rows, contexts)
    candidate_df = pl.DataFrame(candidate_rows, infer_schema_length=None)
    forbidden = {"settlement", "realized_profit", "home_score", "away_score"}.intersection(candidate_df.columns)
    if forbidden:
        raise RuntimeError(f"outcomes leaked into candidate table: {sorted(forbidden)}")
    candidate_df.write_parquet(out / "candidate_table.parquet", compression="zstd")

    reliability_rows = _reliability_rows(board_rows)
    pl.DataFrame(reliability_rows, infer_schema_length=None).write_csv(out / "reliability_table.csv")
    frozen = _frozen_preservation(root, board_rows)
    _json_write(out / "frozen_edge_preservation.json", frozen)

    scorecard = {
        "version": VERSION,
        "development_seasons": DEV,
        "sealed_season": 2025,
        "chronology": "expanding prior season-week blocks only",
        "accepted_families": {"moneyline": "ml_v4", "spread": "spread_v3", "total": "total_v3"},
        "integer_pinnacle_anchor_semantics": "conditional_nonpush_push_cell_corrected",
        "reliability_semantics": "single accepted-family support plus accepted-family strictly-prior OOS uncertainty",
        "arbitrary_offer_interface": "evaluate_offer",
        "manual_offer_parity_checks": parity_checks,
        "candidate_rows": len(candidate_rows),
        "markets": {market: _market_summary(board_rows, market) for market in ("moneyline", "spread", "total")},
        "final_state": {
            "moneyline_model_weight": final_ml.model_weight,
            "spread_beta": final_spread.beta,
            "spread_sigma": final_spread.sigma,
            "total_beta": final_total.beta,
            "total_sigma": final_total.sigma,
            "reliability": {
                market: {
                    "radius": final_reliability[market].radius,
                    "support_n": final_reliability[market].support_n,
                    "block_count": final_reliability[market].block_count,
                    "stable": final_reliability[market].stable,
                }
                for market in final_reliability
            },
        },
        "frozen_edge_preservation": frozen,
        "promotion_status": "EVIDENCE_PENDING_REVIEW",
    }
    _json_write(out / "scorecard.json", scorecard)
    _json_write(
        out / "candidate_manifest.json",
        {
            "rows": len(candidate_rows),
            "unique_candidate_ids": len({row["candidate_id"] for row in candidate_rows}),
            "seasons": seasons,
            "outcome_fields": [],
            "book_context_coverage": {
                book: sum(row.get(f"{book}_price_american") is not None for row in candidate_rows)
                for book in ("draftkings", "fanduel", "pinnacle")
            },
            "selector_scoring": False,
            "account_state": False,
        },
    )
    _json_write(
        out / "provenance.json",
        {
            "version": VERSION,
            "github_sha": os.environ.get("GITHUB_SHA"),
            "config_path": str(config_path.relative_to(root)),
            "config_sha256": config_sha,
            "development_seasons": DEV,
            "sealed_season": 2025,
            "frozen_state_sha256": _sha256(state_path),
            "scope": "evaluator_plus_playthrough_plus_account_independent_candidate_table_only",
            "selectors": False,
            "staking_units_or_dollars": False,
        },
    )

    print(json.dumps(scorecard, indent=2, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "task05f" / "evaluator_final_v1"))
    args = parser.parse_args()
    run(ROOT, Path(args.config), Path(args.out))
