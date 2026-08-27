#!/usr/bin/env python3
"""Preregistered Task05G Model Confidence + Selector V2 experiment.

This runner implements docs/task05g_model_confidence_v2_preregistration.md.
It does not modify frozen football models or Task05F evaluators.

Chronology:
- 2018-2019: strictly-prior calibration warmup only
- 2020-2022: selector development
- 2023-2024: confirmation after the Balanced variant is frozen from development
- 2025: sealed / prohibited

Historical-reproduction note:
The original V2 experiment compared itself with a pre-final Task05G V1 selector
baseline. Those obsolete V1 baseline semantics are retained *locally in this
historical runner only* so the experiment remains reproducible. They are not
exported from ``nfl_edge.recommendation.policy`` and are not a production API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable, Iterable, Mapping

import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss

from nfl_edge.recommendation.policy import shop_exact_offers

CALIBRATION_SEASONS = {2018, 2019}
DEVELOPMENT_SEASONS = {2020, 2021, 2022}
CONFIRMATION_SEASONS = {2023, 2024}
ALLOWED_SEASONS = CALIBRATION_SEASONS | DEVELOPMENT_SEASONS | CONFIRMATION_SEASONS
SEALED_SEASON = 2025
MIN_MODEL_CONFIDENCE_N = 256
HHR_MIN_Q = 0.55
BALANCED_MIN_Q = 0.52
HHR_ODDS = (-300, 200)
BALANCED_ODDS = (-220, 200)
VALUE_ODDS = (-180, 250)
BALANCED_TOLERANCES = {"B0": 0.00, "B1": -0.01, "B2": -0.02}
PREREG_COMMIT = "a6a0fb5cb4d4f742ef6d2708f17c8aac7ba5bf44"
PREREG_BLOB = "d06d64c4aa94d1c4d291f585af5e42003a86a49d"


def _json_write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _block(season: int, week: Any) -> str:
    return f"{int(season):04d}-{int(str(week)):02d}"


def _block_tuple(value: str) -> tuple[int, int]:
    season, week = value.split("-", 1)
    return int(season), int(week)


def _logit(p: float) -> float:
    q = min(1.0 - 1e-6, max(1e-6, float(p)))
    return math.log(q / (1.0 - q))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _reliability_rank(value: Any) -> int:
    return {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(str(value or "").upper(), 0)


def _odds(row: Mapping[str, Any]) -> int | None:
    value = row.get("american_odds")
    return None if value is None else int(value)


def _candidate_id(row: Mapping[str, Any]) -> str:
    value = row.get("candidate_id")
    if value is not None:
        return str(value)
    return "|".join(
        [
            str(row.get("game_id", "")),
            str(row.get("market_type", "")),
            str(row.get("selected_side", "")),
            str(row.get("sportsbook", "")),
            str(row.get("line", "")),
            str(row.get("american_odds", "")),
        ]
    )


def _settled(row: Mapping[str, Any]) -> bool:
    return str(row.get("settlement")) in {"WIN", "LOSS", "PUSH"}


# ---------------------------------------------------------------------------
# Historical V1 baseline snapshot — runner-local, non-production.
# These functions intentionally preserve the obsolete pre-final comparison
# semantics used by the preregistered V2 experiment. Do not import them into
# recommendation production code.
# ---------------------------------------------------------------------------

def _legacy_status(row: Mapping[str, Any]) -> str:
    return str(row.get("price_status") or "UNSUPPORTED").upper()


def _legacy_reliability(row: Mapping[str, Any]) -> str:
    return str(row.get("reliability") or "UNSUPPORTED").upper()


def _legacy_common_eligible(row: Mapping[str, Any]) -> bool:
    return (
        bool(row.get("supported"))
        and _legacy_reliability(row) in {"HIGH", "MEDIUM"}
        and _legacy_status(row) not in {"PASS", "UNSUPPORTED"}
        and str(row.get("sportsbook") or row.get("actionable_book") or "").lower() in {"draftkings", "fanduel"}
    )


def _legacy_odds_in(row: Mapping[str, Any], minimum: int, maximum: int) -> bool:
    odds = row.get("american_odds")
    if odds is None:
        odds = row.get("actionable_price_american")
    return odds is not None and minimum <= int(odds) <= maximum


def _legacy_float(row: Mapping[str, Any], key: str) -> float | None:
    value = row.get(key)
    return None if value is None else float(value)


def _legacy_status_rank(row: Mapping[str, Any]) -> int:
    return {"VALUE": 2, "PLAYABLE": 1}.get(_legacy_status(row), 0)


def _legacy_rel_rank(row: Mapping[str, Any]) -> int:
    return {"HIGH": 2, "MEDIUM": 1}.get(_legacy_reliability(row), 0)


def _legacy_num(value: float | None) -> float:
    return float("-inf") if value is None else float(value)


def _legacy_select(rows: Iterable[Mapping[str, Any]], eligible, key) -> Mapping[str, Any] | str:
    candidates = [row for row in shop_exact_offers(rows) if eligible(row)]
    return "NO_PLAY" if not candidates else sorted(candidates, key=key)[0]


def _legacy_v1_select_hit_rate(rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | str:
    def eligible(row: Mapping[str, Any]) -> bool:
        q = _legacy_float(row, "actionable_probability")
        return (
            _legacy_common_eligible(row)
            and _legacy_status(row) in {"VALUE", "PLAYABLE"}
            and q is not None
            and q >= 0.55
            and _legacy_odds_in(row, -300, 200)
        )
    return _legacy_select(
        rows,
        eligible,
        lambda row: (
            -_legacy_num(_legacy_float(row, "actionable_probability")),
            -_legacy_rel_rank(row),
            -_legacy_status_rank(row),
            -_legacy_num(_legacy_float(row, "expected_value")),
            -int(row.get("american_odds") or -100000),
            _candidate_id(row),
        ),
    )


def _legacy_v1_select_balanced(rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | str:
    def eligible(row: Mapping[str, Any]) -> bool:
        q = _legacy_float(row, "actionable_probability")
        ev = _legacy_float(row, "expected_value")
        return (
            _legacy_common_eligible(row)
            and _legacy_status(row) in {"VALUE", "PLAYABLE"}
            and q is not None
            and q >= 0.50
            and ev is not None
            and ev >= -0.03
            and _legacy_odds_in(row, -220, 200)
        )
    return _legacy_select(
        rows,
        eligible,
        lambda row: (
            -_legacy_status_rank(row),
            -_legacy_rel_rank(row),
            -_legacy_num(_legacy_float(row, "expected_value")),
            -_legacy_num(_legacy_float(row, "actionable_probability")),
            -_legacy_num(_legacy_float(row, "evaluated_edge_probability")),
            _candidate_id(row),
        ),
    )


def _legacy_v1_select_value(rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | str:
    def eligible(row: Mapping[str, Any]) -> bool:
        q = _legacy_float(row, "actionable_probability")
        ev = _legacy_float(row, "expected_value")
        support_n = row.get("support_n")
        support_distance = _legacy_float(row, "support_distance")
        uncertainty = _legacy_float(row, "uncertainty")
        return (
            _legacy_common_eligible(row)
            and _legacy_status(row) == "VALUE"
            and q is not None and q >= 0.35
            and ev is not None and ev >= 0.02
            and support_n is not None and int(support_n) >= 256
            and support_distance is not None and support_distance <= 0.05
            and uncertainty is not None and uncertainty <= 0.045
            and _legacy_odds_in(row, -180, 250)
        )
    return _legacy_select(
        rows,
        eligible,
        lambda row: (
            -_legacy_num(_legacy_float(row, "expected_value")),
            -_legacy_num(_legacy_float(row, "evaluated_edge_probability")),
            -_legacy_rel_rank(row),
            -_legacy_num(_legacy_float(row, "actionable_probability")),
            _candidate_id(row),
        ),
    )


def _scan_model_inputs(root: Path) -> pl.DataFrame:
    """Load only 2018-2024 columns through lazy predicates; 2025 is excluded."""
    season_allowed = pl.col("season").cast(pl.Int64).is_in(sorted(ALLOWED_SEASONS))
    qbelo = (
        pl.scan_parquet(root / "data/modeling/development_v1/qb_elo_predictions_2018_2024.parquet")
        .select(["game_id", "season", "week", "predicted_home_win_probability"])
        .filter(season_allowed)
        .rename({"predicted_home_win_probability": "qbelo_home"})
    )
    xgb = (
        pl.scan_parquet(root / "data/modeling/development_v1/chronology_corrected/xgboost_candidate_predictions_2018_2024.parquet")
        .select(["candidate_id", "game_id", "season", "week", "warmup", "prediction_probability"])
        .filter((pl.col("candidate_id") == "conservative") & season_allowed)
        .with_columns(
            pl.when(pl.col("warmup")).then(None).otherwise(pl.col("prediction_probability")).alias("xgb_home")
        )
        .select(["game_id", "xgb_home"])
    )
    margin = (
        pl.scan_parquet(root / "data/modeling/development_v1/expected_margin_predictions_2018_2024.parquet")
        .select(["candidate_id", "game_id", "season", "week", "expected_home_margin"])
        .filter((pl.col("candidate_id") == "stable") & season_allowed)
        .select(["game_id", "expected_home_margin"])
    )
    outcomes = (
        pl.scan_parquet(root / "data/frozen/games/games_2018_2025.parquet")
        .select(["game_id", "season", "home_score", "away_score"])
        .filter(season_allowed)
    )
    df = qbelo.join(xgb, on="game_id", how="left").join(margin, on="game_id", how="left").join(
        outcomes, on=["game_id", "season"], how="inner"
    ).collect()
    seasons = {int(x) for x in df["season"].unique().to_list()}
    if SEALED_SEASON in seasons or not seasons.issubset(ALLOWED_SEASONS):
        raise RuntimeError(f"sealed/unexpected season entered model-confidence inputs: {sorted(seasons)}")
    return df


def _history_rows(root: Path) -> list[dict[str, Any]]:
    df = _scan_model_inputs(root)
    rows: list[dict[str, Any]] = []
    for src in df.to_dicts():
        row = dict(src)
        row["block"] = _block(int(row["season"]), row["week"])
        if row.get("home_score") is None or row.get("away_score") is None:
            continue
        home_score = int(row["home_score"])
        away_score = int(row["away_score"])
        row["home_margin"] = float(home_score - away_score)
        row["home_binary"] = None if home_score == away_score else int(home_score > away_score)
        if row.get("qbelo_home") is not None and row.get("xgb_home") is not None:
            row["raw_ml_home"] = (float(row["qbelo_home"]) + float(row["xgb_home"])) / 2.0
        else:
            row["raw_ml_home"] = None
        if row.get("expected_home_margin") is not None:
            row["margin_residual"] = float(row["home_margin"]) - float(row["expected_home_margin"])
        else:
            row["margin_residual"] = None
        rows.append(row)
    return sorted(rows, key=lambda r: (_block_tuple(str(r["block"])), str(r["game_id"])))


def _fit_ml_state(prior: list[dict[str, Any]]) -> dict[str, Any]:
    material = [r for r in prior if r.get("raw_ml_home") is not None and r.get("home_binary") is not None]
    n = len(material)
    if n < MIN_MODEL_CONFIDENCE_N or len({int(r["home_binary"]) for r in material}) < 2:
        return {"supported": False, "n": n, "intercept": None, "slope": None}
    X = np.asarray([[_logit(float(r["raw_ml_home"]))] for r in material], dtype=float)
    y = np.asarray([int(r["home_binary"]) for r in material], dtype=int)
    model = LogisticRegression(C=1e6, max_iter=2000, solver="lbfgs", random_state=0).fit(X, y)
    return {
        "supported": True,
        "n": n,
        "intercept": float(model.intercept_[0]),
        "slope": float(model.coef_[0][0]),
    }


def _ml_probability(raw_home: float, state: Mapping[str, Any]) -> float | None:
    if not bool(state.get("supported")):
        return None
    return _sigmoid(float(state["intercept"]) + float(state["slope"]) * _logit(float(raw_home)))


def _spread_probability(
    residuals: list[float], *, expected_home_margin: float, side: str, line: float
) -> tuple[float | None, float | None, float | None, float | None]:
    if len(residuals) < MIN_MODEL_CONFIDENCE_N:
        return None, None, None, None
    wins = pushes = losses = 0
    for residual in residuals:
        actual_home_margin = float(expected_home_margin) + float(residual)
        if str(side).lower() == "home":
            graded = actual_home_margin + float(line)
        elif str(side).lower() == "away":
            graded = -actual_home_margin + float(line)
        else:
            raise ValueError(f"unexpected spread side {side}")
        if graded > 1e-9:
            wins += 1
        elif graded < -1e-9:
            losses += 1
        else:
            pushes += 1
    n = wins + pushes + losses
    p_win = wins / n
    p_push = pushes / n
    p_loss = losses / n
    nonpush = wins + losses
    q = None if nonpush == 0 else wins / nonpush
    return float(p_win), float(p_push), float(p_loss), None if q is None else float(q)


def _build_model_confidence(
    root: Path, board_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    history = _history_rows(root)
    by_game = {str(r["game_id"]): r for r in history}
    blocks = sorted({str(r["block"]) for r in board_rows}, key=_block_tuple)
    if any(_block_tuple(b)[0] == SEALED_SEASON for b in blocks):
        raise RuntimeError("sealed 2025 entered candidate board")

    states: list[dict[str, Any]] = []
    ml_calibration_rows: list[dict[str, Any]] = []
    state_by_block: dict[str, dict[str, Any]] = {}

    for block in blocks:
        cutoff = _block_tuple(block)
        prior = [r for r in history if _block_tuple(str(r["block"])) < cutoff]
        ml_state = _fit_ml_state(prior)
        residuals = [float(r["margin_residual"]) for r in prior if r.get("margin_residual") is not None]
        state = {
            "block": block,
            "ml": ml_state,
            "spread": {
                "supported": len(residuals) >= MIN_MODEL_CONFIDENCE_N,
                "n": len(residuals),
                "residual_mean": None if not residuals else float(mean(residuals)),
                "residual_std": None if len(residuals) < 2 else float(np.std(np.asarray(residuals), ddof=1)),
            },
            "prior_max_block": None if not prior else max(str(r["block"]) for r in prior),
        }
        state_by_block[block] = {**state, "_spread_residuals": residuals}
        states.append(state)

    enriched: list[dict[str, Any]] = []
    seen_ml_metric_game: set[str] = set()
    for src in board_rows:
        row = dict(src)
        block = str(row["block"])
        season = int(row["season"])
        if season == SEALED_SEASON or season not in DEVELOPMENT_SEASONS | CONFIRMATION_SEASONS:
            raise RuntimeError(f"unexpected board season {season}")
        game = by_game.get(str(row["game_id"]))
        row["model_confidence_probability"] = None
        row["model_confidence_support_n"] = 0
        row["model_confidence_supported"] = False
        row["model_confidence_source"] = None
        row["model_price_gap"] = None
        row["consensus_edge"] = None
        row["raw_qbelo_probability_selected"] = None
        row["raw_xgb_probability_selected"] = None
        row["raw_avg_probability_selected"] = None
        if game is None:
            enriched.append(row)
            continue

        market = str(row.get("market_type"))
        side = str(row.get("selected_side"))
        state = state_by_block[block]
        q: float | None = None
        support_n = 0

        if market == "moneyline" and game.get("raw_ml_home") is not None:
            home_q = _ml_probability(float(game["raw_ml_home"]), state["ml"])
            support_n = int(state["ml"]["n"])
            if home_q is not None:
                q = float(home_q if side == "home" else 1.0 - home_q)
                qb = float(game["qbelo_home"])
                xgb = float(game["xgb_home"])
                raw = float(game["raw_ml_home"])
                row["raw_qbelo_probability_selected"] = qb if side == "home" else 1.0 - qb
                row["raw_xgb_probability_selected"] = xgb if side == "home" else 1.0 - xgb
                row["raw_avg_probability_selected"] = raw if side == "home" else 1.0 - raw
                row["model_confidence_source"] = "ML_PLATT_QBELO_XGB_AVG"
            gid = str(row["game_id"])
            if home_q is not None and gid not in seen_ml_metric_game and game.get("home_binary") is not None:
                seen_ml_metric_game.add(gid)
                ml_calibration_rows.append(
                    {
                        "game_id": gid,
                        "season": season,
                        "block": block,
                        "probability": float(home_q),
                        "outcome": int(game["home_binary"]),
                        "support_n": support_n,
                    }
                )
        elif market == "spread" and row.get("line") is not None and game.get("expected_home_margin") is not None:
            residuals = state["_spread_residuals"]
            support_n = len(residuals)
            p_win, p_push, p_loss, q_spread = _spread_probability(
                residuals,
                expected_home_margin=float(game["expected_home_margin"]),
                side=side,
                line=float(row["line"]),
            )
            q = q_spread
            row["model_confidence_p_win"] = p_win
            row["model_confidence_p_push"] = p_push
            row["model_confidence_p_loss"] = p_loss
            row["model_confidence_source"] = "EXPECTED_MARGIN_PRIOR_EMPIRICAL_RESIDUAL"

        if q is not None and support_n >= MIN_MODEL_CONFIDENCE_N:
            row["model_confidence_probability"] = float(q)
            row["model_confidence_support_n"] = int(support_n)
            row["model_confidence_supported"] = True
            be = row.get("break_even_probability")
            if be is not None:
                row["model_price_gap"] = float(q) - float(be)
            eval_edge = row.get("evaluated_edge_probability")
            if row["model_price_gap"] is not None and eval_edge is not None:
                row["consensus_edge"] = min(float(row["model_price_gap"]), float(eval_edge))
        enriched.append(row)

    return enriched, states, ml_calibration_rows


def _group_blocks(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        out.setdefault(str(row["block"]), []).append(row)
    return out


def _common_v2(row: Mapping[str, Any]) -> bool:
    return (
        bool(row.get("supported"))
        and bool(row.get("model_confidence_supported"))
        and int(row.get("model_confidence_support_n") or 0) >= MIN_MODEL_CONFIDENCE_N
        and str(row.get("market_type")) in {"moneyline", "spread"}
        and str(row.get("sportsbook")) in {"draftkings", "fanduel"}
        and row.get("break_even_probability") is not None
    )


def _within_odds(row: Mapping[str, Any], bounds: tuple[int, int]) -> bool:
    odds = _odds(row)
    return odds is not None and bounds[0] <= odds <= bounds[1]


def _hhr_eligible(row: Mapping[str, Any]) -> bool:
    q = row.get("model_confidence_probability")
    return _common_v2(row) and q is not None and float(q) >= HHR_MIN_Q and _within_odds(row, HHR_ODDS)


def _balanced_eligible(row: Mapping[str, Any], tolerance: float) -> bool:
    q = row.get("model_confidence_probability")
    gap = row.get("model_price_gap")
    return (
        _common_v2(row)
        and q is not None
        and float(q) >= BALANCED_MIN_Q
        and gap is not None
        and float(gap) >= float(tolerance)
        and _within_odds(row, BALANCED_ODDS)
    )


def _value_eligible(row: Mapping[str, Any]) -> bool:
    gap = row.get("model_price_gap")
    ev = row.get("expected_value")
    return (
        _common_v2(row)
        and gap is not None
        and float(gap) > 0.0
        and str(row.get("price_status")) == "VALUE"
        and ev is not None
        and float(ev) > 0.0
        and _within_odds(row, VALUE_ODDS)
    )


def _select_one(
    rows: list[Mapping[str, Any]], eligible: Callable[[Mapping[str, Any]], bool], key: Callable[[Mapping[str, Any]], Any]
) -> Mapping[str, Any] | None:
    shopped = [dict(r) for r in shop_exact_offers(rows)]
    candidates = [r for r in shopped if eligible(r)]
    return None if not candidates else sorted(candidates, key=key)[0]


def _select_hhr(rows: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return _select_one(
        rows,
        _hhr_eligible,
        lambda r: (
            -float(r["model_confidence_probability"]),
            -_reliability_rank(r.get("reliability")),
            -float(r.get("model_price_gap") or -99.0),
            -int(r.get("american_odds") or -100000),
            _candidate_id(r),
        ),
    )


def _select_balanced(rows: list[Mapping[str, Any]], tolerance: float) -> Mapping[str, Any] | None:
    return _select_one(
        rows,
        lambda r: _balanced_eligible(r, tolerance),
        lambda r: (
            -float(r["model_confidence_probability"]),
            -float(r.get("model_price_gap") or -99.0),
            -_reliability_rank(r.get("reliability")),
            -int(r.get("american_odds") or -100000),
            _candidate_id(r),
        ),
    )


def _select_value(rows: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return _select_one(
        rows,
        _value_eligible,
        lambda r: (
            -float(r.get("consensus_edge") if r.get("consensus_edge") is not None else -99.0),
            -float(r["model_confidence_probability"]),
            -_reliability_rank(r.get("reliability")),
            -int(r.get("american_odds") or -100000),
            _candidate_id(r),
        ),
    )


def _select_phase(
    rows: list[dict[str, Any]], seasons: set[int], selector: Callable[[list[Mapping[str, Any]]], Mapping[str, Any] | None]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    phase = [r for r in rows if int(r["season"]) in seasons]
    blocks = _group_blocks(phase)
    selected: list[dict[str, Any]] = []
    eligible_counts: dict[str, int] = {}
    for block in sorted(blocks, key=_block_tuple):
        block_rows = [dict(r) for r in blocks[block]]
        choice = selector(block_rows)
        if choice is not None:
            selected.append(dict(choice))
    return selected, eligible_counts


def _v1_selections(rows: list[dict[str, Any]], seasons: set[int], selector) -> list[dict[str, Any]]:
    phase = [r for r in rows if int(r["season"]) in seasons]
    blocks = _group_blocks(phase)
    selected: list[dict[str, Any]] = []
    for block in sorted(blocks, key=_block_tuple):
        choice = selector(blocks[block])
        if not isinstance(choice, str):
            selected.append(dict(choice))
    return selected


def _eligible_counts(
    rows: list[dict[str, Any]], seasons: set[int], eligible: Callable[[Mapping[str, Any]], bool]
) -> dict[str, int]:
    phase = [r for r in rows if int(r["season"]) in seasons]
    out: dict[str, int] = {}
    for block, block_rows in _group_blocks(phase).items():
        shopped = shop_exact_offers(block_rows)
        out[block] = sum(1 for r in shopped if eligible(r))
    return out


def _longest_losing_streak(rows: list[dict[str, Any]]) -> int:
    longest = current = 0
    for row in sorted(rows, key=lambda r: (_block_tuple(str(r["block"])), str(r.get("game_id")))):
        settlement = str(row.get("settlement"))
        if settlement == "LOSS":
            current += 1
            longest = max(longest, current)
        elif settlement == "WIN":
            current = 0
    return longest


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(str(r.get("settlement")) == "WIN" for r in rows)
    losses = sum(str(r.get("settlement")) == "LOSS" for r in rows)
    pushes = sum(str(r.get("settlement")) == "PUSH" for r in rows)
    nonpush = wins + losses
    return {
        "plays": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate_nonpush": None if nonpush == 0 else wins / nonpush,
        "roi": None if not rows else float(mean(float(r["realized_profit"]) for r in rows)),
        "avg_odds": None if not rows else float(mean(int(r["american_odds"]) for r in rows)),
        "avg_model_confidence_probability": None if not rows else float(mean(float(r["model_confidence_probability"]) for r in rows)),
        "avg_model_price_gap": None if not rows else float(mean(float(r["model_price_gap"]) for r in rows)),
        "max_losing_streak": _longest_losing_streak(rows),
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


def _phase_report(
    rows: list[dict[str, Any]], seasons: set[int], selected: list[dict[str, Any]], eligible_counts: dict[str, int]
) -> dict[str, Any]:
    phase_blocks = sorted({str(r["block"]) for r in rows if int(r["season"]) in seasons}, key=_block_tuple)
    counts = [int(eligible_counts.get(block, 0)) for block in phase_blocks]
    result = _summary(selected)
    result.update(
        {
            "seasons": sorted(seasons),
            "total_blocks": len(phase_blocks),
            "play_blocks": len({str(r["block"]) for r in selected}),
            "no_play_blocks": len(phase_blocks) - len({str(r["block"]) for r in selected}),
            "coverage": None if not phase_blocks else len({str(r["block"]) for r in selected}) / len(phase_blocks),
            "mean_eligible_candidates_per_block": None if not counts else float(mean(counts)),
            "median_eligible_candidates_per_block": None if not counts else float(median(counts)),
            "by_season": {str(s): _summary([r for r in selected if int(r["season"]) == s]) for s in sorted(seasons)},
        }
    )
    return result


def _ml_calibration_metrics(rows: list[dict[str, Any]], seasons: set[int]) -> dict[str, Any]:
    rr = [r for r in rows if int(r["season"]) in seasons]
    if not rr:
        return {"n": 0, "brier": None, "log_loss": None, "calibration_intercept": None, "calibration_slope": None, "reliability": []}
    p = np.clip(np.asarray([float(r["probability"]) for r in rr]), 1e-6, 1 - 1e-6)
    y = np.asarray([int(r["outcome"]) for r in rr], dtype=int)
    brier = float(np.mean((p - y) ** 2))
    ll = float(log_loss(y, p, labels=[0, 1]))
    intercept = slope = None
    if len(set(y.tolist())) == 2:
        fit = LogisticRegression(C=1e6, max_iter=2000, solver="lbfgs", random_state=0).fit(
            np.asarray([[_logit(v)] for v in p]), y
        )
        intercept = float(fit.intercept_[0])
        slope = float(fit.coef_[0][0])
    reliability = []
    for lo in np.arange(0.0, 1.0, 0.1):
        hi = float(lo + 0.1)
        mask = (p >= lo) & (p < (hi if hi < 1.0 else 1.000001))
        if np.any(mask):
            reliability.append(
                {
                    "lo": float(lo),
                    "hi": hi,
                    "n": int(np.sum(mask)),
                    "mean_probability": float(np.mean(p[mask])),
                    "hit_rate": float(np.mean(y[mask])),
                }
            )
    return {
        "n": len(rr),
        "brier": brier,
        "log_loss": ll,
        "calibration_intercept": intercept,
        "calibration_slope": slope,
        "reliability": reliability,
    }


def _pick_balanced_winner(
    reports: dict[str, dict[str, Any]], original_v1_dev_plays: int
) -> dict[str, Any]:
    coverage_floor = math.ceil(0.75 * original_v1_dev_plays)
    evaluations: dict[str, Any] = {}
    viable: list[str] = []
    for name in ("B0", "B1", "B2"):
        report = reports[name]
        season_nonnegative = sum(
            report["by_season"][str(s)]["roi"] is not None and float(report["by_season"][str(s)]["roi"]) >= 0.0
            for s in sorted(DEVELOPMENT_SEASONS)
        )
        gates = {
            "coverage": int(report["play_blocks"]) >= coverage_floor,
            "hit_rate": report["hit_rate_nonpush"] is not None and float(report["hit_rate_nonpush"]) >= 0.55,
            "roi": report["roi"] is not None and float(report["roi"]) >= 0.0,
        }
        evaluations[name] = {"gates": gates, "nonnegative_seasons": season_nonnegative}
        if all(gates.values()):
            viable.append(name)
    if not viable:
        return {
            "status": "DEVELOPMENT_FAILURE",
            "winner": None,
            "coverage_floor_plays": coverage_floor,
            "evaluations": evaluations,
        }
    tie_rank = {"B0": 0, "B1": 1, "B2": 2}
    winner = sorted(
        viable,
        key=lambda n: (
            -int(evaluations[n]["nonnegative_seasons"]),
            -float(reports[n]["roi"]),
            -int(reports[n]["play_blocks"]),
            tie_rank[n],
        ),
    )[0]
    return {
        "status": "WINNER_FROZEN_FROM_2020_2022",
        "winner": winner,
        "tolerance": BALANCED_TOLERANCES[winner],
        "coverage_floor_plays": coverage_floor,
        "evaluations": evaluations,
    }


def _markdown(score: dict[str, Any]) -> str:
    lines = [
        "# Task05G Model Confidence + Selector V2 Scorecard",
        "",
        f"Verdict: `{score['verdict']}`",
        "",
        f"Preregistration commit: `{PREREG_COMMIT}`",
        f"Preregistration blob: `{PREREG_BLOB}`",
        "",
        "## Development (2020-2022)",
        "",
        "| Lane | Plays | Coverage | Hit rate | ROI |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, report in [
        ("HHR V2", score["development"]["hhr_v2"]),
        ("Value V2", score["development"]["value_v2"]),
        ("HHR V1", score["development"]["hhr_v1"]),
        ("Balanced V1", score["development"]["balanced_v1"]),
        ("Value V1", score["development"]["value_v1"]),
    ]:
        lines.append(
            f"| {label} | {report['plays']} | {report.get('coverage', 0):.1%} | "
            f"{(report['hit_rate_nonpush'] if report['hit_rate_nonpush'] is not None else 0):.1%} | "
            f"{(report['roi'] if report['roi'] is not None else 0):+.2%} |"
        )
    lines += ["", "### Balanced grid", "", "| Variant | Tolerance | Plays | Coverage | Hit rate | ROI | Pass |", "|---|---:|---:|---:|---:|---:|:---:|"]
    for name in ("B0", "B1", "B2"):
        r = score["development"]["balanced_variants"][name]
        ev = score["balanced_decision"]["evaluations"][name]
        passed = all(ev["gates"].values())
        lines.append(
            f"| {name} | {BALANCED_TOLERANCES[name]:+.1%} | {r['plays']} | {r['coverage']:.1%} | "
            f"{(r['hit_rate_nonpush'] or 0):.1%} | {(r['roi'] or 0):+.2%} | {'YES' if passed else 'NO'} |"
        )
    lines += ["", f"Balanced decision: `{score['balanced_decision']['status']}`"]
    if score["balanced_decision"].get("winner"):
        lines.append(f"Frozen winner: `{score['balanced_decision']['winner']}`")
    lines += ["", "## Confirmation (2023-2024)", ""]
    if score["confirmation"].get("withheld"):
        lines.append("Balanced confirmation withheld because no preregistered development variant passed.")
    lines += ["", "| Lane | Plays | Coverage | Hit rate | ROI |", "|---|---:|---:|---:|---:|"]
    for key, label in (("hhr_v2", "HHR V2"), ("balanced_v2", "Balanced V2"), ("value_v2", "Value V2")):
        r = score["confirmation"].get(key)
        if not r:
            continue
        lines.append(
            f"| {label} | {r['plays']} | {r['coverage']:.1%} | {(r['hit_rate_nonpush'] or 0):.1%} | {(r['roi'] or 0):+.2%} |"
        )
    lines += [
        "",
        "## Coverage guardrails",
        "",
        f"- HHR V2 development coverage guardrail: `{score['coverage_guardrails']['hhr']}`",
        f"- Value V2 development coverage warning: `{score['coverage_guardrails']['value']}`",
        "",
        "## Holdout",
        "",
        "2025 remained sealed and was not loaded into eligible experiment data.",
    ]
    return "\n".join(lines) + "\n"


def run(root: Path, board_path: Path, out: Path, prereg_path: Path) -> None:
    if _sha256(prereg_path) == "":
        raise RuntimeError("unreachable preregistration hash")
    board = pl.read_parquet(board_path)
    seasons = {int(x) for x in board["season"].unique().to_list()}
    expected_board_seasons = DEVELOPMENT_SEASONS | CONFIRMATION_SEASONS
    if seasons != expected_board_seasons or SEALED_SEASON in seasons:
        raise RuntimeError(f"unexpected board seasons {sorted(seasons)}")
    board_rows = board.to_dicts()

    enriched, states, ml_calibration_rows = _build_model_confidence(root, board_rows)
    out.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(enriched).write_parquet(out / "v2_candidate_table.parquet")
    with (out / "model_confidence_state_by_block.ndjson").open("w") as f:
        for state in states:
            f.write(json.dumps(state, sort_keys=True, allow_nan=False) + "\n")

    v1_dev = {
        "hhr": _v1_selections(board_rows, DEVELOPMENT_SEASONS, _legacy_v1_select_hit_rate),
        "balanced": _v1_selections(board_rows, DEVELOPMENT_SEASONS, _legacy_v1_select_balanced),
        "value": _v1_selections(board_rows, DEVELOPMENT_SEASONS, _legacy_v1_select_value),
    }
    v1_conf = {
        "hhr": _v1_selections(board_rows, CONFIRMATION_SEASONS, _legacy_v1_select_hit_rate),
        "balanced": _v1_selections(board_rows, CONFIRMATION_SEASONS, _legacy_v1_select_balanced),
        "value": _v1_selections(board_rows, CONFIRMATION_SEASONS, _legacy_v1_select_value),
    }

    hhr_dev, _ = _select_phase(enriched, DEVELOPMENT_SEASONS, _select_hhr)
    value_dev, _ = _select_phase(enriched, DEVELOPMENT_SEASONS, _select_value)
    hhr_dev_counts = _eligible_counts(enriched, DEVELOPMENT_SEASONS, _hhr_eligible)
    value_dev_counts = _eligible_counts(enriched, DEVELOPMENT_SEASONS, _value_eligible)

    balanced_dev_selected: dict[str, list[dict[str, Any]]] = {}
    balanced_dev_reports: dict[str, dict[str, Any]] = {}
    for name, tolerance in BALANCED_TOLERANCES.items():
        sel, _ = _select_phase(enriched, DEVELOPMENT_SEASONS, lambda rr, t=tolerance: _select_balanced(rr, t))
        balanced_dev_selected[name] = sel
        counts = _eligible_counts(enriched, DEVELOPMENT_SEASONS, lambda r, t=tolerance: _balanced_eligible(r, t))
        balanced_dev_reports[name] = _phase_report(enriched, DEVELOPMENT_SEASONS, sel, counts)

    balanced_decision = _pick_balanced_winner(balanced_dev_reports, len(v1_dev["balanced"]))

    hhr_conf, _ = _select_phase(enriched, CONFIRMATION_SEASONS, _select_hhr)
    value_conf, _ = _select_phase(enriched, CONFIRMATION_SEASONS, _select_value)
    hhr_conf_counts = _eligible_counts(enriched, CONFIRMATION_SEASONS, _hhr_eligible)
    value_conf_counts = _eligible_counts(enriched, CONFIRMATION_SEASONS, _value_eligible)
    balanced_conf = None
    balanced_conf_counts = None
    if balanced_decision.get("winner") is not None:
        frozen_tolerance = float(balanced_decision["tolerance"])
        balanced_conf, _ = _select_phase(enriched, CONFIRMATION_SEASONS, lambda rr: _select_balanced(rr, frozen_tolerance))
        balanced_conf_counts = _eligible_counts(enriched, CONFIRMATION_SEASONS, lambda r: _balanced_eligible(r, frozen_tolerance))

    dev_hhr_report = _phase_report(enriched, DEVELOPMENT_SEASONS, hhr_dev, hhr_dev_counts)
    dev_value_report = _phase_report(enriched, DEVELOPMENT_SEASONS, value_dev, value_dev_counts)
    conf_hhr_report = _phase_report(enriched, CONFIRMATION_SEASONS, hhr_conf, hhr_conf_counts)
    conf_value_report = _phase_report(enriched, CONFIRMATION_SEASONS, value_conf, value_conf_counts)

    def v1_report(selected: list[dict[str, Any]], seasons_set: set[int]) -> dict[str, Any]:
        phase_blocks = sorted({str(r["block"]) for r in board_rows if int(r["season"]) in seasons_set}, key=_block_tuple)
        report = _summary(selected)
        report.update(
            {
                "total_blocks": len(phase_blocks),
                "play_blocks": len({str(r["block"]) for r in selected}),
                "coverage": None if not phase_blocks else len({str(r["block"]) for r in selected}) / len(phase_blocks),
                "by_season": {str(s): _summary([r for r in selected if int(r["season"]) == s]) for s in sorted(seasons_set)},
            }
        )
        return report

    dev_v1_reports = {k: v1_report(v, DEVELOPMENT_SEASONS) for k, v in v1_dev.items()}
    conf_v1_reports = {k: v1_report(v, CONFIRMATION_SEASONS) for k, v in v1_conf.items()}

    hhr_floor = math.ceil(0.75 * len(v1_dev["hhr"]))
    hhr_guard = "PASS" if dev_hhr_report["play_blocks"] >= hhr_floor else "HHR_COVERAGE_COLLAPSE"
    value_ratio = None if len(v1_dev["value"]) == 0 else dev_value_report["play_blocks"] / len(v1_dev["value"])
    value_guard = "PASS" if value_ratio is None or value_ratio >= 0.50 else "VALUE_COVERAGE_COLLAPSE"

    confirmation: dict[str, Any] = {
        "withheld": balanced_decision.get("winner") is None,
        "hhr_v2": conf_hhr_report,
        "value_v2": conf_value_report,
        "hhr_v1": conf_v1_reports["hhr"],
        "balanced_v1": conf_v1_reports["balanced"],
        "value_v1": conf_v1_reports["value"],
    }
    if balanced_conf is not None and balanced_conf_counts is not None:
        confirmation["balanced_v2"] = _phase_report(enriched, CONFIRMATION_SEASONS, balanced_conf, balanced_conf_counts)

    verdict_parts = []
    if hhr_guard != "PASS": verdict_parts.append(hhr_guard)
    if balanced_decision["status"] == "DEVELOPMENT_FAILURE": verdict_parts.append("BALANCED_DEVELOPMENT_FAILURE")
    if value_guard != "PASS": verdict_parts.append(value_guard)
    verdict = "V2_EXPERIMENT_VALIDATED" if not verdict_parts else "V2_EXPERIMENT_PARTIAL__" + "__".join(verdict_parts)

    score = {
        "verdict": verdict,
        "preregistration": {"commit": PREREG_COMMIT,"blob": PREREG_BLOB,"path": str(prereg_path),"sha256": _sha256(prereg_path)},
        "periods": {"calibration_warmup": sorted(CALIBRATION_SEASONS),"selector_development": sorted(DEVELOPMENT_SEASONS),"selector_confirmation": sorted(CONFIRMATION_SEASONS),"sealed": [SEALED_SEASON]},
        "model_confidence": {"ml_development_calibration": _ml_calibration_metrics(ml_calibration_rows, DEVELOPMENT_SEASONS),"ml_confirmation_calibration": _ml_calibration_metrics(ml_calibration_rows, CONFIRMATION_SEASONS),"states": len(states)},
        "development": {"hhr_v2": dev_hhr_report,"balanced_variants": balanced_dev_reports,"value_v2": dev_value_report,"hhr_v1": dev_v1_reports["hhr"],"balanced_v1": dev_v1_reports["balanced"],"value_v1": dev_v1_reports["value"]},
        "balanced_decision": balanced_decision,
        "confirmation": confirmation,
        "coverage_guardrails": {"hhr": hhr_guard,"hhr_floor_plays": hhr_floor,"hhr_v1_development_plays": len(v1_dev["hhr"]),"hhr_v2_development_plays": dev_hhr_report["play_blocks"],"value": value_guard,"value_v1_development_plays": len(v1_dev["value"]),"value_v2_development_plays": dev_value_report["play_blocks"],"value_v2_to_v1_coverage_ratio": value_ratio},
        "totals_headline_eligible": False,
    }
    _json_write(out / "scorecard.json", score)
    (out / "scorecard.md").write_text(_markdown(score))
    _json_write(out / "manifest.json", {"scorecard_sha256": _sha256(out / "scorecard.json"),"candidate_table_sha256": _sha256(out / "v2_candidate_table.parquet"),"state_sha256": _sha256(out / "model_confidence_state_by_block.ndjson"),"preregistration_sha256": _sha256(prereg_path),"sealed_2025": True})
    print(json.dumps(score, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--board", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--prereg", default="docs/task05g_model_confidence_v2_preregistration.md")
    args = parser.parse_args()
    run(Path(args.root), Path(args.board), Path(args.out), Path(args.prereg))
