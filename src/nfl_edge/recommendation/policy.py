"""Shared Task05G recommendation helpers only.

This module intentionally contains no selector, risk-profile, bankroll-conversion,
or unit-sizing implementation. Canonical Task05G behavior lives in:

- ``final_selectors_v1.py`` for HHR/Balanced/Value selection;
- ``headline_staking_v1.py`` for headline actionability/staking;
- ``staking_v1.py`` for generic exact-offer units/risk profiles/dollars;
- ``product_policy_v1.py`` for default/game-detail/manual product behavior.

Only genuinely shared exact-offer utilities and the legacy-compatible evaluator
adapter remain here. This fail-closed shape prevents callers from importing a
stale competing ``select_*`` or ``recommended_units`` implementation from the
historically plausible ``nfl_edge.recommendation.policy`` path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from nfl_edge.value.evaluators import evaluate_offer
from nfl_edge.value.play_through import assess_play_through

NO_HIT_RATE_PLAY = "NO_HIT_RATE_PLAY"
NO_BALANCED_PLAY = "NO_BALANCED_PLAY"
NO_VALUE_PLAY = "NO_VALUE_PLAY"

ACTIONABLE_BOOKS = ("draftkings", "fanduel")
BOOK_TIEBREAK = {"draftkings": 0, "fanduel": 1}


@dataclass(frozen=True)
class PolicyEvaluation:
    evaluation: Any
    price_status: str
    recommended_units: float


def _field(row: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return default


def _float(row: Mapping[str, Any], *names: str) -> float | None:
    value = _field(row, *names)
    return None if value is None else float(value)


def _int(row: Mapping[str, Any], *names: str) -> int | None:
    value = _field(row, *names)
    return None if value is None else int(value)


def _candidate_id(row: Mapping[str, Any]) -> str:
    explicit = _field(row, "candidate_id")
    if explicit is not None:
        return str(explicit)
    return "|".join(
        [
            str(_field(row, "game_id", default="")),
            str(_field(row, "market_type", "market", default="")),
            str(_field(row, "selection", "selected_side", "side", default="")),
        ]
    )


def _book_rank(row: Mapping[str, Any]) -> int:
    book = str(_field(row, "actionable_book", "sportsbook", "book", default="")).lower()
    return BOOK_TIEBREAK.get(book, 99)


def _shopping_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Ascending sort key implementing accepted DK/FD shopping semantics."""
    market = str(_field(row, "market_type", "market", default="")).lower()
    side = str(_field(row, "selection", "selected_side", "side", default="")).lower()
    line = _float(row, "actionable_line", "line")
    price = _int(row, "actionable_price_american", "american_odds", "price_american")
    if price is None:
        price = -100000
    if market == "moneyline":
        return (-price, _book_rank(row), _candidate_id(row))
    if line is None:
        return (float("inf"), -price, _book_rank(row), _candidate_id(row))
    if market == "spread":
        return (-line, -price, _book_rank(row), _candidate_id(row))
    if market == "total" and side == "over":
        return (line, -price, _book_rank(row), _candidate_id(row))
    if market == "total" and side == "under":
        return (-line, -price, _book_rank(row), _candidate_id(row))
    raise ValueError(f"unsupported market/side for shopping: {market}/{side}")


def shop_exact_offers(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Return the best exact DK/FD offer for every game/market/selected-side.

    Each input row must already represent an exact evaluated offer. This helper
    never transfers probability or EV from one line/price to another.
    """
    groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        book = str(_field(row, "actionable_book", "sportsbook", "book", default="")).lower()
        if book not in ACTIONABLE_BOOKS:
            continue
        key = (
            str(_field(row, "game_id", default="")),
            str(_field(row, "market_type", "market", default="")).lower(),
            str(_field(row, "selection", "selected_side", "side", default="")).lower(),
        )
        groups.setdefault(key, []).append(row)
    return [sorted(group, key=_shopping_key)[0] for _, group in sorted(groups.items()) if group]


def evaluate_policy_offer(
    game_state: Any,
    normalized_offer: Any,
    evaluator_state: Any,
    market_anchor: Any,
    reliability_state: Any,
) -> PolicyEvaluation:
    """Evaluate one exact offer and delegate unit sizing to canonical staking V1.

    This adapter is retained for compatibility with callers that need a compact
    Task05F evaluation + Play Through + generic unit result. It does not own a
    separate staking policy.
    """
    from nfl_edge.recommendation.staking_v1 import recommended_units

    result = evaluate_offer(
        game_state,
        normalized_offer,
        evaluator_state,
        market_anchor,
        reliability_state,
    )
    play = assess_play_through(
        supported=result.supported,
        strict_expected_value=result.expected_value,
        conditional_nonpush_probability=result.conditional_nonpush_probability,
        current_break_even_probability=result.break_even_probability,
        reliability=result.reliability,
        uncertainty_radius=result.uncertainty,
    )
    row = {
        "supported": result.supported,
        "reliability": result.reliability,
        "price_status": play.status,
        "actionable_probability": result.actionable_probability,
        "expected_value": result.expected_value,
        "uncertainty": result.uncertainty,
    }
    return PolicyEvaluation(result, play.status, recommended_units(row))
