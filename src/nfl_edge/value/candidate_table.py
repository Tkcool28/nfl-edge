"""Account-independent Task05F candidate table presented to selectors/game explorer."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping

SEALED_SEASONS = {2025}
AUTHORIZED_HOLDOUT_SEASON = 2025
OUTCOME_FIELDS = frozenset({"settlement", "realized_profit", "home_score", "away_score"})


@dataclass(frozen=True)
class BookOfferContext:
    line: float | None
    price_american: int


@dataclass(frozen=True)
class CandidateOfferContext:
    draftkings: BookOfferContext | None = None
    fanduel: BookOfferContext | None = None
    pinnacle: BookOfferContext | None = None


def make_candidate_id(game_id: str, market_type: str, selected_side: str) -> str:
    return f"{str(game_id).strip()}|{str(market_type).lower()}|{str(selected_side).lower()}"


def make_offer_id(
    candidate_id: str,
    actionable_book: str,
    actionable_line: float | None,
    actionable_price_american: int,
    snapshot: str,
) -> str:
    payload = {
        "candidate_id": candidate_id,
        "book": str(actionable_book).lower(),
        "line": actionable_line,
        "price": int(actionable_price_american),
        "snapshot": str(snapshot),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _book_fields(prefix: str, offer: BookOfferContext | None) -> dict[str, Any]:
    return {
        f"{prefix}_line": None if offer is None else offer.line,
        f"{prefix}_price_american": None if offer is None else int(offer.price_american),
    }


def _assert_season_allowed(
    season: int,
    *,
    allow_authorized_holdout_2025: bool = False,
) -> None:
    if season not in SEALED_SEASONS:
        return
    if allow_authorized_holdout_2025 and season == AUTHORIZED_HOLDOUT_SEASON:
        return
    raise RuntimeError(f"sealed season {season} cannot enter candidate table")


def build_candidate_row(
    upstream: Mapping[str, Any],
    context: CandidateOfferContext,
    *,
    allow_authorized_holdout_2025: bool = False,
) -> dict[str, Any]:
    season = int(upstream["season"])
    _assert_season_allowed(
        season,
        allow_authorized_holdout_2025=allow_authorized_holdout_2025,
    )
    candidate_id = make_candidate_id(upstream["game_id"], upstream["market_type"], upstream["selected_side"])
    snapshot = str(upstream.get("market_snapshot_timestamp") or "")
    line = upstream.get("line")
    price = int(upstream["american_odds"])
    book = str(upstream["sportsbook"]).lower()
    supported = bool(upstream.get("supported"))
    reliability = upstream.get("reliability")
    price_status = "UNSUPPORTED" if (not supported or reliability == "UNSUPPORTED") else upstream.get("price_status")
    row: dict[str, Any] = {
        "candidate_id": candidate_id,
        "offer_id": make_offer_id(candidate_id, book, line, price, snapshot),
        "game_id": str(upstream["game_id"]),
        "season": season,
        "week": upstream.get("week"),
        "block": upstream.get("block"),
        "market_type": str(upstream["market_type"]),
        "selection": str(upstream["selected_side"]),
        "actionable_book": book,
        "actionable_line": line,
        "actionable_price_american": price,
        "market_snapshot_timestamp": snapshot,
        "raw_football_output": upstream.get("raw_model_output"),
        "football_model_name": upstream.get("football_model_name"),
        "model_market_disagreement": upstream.get("model_market_disagreement"),
        "pinnacle_anchor_probability": upstream.get("pinnacle_anchor_probability"),
        "pinnacle_anchor_threshold": upstream.get("pinnacle_anchor_threshold"),
        "p_win": upstream.get("p_win"),
        "p_push": upstream.get("p_push"),
        "p_loss": upstream.get("p_loss"),
        "actionable_probability": upstream.get("actionable_probability"),
        "conditional_nonpush_probability": upstream.get("conditional_nonpush_probability"),
        "staking_probability": upstream.get("staking_probability"),
        "staking_anchor_probability": upstream.get("staking_anchor_probability"),
        "fair_price_american": upstream.get("fair_price_american"),
        "break_even_probability": upstream.get("break_even_probability"),
        "expected_value": upstream.get("expected_value"),
        "strict_positive_value": upstream.get("strict_positive_value"),
        "evaluated_edge_probability": upstream.get("evaluated_edge_probability"),
        "staking_edge_probability": upstream.get("staking_edge_probability"),
        "supported": supported,
        "reason": upstream.get("reason"),
        "reliability": reliability,
        "uncertainty": upstream.get("uncertainty"),
        "support_n": upstream.get("support_n"),
        "support_distance": upstream.get("support_distance"),
        "evaluator_version": upstream.get("evaluator_version"),
        "price_status": price_status,
        "play_through_confidence_multiplier": upstream.get("play_through_confidence_multiplier"),
        "play_through_break_even_concession": upstream.get("play_through_break_even_concession"),
        "play_through_break_even_probability": upstream.get("play_through_break_even_probability"),
        "play_through_price_american": upstream.get("play_through_price_american"),
    }
    row.update(_book_fields("draftkings", context.draftkings))
    row.update(_book_fields("fanduel", context.fanduel))
    row.update(_book_fields("pinnacle", context.pinnacle))
    leaked = OUTCOME_FIELDS.intersection(row)
    if leaked:
        raise RuntimeError(f"outcome fields leaked into candidate table: {sorted(leaked)}")
    return row


def build_candidate_table(
    upstream_rows: Iterable[Mapping[str, Any]],
    contexts: Mapping[str, CandidateOfferContext],
    *,
    allow_authorized_holdout_2025: bool = False,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for upstream in upstream_rows:
        cid = make_candidate_id(upstream["game_id"], upstream["market_type"], upstream["selected_side"])
        if cid in seen:
            raise RuntimeError(f"duplicate candidate identity {cid}")
        seen.add(cid)
        output.append(
            build_candidate_row(
                upstream,
                contexts.get(cid, CandidateOfferContext()),
                allow_authorized_holdout_2025=allow_authorized_holdout_2025,
            )
        )
    output.sort(key=lambda row: row["candidate_id"])
    return output
