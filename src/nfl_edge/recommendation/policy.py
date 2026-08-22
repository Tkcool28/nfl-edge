"""Deterministic Task05G selectors, unit sizing, and product-policy adapters.

This module is downstream of the frozen Task05F evaluators.  It deliberately
keeps football probability, evaluator reliability, and exact-offer value as
separate fields and never retrains or modifies an evaluator.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Iterable, Mapping, Sequence

from nfl_edge.value.evaluators import evaluate_offer
from nfl_edge.value.play_through import assess_play_through

NO_HIT_RATE_PLAY = "NO_HIT_RATE_PLAY"
NO_BALANCED_PLAY = "NO_BALANCED_PLAY"
NO_VALUE_PLAY = "NO_VALUE_PLAY"

ACTIONABLE_BOOKS = ("draftkings", "fanduel")
BOOK_TIEBREAK = {"draftkings": 0, "fanduel": 1}
ALLOWED_RELIABILITY = frozenset({"HIGH", "MEDIUM"})

UNIT_LADDER = (0.0, 0.5, 0.75, 1.0, 1.25, 1.5)
PER_WAGER_BANKROLL_CAP_PCT = 0.025
SLATE_BANKROLL_CAP_PCT = 0.10
MINIMUM_STAKE_DOLLARS = 0.50


@dataclass(frozen=True)
class RiskProfile:
    name: str
    unit_bankroll_pct: float


RISK_PROFILES = (
    RiskProfile("Cautious", 0.0050),
    RiskProfile("Steady", 0.0075),
    RiskProfile("Balanced", 0.0100),
    RiskProfile("Bold", 0.0125),
    RiskProfile("High Gear", 0.0150),
)
RISK_PROFILE_BY_NAME = {profile.name: profile for profile in RISK_PROFILES}


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


def _status(row: Mapping[str, Any]) -> str:
    return str(_field(row, "price_status", default="UNSUPPORTED")).upper()


def _reliability(row: Mapping[str, Any]) -> str:
    return str(_field(row, "reliability", default="UNSUPPORTED")).upper()


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


def _offer_identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(_field(row, "game_id", default="")),
        str(_field(row, "market_type", "market", default="")).lower(),
        str(_field(row, "selection", "selected_side", "side", default="")).lower(),
        str(_field(row, "actionable_book", "sportsbook", "book", default="")).lower(),
        _field(row, "actionable_line", "line"),
        _int(row, "actionable_price_american", "american_odds", "price_american"),
    )


def _common_eligible(row: Mapping[str, Any]) -> bool:
    if not bool(_field(row, "supported", default=False)):
        return False
    if _reliability(row) not in ALLOWED_RELIABILITY:
        return False
    if _status(row) in {"PASS", "UNSUPPORTED"}:
        return False
    book = str(_field(row, "actionable_book", "sportsbook", "book", default="")).lower()
    return book in ACTIONABLE_BOOKS


def _odds_in(row: Mapping[str, Any], minimum: int, maximum: int) -> bool:
    odds = _int(row, "actionable_price_american", "american_odds", "price_american")
    return odds is not None and minimum <= odds <= maximum


def _reliability_rank(row: Mapping[str, Any]) -> int:
    return {"HIGH": 2, "MEDIUM": 1}.get(_reliability(row), 0)


def _status_rank(row: Mapping[str, Any]) -> int:
    return {"VALUE": 2, "PLAYABLE": 1}.get(_status(row), 0)


def _safe_sort_number(value: float | None) -> float:
    return float("-inf") if value is None else float(value)


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
        # Larger selected-side line is always better: +3 > +2.5 and -2.5 > -3.
        return (-line, -price, _book_rank(row), _candidate_id(row))
    if market == "total" and side == "over":
        return (line, -price, _book_rank(row), _candidate_id(row))
    if market == "total" and side == "under":
        return (-line, -price, _book_rank(row), _candidate_id(row))
    raise ValueError(f"unsupported market/side for shopping: {market}/{side}")


def shop_exact_offers(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Return the best exact DK/FD offer for every game/market/selected-side.

    Each input row must already represent an exact evaluated offer.  This
    function never transfers probability or EV from one line/price to another.
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
    output = [sorted(group, key=_shopping_key)[0] for _, group in sorted(groups.items()) if group]
    return output


def _hit_rate_eligible(row: Mapping[str, Any]) -> bool:
    q = _float(row, "actionable_probability")
    return (
        _common_eligible(row)
        and _status(row) in {"VALUE", "PLAYABLE"}
        and q is not None
        and q >= 0.55
        and _odds_in(row, -300, 200)
    )


def _balanced_eligible(row: Mapping[str, Any]) -> bool:
    q = _float(row, "actionable_probability")
    ev = _float(row, "expected_value")
    return (
        _common_eligible(row)
        and _status(row) in {"VALUE", "PLAYABLE"}
        and q is not None
        and q >= 0.50
        and ev is not None
        and ev >= -0.03
        and _odds_in(row, -220, 200)
    )


def _value_eligible(row: Mapping[str, Any]) -> bool:
    q = _float(row, "actionable_probability")
    ev = _float(row, "expected_value")
    support_n = _int(row, "support_n")
    support_distance = _float(row, "support_distance")
    uncertainty = _float(row, "uncertainty")
    return (
        _common_eligible(row)
        and _status(row) == "VALUE"
        and q is not None
        and q >= 0.35
        and ev is not None
        and ev >= 0.02
        and support_n is not None
        and support_n >= 256
        and support_distance is not None
        and support_distance <= 0.05
        and uncertainty is not None
        and uncertainty <= 0.045
        and _odds_in(row, -180, 250)
    )


def _select(rows: Sequence[Mapping[str, Any]], eligible, key, no_play: str) -> Mapping[str, Any] | str:
    candidates = [row for row in rows if eligible(row)]
    if not candidates:
        return no_play
    return sorted(candidates, key=key)[0]


def select_hit_rate(rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | str:
    shopped = shop_exact_offers(rows)
    return _select(
        shopped,
        _hit_rate_eligible,
        lambda row: (
            -_safe_sort_number(_float(row, "actionable_probability")),
            -_reliability_rank(row),
            -_status_rank(row),
            -_safe_sort_number(_float(row, "expected_value")),
            -(_int(row, "actionable_price_american", "american_odds", "price_american") or -100000),
            _candidate_id(row),
        ),
        NO_HIT_RATE_PLAY,
    )


def select_balanced(rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | str:
    shopped = shop_exact_offers(rows)
    return _select(
        shopped,
        _balanced_eligible,
        lambda row: (
            -_status_rank(row),
            -_reliability_rank(row),
            -_safe_sort_number(_float(row, "expected_value")),
            -_safe_sort_number(_float(row, "actionable_probability")),
            -_safe_sort_number(_float(row, "evaluated_edge_probability")),
            _candidate_id(row),
        ),
        NO_BALANCED_PLAY,
    )


def select_value(rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | str:
    shopped = shop_exact_offers(rows)
    return _select(
        shopped,
        _value_eligible,
        lambda row: (
            -_safe_sort_number(_float(row, "expected_value")),
            -_safe_sort_number(_float(row, "evaluated_edge_probability")),
            -_reliability_rank(row),
            -_safe_sort_number(_float(row, "actionable_probability")),
            _candidate_id(row),
        ),
        NO_VALUE_PLAY,
    )


def select_headlines(rows: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any] | str]:
    material = list(rows)
    return {
        "hit_rate": select_hit_rate(material),
        "balanced": select_balanced(material),
        "value": select_value(material),
    }


def recommended_units(row: Mapping[str, Any]) -> float:
    """Assign a discrete, auditable unit recommendation to one exact offer."""
    if not bool(_field(row, "supported", default=False)):
        return 0.0
    reliability = _reliability(row)
    if reliability not in ALLOWED_RELIABILITY:
        return 0.0
    status = _status(row)
    q = _float(row, "actionable_probability")
    ev = _float(row, "expected_value")
    uncertainty = _float(row, "uncertainty")
    if status in {"UNSUPPORTED", "PASS", "LEAN"} or q is None or ev is None:
        return 0.0
    if status == "PLAYABLE":
        return 0.75 if reliability == "HIGH" and q >= 0.55 else 0.5
    if status != "VALUE" or ev <= 0.0:
        return 0.0
    if reliability == "HIGH" and ev >= 0.06 and q >= 0.55 and uncertainty is not None and uncertainty <= 0.025:
        return 1.5
    if reliability == "HIGH" and ev >= 0.04 and q >= 0.52:
        return 1.25
    if ev >= 0.025 and q >= 0.50:
        return 1.0
    return 0.75


def dollar_stake(bankroll: float, profile: RiskProfile | str, units: float) -> float:
    """Convert units to dollars without ever rounding above the wager cap."""
    bankroll_d = Decimal(str(bankroll))
    if bankroll_d < 0:
        raise ValueError("bankroll must be non-negative")
    if float(units) not in UNIT_LADDER:
        raise ValueError(f"units must be on frozen ladder {UNIT_LADDER}")
    selected = RISK_PROFILE_BY_NAME[profile] if isinstance(profile, str) else profile
    raw = bankroll_d * Decimal(str(selected.unit_bankroll_pct)) * Decimal(str(float(units)))
    cap = bankroll_d * Decimal(str(PER_WAGER_BANKROLL_CAP_PCT))
    bounded = min(raw, cap)
    quantum = Decimal("0.50")
    rounded = (bounded / quantum).to_integral_value(rounding=ROUND_FLOOR) * quantum
    if rounded < Decimal(str(MINIMUM_STAKE_DOLLARS)):
        return 0.0
    return float(rounded)


def cap_slate_stakes(bankroll: float, proposed: Sequence[tuple[str, float]]) -> dict[str, float]:
    """Apply the frozen 10% slate cap in stable input order.

    ``proposed`` contains (offer_id, already-rounded-dollar-stake). Duplicate
    offer IDs are counted once so overlapping headline roles never multiply risk.
    """
    limit = max(0.0, float(bankroll)) * SLATE_BANKROLL_CAP_PCT
    remaining = limit
    output: dict[str, float] = {}
    for offer_id, stake in proposed:
        if offer_id in output:
            continue
        allowed = min(max(0.0, float(stake)), remaining)
        allowed = float((Decimal(str(allowed)) / Decimal("0.50")).to_integral_value(rounding=ROUND_FLOOR) * Decimal("0.50"))
        output[str(offer_id)] = allowed
        remaining = max(0.0, remaining - allowed)
    return output


def evaluate_policy_offer(
    game_state: Any,
    normalized_offer: Any,
    evaluator_state: Any,
    market_anchor: Any,
    reliability_state: Any,
) -> PolicyEvaluation:
    """Evaluate an exact stored/manual/full-board offer then apply Task05G policy.

    No inferred line/price conversion is permitted: callers must supply the exact
    offer they want approved.  Task05F ``evaluate_offer`` is the sole evaluator.
    """
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
