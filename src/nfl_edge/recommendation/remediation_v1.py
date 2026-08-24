"""Preregistered Task05G remediation: model-first candidate-gated selectors.

This module is intentionally downstream of both the frozen Task05E candidate
provenance and frozen Task05F evaluator.  It does not retrain a football model,
change Task05F probability/economics, or discover candidates from generic
full-board evaluator VALUE.

Architecture:
    football-model candidate -> exact Task05F offer -> selector
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Iterable, Mapping, Sequence

from nfl_edge.recommendation.policy import (
    ALLOWED_RELIABILITY,
    NO_BALANCED_PLAY,
    NO_HIT_RATE_PLAY,
    NO_VALUE_PLAY,
    _candidate_id,
    _int,
    _reliability_rank,
    _safe_sort_number,
    _status_rank,
    shop_exact_offers,
)
from nfl_edge.value.market_math import american_to_decimal


def _f(row: Mapping[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def is_model_candidate(row: Mapping[str, Any]) -> bool:
    """Return True only for a side admitted by frozen Task05E provenance."""
    return bool(row.get("model_candidate", False))


def robust_expected_value(row: Mapping[str, Any]) -> float | None:
    """One-uncertainty-radius downside EV for one exact evaluated offer.

    Preregistered formula:
      q_lower = max(0, conditional_nonpush_probability - uncertainty)
      p_win_lower = (1 - p_push) * q_lower
      robust_EV = p_win_lower * decimal_odds + p_push - 1

    Missing/invalid inputs fail closed and return None.  This does not alter the
    frozen Task05F point estimate; it is a downstream selector statistic only.
    """
    q = _f(row, "conditional_nonpush_probability")
    uncertainty = _f(row, "uncertainty")
    p_push = _f(row, "p_push")
    odds = _int(row, "actionable_price_american", "american_odds", "price_american")
    if q is None or uncertainty is None or p_push is None or odds is None:
        return None
    if not (0.0 <= q <= 1.0 and uncertainty >= 0.0 and 0.0 <= p_push <= 1.0):
        return None
    try:
        decimal_odds = float(american_to_decimal(int(odds)))
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if not isfinite(decimal_odds) or decimal_odds <= 1.0:
        return None
    q_lower = max(0.0, q - uncertainty)
    p_win_lower = (1.0 - p_push) * q_lower
    return p_win_lower * decimal_odds + p_push - 1.0


def _status(row: Mapping[str, Any]) -> str:
    return str(row.get("price_status", "UNSUPPORTED")).upper()


def _reliability(row: Mapping[str, Any]) -> str:
    return str(row.get("reliability", "UNSUPPORTED")).upper()


def _odds_in(row: Mapping[str, Any], minimum: int, maximum: int) -> bool:
    odds = _int(row, "actionable_price_american", "american_odds", "price_american")
    return odds is not None and minimum <= odds <= maximum


def _common_eligible(row: Mapping[str, Any]) -> bool:
    if not is_model_candidate(row):
        return False
    if not bool(row.get("supported", False)):
        return False
    if _reliability(row) not in ALLOWED_RELIABILITY:
        return False
    if _status(row) in {"PASS", "UNSUPPORTED"}:
        return False
    # The preregistered ranking uses robust EV. Missing uncertainty/push inputs
    # therefore fail closed instead of receiving an implicit favorable value.
    return robust_expected_value(row) is not None


def _hit_rate_eligible(row: Mapping[str, Any]) -> bool:
    q = _f(row, "actionable_probability")
    return (
        _common_eligible(row)
        and _status(row) in {"VALUE", "PLAYABLE"}
        and q is not None
        and q >= 0.55
        and _odds_in(row, -300, 200)
    )


def _balanced_eligible(row: Mapping[str, Any]) -> bool:
    q = _f(row, "actionable_probability")
    ev = _f(row, "expected_value")
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
    q = _f(row, "actionable_probability")
    ev = _f(row, "expected_value")
    support_n = _int(row, "support_n")
    support_distance = _f(row, "support_distance")
    uncertainty = _f(row, "uncertainty")
    robust_ev = robust_expected_value(row)
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
        and robust_ev is not None
        and robust_ev > 0.0
    )


def _select(
    rows: Sequence[Mapping[str, Any]],
    eligible,
    key,
    no_play: str,
) -> Mapping[str, Any] | str:
    candidates = [row for row in rows if eligible(row)]
    if not candidates:
        return no_play
    return sorted(candidates, key=key)[0]


def _robust_sort(row: Mapping[str, Any]) -> float:
    return _safe_sort_number(robust_expected_value(row))


def select_hit_rate(rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | str:
    """Pick highest cash probability among exact model-supported offers."""
    shopped = shop_exact_offers(rows)
    return _select(
        shopped,
        _hit_rate_eligible,
        lambda row: (
            -_safe_sort_number(_f(row, "actionable_probability")),
            -_reliability_rank(row),
            -_status_rank(row),
            -_robust_sort(row),
            -_safe_sort_number(_f(row, "expected_value")),
            -(_int(row, "actionable_price_american", "american_odds", "price_american") or -100000),
            _candidate_id(row),
        ),
        NO_HIT_RATE_PLAY,
    )


def select_balanced(rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | str:
    """Probability-first middle lane over model-supported exact offers."""
    shopped = shop_exact_offers(rows)
    return _select(
        shopped,
        _balanced_eligible,
        lambda row: (
            -_safe_sort_number(_f(row, "actionable_probability")),
            -_reliability_rank(row),
            -_status_rank(row),
            -_robust_sort(row),
            -_safe_sort_number(_f(row, "expected_value")),
            _candidate_id(row),
        ),
        NO_BALANCED_PLAY,
    )


def select_value(rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | str:
    """Pick strongest uncertainty-adjusted price among model candidates."""
    shopped = shop_exact_offers(rows)
    return _select(
        shopped,
        _value_eligible,
        lambda row: (
            -_robust_sort(row),
            -_reliability_rank(row),
            -_safe_sort_number(_f(row, "actionable_probability")),
            -_safe_sort_number(_f(row, "expected_value")),
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
