"""Accepted-evaluator support and reliability logic for Task05F."""
from __future__ import annotations

from dataclasses import dataclass
from .contracts import ReliabilityState, SupportFeature

SUPPORT_FLOOR = 1e-6
MAX_OUT_OF_SUPPORT_DISTANCE = 0.10
MIN_SUPPORT_LOW = 128
MIN_SUPPORT_MEDIUM = 256
MIN_SUPPORT_HIGH = 512
UNCERTAINTY_HIGH_MAX = 0.025
UNCERTAINTY_MEDIUM_MAX = 0.045
RELIABILITY_HAIRCUT = {"HIGH": 1.0, "MEDIUM": 0.70, "LOW": 0.35, "UNSUPPORTED": 0.0}


@dataclass(frozen=True)
class ReliabilityEvidence:
    # support_n is the amount of strictly-prior accepted-evaluator OOS evidence
    # available for reliability tiering. Structural evaluator fit support is
    # already enforced before an accepted evaluator state can be constructed.
    support_n: int
    uncertainty: float | None
    support_distance: float
    constituent_disagreement: float
    stable_blocks: bool


def support_feature(name: str, values: list[float]) -> SupportFeature:
    if not values:
        return SupportFeature(name, 0.0, 0.0, SUPPORT_FLOOR)
    lo = float(min(values))
    hi = float(max(values))
    return SupportFeature(name, lo, hi, max(hi - lo, SUPPORT_FLOOR))


def feature_distance(value: float, feature: SupportFeature) -> float:
    v = float(value)
    if feature.min_value <= v <= feature.max_value:
        return 0.0
    if v < feature.min_value:
        return (feature.min_value - v) / feature.span
    return (v - feature.max_value) / feature.span


def overall_support_distance(values: dict[str, float | None], features: tuple[SupportFeature, ...]) -> float:
    distance = 0.0
    for feature in features:
        value = values.get(feature.name)
        if value is None:
            continue
        distance = max(distance, feature_distance(float(value), feature))
    return distance


def reliability_tier(e: ReliabilityEvidence) -> str:
    """Assign reliability once from accepted-family OOS evidence.

    Missing/young OOS reliability history is LOW, not structurally unsupported.
    That distinction is required so cold-start accepted rows can enter the OOS
    reliability history for later blocks. Structural unsupported conditions
    (missing model/anchor, insufficient evaluator fit, sealed season) are handled
    before this function; real OOD remains fail-closed here.
    """
    if e.support_distance > MAX_OUT_OF_SUPPORT_DISTANCE:
        return "UNSUPPORTED"
    if e.support_n < MIN_SUPPORT_LOW or not e.stable_blocks or e.uncertainty is None:
        return "LOW"
    if (
        e.support_n >= MIN_SUPPORT_HIGH
        and 0.0 < e.uncertainty <= UNCERTAINTY_HIGH_MAX
        and e.constituent_disagreement <= 0.08
    ):
        return "HIGH"
    if (
        e.support_n >= MIN_SUPPORT_MEDIUM
        and 0.0 < e.uncertainty <= UNCERTAINTY_MEDIUM_MAX
        and e.constituent_disagreement <= 0.15
    ):
        return "MEDIUM"
    return "LOW"


def unsupported_reason(e: ReliabilityEvidence) -> str | None:
    if e.support_distance > MAX_OUT_OF_SUPPORT_DISTANCE:
        return "out_of_support"
    return None


def uncertainty_factor(radius: float | None, *, scale: float = 0.10) -> float:
    if radius is None:
        return 0.0
    return max(0.0, 1.0 - min(1.0, float(radius) / float(scale)))


def conservative_staking_probability(
    evaluator_probability: float,
    market_anchor_probability: float,
    reliability: str,
    radius: float | None,
) -> float:
    q = float(evaluator_probability)
    anchor = float(market_anchor_probability)
    if not 0.0 <= q <= 1.0 or not 0.0 <= anchor <= 1.0:
        raise ValueError("probabilities must be in [0,1]")
    haircut = RELIABILITY_HAIRCUT[reliability]
    value = anchor + haircut * uncertainty_factor(radius) * (q - anchor)
    return min(0.99, max(0.01, value))


def make_evidence(
    support_n: int,
    support_distance: float,
    constituent_disagreement: float,
    reliability_state: ReliabilityState,
) -> ReliabilityEvidence:
    # HIGH/MEDIUM cannot outrun either the accepted-family fit or its strictly
    # prior OOS calibration history. During reliability cold start this effective
    # count may be <128; such rows remain supported but LOW.
    effective_support_n = min(int(support_n), int(reliability_state.support_n))
    return ReliabilityEvidence(
        support_n=effective_support_n,
        uncertainty=reliability_state.radius,
        support_distance=float(support_distance),
        constituent_disagreement=float(constituent_disagreement),
        stable_blocks=bool(reliability_state.stable),
    )
