"""Task05G recommendation-policy layer built on frozen Task05F evaluators.

The package-level recommendation surface is the forward/live product contract.
Historical and V5 reproduction code imports ``final_selectors_v1`` explicitly;
new application callers receive the post-V5 V2 headline selector surface.
"""

from .policy import (
    NO_BALANCED_PLAY,
    NO_HIT_RATE_PLAY,
    NO_VALUE_PLAY,
    PolicyEvaluation,
    evaluate_policy_offer,
    shop_exact_offers,
)
from .final_selectors_v2 import (
    FamilyTrust,
    TrustObservation,
    ValueSelectorState,
    advance_value_state,
    family_trust,
    select_balanced,
    select_headlines,
    select_hit_rate,
    select_value,
)
from .staking_v1 import (
    RISK_PROFILES,
    ULTRA_CAUTION,
    RiskProfile,
    cap_slate_stakes,
    dollar_stake,
    recommended_units,
    risk_profile,
    unit_dollars,
    user_wager_view,
)

__all__ = [
    "NO_BALANCED_PLAY",
    "NO_HIT_RATE_PLAY",
    "NO_VALUE_PLAY",
    "PolicyEvaluation",
    "evaluate_policy_offer",
    "shop_exact_offers",
    "FamilyTrust",
    "TrustObservation",
    "ValueSelectorState",
    "advance_value_state",
    "family_trust",
    "select_balanced",
    "select_headlines",
    "select_hit_rate",
    "select_value",
    "RISK_PROFILES",
    "ULTRA_CAUTION",
    "RiskProfile",
    "cap_slate_stakes",
    "dollar_stake",
    "recommended_units",
    "risk_profile",
    "unit_dollars",
    "user_wager_view",
]
