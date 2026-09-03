"""Adapter for comparing frozen moneyline states across pending roof scenarios.

This module does not alter Task05F evaluator semantics.  It supplies the exact
OPEN and CLOSED XGBoost probabilities independently to the existing evaluator
and exposes a shared state only when both frozen results are byte-identical.
"""
from __future__ import annotations

from dataclasses import replace
from math import isfinite
from typing import Any

from nfl_edge.value.contracts import (
    GameState,
    MarketAnchor,
    MoneylineV4State,
    NormalizedOffer,
    ReliabilityState,
    as_safe_dict,
)
from nfl_edge.value.evaluators import evaluate_moneyline_v4

_MISSING_EVIDENCE_RESULT: dict[str, Any] = {
    "status": "NOT_EVALUATED_MISSING_EVIDENCE",
    "agreement_status": "NOT_EVALUABLE",
    "open_state": None,
    "closed_state": None,
    "shared_state": None,
}


def _scenario_probability(value: float, name: str) -> float:
    probability = float(value)
    if not isfinite(probability) or not 0.0 <= probability <= 1.0:
        raise ValueError(f"{name} must be a finite probability in [0, 1]")
    return probability


def missing_roof_scenario_evaluation() -> dict[str, Any]:
    """Return the stable no-market-evidence state without inventing a decision."""
    return dict(_MISSING_EVIDENCE_RESULT)


def compare_moneyline_roof_scenarios(
    *,
    game: GameState,
    open_xgb_home: float,
    closed_xgb_home: float,
    offer: NormalizedOffer | None = None,
    evaluator_state: MoneylineV4State | None = None,
    anchor: MarketAnchor | None = None,
    reliability_state: ReliabilityState | None = None,
) -> dict[str, Any]:
    """Compare exact OPEN/CLOSED Task05F moneyline evaluation states.

    Market/evaluator inputs are deliberately optional because the live scorer
    never acquires markets.  With any required input absent, this reports only
    that downstream comparison is not evaluable; callers retain the scenario
    model probabilities separately.
    """
    open_probability = _scenario_probability(open_xgb_home, "open_xgb_home")
    closed_probability = _scenario_probability(closed_xgb_home, "closed_xgb_home")
    if (
        offer is None
        or evaluator_state is None
        or anchor is None
        or reliability_state is None
    ):
        return missing_roof_scenario_evaluation()

    open_result = as_safe_dict(
        evaluate_moneyline_v4(
            replace(game, xgb_home=open_probability),
            offer,
            evaluator_state,
            anchor,
            reliability_state,
        )
    )
    closed_result = as_safe_dict(
        evaluate_moneyline_v4(
            replace(game, xgb_home=closed_probability),
            offer,
            evaluator_state,
            anchor,
            reliability_state,
        )
    )
    if open_result == closed_result:
        return {
            "status": "EVALUATED",
            "agreement_status": "AGREE",
            "open_state": open_result,
            "closed_state": closed_result,
            "shared_state": open_result,
        }
    return {
        "status": "ROOF_SENSITIVE",
        "agreement_status": "ROOF_SENSITIVE",
        "open_state": open_result,
        "closed_state": closed_result,
        "shared_state": None,
    }
