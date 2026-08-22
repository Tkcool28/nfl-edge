"""Common Task05F evaluated-wager candidate table.

This module is a downstream interface layer only. It standardizes the accepted
Play Through board for the game explorer and deterministic selectors while
keeping historical outcomes out of the production-facing candidate rows.

Contract: config/task05f_candidate_table_v1.yaml
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping


SEALED_SEASONS = {2025}
OUTCOME_FIELDS = frozenset({"settlement", "realized_profit", "home_score", "away_score"})

FOOTBALL_MODEL = {
    "moneyline": ("QB_ELO_XGB_EXACT_AVG", "probability_home_or_away_orientation"),
    "spread": ("EXPECTED_MARGIN_V1_STABLE", "home_margin_points"),
    "total": ("RIDGE_TOTALS_R4", "total_points"),
}

PRESERVED_FIELDS = (
    "p_win",
    "p_push",
    "p_loss",
    "actionable_probability",
    "fair_price_american",
    "break_even_probability",
    "evaluated_edge_probability",
    "expected_value",
    "strict_positive_value",
    "supported",
    "support_n",
    "reason",
    "reliability",
    "base_reliability",
    "uncertainty",
    "uncertainty_support_n",
    "uncertainty_block_count",
    "candidate_uncertainty_tier",
    "staking_probability",
    "staking_expected_value",
    "price_status",
    "play_through_confidence_multiplier",
    "play_through_break_even_concession",
    "play_through_break_even_probability",
    "play_through_price_american",
)

DIAGNOSTIC_FIELDS = (
    "benchmark_probability",
    "raw_pinnacle_no_vig_probability",
    "calibrated_market_probability",
    "calibrated_model_output",
    "calibration_market_intercept",
    "calibration_market_slope",
    "calibration_model_weight",
    "calibration_weight",
    "calibration_beta",
    "market_scale",
    "staking_anchor_probability",
    "staking_p_win",
    "staking_p_push",
    "staking_p_loss",
    "staking_edge_probability",
)


@dataclass(frozen=True)
class BookOfferContext:
    """Display-only offer context for one book and selected wager side."""

    line: float | None
    price_american: int


@dataclass(frozen=True)
class CandidateOfferContext:
    draftkings: BookOfferContext | None = None
    fanduel: BookOfferContext | None = None
    pinnacle: BookOfferContext | None = None


def _identity_value(value: Any) -> str:
    if value is None:
        return "~"
    if isinstance(value, float):
        return format(value, ".12g")
    return str(value)


def make_candidate_id(game_id: str, market_type: str, selected_side: str) -> str:
    """Stable wager identity that intentionally ignores current offer details."""
    game = str(game_id).strip()
    market = str(market_type).strip().lower()
    side = str(selected_side).strip().lower()
    if not game:
        raise ValueError("candidate game_id cannot be empty")
    if market not in FOOTBALL_MODEL:
        raise ValueError(f"unknown candidate market_type {market}")
    valid_sides = {
        "moneyline": {"home", "away"},
        "spread": {"home", "away"},
        "total": {"over", "under"},
    }[market]
    if side not in valid_sides:
        raise ValueError(f"invalid {market} selected_side {side}")
    return f"{game}|{market}|{side}"


def make_offer_id(
    candidate_id: str,
    actionable_book: str,
    actionable_line: float | None,
    actionable_price_american: int,
    market_snapshot_timestamp: str,
) -> str:
    """Deterministic dynamic identifier for the currently selected offer."""
    payload = {
        "candidate_id": str(candidate_id),
        "book": str(actionable_book).strip().lower(),
        "line": _identity_value(actionable_line),
        "price": int(actionable_price_american),
        "snapshot": str(market_snapshot_timestamp),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _book_fields(prefix: str, offer: BookOfferContext | None) -> dict[str, Any]:
    return {
        f"{prefix}_line": None if offer is None else offer.line,
        f"{prefix}_price_american": None if offer is None else int(offer.price_american),
    }


def build_candidate_row(
    upstream: Mapping[str, Any],
    offer_context: CandidateOfferContext | None = None,
) -> dict[str, Any]:
    """Standardize one accepted Phase-G board row without changing its decisions."""
    season = int(upstream["season"])
    if season in SEALED_SEASONS:
        raise RuntimeError(f"sealed season {season} cannot enter candidate table")

    market = str(upstream["market_type"]).lower()
    side = str(upstream["selected_side"]).lower()
    candidate_id = make_candidate_id(str(upstream["game_id"]), market, side)
    model_name, output_unit = FOOTBALL_MODEL[market]

    actionable_book = str(upstream["sportsbook"]).lower()
    actionable_line = upstream.get("line")
    actionable_price = int(upstream["american_odds"])
    snapshot = str(upstream.get("market_snapshot_timestamp") or "")
    offer_id = make_offer_id(
        candidate_id,
        actionable_book,
        None if actionable_line is None else float(actionable_line),
        actionable_price,
        snapshot,
    )

    context = offer_context or CandidateOfferContext()
    row: dict[str, Any] = {
        "candidate_id": candidate_id,
        "offer_id": offer_id,
        "game_id": str(upstream["game_id"]),
        "season": season,
        "week": upstream.get("week"),
        "block": upstream.get("block"),
        "market_type": market,
        "selection": side,
        "football_model_name": model_name,
        "raw_football_output": upstream.get("raw_model_output"),
        "raw_football_output_unit": output_unit,
        "model_market_disagreement": upstream.get("model_market_disagreement"),
        "pinnacle_no_vig_probability": upstream.get("pinnacle_no_vig_probability"),
        "pinnacle_anchor_probability": upstream.get("pinnacle_anchor_probability"),
        "pinnacle_anchor_threshold": upstream.get("pinnacle_anchor_threshold"),
        "actionable_book": actionable_book,
        "actionable_line": None if actionable_line is None else float(actionable_line),
        "actionable_price_american": actionable_price,
        "actionable_decimal_price": upstream.get("decimal_odds"),
        "market_snapshot_timestamp": snapshot,
    }
    row.update(_book_fields("draftkings", context.draftkings))
    row.update(_book_fields("fanduel", context.fanduel))
    row.update(_book_fields("pinnacle", context.pinnacle))

    for field in PRESERVED_FIELDS:
        row[field] = upstream.get(field)
    for field in DIAGNOSTIC_FIELDS:
        row[field] = upstream.get(field)

    leaked = OUTCOME_FIELDS.intersection(row)
    if leaked:
        raise RuntimeError(f"outcome fields leaked into candidate table: {sorted(leaked)}")
    return row


def build_candidate_table(
    upstream_rows: Iterable[Mapping[str, Any]],
    offer_context_by_candidate: Mapping[str, CandidateOfferContext] | None = None,
) -> list[dict[str, Any]]:
    """Build deterministic one-row-per-wager table, retaining unsupported rows."""
    contexts = offer_context_by_candidate or {}
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for upstream in upstream_rows:
        cid = make_candidate_id(
            str(upstream["game_id"]),
            str(upstream["market_type"]),
            str(upstream["selected_side"]),
        )
        if cid in seen:
            raise RuntimeError(f"duplicate candidate identity {cid}")
        seen.add(cid)
        output.append(build_candidate_row(upstream, contexts.get(cid)))
    output.sort(key=lambda row: row["candidate_id"])
    return output


def build_historical_outcome_sidecar(
    upstream_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build outcome-only diagnostic sidecar; never pass this to selectors."""
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for upstream in upstream_rows:
        season = int(upstream["season"])
        if season in SEALED_SEASONS:
            raise RuntimeError(f"sealed season {season} cannot enter outcome sidecar")
        cid = make_candidate_id(
            str(upstream["game_id"]),
            str(upstream["market_type"]),
            str(upstream["selected_side"]),
        )
        if cid in seen:
            raise RuntimeError(f"duplicate outcome identity {cid}")
        seen.add(cid)
        output.append(
            {
                "candidate_id": cid,
                "game_id": str(upstream["game_id"]),
                "season": season,
                "week": upstream.get("week"),
                "market_type": str(upstream["market_type"]).lower(),
                "selection": str(upstream["selected_side"]).lower(),
                "settlement": upstream.get("settlement"),
                "realized_profit": upstream.get("realized_profit"),
            }
        )
    output.sort(key=lambda row: row["candidate_id"])
    return output


def assert_preserved_fields(
    upstream_rows: Iterable[Mapping[str, Any]],
    candidate_rows: Iterable[Mapping[str, Any]],
) -> None:
    """Hard gate that the interface layer did not alter upstream decision fields."""
    source = {
        make_candidate_id(str(row["game_id"]), str(row["market_type"]), str(row["selected_side"])): row
        for row in upstream_rows
    }
    candidates = {str(row["candidate_id"]): row for row in candidate_rows}
    if source.keys() != candidates.keys():
        raise RuntimeError("candidate identity set differs from upstream board")
    for cid, upstream in source.items():
        candidate = candidates[cid]
        for field in PRESERVED_FIELDS:
            if upstream.get(field) != candidate.get(field):
                raise RuntimeError(f"candidate table modified {field} for {cid}")
