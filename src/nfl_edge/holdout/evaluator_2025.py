"""Authorized holdout-only seam for the frozen Task05F evaluator.

Task05F intentionally hard-seals season 2025 in its public evaluator. The
accepted evaluator mathematics contain no season-specific term; the season
field is used only by that firewall. This adapter preserves the firewall and
reuses the canonical evaluator unchanged by evaluating an otherwise identical
shadow GameState with a development-season sentinel after asserting the real
input is exactly the authorized 2025 holdout.

Parity tests must prove that shadowing the season field changes no result on
exposed development inputs. No outcome field exists on GameState.
"""
from __future__ import annotations

from dataclasses import replace

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
SHADOW_SEASON = 2024


def evaluate_authorized_holdout_offer(
    game_state: GameState,
    normalized_offer: NormalizedOffer,
    evaluator_state: MoneylineV4State | PointV3State,
    market_anchor: MarketAnchor,
    reliability_state: ReliabilityState,
) -> EvaluationResult:
    """Reuse exact Task05F math for one already-authorized 2025 pregame state."""
    if int(game_state.season) != HOLDOUT_SEASON:
        raise HoldoutOneShotError(
            f"holdout evaluator seam requires season {HOLDOUT_SEASON}: {game_state.season}"
        )
    shadow = replace(game_state, season=SHADOW_SEASON)
    return evaluate_offer(
        shadow,
        normalized_offer,
        evaluator_state,
        market_anchor,
        reliability_state,
    )


def prove_shadow_parity(
    development_game_state: GameState,
    normalized_offer: NormalizedOffer,
    evaluator_state: MoneylineV4State | PointV3State,
    market_anchor: MarketAnchor,
    reliability_state: ReliabilityState,
) -> None:
    """Assert the holdout shadow transform is identity on evaluator output."""
    if int(development_game_state.season) == HOLDOUT_SEASON:
        raise HoldoutOneShotError("parity proof requires exposed development input")
    direct = evaluate_offer(
        development_game_state,
        normalized_offer,
        evaluator_state,
        market_anchor,
        reliability_state,
    )
    shadow = evaluate_offer(
        replace(development_game_state, season=SHADOW_SEASON),
        normalized_offer,
        evaluator_state,
        market_anchor,
        reliability_state,
    )
    if direct != shadow:
        raise HoldoutOneShotError("Task05F evaluator unexpectedly depends on season identity")
