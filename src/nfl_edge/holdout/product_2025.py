"""Pre-result Task05F -> Task05G product adapter for the sealed 2025 walkthrough.

This module is orchestration only. It reuses the frozen evaluator, confidence,
selector, headline, staking, and product-policy implementations. Current-block
outcomes are rejected before any evaluator/product work. Historical runner
settlement fields are never persisted on the pre-result surface.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Mapping

from nfl_edge.recommendation.final_selectors_v1 import (
    ValueSelectorState,
    select_balanced,
    select_hit_rate,
    select_value,
)
from nfl_edge.recommendation.headline_staking_v1 import headline_actionability
from nfl_edge.recommendation.policy import NO_BALANCED_PLAY, NO_HIT_RATE_PLAY, NO_VALUE_PLAY
from nfl_edge.recommendation.staking_v1 import cap_slate_stakes, dollar_stake
from nfl_edge.value.candidate_table import build_candidate_table, make_candidate_id
from nfl_edge.value.contracts import GameState, NormalizedOffer
from nfl_edge.value.reliability import fit_reliability_state
from nfl_edge.value.wager_economics import Settlement

from .evaluator_2025 import evaluate_authorized_holdout_offer
from .one_shot_2025 import HoldoutOneShotError, assert_pre_result_surface

PROFILES = ("Cautious", "Conservative", "Normal", "Aggressive", "Ultra")
REFERENCE_BANKROLL = 1000.0


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise HoldoutOneShotError(f"unable to load frozen runner {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _block(season: int, week: Any) -> str:
    return f"{int(season):04d}-{int(str(week)):02d}"


def _assert_current_games_unrevealed(current_games: Mapping[str, Mapping[str, Any]]) -> None:
    if not current_games:
        raise HoldoutOneShotError("current product block is empty")
    for gid, game in current_games.items():
        if int(game.get("season", -1)) != 2025:
            raise HoldoutOneShotError(f"current product game is not 2025: {gid}")
        for key in ("home_score", "away_score", "target_margin", "target_home_win", "target_total_points"):
            if game.get(key) is not None:
                raise HoldoutOneShotError(f"current outcome field populated before product freeze: {gid}:{key}")
        if bool(game.get("target_available", False)):
            raise HoldoutOneShotError(f"current target marked available before product freeze: {gid}")


def _history_rows(prior_games: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for gid, src in prior_games.items():
        season = int(src["season"])
        if season > 2025:
            raise HoldoutOneShotError(f"future season in prior product history: {season}")
        if src.get("home_score") is None or src.get("away_score") is None:
            raise HoldoutOneShotError(f"prior product history is unrevealed: {gid}")
        home_score = int(src["home_score"])
        away_score = int(src["away_score"])
        row = dict(src)
        row["game_id"] = str(gid)
        row["block"] = _block(season, src["week"])
        row["home_binary"] = None if home_score == away_score else int(home_score > away_score)
        if src.get("qbelo_home") is not None and src.get("xgb_home") is not None:
            row["raw_ml_home"] = (float(src["qbelo_home"]) + float(src["xgb_home"])) / 2.0
        else:
            row["raw_ml_home"] = None
        row["margin_residual"] = None
        if src.get("expected_home_margin") is not None:
            row["margin_residual"] = float(home_score - away_score) - float(src["expected_home_margin"])
        rows.append(row)
    return sorted(rows, key=lambda r: ((int(r["season"]), int(r["week"])), str(r["game_id"])))


def _task05f_pre_result(
    *,
    root: Path,
    config_sha: str,
    prior_games: Mapping[str, Mapping[str, Any]],
    current_games: Mapping[str, Mapping[str, Any]],
    market_index: Mapping[Any, Any],
    prior_board_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    task05f = _load("holdout_task05f", root / "scripts/task05f_evaluator_final_runner.py")
    all_games = {str(k): dict(v) for k, v in prior_games.items()}
    all_games.update({str(k): dict(v) for k, v in current_games.items()})
    prior_gids = sorted(str(gid) for gid in prior_games)
    ml_state, spread_state, total_state, _ = task05f._fit_states(all_games, market_index, prior_gids, config_sha)
    states = {"moneyline": ml_state, "spread": spread_state, "total": total_state}

    histories: dict[str, list[tuple[str, float, int]]] = {"moneyline": [], "spread": [], "total": []}
    task05f._history_append(histories, [dict(r) for r in prior_board_rows])
    rel_states = {market: fit_reliability_state(histories[market]) for market in histories}

    rows: list[dict[str, Any]] = []
    for gid in sorted(current_games):
        game = dict(current_games[gid])
        block = _block(2025, game["week"])
        game_state = GameState(
            gid,
            2025,
            str(game["week"]),
            None,
            qbelo_home=game.get("qbelo_home"),
            xgb_home=game.get("xgb_home"),
            expected_home_margin=game.get("expected_home_margin"),
            predicted_total_r4=game.get("predicted_total"),
        )
        anchors = {
            "moneyline": task05f._moneyline_anchor(market_index, gid),
            "spread": task05f._spread_anchor(market_index, gid),
            "total": task05f._total_anchor(market_index, gid),
        }
        for market, sides in (
            ("moneyline", ("home", "away")),
            ("spread", ("home", "away")),
            ("total", ("over", "under")),
        ):
            for side in sides:
                offer = task05f._best(market_index, gid, market, side)
                if offer is None:
                    continue
                state = states[market]
                anchor = anchors[market]
                if state is None:
                    material = task05f._unsupported_row(
                        gid, game, block, offer, market, "accepted_family_cold_start", Settlement.PUSH
                    )
                elif anchor is None:
                    material = task05f._unsupported_row(
                        gid, game, block, offer, market, "missing_pinnacle_anchor", Settlement.PUSH
                    )
                else:
                    result = evaluate_authorized_holdout_offer(
                        game_state, offer, state, anchor, rel_states[market]
                    )
                    manual = NormalizedOffer(
                        market_type=offer.market_type,
                        side=offer.side,
                        book="manual",
                        price_american=offer.price_american,
                        line=offer.line,
                        snapshot_utc=offer.snapshot_utc,
                        source="manual",
                    )
                    parity = evaluate_authorized_holdout_offer(
                        game_state, manual, state, anchor, rel_states[market]
                    )
                    if parity != result:
                        raise HoldoutOneShotError(
                            f"authorized stored/manual evaluator parity failed: {gid} {market} {side}"
                        )
                    material = task05f._result_row(gid, game, block, offer, anchor, result, Settlement.PUSH)
                material.pop("settlement", None)
                material.pop("realized_profit", None)
                rows.append(material)

    assert_pre_result_surface(rows)
    contexts: dict[str, Any] = {}
    for row in rows:
        cid = make_candidate_id(row["game_id"], row["market_type"], row["selected_side"])
        contexts[cid] = task05f._book_context(
            market_index, row["game_id"], row["market_type"], row["selected_side"]
        )
    candidates = build_candidate_table(rows, contexts)
    assert_pre_result_surface(candidates)
    return [dict(r) for r in candidates]


def _apply_v2(
    *, root: Path, candidates: list[dict[str, Any]], prior_games: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    core = _load("holdout_task05g_v2", root / "scripts/task05g_model_confidence_v2_runner.py")
    history = _history_rows(prior_games)
    ml_state = core._fit_ml_state(history)
    residuals = [float(r["margin_residual"]) for r in history if r.get("margin_residual") is not None]
    out: list[dict[str, Any]] = []
    for src in candidates:
        row = dict(src)
        row["model_confidence_probability"] = None
        row["model_confidence_support_n"] = 0
        row["model_confidence_supported"] = False
        row["model_confidence_source"] = None
        row["model_price_gap"] = None
        row["consensus_edge"] = None
        row["raw_qbelo_probability_selected"] = None
        row["raw_xgb_probability_selected"] = None
        row["raw_avg_probability_selected"] = None

        market = str(row.get("market_type"))
        side = str(row.get("selected_side"))
        q: float | None = None
        support_n = 0
        if market == "moneyline":
            raw_selected = row.get("raw_model_output")
            if raw_selected is not None:
                home_raw = float(raw_selected) if side == "home" else 1.0 - float(raw_selected)
                home_q = core._ml_probability(home_raw, ml_state)
                support_n = int(ml_state["n"])
                if home_q is not None:
                    q = float(home_q if side == "home" else 1.0 - home_q)
                    row["raw_avg_probability_selected"] = float(raw_selected)
                    row["model_confidence_source"] = "ML_PLATT_QBELO_XGB_AVG"
        elif market == "spread" and row.get("line") is not None and row.get("raw_model_output") is not None:
            support_n = len(residuals)
            p_win, p_push, p_loss, q = core._spread_probability(
                residuals,
                expected_home_margin=float(row["raw_model_output"]),
                side=side,
                line=float(row["line"]),
            )
            row["model_confidence_p_win"] = p_win
            row["model_confidence_p_push"] = p_push
            row["model_confidence_p_loss"] = p_loss
            row["model_confidence_source"] = "EXPECTED_MARGIN_PRIOR_EMPIRICAL_RESIDUAL"

        if q is not None and support_n >= core.MIN_MODEL_CONFIDENCE_N:
            row["model_confidence_probability"] = float(q)
            row["model_confidence_support_n"] = int(support_n)
            row["model_confidence_supported"] = True
            if row.get("break_even_probability") is not None:
                row["model_price_gap"] = float(q) - float(row["break_even_probability"])
            if row["model_price_gap"] is not None and row.get("evaluated_edge_probability") is not None:
                row["consensus_edge"] = min(float(row["model_price_gap"]), float(row["evaluated_edge_probability"]))
        out.append(row)
    assert_pre_result_surface(out)
    return out


def _apply_v3(
    *, root: Path, rows: list[dict[str, Any]], prior_board_rows: list[dict[str, Any]], prior_games: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    v3 = _load("holdout_task05g_v3", root / "scripts/task05g_spread_confidence_v3_runner.py")
    observations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, float]] = set()
    for r in prior_board_rows:
        if str(r.get("market_type")) != "spread" or str(r.get("settlement")) not in {"WIN", "LOSS"}:
            continue
        gid = str(r.get("game_id"))
        game = prior_games.get(gid)
        if not game or game.get("expected_home_margin") is None or r.get("line") is None:
            continue
        key = (gid, str(r.get("selected_side")), float(r["line"]))
        if key in seen:
            continue
        seen.add(key)
        observations.append(
            {
                "model_cover_margin": v3._cover_margin(
                    float(game["expected_home_margin"]), str(r.get("selected_side")), float(r["line"])
                ),
                "outcome": 1 if str(r.get("settlement")) == "WIN" else 0,
            }
        )
    state = v3._fit_state(observations)
    out: list[dict[str, Any]] = []
    for src in rows:
        r = dict(src)
        if str(r.get("market_type")) == "spread":
            r["model_confidence_probability"] = None
            r["model_confidence_support_n"] = 0
            r["model_confidence_supported"] = False
            r["model_confidence_source"] = "EXPECTED_MARGIN_DIRECT_LOGISTIC_V3"
            r["model_price_gap"] = None
            r["consensus_edge"] = None
            if r.get("line") is not None and r.get("raw_model_output") is not None:
                margin = v3._cover_margin(
                    float(r["raw_model_output"]), str(r.get("selected_side")), float(r["line"])
                )
                q = v3._probability(margin, state)
                r["model_cover_margin_v3"] = float(margin)
                r["spread_calibration_intercept_v3"] = state.get("intercept")
                r["spread_calibration_slope_v3"] = state.get("slope")
                if q is not None:
                    r["model_confidence_probability"] = float(q)
                    r["model_confidence_support_n"] = int(state["n"])
                    r["model_confidence_supported"] = True
                    if r.get("break_even_probability") is not None:
                        r["model_price_gap"] = float(q) - float(r["break_even_probability"])
                    if r["model_price_gap"] is not None and r.get("evaluated_edge_probability") is not None:
                        r["consensus_edge"] = min(
                            float(r["model_price_gap"]), float(r["evaluated_edge_probability"])
                        )
        out.append(r)
    assert_pre_result_surface(out)
    return out


def _candidate_id(row: Mapping[str, Any]) -> str:
    return str(
        row.get("candidate_id")
        or "|".join((str(row.get("game_id")), str(row.get("market_type")), str(row.get("selected_side"))))
    )


def _offer_key(row: Mapping[str, Any]) -> str:
    return "|".join(
        (
            _candidate_id(row),
            str(row.get("sportsbook") or row.get("actionable_book") or ""),
            str(row.get("line") if row.get("line") is not None else row.get("actionable_line")),
            str(
                row.get("american_odds")
                if row.get("american_odds") is not None
                else row.get("actionable_price_american")
            ),
        )
    )


def build_pre_result_product_block(
    *,
    root: Path,
    config_sha: str,
    prior_games: Mapping[str, Mapping[str, Any]],
    current_games: Mapping[str, Mapping[str, Any]],
    market_index: Mapping[Any, Any],
    prior_board_rows: list[dict[str, Any]],
    value_state: ValueSelectorState,
) -> dict[str, Any]:
    """Build the complete frozen user-facing product for one unrevealed block."""
    _assert_current_games_unrevealed(current_games)
    candidates = _task05f_pre_result(
        root=root,
        config_sha=config_sha,
        prior_games=prior_games,
        current_games=current_games,
        market_index=market_index,
        prior_board_rows=prior_board_rows,
    )
    v2 = _apply_v2(root=root, candidates=candidates, prior_games=prior_games)
    board = _apply_v3(
        root=root,
        rows=v2,
        prior_board_rows=prior_board_rows,
        prior_games=prior_games,
    )

    hit = select_hit_rate(board)
    balanced = select_balanced(board)
    value = select_value(board, value_state)
    selected = {
        "hit_rate": None if hit == NO_HIT_RATE_PLAY else dict(hit),
        "balanced": None if balanced == NO_BALANCED_PLAY else dict(balanced),
        "value": None if value == NO_VALUE_PLAY else dict(value),
    }

    headlines: list[dict[str, Any]] = []
    unique: dict[str, dict[str, Any]] = {}
    for lane in ("hit_rate", "balanced", "value"):
        row = selected[lane]
        if row is None:
            headlines.append(
                {"lane": lane, "headline_action": "NO_PLAY", "published": False, "current_units": 0.0}
            )
            continue
        action = headline_actionability(lane, row)
        material = dict(row)
        material.update(
            {
                "lane": lane,
                "published": bool(action.published),
                "headline_action": action.primary_action,
                "current_units": float(action.current_units),
                "action_units": float(action.action_units),
                "value_at_price_american": action.value_at_price_american,
                "heavily_juiced": bool(action.heavily_juiced),
                "offer_key": _offer_key(row),
            }
        )
        headlines.append(material)
        if action.published and action.current_units > 0.0:
            key = material["offer_key"]
            prior = unique.get(key)
            if prior is None or float(material["current_units"]) > float(prior["current_units"]):
                unique[key] = material

    exposure_rows = list(unique.values())
    profile_stakes: dict[str, dict[str, float]] = {}
    for profile in PROFILES:
        proposed = [
            (r["offer_key"], dollar_stake(REFERENCE_BANKROLL, profile, float(r["current_units"])))
            for r in exposure_rows
        ]
        profile_stakes[profile] = cap_slate_stakes(REFERENCE_BANKROLL, proposed)

    for row in headlines:
        key = row.get("offer_key")
        row["reference_1000_profile_stakes"] = {
            profile: 0.0 if key is None else float(profile_stakes[profile].get(str(key), 0.0))
            for profile in PROFILES
        }

    assert_pre_result_surface(board)
    assert_pre_result_surface(headlines)
    return {
        "candidate_rows": candidates,
        "board_rows": board,
        "headlines": headlines,
        "unique_exposure": exposure_rows,
        "reference_bankroll": REFERENCE_BANKROLL,
        "profile_stakes": profile_stakes,
        "profile_total_risk": {
            profile: float(sum(stakes.values())) for profile, stakes in profile_stakes.items()
        },
    }
