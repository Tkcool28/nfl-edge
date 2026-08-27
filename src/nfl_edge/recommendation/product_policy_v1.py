"""Task05G default/game-detail/manual product policy V1.

This layer is downstream of the frozen Task05F evaluators, final three weekly
headline selectors, and canonical staking_v1. It defines how a user-selected
market outside the three weekly headline cards is evaluated and presented.

Product contract:
- all non-headline/game-detail/manual wagers default to the Balanced philosophy;
- manual input is source-agnostic and must classify identically to an otherwise
  identical stored DK/FD exact offer;
- current actionable recommendation uses the primary verb ``BET``;
- current non-actionable recommendation uses the primary verdict ``NO``;
- when current price is outside the actionable corridor, expose the first same-
  line American price where it becomes actionable as ``BET at ... or better``;
- when current price is actionable, expose the reduced-stake extension as
  ``Playable through ...``;
- line changes for spreads/totals must be supplied/evaluated as genuinely new
  exact offers. No synthetic line conversion may approve action.

HHR and Value weekly headline price-extension semantics are intentionally not
implemented here: HHR uses ``Value at`` and the Value headline may only extend
while remaining strict +EV. This module owns the default/rest-of-app path.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from nfl_edge.recommendation.staking_v1 import dollar_stake, recommended_units, risk_profile
from nfl_edge.value.contracts import NormalizedOffer
from nfl_edge.value.evaluators import evaluate_offer
from nfl_edge.value.play_through import assess_play_through

DEFAULT_NON_HEADLINE_POLICY = "BALANCED"
PRIMARY_BET = "BET"
PRIMARY_NO = "NO"
SECONDARY_PLAYABLE_THROUGH = "PLAYABLE_THROUGH"
SECONDARY_BET_AT = "BET_AT"


@dataclass(frozen=True)
class DefaultOfferDecision:
    policy: str
    source: str
    current_price_american: int
    current_line: float | None
    current_status: str
    primary_action: str
    current_units: float
    current_stake: float
    secondary_action: str | None
    secondary_price_american: int | None
    secondary_line: float | None
    secondary_units: float
    secondary_stake: float
    reliability: str
    strict_value: bool
    expected_value: float | None
    actionable_probability: float | None
    fair_price_american: int | None


def _staking_row(result: Any, status: str) -> dict[str, Any]:
    return {
        "supported": bool(result.supported),
        "reliability": result.reliability,
        "price_status": status,
        "actionable_probability": result.actionable_probability,
        "expected_value": result.expected_value,
        "uncertainty": result.uncertainty,
    }


def _evaluate_exact(
    game_state: Any,
    offer: NormalizedOffer,
    evaluator_state: Any,
    market_anchor: Any,
    reliability_state: Any,
):
    result = evaluate_offer(
        game_state,
        offer,
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
    units = recommended_units(_staking_row(result, play.status))
    return result, play, units


def evaluate_default_market_offer(
    *,
    game_state: Any,
    offer: NormalizedOffer,
    evaluator_state: Any,
    market_anchor: Any,
    reliability_state: Any,
    bankroll: float,
    profile: str,
) -> DefaultOfferDecision:
    """Evaluate one game-detail/default/manual exact offer.

    ``offer.source`` never changes methodology. A manually typed exact line and
    price therefore uses the same evaluator and staking logic as a stored book
    offer. The caller may retain ``source='manual'`` for provenance/UI display.

    For the same line, the frozen Play Through boundary gives the first/worst
    American price inside the Balanced actionability corridor. We verify that
    boundary by passing an exact offer at that price back through Task05F before
    exposing a stake. For a different spread/total line the caller must invoke
    this function again with that exact line; this function never synthetically
    converts line movement.
    """

    selected_profile = risk_profile(profile)
    result, play, units = _evaluate_exact(
        game_state,
        offer,
        evaluator_state,
        market_anchor,
        reliability_state,
    )
    current_stake = dollar_stake(bankroll, selected_profile, units)
    primary = PRIMARY_BET if units > 0.0 else PRIMARY_NO

    secondary_action: str | None = None
    secondary_price: int | None = None
    secondary_line: float | None = None
    secondary_units = 0.0
    secondary_stake = 0.0

    boundary = play.play_through_price_american
    if result.supported and boundary is not None and result.reliability in {"HIGH", "MEDIUM"}:
        boundary_offer = replace(
            offer,
            price_american=int(boundary),
            source=offer.source,
        )
        boundary_result, boundary_play, boundary_units = _evaluate_exact(
            game_state,
            boundary_offer,
            evaluator_state,
            market_anchor,
            reliability_state,
        )
        boundary_stake = dollar_stake(bankroll, selected_profile, boundary_units)

        if units > 0.0:
            # Current offer already qualifies. Only expose a real extension when
            # the threshold is worse than the current American price and the
            # boundary itself remains actionable under exact re-evaluation.
            if (
                int(boundary) < int(offer.price_american)
                and boundary_units > 0.0
                and boundary_play.status in {"VALUE", "PLAYABLE"}
            ):
                secondary_action = SECONDARY_PLAYABLE_THROUGH
                secondary_price = int(boundary)
                secondary_line = offer.line
                secondary_units = float(boundary_units)
                secondary_stake = float(boundary_stake)
        else:
            # Current offer is outside the corridor. Expose the first same-line
            # price where a positive stake becomes valid, using the clear
            # product wording ``NO at X`` / ``BET at Y or better``.
            if (
                int(boundary) > int(offer.price_american)
                and boundary_units > 0.0
                and boundary_play.status in {"VALUE", "PLAYABLE"}
            ):
                secondary_action = SECONDARY_BET_AT
                secondary_price = int(boundary)
                secondary_line = offer.line
                secondary_units = float(boundary_units)
                secondary_stake = float(boundary_stake)

    return DefaultOfferDecision(
        policy=DEFAULT_NON_HEADLINE_POLICY,
        source=str(offer.source),
        current_price_american=int(offer.price_american),
        current_line=offer.line,
        current_status=str(play.status),
        primary_action=primary,
        current_units=float(units),
        current_stake=float(current_stake),
        secondary_action=secondary_action,
        secondary_price_american=secondary_price,
        secondary_line=secondary_line,
        secondary_units=float(secondary_units),
        secondary_stake=float(secondary_stake),
        reliability=str(result.reliability),
        strict_value=bool(result.strict_positive_value),
        expected_value=None if result.expected_value is None else float(result.expected_value),
        actionable_probability=None if result.actionable_probability is None else float(result.actionable_probability),
        fair_price_american=result.fair_price_american,
    )
