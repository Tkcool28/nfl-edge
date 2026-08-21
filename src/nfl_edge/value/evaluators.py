from __future__ import annotations
import math
from .contracts import EvaluationResult,EvaluatorState,GameState,NormalizedOffer
from .market_math import clip_probability,expected_value_per_unit,normal_cdf,probability_to_fair_american,break_even_probability
from .reliability import (ReliabilityEvidence, tier, staking_probability, overall_support_distance,
                          unsupported_reason, MAX_OUT_OF_SUPPORT_DISTANCE)

def _side_prob(home_p:float,side:str)->float:return home_p if side.lower()=="home" else 1.0-home_p

def exact_avg(game:GameState, side:str)->float|None:
    if game.qbelo_home is None or game.xgb_home is None:return None
    return (_side_prob(game.qbelo_home,side)+_side_prob(game.xgb_home,side))/2.0

def _moneyline_feature_values(q: float|None, x: float|None, avg: float|None, pin: float, state: EvaluatorState) -> list[float]:
    """Build the per-feature values (same order as state.support_features).

    avg_pin_gap uses the SIGNED coordinate (avg - pin), matching the historical
    support envelope coordinate (whose sign reflects the direction of football-
    model disagreement relative to the market). qb_xgb_gap stays absolute.
    """
    fam = state.family
    values = []
    for f in state.support_features:
        if f.name == "pin":
            values.append(pin)
        elif f.name == "avg_pin_gap":
            values.append(None if avg is None else (avg - pin))
        elif f.name == "qb_xgb_gap":
            values.append(None if q is None or x is None else abs(q - x))
        else:
            values.append(None)
    return values

def _point_feature_values(delta: float, market: float|None, state: EvaluatorState) -> list[float]:
    """Build the per-feature values (same order as state.support_features).

    delta_magnitude uses abs(selected-side delta) so mirrored sides share one
    orientation-invariant support space. market_magnitude uses abs(line).
    """
    out = []
    for f in state.support_features:
        if f.name == "delta_magnitude":
            out.append(abs(delta))
        elif f.name == "market_magnitude":
            out.append(None if market is None else abs(market))
        else:
            out.append(None)
    return out

def _finish(p:float, offer:NormalizedOffer, state:EvaluatorState, anchor:float, disagreement:float=0.0,
            evidence:dict|None=None, support_values:list[float]|None=None)->EvaluationResult:
    p=clip_probability(p)
    sd = overall_support_distance(support_values or [], list(state.support_features))
    ev = ReliabilityEvidence(state.training_n, state.uncertainty, sd, disagreement, stable_blocks=state.stable_blocks)
    rel=tier(ev)
    reason=unsupported_reason(ev) if rel=="UNSUPPORTED" else None
    if rel=="UNSUPPORTED":
        return EvaluationResult(None,None,None,None,rel,state.uncertainty,state.training_n,state.version,evidence or {},False,reason)
    ps=clip_probability(staking_probability(p,anchor,rel,state.uncertainty))
    return EvaluationResult(p,ps,probability_to_fair_american(p),expected_value_per_unit(p,offer.price_american),rel,state.uncertainty,state.training_n,state.version,evidence or {})

def evaluate_ml(game:GameState, offer:NormalizedOffer, state:EvaluatorState, pinnacle_no_vig_selected:float)->EvaluationResult:
    if game.season==2025: raise RuntimeError("2025 SEALED")
    q=None if game.qbelo_home is None else _side_prob(game.qbelo_home,offer.side)
    x=None if game.xgb_home is None else _side_prob(game.xgb_home,offer.side)
    avg=exact_avg(game,offer.side)
    fam=state.family
    if fam in {"exact_avg","global_shrinkage","reliability_aware_shrinkage","strong_logistic"} and avg is None:
        return EvaluationResult(None,None,None,None,"UNSUPPORTED",None,state.training_n,state.version,{},False,"exact_avg_requires_both_models")
    if fam=="pinnacle":p=pinnacle_no_vig_selected
    elif fam=="raw_qbelo":
        if q is None:return EvaluationResult(None,None,None,None,"UNSUPPORTED",None,state.training_n,state.version,{},False,"missing_qbelo")
        p=q
    elif fam=="raw_xgb":
        if x is None:return EvaluationResult(None,None,None,None,"UNSUPPORTED",None,state.training_n,state.version,{},False,"missing_xgb")
        p=x
    elif fam=="exact_avg":p=avg
    elif fam=="global_shrinkage":p=pinnacle_no_vig_selected+float(state.parameters["lambda"])*(avg-pinnacle_no_vig_selected)
    elif fam=="reliability_aware_shrinkage":
        region="low" if pinnacle_no_vig_selected<.40 else "mid" if pinnacle_no_vig_selected<=.60 else "high"
        band="small" if abs(avg-pinnacle_no_vig_selected)<.05 else "large"
        lam=float(state.parameters.get(f"lambda_{region}_{band}",state.parameters["lambda_global"]))
        p=pinnacle_no_vig_selected+lam*(avg-pinnacle_no_vig_selected)
    elif fam=="strong_logistic":
        b=state.parameters["coef"]; z=float(state.parameters["intercept"])+b[0]*q+b[1]*x+b[2]*pinnacle_no_vig_selected+b[3]*abs(q-x)+b[4]*(avg-pinnacle_no_vig_selected)
        p=1/(1+math.exp(-z))
    else:raise ValueError(fam)
    svals = _moneyline_feature_values(q, x, avg, pinnacle_no_vig_selected, state)
    return _finish(p,offer,state,pinnacle_no_vig_selected,0 if q is None or x is None else abs(q-x),
                   evidence={"qbelo":q,"xgb":x,"avg":avg,"pinnacle_no_vig":pinnacle_no_vig_selected}, support_values=svals)

def evaluate_spread(game:GameState, offer:NormalizedOffer, state:EvaluatorState, benchmark_anchor:float|None=None)->EvaluationResult:
    if game.season==2025:raise RuntimeError("2025 SEALED")
    if game.expected_home_margin is None:return EvaluationResult(None,None,None,None,"UNSUPPORTED",None,state.training_n,state.version,{},False,"missing_expected_margin")
    selected_margin=game.expected_home_margin if offer.side.lower()=="home" else -game.expected_home_margin
    delta=selected_margin+float(offer.line); sigma=float(state.parameters["sigma"]); z=delta/sigma
    if state.family=="normal_cdf":p=normal_cdf(z)
    elif state.family=="calibrated_normal":p=1/(1+math.exp(-(float(state.parameters["intercept"])+float(state.parameters["slope"])*z)))
    elif state.family=="strong_logistic":
        b=state.parameters["coef"]; zz=float(state.parameters["intercept"])+b[0]*delta+b[1]*abs(float(offer.line));p=1/(1+math.exp(-zz))
    else:raise ValueError(state.family)
    anchor=benchmark_anchor if benchmark_anchor is not None else break_even_probability(offer.price_american)
    svals=_point_feature_values(delta, offer.line, state)
    return _finish(p,offer,state,anchor,evidence={"delta":delta,"sigma":sigma}, support_values=svals)

def evaluate_total(game:GameState, offer:NormalizedOffer, state:EvaluatorState, benchmark_anchor:float|None=None)->EvaluationResult:
    if game.season==2025:raise RuntimeError("2025 SEALED")
    if game.predicted_total_r4 is None:return EvaluationResult(None,None,None,None,"UNSUPPORTED",None,state.training_n,state.version,{},False,"missing_ridge_r4")
    delta=(game.predicted_total_r4-float(offer.line)) if offer.side.lower()=="over" else (float(offer.line)-game.predicted_total_r4)
    sigma=float(state.parameters["sigma"]);z=delta/sigma
    if state.family=="normal_cdf":p=normal_cdf(z)
    elif state.family=="calibrated_normal":p=1/(1+math.exp(-(float(state.parameters["intercept"])+float(state.parameters["slope"])*z)))
    elif state.family=="strong_logistic":
        b=state.parameters["coef"]; zz=float(state.parameters["intercept"])+b[0]*delta+b[1]*float(offer.line);p=1/(1+math.exp(-zz))
    else:raise ValueError(state.family)
    anchor=benchmark_anchor if benchmark_anchor is not None else break_even_probability(offer.price_american)
    svals=_point_feature_values(delta, offer.line, state)
    return _finish(p,offer,state,anchor,evidence={"delta":delta,"sigma":sigma}, support_values=svals)

def evaluate_offer(game_state:GameState, normalized_offer:NormalizedOffer, evaluator_state:EvaluatorState, *, pinnacle_no_vig_selected:float|None=None, benchmark_anchor:float|None=None)->EvaluationResult:
    if normalized_offer.market_type=="moneyline":
        if pinnacle_no_vig_selected is None:return EvaluationResult(None,None,None,None,"UNSUPPORTED",None,evaluator_state.training_n,evaluator_state.version,{},False,"missing_pinnacle_benchmark")
        return evaluate_ml(game_state,normalized_offer,evaluator_state,pinnacle_no_vig_selected)
    if normalized_offer.market_type=="spread":return evaluate_spread(game_state,normalized_offer,evaluator_state,benchmark_anchor)
    return evaluate_total(game_state,normalized_offer,evaluator_state,benchmark_anchor)
