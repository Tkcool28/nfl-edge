"""Authorized holdout-only seam for the frozen Task05F evaluator.

Task05F intentionally seals season 2025 for ordinary development/public calls.
The accepted evaluator mathematics contain no season-specific term; the season
field is used only by that firewall. This adapter uses the canonical evaluator
on the real 2025 GameState and opens the firewall only through the explicit,
fail-closed authorized-holdout keyword.

The normal evaluator path remains sealed. No outcome field exists on GameState.
"""
from __future__ import annotations

from nfl_edge.value.contracts import (
    EvaluationResult,
    GameState,
    MarketAnchor,
    MoneylineV4State,
    NormalizedOffer,
    PointV3State,
    ReliabilityState,
)
from nfl_edge.value.evaluators import evaluate_offer

from .one_shot_2025 import HoldoutOneShotError

HOLDOUT_SEASON = 2025


def evaluate_authorized_holdout_offer(
    game_state: GameState,
    normalized_offer: NormalizedOffer,
    evaluator_state: MoneylineV4State | PointV3State,
    market_anchor: MarketAnchor,
    reliability_state: ReliabilityState,
) -> EvaluationResult:
    """Reuse exact Task05F math for one already-authorized true-2025 pregame state."""
    if int(game_state.season) != HOLDOUT_SEASON:
        raise HoldoutOneShotError(
            f"holdout evaluator seam requires season {HOLDOUT_SEASON}: {game_state.season}"
        )
    return evaluate_offer(
        game_state,
        normalized_offer,
        evaluator_state,
        market_anchor,
        reliability_state,
        allow_authorized_holdout_2025=True,
    )


def prove_shadow_parity(
    development_game_state: GameState,
    normalized_offer: NormalizedOffer,
    evaluator_state: MoneylineV4State | PointV3State,
    market_anchor: MarketAnchor,
    reliability_state: ReliabilityState,
) -> None:
    """Compatibility proof: enabling the authorization seam does not alter DEV output.

    The function name is retained for existing callers/tests from the former
    shadow-season implementation. No season replacement occurs here.
    """
    if int(development_game_state.season) == HOLDOUT_SEASON:
        raise HoldoutOneShotError("parity proof requires exposed development input")
    direct = evaluate_offer(
        development_game_state,
        normalized_offer,
        evaluator_state,
        market_anchor,
        reliability_state,
    )
    authorized_path = evaluate_offer(
        development_game_state,
        normalized_offer,
        evaluator_state,
        market_anchor,
        reliability_state,
        allow_authorized_holdout_2025=True,
    )
    if direct != authorized_path:
        raise HoldoutOneShotError("Task05F authorization seam unexpectedly changes evaluator output")
