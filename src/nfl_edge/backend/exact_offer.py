"""Exact retail-offer evaluation using only frozen state and the loaded product snapshot."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from nfl_edge.contracts.live_product_v1 import validate_exact_offer_request, validate_exact_offer_response
from nfl_edge.recommendation.headline_staking_v1 import value_headline_actionability
from nfl_edge.staking_policy_v1 import recommended_units
from nfl_edge.value.contracts import GameState, MarketAnchor, NormalizedOffer
from nfl_edge.value.evaluators import evaluate_offer
from nfl_edge.value.market_math import proportional_no_vig, shop_moneyline, shop_spread, shop_total
from nfl_edge.value.play_through import assess_play_through
from nfl_edge.value.state_io import moneyline_state_from_dict, point_state_from_dict, reliability_state_from_dict
from nfl_edge.value.wager_economics import line_allows_push

STATE_SCHEMA = "NFL_EDGE_ENTERING_2026_PRODUCT_STATE_V1"
BOOKS = {"DRAFTKINGS": "draftkings", "FANDUEL": "fanduel", "PINNACLE": "pinnacle"}
MARKETS = {"MONEYLINE": "moneyline", "SPREAD": "spread", "TOTAL": "total"}


class ExactOfferError(ValueError):
    pass


def _prediction(output: Mapping[str, Any]) -> float | None:
    if str(output.get("status")) != "AVAILABLE":
        return None
    value = output.get("prediction")
    return None if value is None else float(value)


def _side(game: Mapping[str, Any], market: str, selection: str) -> str:
    text = str(selection).strip()
    if market == "total":
        lowered = text.lower()
        if lowered not in {"over", "under"}:
            raise ExactOfferError("TOTAL selection must be OVER or UNDER")
        return lowered
    if text.casefold() == str(game["home_team"]).casefold():
        return "home"
    if text.casefold() == str(game["away_team"]).casefold():
        return "away"
    raise ExactOfferError("selection does not match the current game's home or away team")


def _market_index(game: Mapping[str, Any]) -> dict[tuple[str, str, str, str], list[NormalizedOffer]]:
    idx: dict[tuple[str, str, str, str], list[NormalizedOffer]] = {}
    gid = str(game["game_id"])
    board = game["market_board"]
    for board_key, market in (("moneyline", "moneyline"), ("spread", "spread"), ("total", "total")):
        for contract_book, offers in dict(board[board_key]).items():
            book = BOOKS.get(str(contract_book))
            if book is None:
                continue
            for source in offers:
                if str(source["freshness"]["state"]) == "STALE":
                    continue
                selection = str(source["normalized_selection"])
                try:
                    side = _side(game, market, selection)
                except ExactOfferError:
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


def _best(idx, gid: str, market: str, side: str, books: tuple[str, ...]) -> NormalizedOffer | None:
    offers = [offer for book in books for offer in idx.get((gid, market, side, book), [])]
    if market == "moneyline":
        return shop_moneyline(offers)
    if market == "spread":
        return shop_spread(offers)
    return shop_total(side, offers)


def _best_same_line(offers: list[NormalizedOffer], line: float) -> NormalizedOffer | None:
    same = [
        offer for offer in offers
        if offer.line is not None and abs(float(offer.line) - float(line)) <= 1e-6
    ]
    return max(same, key=lambda offer: (int(offer.price_american), str(offer.snapshot_utc or "")), default=None)


def _anchor(idx, gid: str, market: str) -> MarketAnchor | None:
    if market == "moneyline":
        home = _best(idx, gid, market, "home", ("pinnacle",))
        away = _best(idx, gid, market, "away", ("pinnacle",))
        if home is None or away is None:
            return None
        p_home, _ = proportional_no_vig(home.price_american, away.price_american)
        return MarketAnchor("moneyline", home_no_vig_probability=float(p_home))
    if market == "spread":
        homes = idx.get((gid, market, "home", "pinnacle"), [])
        aways = idx.get((gid, market, "away", "pinnacle"), [])
        mirrored = sorted({
            round(float(home.line), 6)
            for home in homes
            if home.line is not None
            and any(away.line is not None and abs(float(home.line) + float(away.line)) <= 1e-6 for away in aways)
        })
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
    overs = idx.get((gid, market, "over", "pinnacle"), [])
    unders = idx.get((gid, market, "under", "pinnacle"), [])
    common = sorted({
        round(float(over.line), 6)
        for over in overs
        if over.line is not None
        and any(under.line is not None and abs(float(over.line) - float(under.line)) <= 1e-6 for under in unders)
    })
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


class ExactOfferEngine:
    def __init__(self, state_path: str | Path) -> None:
        payload = json.loads(Path(state_path).read_text(encoding="utf-8"))
        if payload.get("schema_version") != STATE_SCHEMA:
            raise ExactOfferError(f"unsupported entering-2026 state {payload.get('schema_version')!r}")
        task = payload["task05f"]
        self.states = {
            "moneyline": moneyline_state_from_dict(task["evaluators"]["moneyline"]),
            "spread": point_state_from_dict(task["evaluators"]["spread"]),
            "total": point_state_from_dict(task["evaluators"]["total"]),
        }
        self.reliability = {
            market: reliability_state_from_dict(task["reliability"][market])
            for market in ("moneyline", "spread", "total")
        }
        self.state_version = str(payload.get("state_version") or payload.get("schema_version"))

    def evaluate(self, product: Mapping[str, Any], request: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        req = validate_exact_offer_request(request)
        games = {str(game["game_id"]): game for game in product["games"]}
        game = games.get(str(req["game_id"]))
        if game is None:
            raise ExactOfferError("game_id is not present in the currently served product")
        market = MARKETS[str(req["market_type"])]
        side = _side(game, market, str(req["selection"]))
        idx = _market_index(game)
        anchor = _anchor(idx, str(game["game_id"]), market)
        if anchor is None:
            response = validate_exact_offer_response({
                "supported": False,
                "probability": None,
                "trust_probability": None,
                "break_even_probability": None,
                "ev": None,
                "verdict": "UNSUPPORTED",
                "recommended_units": 0.0,
                "play_through": None,
                "value_at": None,
                "warnings": ["Required current Pinnacle benchmark evidence is unavailable."],
            })
            return response, {"request": dict(req), "reason": "missing_pinnacle_anchor"}

        output = game["football_outputs"]
        game_state = GameState(
            game_id=str(game["game_id"]),
            season=int(game["season"]),
            week=str(game["week"]),
            kickoff_utc=str(game["kickoff_at_utc"]),
            qbelo_home=_prediction(output["qb_elo"]),
            xgb_home=_prediction(output["xgboost_v2"]),
            expected_home_margin=_prediction(output["expected_margin"]),
            predicted_total_r4=_prediction(output["ridge_totals_r4"]),
        )
        offer = NormalizedOffer(
            market_type=market,
            side=side,
            book=BOOKS[str(req["book"])],
            price_american=int(req["price"]),
            line=None if req["line"] is None else float(req["line"]),
            snapshot_utc=str(product["generated_at_utc"]),
            source="backend_exact_offer_v1",
        )
        result = evaluate_offer(game_state, offer, self.states[market], anchor, self.reliability[market])
        play = assess_play_through(
            supported=result.supported,
            strict_expected_value=result.expected_value,
            conditional_nonpush_probability=result.conditional_nonpush_probability,
            current_break_even_probability=result.break_even_probability,
            reliability=result.reliability,
            uncertainty_radius=result.uncertainty,
        )
        row = {
            "supported": bool(result.supported),
            "reliability": result.reliability,
            "price_status": play.status,
            "actionable_probability": result.actionable_probability,
            "expected_value": result.expected_value,
            "uncertainty": result.uncertainty,
            "american_odds": int(req["price"]),
            "line": req["line"],
        }
        units = float(recommended_units(row))
        value_at = None
        verdict = "UNSUPPORTED" if not result.supported else "BET" if units > 0 else "NO"
        if result.supported and units == 0.0 and str(play.status).upper() == "VALUE":
            action = value_headline_actionability(row)
            if action.primary_action == "VALUE_AT" and action.value_at_price_american is not None:
                verdict = "TARGET_ONLY"
                value_at = {"line": req["line"], "price_american": int(action.value_at_price_american)}
        play_through = None
        if play.play_through_price_american is not None:
            play_through = {"line": req["line"], "price_american": int(play.play_through_price_american)}
        warnings: list[str] = []
        if not result.supported:
            warnings.append(str(result.reason or "Unsupported by frozen evaluator state."))
        response = validate_exact_offer_response({
            "supported": bool(result.supported),
            "probability": result.actionable_probability,
            "trust_probability": result.staking_probability,
            "break_even_probability": result.break_even_probability,
            "ev": result.expected_value,
            "verdict": verdict,
            "recommended_units": units,
            "play_through": play_through,
            "value_at": value_at,
            "warnings": warnings,
        })
        context = {
            "request": dict(req),
            "side": side,
            "evaluator_version": result.evaluator_version,
            "reliability": result.reliability,
            "state_version": self.state_version,
            "recommendation": dict(response),
        }
        return response, context