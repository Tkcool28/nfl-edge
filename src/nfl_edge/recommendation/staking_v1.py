"""Compatibility surface for the frozen Task05G staking policy V1.

The authoritative implementation lives in ``nfl_edge.staking_policy_v1`` so
base production contract/publication imports do not execute the eager
``nfl_edge.recommendation`` package initializer.  This module intentionally
re-exports that single implementation without changing staking semantics.
"""

from nfl_edge.staking_policy_v1 import (
    ALLOWED_STAKING_RELIABILITY,
    MINIMUM_STAKE_DOLLARS,
    PER_WAGER_BANKROLL_CAP_PCT,
    RISK_PROFILES,
    RISK_PROFILE_BY_NAME,
    ROUNDING_QUANTUM_DOLLARS,
    SLATE_BANKROLL_CAP_PCT,
    ULTRA_CAUTION,
    UNIT_LADDER,
    RiskProfile,
    cap_slate_stakes,
    dollar_stake,
    recommended_units,
    risk_profile,
    unit_dollars,
    user_wager_view,
)

__all__ = [
    "ALLOWED_STAKING_RELIABILITY",
    "MINIMUM_STAKE_DOLLARS",
    "PER_WAGER_BANKROLL_CAP_PCT",
    "RISK_PROFILES",
    "RISK_PROFILE_BY_NAME",
    "ROUNDING_QUANTUM_DOLLARS",
    "SLATE_BANKROLL_CAP_PCT",
    "ULTRA_CAUTION",
    "UNIT_LADDER",
    "RiskProfile",
    "cap_slate_stakes",
    "dollar_stake",
    "recommended_units",
    "risk_profile",
    "unit_dollars",
    "user_wager_view",
]
