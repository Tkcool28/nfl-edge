"""Compose frozen evaluators/selectors/staking into the canonical live 2026 product snapshot."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from nfl_edge.contracts.product_api_v1 import validate_product_snapshot
from nfl_edge.live.roof_scenarios import compare_moneyline_roof_scenarios, missing_roof_scenario_evaluation
from nfl_edge.market_edge import candidates as task05e_candidates
from nfl_edge.recommendation.final_selectors_v1 import (
    ValueSelectorState,
    select_balanced,
    select_hit_rate,
    select_value,
)
from nfl_edge.recommendation.headline_staking_v1 import headline_actionability
from nfl_edge.recommendation.policy import NO_BALANCED_PLAY, NO_HIT_RATE_PLAY, NO_VALUE_PLAY
from nfl_edge.recommendation.remediation_provenance_v1 import REGION_SPECS
from nfl_edge.value.candidate_table import build_candidate_table, make_candidate_id
from nfl_edge.value.contracts import GameState, NormalizedOffer
from nfl_edge.value.evaluators import evaluate_offer
from nfl_edge.value.wager_economics import Settlement

from .markets_2026 import BOOK_MAP

PRODUCT_VERSION = "live-2026-week1-product-v1"
PRODUCT_FRESHNESS_THRESHOLD_SECONDS = 12 * 60 * 60
SELECTOR_VERSIONS = {
    "hit_rate": "v1",
    "balanced": "balanced-price-bounded-v2",
    "value": "v1",
}
BOOK_FROM_CONTRACT = {value: key for key, value in BOOK_MAP.items()}


class LiveProductError(RuntimeError):
    """Raised when the frozen live-product composition cannot be completed safely."""


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise LiveProductError(f"unable to load frozen runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_utc(value: str) -> datetime:
    text = str(value)
    if not text.endswith("Z"):
        raise LiveProductError(f"timestamp must be UTC Z: {text!r}")
    return datetime.fromisoformat(text[:-1] + "+00:00").astimezone(timezone.utc)


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _market_snapshot_index(
    market_snapshot: Mapping[str, Any],
    football_games: Mapping[str, Mapping[str, Any]],
) -> dict[tuple[str, str, str, str], list[NormalizedOffer]]:
    """Build evaluator index from FRESH/AGING offers only; STALE remains display-only."""
    idx: dict[tuple[str, str, str, str], list[NormalizedOffer]] = {}
    for game_row in market_snapshot.get("games") or []:
        gid = str(game_row["game_id"])
        game = football_games.get(gid)
        if game is None:
            raise LiveProductError(f"market snapshot contains unknown game {gid}")
        board = game_row["market_board"]
        for board_key, market in (("moneyline", "moneyline"), ("spread", "spread"), ("total", "total")):
            for contract_book, offers in dict(board[board_key]).items():
                book = BOOK_FROM_CONTRACT.get(str(contract_book))
                if book is None:
                    continue
                for source in offers:
                    if str(source["freshness"]["state"]) == "STALE":
                        continue
                    selection = str(source["normalized_selection"])
                    if market == "total":
                        side = selection.lower()
                    elif selection == str(game["home_team"]):
                        side = "home"
                    elif selection == str(game["away_team"]):
                        side = "away"
                    else:
                        continue
                    idx.setdefault((gid, market, side, book), []).append(
                        NormalizedOffer(
                            market_type=market,
                            side=side,
                            book=book,
                            price_american=int(source["price"]),
                            line=None if source["line"] is None else float(source["line"]),
                            snapshot_utc=str(source["snapshot_at_utc"]),
                            source=str(source["provider"]),
                        )
                    )
    return idx


def _model_prediction(output: Mapping[str, Any]) -> float | None:
    if str(output.get("status")) != "AVAILABLE":
        return None
    value = output.get("prediction")
    return None if value is None else float(value)


def _current_game(game: Mapping[str, Any], *, xgb_override: float | None = None) -> dict[str, Any]:
    outputs = game["football_outputs"]
    xgb = xgb_override if xgb_override is not None else _model_prediction(outputs["xgboost_v2"])
    return {
        "game_id": str(game["game_id"]),
        "season": 2026,
        "week": 1,
        "qbelo_home": _model_prediction(outputs["qb_elo"]),
        "xgb_home": xgb,
        "expected_home_margin": _model_prediction(outputs["expected_margin"]),
        "predicted_total": _model_prediction(outputs["ridge_totals_r4"]),
        "home_score": None,
        "away_score": None,
        "target_margin": None,
        "target_home_win": None,
        "target_total_points": None,
        "target_available": False,
    }


def _legacy_current_rows(
    rows: Iterable[Mapping[str, Any]],
    current_games: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        for legacy, canonical in (
            ("selected_side", "selection"),
            ("line", "actionable_line"),
            ("american_odds", "actionable_price_american"),
            ("sportsbook", "actionable_book"),
        ):
            if row.get(legacy) is None and row.get(canonical) is not None:
                row[legacy] = row[canonical]
        gid = str(row["game_id"])
        game = current_games[gid]
        market = str(row["market_type"])
        side = str(row["selected_side"])
        raw: float | None = None
        if market == "moneyline":
            q = game.get("qbelo_home")
            x = game.get("xgb_home")
            if q is not None and x is not None:
                home = (float(q) + float(x)) / 2.0
                raw = home if side == "home" else 1.0 - home
        elif market == "spread" and game.get("expected_home_margin") is not None:
            raw = float(game["expected_home_margin"])
        elif market == "total" and game.get("predicted_total") is not None:
            raw = float(game["predicted_total"])
        row["raw_model_output"] = raw
        out.append(row)
    return out


def _region_name(family: str, model: str, bucket: str) -> str | None:
    for name, expected_family, expected_model, buckets in REGION_SPECS:
        if family == expected_family and model == expected_model and bucket in buckets:
            return name
    return None


def _positive_edge_side(model_home: float, benchmark_home: float) -> tuple[str, float, float] | None:
    delta = float(model_home) - float(benchmark_home)
    if abs(delta) <= 1e-12:
        return None
    if delta > 0.0:
        return "home", float(model_home), abs(delta) * 100.0
    return "away", 1.0 - float(model_home), abs(delta) * 100.0


def _candidate_registry(task05f: Any, current_games: Mapping[str, Mapping[str, Any]], market_index: Mapping[Any, Any]):
    """Reproduce frozen Task05E candidate-region predicates for prospective 2026 rows."""
    tags: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for gid, game in sorted(current_games.items()):
        qh = game.get("qbelo_home")
        xh = game.get("xgb_home")
        ml_anchor = task05f._moneyline_anchor(market_index, gid)
        if qh is not None and xh is not None and ml_anchor is not None:
            qh, xh = float(qh), float(xh)
            avg = (qh + xh) / 2.0
            benchmark = float(ml_anchor.home_no_vig_probability)
            q_side = _positive_edge_side(qh, benchmark)
            x_side = _positive_edge_side(xh, benchmark)
            avg_side = _positive_edge_side(avg, benchmark)
            if avg_side is not None:
                side, p_selected, edge_pp = avg_side
                offer = task05f._best(market_index, gid, "moneyline", side)
                if offer is not None:
                    bucket = task05e_candidates._ml_bucket(edge_pp)
                    if bucket is not None:
                        name = _region_name("ML_AVG_DISAGREEMENT", "AVG", bucket)
                        if name:
                            tags[(gid, "moneyline", side)].add(name)
                    if task05e_candidates._in_dog_zone(p_selected, int(offer.price_american)):
                        name = _region_name("ML_DOG_VALUE_ZONE", "AVG", "ZONE")
                        if name:
                            tags[(gid, "moneyline", side)].add(name)
                        if q_side and x_side and q_side[0] == x_side[0] == side:
                            name = _region_name("ML_DOG_VALUE_ZONE", "CORROB", "ZONE")
                            if name:
                                tags[(gid, "moneyline", side)].add(name)
        expected = game.get("expected_home_margin")
        spread_anchor = task05f._spread_anchor(market_index, gid)
        if expected is not None and spread_anchor is not None:
            signed = float(expected) - float(spread_anchor.threshold)
            if abs(signed) > 1e-9:
                side = "home" if signed > 0 else "away"
                dk = list(market_index.get((gid, "spread", side, "draftkings"), []))
                fd = list(market_index.get((gid, "spread", side, "fanduel"), []))
                if dk and fd:
                    bucket = task05e_candidates._st_bucket(abs(signed))
                    if bucket is not None:
                        name = _region_name("SPREAD_DISAGREEMENT", "EXPECTED_MARGIN", bucket)
                        if name:
                            tags[(gid, "spread", side)].add(name)
    return {key: tuple(sorted(value)) for key, value in sorted(tags.items())}


def _attach_regions(rows: Iterable[Mapping[str, Any]], registry: Mapping[tuple[str, str, str], tuple[str, ...]]):
    out = []
    for source in rows:
        row = dict(source)
        key = (str(row["game_id"]), str(row["market_type"]), str(row["selected_side"]))
        regions = registry.get(key, ())
        row["model_candidate"] = bool(regions)
        row["model_candidate_regions"] = ";".join(regions)
        out.append(row)
    return out


def _evaluate_candidates(
    *,
    task05f: Any,
    confidence_v2: Any,
    spread_v3: Any,
    current_games: Mapping[str, Mapping[str, Any]],
    market_index: Mapping[Any, Any],
    decision_state: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    states = {
        "moneyline": decision_state["moneyline"],
        "spread": decision_state["spread"],
        "total": decision_state["total"],
    }
    for gid in sorted(current_games):
        game = dict(current_games[gid])
        game_state = GameState(
            gid,
            2026,
            "1",
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
                anchor = anchors[market]
                if anchor is None:
                    material = task05f._unsupported_row(
                        gid, game, "2026-01", offer, market, "missing_pinnacle_anchor", Settlement.PUSH
                    )
                else:
                    result = evaluate_offer(
                        game_state,
                        offer,
                        states[market],
                        anchor,
                        decision_state["reliability"][market],
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
                    parity = evaluate_offer(
                        game_state,
                        manual,
                        states[market],
                        anchor,
                        decision_state["reliability"][market],
                    )
                    if parity != result:
                        raise LiveProductError(f"stored/manual evaluator parity failed: {gid} {market} {side}")
                    material = task05f._result_row(
                        gid, game, "2026-01", offer, anchor, result, Settlement.PUSH
                    )
                material.pop("settlement", None)
                material.pop("realized_profit", None)
                rows.append(material)

    contexts = {}
    for row in rows:
        cid = make_candidate_id(row["game_id"], row["market_type"], row["selected_side"])
        contexts[cid] = task05f._book_context(
            market_index, row["game_id"], row["market_type"], row["selected_side"]
        )
    candidates = build_candidate_table(rows, contexts)
    board = _legacy_current_rows(candidates, current_games)

    for row in board:
        row["model_confidence_probability"] = None
        row["model_confidence_support_n"] = 0
        row["model_confidence_supported"] = False
        row["model_confidence_source"] = None
        row["model_price_gap"] = None
        row["consensus_edge"] = None
        row["raw_qbelo_probability_selected"] = None
        row["raw_xgb_probability_selected"] = None
        row["raw_avg_probability_selected"] = None
        market = str(row["market_type"])
        side = str(row["selected_side"])
        if market == "moneyline" and row.get("raw_model_output") is not None:
            selected_raw = float(row["raw_model_output"])
            home_raw = selected_raw if side == "home" else 1.0 - selected_raw
            home_q = confidence_v2._ml_probability(home_raw, decision_state["ml_confidence"])
            if home_q is not None:
                q = home_q if side == "home" else 1.0 - home_q
                row["model_confidence_probability"] = float(q)
                row["model_confidence_support_n"] = int(decision_state["ml_confidence"]["n"])
                row["model_confidence_supported"] = True
                row["model_confidence_source"] = "ML_PLATT_QBELO_XGB_AVG"
                row["raw_avg_probability_selected"] = selected_raw
                if row.get("break_even_probability") is not None:
                    row["model_price_gap"] = float(q) - float(row["break_even_probability"])
                if row["model_price_gap"] is not None and row.get("evaluated_edge_probability") is not None:
                    row["consensus_edge"] = min(
                        float(row["model_price_gap"]), float(row["evaluated_edge_probability"])
                    )
        elif market == "spread":
            row["model_confidence_source"] = "EXPECTED_MARGIN_DIRECT_LOGISTIC_V3"
            if row.get("line") is not None and row.get("raw_model_output") is not None:
                margin = spread_v3._cover_margin(
                    float(row["raw_model_output"]), side, float(row["line"])
                )
                q = spread_v3._probability(margin, decision_state["spread_v3"])
                row["model_cover_margin_v3"] = float(margin)
                row["spread_calibration_intercept_v3"] = decision_state["spread_v3"].get("intercept")
                row["spread_calibration_slope_v3"] = decision_state["spread_v3"].get("slope")
                if q is not None:
                    row["model_confidence_probability"] = float(q)
                    row["model_confidence_support_n"] = int(decision_state["spread_v3"]["n"])
                    row["model_confidence_supported"] = True
                    if row.get("break_even_probability") is not None:
                        row["model_price_gap"] = float(q) - float(row["break_even_probability"])
                    if row["model_price_gap"] is not None and row.get("evaluated_edge_probability") is not None:
                        row["consensus_edge"] = min(
                            float(row["model_price_gap"]), float(row["evaluated_edge_probability"])
                        )

    registry = _candidate_registry(task05f, current_games, market_index)
    return _attach_regions(board, registry)


def _lane_selection(board: list[dict[str, Any]], value_state: ValueSelectorState):
    hit = select_hit_rate(board)
    balanced = select_balanced(board)
    value = select_value(board, value_state)
    return {
        "hit_rate": None if hit == NO_HIT_RATE_PLAY else dict(hit),
        "balanced": None if balanced == NO_BALANCED_PLAY else dict(balanced),
        "value": None if value == NO_VALUE_PLAY else dict(value),
    }


def _public_selection(row: Mapping[str, Any], football_game: Mapping[str, Any]) -> str:
    side = str(row["selected_side"])
    if side == "home":
        return str(football_game["home_team"])
    if side == "away":
        return str(football_game["away_team"])
    return side.upper()


def _headline(lane: str, row: Mapping[str, Any] | None, football_games: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    lane_name = {"hit_rate": "HIT_RATE", "balanced": "BALANCED", "value": "VALUE"}[lane]
    if row is None:
        return {
            "lane": lane_name,
            "state": "NO_PLAY",
            "game_id": None,
            "matchup": None,
            "market": None,
            "selection": None,
            "book": None,
            "line": None,
            "american_odds": None,
            "model_probability": None,
            "trust_probability": None,
            "market_probability": None,
            "ev": None,
            "support": "SUPPORTED",
            "reliability": None,
            "recommended_units": 0.0,
            "play_through": None,
            "value_at": None,
            "warnings": [f"No offer currently satisfies the frozen {lane_name} lane contract."],
        }
    material = dict(row)
    action = headline_actionability(lane, material)
    gid = str(material["game_id"])
    game = football_games[gid]
    if action.primary_action == "BET":
        state = "BET"
        units = float(action.current_units)
    elif action.primary_action == "VALUE_AT" and action.published:
        state = "TARGET_ONLY"
        units = 0.0
    else:
        state = "SUPPRESSED"
        units = 0.0
    play_through = None
    if material.get("play_through_price_american") is not None:
        play_through = {
            "line": material.get("line"),
            "price_american": int(material["play_through_price_american"]),
        }
    value_at = None
    if action.value_at_price_american is not None:
        value_at = {
            "line": material.get("line"),
            "price_american": int(action.value_at_price_american),
        }
    warnings = []
    if action.heavily_juiced:
        warnings.append("HEAVILY_JUICED")
    if state == "SUPPRESSED":
        warnings.append("Selected frozen lane candidate is suppressed by frozen product policy.")
    return {
        "lane": lane_name,
        "state": state,
        "game_id": gid,
        "matchup": {"away_team": str(game["away_team"]), "home_team": str(game["home_team"])},
        "market": str(material["market_type"]).upper(),
        "selection": _public_selection(material, game),
        "book": str(material["sportsbook"]).upper(),
        "line": material.get("line"),
        "american_odds": int(material["american_odds"]),
        "model_probability": material.get("model_confidence_probability"),
        "trust_probability": material.get("selector_trust", material.get("model_confidence_probability")),
        "market_probability": material.get("pinnacle_anchor_probability"),
        "ev": material.get("expected_value"),
        "support": "SUPPORTED" if material.get("supported") else "UNSUPPORTED",
        "reliability": str(material.get("reliability")) if material.get("reliability") is not None else None,
        "recommended_units": units,
        "play_through": play_through,
        "value_at": value_at,
        "warnings": warnings,
    }


def _aggregate_roof_scenarios(
    *,
    task05f: Any,
    game: Mapping[str, Any],
    current_game: Mapping[str, Any],
    market_index: Mapping[Any, Any],
    decision_state: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare OPEN/CLOSED on the canonical home-side best retail moneyline offer.

    ``roof_scenario_downstream`` is a single evaluation-state slot in the frozen
    product schema, not a multi-offer board. The canonical home-side exact offer
    gives one deterministic, auditable comparison while the complete DK/FD board
    remains available elsewhere in the game object. If the required Pinnacle
    anchor or home-side retail offer is absent, do not invent a downstream state.
    """
    xgb = game["football_outputs"]["xgboost_v2"]
    if str(xgb.get("status")) != "AVAILABLE_WITH_ROOF_SCENARIOS":
        raise LiveProductError("roof scenario aggregation called for non-pending game")
    anchor = task05f._moneyline_anchor(market_index, str(game["game_id"]))
    offer = task05f._best(market_index, str(game["game_id"]), "moneyline", "home")
    if anchor is None or offer is None:
        return missing_roof_scenario_evaluation()
    base = GameState(
        str(game["game_id"]),
        2026,
        "1",
        None,
        qbelo_home=current_game.get("qbelo_home"),
        xgb_home=None,
        expected_home_margin=current_game.get("expected_home_margin"),
        predicted_total_r4=current_game.get("predicted_total"),
    )
    return compare_moneyline_roof_scenarios(
        game=base,
        open_xgb_home=float(xgb["xgboost_open_probability"]),
        closed_xgb_home=float(xgb["xgboost_closed_probability"]),
        offer=offer,
        evaluator_state=decision_state["moneyline"],
        anchor=anchor,
        reliability_state=decision_state["reliability"]["moneyline"],
    )


def _game_warnings(market_board: Mapping[str, Any], xgb: Mapping[str, Any]) -> list[str]:
    warnings = []
    if not any(market_board[key] for key in ("moneyline", "spread", "total")):
        warnings.append("No required current market observations are available for this matched game.")
    if str(xgb.get("status")) == "AVAILABLE_WITH_ROOF_SCENARIOS":
        downstream = xgb["roof_scenario_downstream"]
        if downstream["status"] == "ROOF_SENSITIVE":
            warnings.append("XGBoost moneyline evaluation is ROOF_SENSITIVE; no singular pending-roof ML state is published.")
        elif downstream["status"] == "NOT_EVALUATED_MISSING_EVIDENCE":
            warnings.append("Pending-roof XGBoost downstream state lacks current market/evaluator evidence.")
    return warnings


def build_product_snapshot(
    *,
    root: Path,
    football_snapshot: Mapping[str, Any],
    market_snapshot: Mapping[str, Any],
    decision_state: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if int(football_snapshot.get("season", -1)) != 2026 or int(football_snapshot.get("week", -1)) != 1:
        raise LiveProductError("football snapshot must be 2026 Week 1")
    if int(market_snapshot.get("season", -1)) != 2026 or int(market_snapshot.get("week", -1)) != 1:
        raise LiveProductError("market snapshot must be 2026 Week 1")
    football_games = {str(game["game_id"]): dict(game) for game in football_snapshot["games"]}
    if len(football_games) != 16:
        raise LiveProductError("football snapshot must contain 16 games")
    market_boards = {str(row["game_id"]): row["market_board"] for row in market_snapshot["games"]}
    if set(market_boards) != set(football_games):
        raise LiveProductError("football/market canonical game IDs differ")

    task05f = _load_script("live_2026_task05f_product", root / "scripts/task05f_evaluator_final_runner.py")
    confidence_v2 = _load_script("live_2026_confidence_v2_product", root / "scripts/task05g_model_confidence_v2_runner.py")
    spread_v3 = _load_script("live_2026_spread_v3_product", root / "scripts/task05g_spread_confidence_v3_runner.py")
    market_index = _market_snapshot_index(market_snapshot, football_games)
    current_games = {gid: _current_game(game) for gid, game in football_games.items()}

    board = _evaluate_candidates(
        task05f=task05f,
        confidence_v2=confidence_v2,
        spread_v3=spread_v3,
        current_games=current_games,
        market_index=market_index,
        decision_state=decision_state,
    )
    selections = _lane_selection(board, decision_state.get("value_state") or ValueSelectorState())
    headlines = {
        lane: _headline(lane, selections[lane], football_games)
        for lane in ("hit_rate", "balanced", "value")
    }

    generated = str(market_snapshot["acquired_at_utc"])
    prediction_as_of = str(football_snapshot["prediction_as_of_utc"])
    if _parse_utc(generated) < _parse_utc(prediction_as_of):
        raise LiveProductError("market acquisition precedes football prediction_as_of")
    product_freshness = {
        "state": "FRESH",
        "observed_at_utc": generated,
        "age_seconds": 0.0,
        "threshold_seconds": float(PRODUCT_FRESHNESS_THRESHOLD_SECONDS),
    }

    games = []
    roof_counts = Counter()
    for gid in sorted(football_games):
        source = football_games[gid]
        outputs = deepcopy(source["football_outputs"])
        xgb = outputs["xgboost_v2"]
        if str(xgb.get("status")) == "AVAILABLE_WITH_ROOF_SCENARIOS":
            downstream = _aggregate_roof_scenarios(
                task05f=task05f,
                game=source,
                current_game=current_games[gid],
                market_index=market_index,
                decision_state=decision_state,
            )
            xgb["roof_scenario_downstream"] = downstream
            roof_counts[downstream["status"]] += 1
        outputs = {
            "prediction_as_of_utc": prediction_as_of,
            "provenance_id": f"football:{football_snapshot['snapshot_sha256']}:{gid}",
            **outputs,
        }
        board_for_game = market_boards[gid]
        games.append(
            {
                "game_id": gid,
                "season": 2026,
                "week": 1,
                "home_team": str(source["home_team"]),
                "away_team": str(source["away_team"]),
                "kickoff_at_utc": str(source["kickoff_at_utc"]),
                "game_status": "PREGAME" if _parse_utc(generated) < _parse_utc(str(source["kickoff_at_utc"])) else "IN_PROGRESS",
                "venue": source.get("venue"),
                "neutral_site": bool(source["neutral_site"]),
                "updated_at_utc": generated,
                "quarterbacks": deepcopy(source["quarterbacks"]),
                "market_board": deepcopy(board_for_game),
                "football_outputs": outputs,
                "warnings": _game_warnings(board_for_game, xgb),
            }
        )

    top_warnings = []
    audit = market_snapshot["audit"]
    if audit.get("unmatched_canonical_game_ids"):
        top_warnings.append(
            f"{len(audit['unmatched_canonical_game_ids'])} canonical Week 1 game(s) lack a provider event."
        )
    if int(audit.get("stale_offers") or 0) > 0:
        top_warnings.append(
            f"{int(audit['stale_offers'])} stale market offer(s) are display-only and excluded from evaluation."
        )

    snapshot = {
        "schema_version": "NFL_EDGE_PRODUCT_API_V1",
        "product_version": PRODUCT_VERSION,
        "generated_at_utc": generated,
        "prediction_as_of_utc": prediction_as_of,
        "season": 2026,
        "week": 1,
        "slate_status": "UPCOMING",
        "football_data_version": str(football_snapshot["completed_football_state_version"]),
        "qb_snapshot_version": str(football_snapshot["qb_snapshot_version"]),
        "market_snapshot_version": str(market_snapshot["market_snapshot_version"]),
        "model_versions": dict(football_snapshot["model_versions"]),
        "evaluator_versions": {
            "moneyline": str(decision_state["moneyline"].version),
            "spread": str(decision_state["spread"].version),
            "total": str(decision_state["total"].version),
        },
        "selector_versions": dict(SELECTOR_VERSIONS),
        "freshness": product_freshness,
        "stale": False,
        "warnings": top_warnings,
        "headlines": headlines,
        "games": games,
    }
    validate_product_snapshot(snapshot)
    proof = {
        "evaluator_rows": len(board),
        "evaluator_by_market": dict(sorted(Counter(str(row["market_type"]) for row in board).items())),
        "evaluator_supported_by_market": dict(sorted(Counter(
            str(row["market_type"]) for row in board if bool(row.get("supported"))
        ).items())),
        "headline_states": {lane: headline["state"] for lane, headline in headlines.items()},
        "roof_downstream_counts": dict(sorted(roof_counts.items())),
        "stale_offers_excluded_from_evaluation": int(audit.get("stale_offers") or 0),
        "product_snapshot_sha256": hashlib.sha256(_canonical_bytes(snapshot)).hexdigest(),
        "schema_validation": "PASS",
        "methodology_changed": False,
    }
    return snapshot, proof


def product_snapshot_bytes(snapshot: Mapping[str, Any]) -> bytes:
    validate_product_snapshot(snapshot)
    return _canonical_bytes(snapshot)
