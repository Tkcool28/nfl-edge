"""Reliability tiering for Task05F evaluators.

Remediation: real out-of-support distance, real prior-block stability evidence,
and honest uncertainty semantics (never treat uncomputed uncertainty as perfect
certainty / 0.0).

Reliability tiers (frozen preregistration):
  UNSUPPORTED - insufficient support, out of support, or unstable history
  HIGH        - high support (>=512), tight uncertainty (<=0.025), low disagreement
  MEDIUM      - medium support (>=256), uncertainty <=0.045
  LOW         - supported but below HIGH/MEDIUM
"""
from __future__ import annotations
from dataclasses import dataclass

from .contracts import SupportFeature

SUPPORT_FLOOR = 1e-6
MAX_OUT_OF_SUPPORT_DISTANCE = 0.10
MIN_SUPPORT_LOW = 128
MIN_SUPPORT_MEDIUM = 256
MIN_SUPPORT_HIGH = 512
UNCERTAINTY_HIGH_MAX = 0.025
UNCERTAINTY_MEDIUM_MAX = 0.045


@dataclass(frozen=True)
class ReliabilityEvidence:
    support_n: int
    uncertainty: float | None
    support_distance: float = 0.0
    constituent_disagreement: float = 0.0
    stable_blocks: bool = True


def support_feature(name: str, values: list[float]) -> SupportFeature:
    """Deterministic historical support envelope (min/max) with a safe span floor."""
    if not values:
        return SupportFeature(name, 0.0, 0.0, SUPPORT_FLOOR)
    lo = float(min(values))
    hi = float(max(values))
    span = max(hi - lo, SUPPORT_FLOOR)
    return SupportFeature(name, lo, hi, span)


def feature_distance(value: float, feature: SupportFeature) -> float:
    """0 if inside support, else normalized distance beyond the nearest bound."""
    lo, hi, span = feature.min_value, feature.max_value, feature.span
    if lo <= value <= hi:
        return 0.0
    if value < lo:
        return (lo - value) / span
    return (value - hi) / span


def overall_support_distance(values: list[float], features: list[SupportFeature]) -> float:
    """max over per-feature distance; 0 when no features/values defined."""
    if not features or not values:
        return 0.0
    d = 0.0
    for v, f in zip(values, features):
        if v is None:
            continue
        d = max(d, feature_distance(float(v), f))
    return d


def tier(e: ReliabilityEvidence) -> str:
    # Hard fail-closed: out of support or insufficient prior support.
    if e.support_n < MIN_SUPPORT_LOW or e.support_distance > MAX_OUT_OF_SUPPORT_DISTANCE:
        return "UNSUPPORTED"
    # Stability evidence: unstable history (or insufficient stability history)
    # can never be HIGH/MEDIUM; capped at LOW.
    if not e.stable_blocks:
        return "LOW"
    if e.support_n >= MIN_SUPPORT_HIGH and e.uncertainty is not None and 0 < e.uncertainty <= UNCERTAINTY_HIGH_MAX and e.constituent_disagreement <= 0.08:
        return "HIGH"
    if e.support_n >= MIN_SUPPORT_MEDIUM and e.uncertainty is not None and 0 < e.uncertainty <= UNCERTAINTY_MEDIUM_MAX and e.constituent_disagreement <= 0.15:
        return "MEDIUM"
    return "LOW"


def unsupported_reason(e: ReliabilityEvidence) -> str:
    if e.support_distance > MAX_OUT_OF_SUPPORT_DISTANCE:
        return "out_of_support"
    if e.support_n < MIN_SUPPORT_LOW:
        return "insufficient_prior_support"
    if not e.stable_blocks:
        return "unstable_stability_blocks"
    return "unsupported"


def staking_probability(actionable, anchor, reliability, uncertainty):
    haircut = {"HIGH": 1.0, "MEDIUM": 0.70, "LOW": 0.35, "UNSUPPORTED": 0.0}[reliability]
    # Missing/None uncertainty must not be treated as perfect certainty:
    # treat it as conservative (no de-risking benefit).
    if uncertainty is None:
        uncertainty_factor = 0.0
    else:
        uncertainty_factor = max(0.0, 1.0 - min(1.0, float(uncertainty) / 0.10))
    return anchor + haircut * uncertainty_factor * (actionable - anchor)
