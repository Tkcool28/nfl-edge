"""Forward/live Task05G recommendation API after V5 diagnosis.

The package root remains frozen on V1 so historical product freezes and V5
reproduction keep their exact routing. New application code should import this
module explicitly for the post-V5 launch contract.
"""
from __future__ import annotations

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
from .policy import (
    NO_BALANCED_PLAY,
    NO_HIT_RATE_PLAY,
    NO_VALUE_PLAY,
    PolicyEvaluation,
    evaluate_policy_offer,
    shop_exact_offers,
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
