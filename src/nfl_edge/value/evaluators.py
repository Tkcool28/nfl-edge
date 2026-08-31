"""Production evaluator interface for accepted Task05F families.

This is the interface the app/game explorer can call for a stored or manual
NormalizedOffer. It contains no historical outcomes, selector policy, bankroll,
or unit sizing.
"""
from __future__ import annotations

from .accepted_calibration import (
    MlV4Fit,
    calibrated_market_probability,
    conditional_above_probability,
    final_ml_home_probability,
    market_implied_mean,
)
from .contracts import (
    EvaluationResult,
    GameState,
    MarketAnchor,
    MoneylineV4State,
    NormalizedOffer,
    PointV3State,
    ReliabilityState,
    SEALED_SEASONS,
)
from .market_math import break_even_probability
from .reliability import (
    conservative_staking_probability,
    make_evidence,
    overall_support_distance,
    reliability_tier,
    unsupported_reason,
)
from .wager_economics import (
    OutcomeProbabilities,
    empirical_spread_probabilities,
    empirical_total_probabilities,
    expected_value_three_way,
    fair_american_three_way,
    line_allows_push,
    moneyline_outcome_probabilities,
)

AUTHORIZED_HOLDOUT_SEASON = 2025


def _assert_season_allowed(
    game: GameState,
    *,
    allow_authorized_holdout_2025: bool = False,
) -> None:
    season = int(game.season)
    if season not in SEALED_SEASONS:
        return
    if allow_authorized_holdout_2025 and season == AUTHORIZED_HOLDOUT_SEASON:
        return
    raise RuntimeError(f"sealed season {game.season}")


def _side_probability(home_probability: float, side: str) -> float:
    return float(home_probability) if side.lower() == "home" else 1.0 - float(home_probability)


def _unsupported(version: str, support_n: int, reason: str, uncertainty: float | None = None) -> EvaluationResult:
    return EvaluationResult(
        p_win=None,
        p_push=None,
        p_loss=None,
        actionable_probability=None,
        conditional_nonpush_probability=None,
        staking_probability=None,
        staking_anchor_probability=None,
        fair_price_american=None,
        expected_value=None,
        strict_positive_value=False,
        break_even_probability=None,
        evaluated_edge_probability=None,
        staking_edge_probability=None,
        reliability="UNSUPPORTED",
        uncertainty=uncertainty,
        support_n=int(support_n),
        support_distance=None,
        evaluator_version=version,
        supported=False,
        reason=reason,
        evidence={},
    )


def _finish(
    *,
    prob: OutcomeProbabilities,
    offer: NormalizedOffer,
    evaluator_version: str,
    support_n: int,
    support_distance: float,
    constituent_disagreement: float,
    reliability_state: ReliabilityState,
    staking_anchor_probability: float,
    evidence: dict,
) -> EvaluationResult:
    rel_evidence = make_evidence(
        support_n,
        support_distance,
        constituent_disagreement,
        reliability_state,
    )
    reliability = reliability_tier(rel_evidence)
    reason = unsupported_reason(rel_evidence)
    if reliability == "UNSUPPORTED":
        return EvaluationResult(
            p_win=None,
            p_push=None,
            p_loss=None,
            actionable_probability=None,
            conditional_nonpush_probability=None,
            staking_probability=None,
            staking_anchor_probability=None,
            fair_price_american=None,
            expected_value=None,
            strict_positive_value=False,
            break_even_probability=None,
            evaluated_edge_probability=None,
            staking_edge_probability=None,
            reliability="UNSUPPORTED",
            uncertainty=reliability_state.radius,
            support_n=int(support_n),
            support_distance=float(support_distance),
            evaluator_version=evaluator_version,
            supported=False,
            reason=reason or "unsupported",
            evidence=evidence,
        )

    q_eval = prob.conditional_nonpush_probability
    q_stake = conservative_staking_probability(
        q_eval,
        float(staking_anchor_probability),
        reliability,
        reliability_state.radius,
    )
    ev = expected_value_three_way(prob, offer.price_american)
    be = break_even_probability(offer.price_american)
    return EvaluationResult(
        p_win=float(prob.p_win),
        p_push=float(prob.p_push),
        p_loss=float(prob.p_loss),
        actionable_probability=float(prob.p_win),
        conditional_nonpush_probability=float(q_eval),
        staking_probability=float(q_stake),
        staking_anchor_probability=float(staking_anchor_probability),
        fair_price_american=int(fair_american_three_way(prob)),
        expected_value=float(ev),
        strict_positive_value=bool(ev > 0.0),
        break_even_probability=float(be),
        evaluated_edge_probability=float(q_eval - be),
        staking_edge_probability=float(q_stake - be),
        reliability=reliability,
        uncertainty=reliability_state.radius,
        support_n=int(support_n),
        support_distance=float(support_distance),
        evaluator_version=evaluator_version,
        supported=True,
        reason=None,
        evidence=evidence,
    )


def evaluate_moneyline_v4(
    game: GameState,
    offer: NormalizedOffer,
    state: MoneylineV4State,
    anchor: MarketAnchor,
    reliability_state: ReliabilityState,
    *,
    allow_authorized_holdout_2025: bool = False,
) -> EvaluationResult:
    _assert_season_allowed(
        game,
        allow_authorized_holdout_2025=allow_authorized_holdout_2025,
    )
    if offer.market_type != "moneyline" or anchor.market_type != "moneyline":
        raise ValueError("moneyline V4 requires moneyline offer and anchor")
    if anchor.home_no_vig_probability is None:
        return _unsupported(state.version, state.training_n, "missing_pinnacle_benchmark", reliability_state.radius)
    if game.qbelo_home is None or game.xgb_home is None:
        return _unsupported(state.version, state.training_n, "exact_avg_requires_both_models", reliability_state.radius)

    fit = MlV4Fit(
        state.market_intercept,
        state.market_slope,
        state.model_weight,
        state.training_n,
        True,
        None,
    )
    raw_model_home = (float(game.qbelo_home) + float(game.xgb_home)) / 2.0
    raw_pin_home = float(anchor.home_no_vig_probability)
    p_market_cal_home = calibrated_market_probability(raw_pin_home, fit)
    p_final_home = final_ml_home_probability(raw_model_home, raw_pin_home, fit)

    selected_model = _side_probability(raw_model_home, offer.side)
    selected_market = _side_probability(p_market_cal_home, offer.side)
    selected_final = _side_probability(p_final_home, offer.side)
    selected_qb = _side_probability(float(game.qbelo_home), offer.side)
    selected_xgb = _side_probability(float(game.xgb_home), offer.side)
    constituent_gap = abs(selected_qb - selected_xgb)

    support_values = {
        "pinnacle_extremity": abs(selected_market - 0.5),
        "model_market_gap": abs(selected_model - selected_market),
        "constituent_gap": constituent_gap,
    }
    distance = overall_support_distance(support_values, state.support_features)
    prob = moneyline_outcome_probabilities(
        selected_final,
        prior_ties=state.prior_ties,
        prior_games=state.prior_games,
    )
    return _finish(
        prob=prob,
        offer=offer,
        evaluator_version=state.version,
        support_n=state.training_n,
        support_distance=distance,
        constituent_disagreement=constituent_gap,
        reliability_state=reliability_state,
        staking_anchor_probability=selected_market,
        evidence={
            "raw_qbelo_probability": selected_qb,
            "raw_xgb_probability": selected_xgb,
            "raw_exact_avg_probability": selected_model,
            "raw_pinnacle_no_vig_probability": _side_probability(raw_pin_home, offer.side),
            "calibrated_market_probability": selected_market,
            "final_probability_conditional_nonpush": selected_final,
            "model_market_disagreement": selected_model - selected_market,
            "model_pool_weight": state.model_weight,
        },
    )


def _point_market_anchor_at_offer(
    *,
    market_type: str,
    side: str,
    line: float,
    mu_market: float,
    sigma: float,
) -> float:
    if market_type == "spread":
        threshold = -float(line) if side.lower() == "home" else float(line)
        q_above = conditional_above_probability(
            mu_market,
            threshold,
            sigma,
            push_possible=line_allows_push(line),
        )
        return q_above if side.lower() == "home" else 1.0 - q_above
    threshold = float(line)
    q_above = conditional_above_probability(
        mu_market,
        threshold,
        sigma,
        push_possible=line_allows_push(line),
    )
    return q_above if side.lower() == "over" else 1.0 - q_above


def evaluate_point_v3(
    game: GameState,
    offer: NormalizedOffer,
    state: PointV3State,
    anchor: MarketAnchor,
    reliability_state: ReliabilityState,
    *,
    allow_authorized_holdout_2025: bool = False,
) -> EvaluationResult:
    _assert_season_allowed(
        game,
        allow_authorized_holdout_2025=allow_authorized_holdout_2025,
    )
    if offer.market_type != state.market_type or anchor.market_type != state.market_type:
        raise ValueError("point V3 state/offer/anchor market mismatch")
    if offer.line is None:
        return _unsupported(state.version, state.training_n, "missing_actionable_line", reliability_state.radius)
    if anchor.threshold is None or anchor.probability_above_nonpush is None:
        return _unsupported(state.version, state.training_n, "missing_pinnacle_line_price_anchor", reliability_state.radius)

    if state.market_type == "spread":
        if game.expected_home_margin is None:
            return _unsupported(state.version, state.training_n, "missing_expected_margin", reliability_state.radius)
        model_value = float(game.expected_home_margin)
    else:
        if game.predicted_total_r4 is None:
            return _unsupported(state.version, state.training_n, "missing_ridge_r4", reliability_state.radius)
        model_value = float(game.predicted_total_r4)

    mu_market = market_implied_mean(
        float(anchor.threshold),
        float(anchor.probability_above_nonpush),
        float(state.sigma),
        push_possible=bool(anchor.push_possible),
    )
    calibrated_mean = mu_market + float(state.beta) * (model_value - mu_market)
    if state.market_type == "spread":
        prob = empirical_spread_probabilities(
            state.residuals,
            calibrated_mean,
            offer.side,
            float(offer.line),
        )
    else:
        prob = empirical_total_probabilities(
            state.residuals,
            calibrated_mean,
            offer.side,
            float(offer.line),
        )

    # The support envelope is learned from historical sharp-market thresholds,
    # but the value checked against it must be the exact wager being evaluated.
    # This keeps arbitrary/manual offers from bypassing OOD via a normal-looking
    # Pinnacle anchor while presenting an extreme actionable line.
    support_values = {
        "model_market_gap": abs(model_value - mu_market),
        "anchor_threshold_magnitude": abs(float(offer.line)),
    }
    distance = overall_support_distance(support_values, state.support_features)
    staking_anchor = _point_market_anchor_at_offer(
        market_type=state.market_type,
        side=offer.side,
        line=float(offer.line),
        mu_market=mu_market,
        sigma=float(state.sigma),
    )
    return _finish(
        prob=prob,
        offer=offer,
        evaluator_version=state.version,
        support_n=state.training_n,
        support_distance=distance,
        constituent_disagreement=0.0,
        reliability_state=reliability_state,
        staking_anchor_probability=staking_anchor,
        evidence={
            "raw_football_output": model_value,
            "pinnacle_anchor_threshold": float(anchor.threshold),
            "pinnacle_anchor_probability": float(anchor.probability_above_nonpush),
            "pinnacle_anchor_push_possible": bool(anchor.push_possible),
            "market_implied_mean": mu_market,
            "calibrated_mean": calibrated_mean,
            "calibration_beta": float(state.beta),
            "market_scale": float(state.sigma),
            "model_market_disagreement": model_value - mu_market,
        },
    )


def evaluate_offer(
    game_state: GameState,
    normalized_offer: NormalizedOffer,
    evaluator_state: MoneylineV4State | PointV3State,
    market_anchor: MarketAnchor,
    reliability_state: ReliabilityState,
    *,
    allow_authorized_holdout_2025: bool = False,
) -> EvaluationResult:
    """Evaluate any stored or manual exact offer with the frozen accepted family."""
    if isinstance(evaluator_state, MoneylineV4State):
        return evaluate_moneyline_v4(
            game_state,
            normalized_offer,
            evaluator_state,
            market_anchor,
            reliability_state,
            allow_authorized_holdout_2025=allow_authorized_holdout_2025,
        )
    return evaluate_point_v3(
        game_state,
        normalized_offer,
        evaluator_state,
        market_anchor,
        reliability_state,
        allow_authorized_holdout_2025=allow_authorized_holdout_2025,
    )
