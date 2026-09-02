"""Post-V5 prelaunch successor selector contract.

V5 remains immutable evidence for the frozen V1 product.  This module keeps
HHR and Value exactly on their V1 implementations and replaces only Balanced
with a market-specific protocol:

- Moneyline: short favorites only, -130 through -100, q >= .52.
- Spread: validated Expected-Margin 0-4 candidate provenance, positive model
  cover margin, supported Spread Confidence V3, q >= .50, price >= -130.
- No strict +EV, VALUE/PLAYABLE, or positive model-price-gap eligibility.
- Cross-market ranking uses trustworthy probability after a deterministic
  "juice tax" above 50% break-even, so properly calibrated ~50-51% spreads
  are not automatically dominated by ML favorites solely because the market
  types live on different raw probability scales.

This is a versioned successor; ``final_selectors_v1`` is preserved byte-for-
byte for historical replay and V5 provenance.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from nfl_edge.recommendation.final_selectors_v1 import (
    FamilyTrust,
    TrustObservation,
    ValueSelectorState,
    SPREAD_VALUE_REGION,
    _candidate_id,
    _common_model_offer,
    _finite,
    _market_half_trust,
    _model_q,
    _odds,
    _reliability_rank,
    _tags,
    advance_value_state,
    family_trust,
    select_hit_rate,
    select_value,
)
from nfl_edge.recommendation.policy import NO_BALANCED_PLAY, shop_exact_offers

BALANCED_ML_MIN_Q = 0.52
BALANCED_ML_ODDS = (-130, -100)
BALANCED_SPREAD_MIN_Q = 0.50
BALANCED_SPREAD_ODDS = (-130, 200)
BALANCED_SPREAD_REGION = SPREAD_VALUE_REGION


def _within(row: Mapping[str, Any], bounds: tuple[int, int]) -> bool:
    odds = _odds(row)
    return odds is not None and bounds[0] <= odds <= bounds[1]


def _balanced_eligible(row: Mapping[str, Any]) -> bool:
    if not _common_model_offer(row):
        return False
    q = _model_q(row)
    if q is None:
        return False

    market = str(row.get("market_type", "")).lower()
    if market == "moneyline":
        # Bread-and-butter Balanced ML is intentionally short-favorite only.
        # Plus-money ML belongs to Value; heavier juice belongs to HHR.
        return q >= BALANCED_ML_MIN_Q and _within(row, BALANCED_ML_ODDS)

    if market == "spread":
        cover_margin = _finite(row.get("model_cover_margin_v3"))
        return (
            q >= BALANCED_SPREAD_MIN_Q
            and _within(row, BALANCED_SPREAD_ODDS)
            and BALANCED_SPREAD_REGION in _tags(row)
            and cover_margin is not None
            and cover_margin > 0.0
        )

    return False


def _balanced_utility(row: Mapping[str, Any], trust: float) -> float | None:
    """Probability-first utility with a deterministic juice penalty.

    This is deliberately not an EV gate.  A negative utility remains eligible.
    We simply subtract the portion of book break-even above a 50/50 price so a
    -130 ML favorite and a standard spread can be compared without pretending
    their raw cash probabilities are directly interchangeable.
    """
    break_even = _finite(row.get("break_even_probability"))
    if break_even is None:
        return None
    juice_tax = max(float(break_even) - 0.50, 0.0)
    return float(trust) - juice_tax


def _balanced_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    utility = _finite(row.get("balanced_utility"))
    trust = _finite(row.get("selector_trust"))
    q = _model_q(row)
    return (
        -float(utility if utility is not None else -99.0),
        -float(trust if trust is not None else -99.0),
        -float(q if q is not None else -99.0),
        -_reliability_rank(row),
        -int(_odds(row) or -100000),
        _candidate_id(row),
    )


def select_balanced(rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | str:
    """Balanced V2: trustworthy probability at a genuinely bounded price."""
    candidates: list[dict[str, Any]] = []
    for source in shop_exact_offers(rows):
        row = dict(source)
        if not _balanced_eligible(row):
            continue
        trust = _market_half_trust(row)
        if trust is None:
            continue
        utility = _balanced_utility(row, trust)
        if utility is None:
            continue
        row["selector_trust"] = float(trust)
        row["balanced_utility"] = float(utility)
        row["balanced_protocol_version"] = "BALANCED_PRICE_BOUNDED_V2"
        candidates.append(row)

    if not candidates:
        return NO_BALANCED_PLAY
    return dict(sorted(candidates, key=_balanced_key)[0])


def select_headlines(
    rows: Iterable[Mapping[str, Any]],
    state: ValueSelectorState | None = None,
) -> dict[str, Mapping[str, Any] | str]:
    """Successor headline surface: V1 HHR/Value plus Balanced V2."""
    material = list(rows)
    return {
        "hit_rate": select_hit_rate(material),
        "balanced": select_balanced(material),
        "value": select_value(material, state),
    }


__all__ = [
    "BALANCED_ML_MIN_Q",
    "BALANCED_ML_ODDS",
    "BALANCED_SPREAD_MIN_Q",
    "BALANCED_SPREAD_ODDS",
    "BALANCED_SPREAD_REGION",
    "FamilyTrust",
    "TrustObservation",
    "ValueSelectorState",
    "advance_value_state",
    "family_trust",
    "select_balanced",
    "select_headlines",
    "select_hit_rate",
    "select_value",
]
