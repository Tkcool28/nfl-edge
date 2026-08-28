"""Final Task05G three-lane selector protocols V1.

This module is the canonical selector implementation downstream of frozen
Task05F exact-offer evaluation, Model Confidence V2, Spread Confidence V3, and
frozen Task05E candidate provenance.

The three lanes intentionally use separate objectives:
- Hit Rate: trustworthy football-model hit probability.
- Balanced: trustworthy football-model probability inside a reasonable price band.
- Value: strict +EV from validated model families, with causal family trust and
  fail-closed safety valves.

No selector in this module trains or recalibrates a football model or Task05F.
Totals are not headline eligible in V1.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence

from nfl_edge.recommendation.policy import (
    NO_BALANCED_PLAY,
    NO_HIT_RATE_PLAY,
    NO_VALUE_PLAY,
    shop_exact_offers,
)

ACTIONABLE_BOOKS = frozenset({"draftkings", "fanduel"})
MIN_MODEL_CONFIDENCE_SUPPORT_N = 256

HHR_MIN_Q = 0.55
HHR_ODDS = (-300, 200)
BALANCED_MIN_Q = 0.52
BALANCED_ODDS = (-220, 200)
VALUE_ODDS = (-180, 250)
MARKET_HALF = 0.50

RESET_TRUST = 0.50
PSEUDO_N = 8
AMBER_MIN_N = 3
AMBER_TRUST = 0.50
RED_MIN_N = 8
RED_TRUST = 0.25

ML_VALUE_REGIONS = frozenset(
    {
        "ML_DOG_VALUE_ZONE_AVG",
        "ML_DOG_VALUE_ZONE_CORROB",
        "ML_AVG_DISAGREEMENT_AVG_0_2",
    }
)
SPREAD_VALUE_REGION = "SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4"


@dataclass(frozen=True)
class TrustObservation:
    predicted_edge: float
    realized_edge: float


@dataclass(frozen=True)
class ValueSelectorState:
    """Strictly-prior settled family-frontier evidence for one NFL season."""

    ml_observations: tuple[TrustObservation, ...] = ()
    spread_observations: tuple[TrustObservation, ...] = ()


@dataclass(frozen=True)
class FamilyTrust:
    n: int
    predicted_edge_sum: float
    realized_edge_sum: float
    data_trust: float | None
    trust: float
    state: str
    evidence_status: str


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _candidate_id(row: Mapping[str, Any]) -> str:
    explicit = row.get("candidate_id")
    if explicit is not None:
        return str(explicit)
    return "|".join(
        [
            str(row.get("game_id", "")),
            str(row.get("market_type", "")),
            str(row.get("selected_side", "")),
            str(row.get("sportsbook", "")),
            str(row.get("line", "")),
            str(row.get("american_odds", "")),
        ]
    )


def _odds(row: Mapping[str, Any]) -> int | None:
    value = row.get("american_odds")
    return None if value is None else int(value)


def _reliability(row: Mapping[str, Any]) -> str:
    return str(row.get("reliability", "UNSUPPORTED")).upper()


def _reliability_rank(row: Mapping[str, Any]) -> int:
    return {"HIGH": 2, "MEDIUM": 1}.get(_reliability(row), 0)


def _tags(row: Mapping[str, Any]) -> set[str]:
    return {tag for tag in str(row.get("model_candidate_regions") or "").split(";") if tag}


def _within(row: Mapping[str, Any], bounds: tuple[int, int]) -> bool:
    odds = _odds(row)
    return odds is not None and bounds[0] <= odds <= bounds[1]


def _common_model_offer(row: Mapping[str, Any]) -> bool:
    """Frozen common support gate; reliability is a ranking signal, not an extra veto."""
    return (
        bool(row.get("supported"))
        and bool(row.get("model_confidence_supported"))
        and int(row.get("model_confidence_support_n") or 0) >= MIN_MODEL_CONFIDENCE_SUPPORT_N
        and str(row.get("market_type", "")).lower() in {"moneyline", "spread"}
        and str(row.get("sportsbook", "")).lower() in ACTIONABLE_BOOKS
        and _finite(row.get("model_confidence_probability")) is not None
        and _finite(row.get("break_even_probability")) is not None
    )


def _model_q(row: Mapping[str, Any]) -> float | None:
    return _finite(row.get("model_confidence_probability"))


def _market_half_trust(row: Mapping[str, Any]) -> float | None:
    q = _model_q(row)
    if q is None:
        return None
    market = str(row.get("market_type", "")).lower()
    if market == "spread":
        return q
    if market != "moneyline":
        return None
    pinnacle = _finite(row.get("pinnacle_anchor_probability"))
    if pinnacle is None:
        return None
    return q - MARKET_HALF * max(q - pinnacle, 0.0)


def _lane_eligible(row: Mapping[str, Any], *, min_q: float, odds: tuple[int, int]) -> bool:
    q = _model_q(row)
    return _common_model_offer(row) and q is not None and q >= min_q and _within(row, odds)


def _lane_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    trust = _market_half_trust(row)
    q = _model_q(row)
    return (
        -float(trust if trust is not None else -99.0),
        -float(q if q is not None else -99.0),
        -_reliability_rank(row),
        -int(_odds(row) or -100000),
        _candidate_id(row),
    )


def _select_probability_lane(
    rows: Iterable[Mapping[str, Any]],
    *,
    min_q: float,
    odds: tuple[int, int],
    no_play: str,
) -> Mapping[str, Any] | str:
    candidates: list[dict[str, Any]] = []
    for source in shop_exact_offers(rows):
        row = dict(source)
        if not _lane_eligible(row, min_q=min_q, odds=odds):
            continue
        trust = _market_half_trust(row)
        if trust is None:
            continue
        row["selector_trust"] = trust
        candidates.append(row)
    if not candidates:
        return no_play
    return dict(sorted(candidates, key=_lane_key)[0])


def select_hit_rate(rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | str:
    """HALF_SHRINK HHR: maximize trustworthy football-model hit probability."""

    return _select_probability_lane(rows, min_q=HHR_MIN_Q, odds=HHR_ODDS, no_play=NO_HIT_RATE_PLAY)


def select_balanced(rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | str:
    """MARKET_HALF_ONLY Balanced: probability first inside the frozen price band."""

    return _select_probability_lane(
        rows,
        min_q=BALANCED_MIN_Q,
        odds=BALANCED_ODDS,
        no_play=NO_BALANCED_PLAY,
    )


def _strict_value_common(row: Mapping[str, Any]) -> bool:
    ev = _finite(row.get("expected_value"))
    return (
        _common_model_offer(row)
        and bool(_tags(row))
        and ev is not None
        and ev > 0.0
        and str(row.get("price_status", "")).upper() == "VALUE"
        and _within(row, VALUE_ODDS)
    )


def ml_value_candidates(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for source in shop_exact_offers(rows):
        row = dict(source)
        gap = _finite(row.get("model_price_gap"))
        edge = _finite(row.get("evaluated_edge_probability"))
        if (
            _strict_value_common(row)
            and str(row.get("market_type", "")).lower() == "moneyline"
            and bool(_tags(row).intersection(ML_VALUE_REGIONS))
            and gap is not None
            and gap > 0.0
            and edge is not None
            and edge > 0.0
        ):
            candidates.append(row)
    return candidates


def ml_value_frontier(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    candidates = ml_value_candidates(rows)
    if not candidates:
        return None
    return dict(
        sorted(
            candidates,
            key=lambda row: (
                -float(row["model_price_gap"]),
                -float(row["model_confidence_probability"]),
                -float(row["evaluated_edge_probability"]),
                -_reliability_rank(row),
                -int(_odds(row) or -100000),
                _candidate_id(row),
            ),
        )[0]
    )


def spread_value_candidates(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for source in shop_exact_offers(rows):
        row = dict(source)
        margin = _finite(row.get("model_cover_margin_v3"))
        edge = _finite(row.get("evaluated_edge_probability"))
        if (
            _strict_value_common(row)
            and str(row.get("market_type", "")).lower() == "spread"
            and SPREAD_VALUE_REGION in _tags(row)
            and margin is not None
            and margin > 0.0
            and edge is not None
            and edge > 0.0
        ):
            candidates.append(row)
    return candidates


def spread_pareto_frontier(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Coefficient-free maximin consensus of model strength and Task05F economics."""

    candidates = spread_value_candidates(rows)
    if not candidates:
        return None

    model_order = sorted(
        candidates,
        key=lambda row: (-float(row["model_cover_margin_v3"]), _candidate_id(row)),
    )
    economic_order = sorted(
        candidates,
        key=lambda row: (
            -float(row["evaluated_edge_probability"]),
            -float(row["expected_value"]),
            _candidate_id(row),
        ),
    )
    model_rank = {_candidate_id(row): idx for idx, row in enumerate(model_order, start=1)}
    economic_rank = {_candidate_id(row): idx for idx, row in enumerate(economic_order, start=1)}

    decorated: list[dict[str, Any]] = []
    for source in candidates:
        row = dict(source)
        cid = _candidate_id(row)
        mr = model_rank[cid]
        er = economic_rank[cid]
        row["pareto_model_rank"] = mr
        row["pareto_economic_rank"] = er
        row["pareto_worst_rank"] = max(mr, er)
        row["pareto_rank_sum"] = mr + er
        decorated.append(row)

    return dict(
        sorted(
            decorated,
            key=lambda row: (
                int(row["pareto_worst_rank"]),
                int(row["pareto_rank_sum"]),
                int(row["pareto_model_rank"]),
                int(row["pareto_economic_rank"]),
                -_reliability_rank(row),
                -int(_odds(row) or -100000),
                _candidate_id(row),
            ),
        )[0]
    )


def family_trust(observations: Sequence[TrustObservation]) -> FamilyTrust:
    n = len(observations)
    if n == 0:
        predicted = 0.0
        realized = 0.0
        data_trust = None
        trust = RESET_TRUST
    else:
        predicted = sum(float(obs.predicted_edge) for obs in observations)
        realized = sum(float(obs.realized_edge) for obs in observations)
        data_trust = 0.0 if predicted <= 0.0 else min(1.0, max(0.0, realized / predicted))
        trust = (PSEUDO_N * RESET_TRUST + n * data_trust) / (PSEUDO_N + n)

    if n >= RED_MIN_N and trust < RED_TRUST:
        state = "RED"
    elif n >= AMBER_MIN_N and trust < AMBER_TRUST:
        state = "AMBER"
    else:
        state = "GREEN"

    if n < AMBER_MIN_N:
        evidence = "COLD"
    elif state == "GREEN":
        evidence = "MATURE_GREEN"
    else:
        evidence = state

    return FamilyTrust(
        n=n,
        predicted_edge_sum=float(predicted),
        realized_edge_sum=float(realized),
        data_trust=None if data_trust is None else float(data_trust),
        trust=float(trust),
        state=state,
        evidence_status=evidence,
    )


def _ml_dynamic_edge(row: Mapping[str, Any], trust: float) -> float:
    return min(float(row["model_price_gap"]) * float(trust), float(row["evaluated_edge_probability"]))


def _spread_dynamic_edge(row: Mapping[str, Any]) -> float:
    return float(row["evaluated_edge_probability"])


def _cross_market(
    ml: Mapping[str, Any] | None,
    spread: Mapping[str, Any] | None,
    *,
    ml_trust: float,
) -> dict[str, Any] | None:
    if ml is None:
        return None if spread is None else dict(spread)
    if spread is None:
        return dict(ml)
    candidates = [
        (_ml_dynamic_edge(ml, ml_trust), ml),
        (_spread_dynamic_edge(spread), spread),
    ]
    _, winner = sorted(
        candidates,
        key=lambda item: (
            -float(item[0]),
            -_reliability_rank(item[1]),
            -int(_odds(item[1]) or -100000),
            _candidate_id(item[1]),
        ),
    )[0]
    return dict(winner)


def select_value(
    rows: Iterable[Mapping[str, Any]],
    state: ValueSelectorState | None = None,
) -> Mapping[str, Any] | str:
    """Final strict-Value protocol with causal family trust and safety valves."""

    material = list(rows)
    current = state or ValueSelectorState()
    ml_candidates = ml_value_candidates(material)
    spread_candidates = spread_value_candidates(material)
    ml = ml_value_frontier(material)
    spread = spread_pareto_frontier(material)

    ml_trust = family_trust(current.ml_observations)
    spread_trust = family_trust(current.spread_observations)

    # Existing causal ML family policy from FRONTIER_STATE_V3.
    if ml_trust.state == "RED":
        choice = None if spread is None else dict(spread)
    elif ml_trust.state == "AMBER" and spread is not None:
        choice = dict(spread)
    else:
        choice = _cross_market(ml, spread, ml_trust=ml_trust.trust)

    if choice is None:
        return NO_VALUE_PLAY

    # Spread safety valve: degraded family + lone surviving spread => PASS.
    if str(choice.get("market_type", "")).lower() == "spread":
        if spread_trust.state in {"AMBER", "RED"} and len(spread_candidates) == 1:
            return NO_VALUE_PLAY
        return dict(choice)

    # ML safety valve: immature/degraded family + lone surviving ML + no spread
    # corroboration => PASS. Mature singleton ML remains fully eligible.
    if (
        ml_trust.evidence_status in {"COLD", "AMBER"}
        and len(ml_candidates) == 1
        and spread is None
    ):
        return NO_VALUE_PLAY
    return dict(choice)


def _settlement(row: Mapping[str, Any] | None) -> str:
    return "" if row is None else str(row.get("settlement") or "").upper()


def _ml_observation(row: Mapping[str, Any] | None) -> TrustObservation | None:
    if row is None or _settlement(row) not in {"WIN", "LOSS"}:
        return None
    q = _model_q(row)
    break_even = _finite(row.get("break_even_probability"))
    if q is None or break_even is None:
        return None
    predicted = q - break_even
    if predicted <= 0.0:
        return None
    outcome = 1.0 if _settlement(row) == "WIN" else 0.0
    return TrustObservation(predicted_edge=float(predicted), realized_edge=float(outcome - break_even))


def _spread_observation(row: Mapping[str, Any] | None) -> TrustObservation | None:
    if row is None or _settlement(row) not in {"WIN", "LOSS"}:
        return None
    predicted = _finite(row.get("evaluated_edge_probability"))
    break_even = _finite(row.get("break_even_probability"))
    if predicted is None or predicted <= 0.0 or break_even is None:
        return None
    outcome = 1.0 if _settlement(row) == "WIN" else 0.0
    return TrustObservation(predicted_edge=float(predicted), realized_edge=float(outcome - break_even))


def advance_value_state(
    state: ValueSelectorState,
    settled_block_rows: Iterable[Mapping[str, Any]],
) -> ValueSelectorState:
    """Return next strictly-prior state after one block has settled.

    Family trust observes each family's own deterministic frontier, whether or
    not that family supplied the user-facing Value headline. This matches the
    causal development protocol and prevents headline-selection feedback from
    defining family health.
    """

    material = list(settled_block_rows)
    ml_obs = _ml_observation(ml_value_frontier(material))
    spread_obs = _spread_observation(spread_pareto_frontier(material))
    return ValueSelectorState(
        ml_observations=state.ml_observations + (() if ml_obs is None else (ml_obs,)),
        spread_observations=state.spread_observations + (() if spread_obs is None else (spread_obs,)),
    )


def select_headlines(
    rows: Iterable[Mapping[str, Any]],
    state: ValueSelectorState | None = None,
) -> dict[str, Mapping[str, Any] | str]:
    material = list(rows)
    return {
        "hit_rate": select_hit_rate(material),
        "balanced": select_balanced(material),
        "value": select_value(material, state),
    }
