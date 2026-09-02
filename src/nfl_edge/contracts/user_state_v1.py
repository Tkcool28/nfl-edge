"""Persistent user bankroll/risk-profile contract V1."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nfl_edge.contracts.common_v1 import (
    USER_STATE_SCHEMA_VERSION,
    ContractValidationError,
    require_string,
    validate_units,
    validate_utc_timestamp,
)
from nfl_edge.recommendation.staking_v1 import RISK_PROFILE_BY_NAME, dollar_stake

RISK_PROFILES = tuple(RISK_PROFILE_BY_NAME)


@dataclass(frozen=True)
class UserProfileState:
    user_id: str
    bankroll: float
    risk_profile: str
    created_at: str
    updated_at: str
    schema_version: str = USER_STATE_SCHEMA_VERSION

    def validate(self) -> "UserProfileState":
        require_string(self.user_id, "profile.user_id")
        if self.schema_version != USER_STATE_SCHEMA_VERSION:
            raise ContractValidationError(f"profile.schema_version must equal {USER_STATE_SCHEMA_VERSION}")
        amount = Decimal(str(self.bankroll))
        if not amount.is_finite():
            raise ContractValidationError("profile.bankroll must be finite")
        if amount < 0 or amount > Decimal("1000000000"):
            raise ContractValidationError("profile.bankroll must be between 0 and 1,000,000,000 inclusive")
        if amount.as_tuple().exponent < -2:
            raise ContractValidationError("profile.bankroll must have at most two decimal places")
        if self.risk_profile not in RISK_PROFILE_BY_NAME:
            raise ContractValidationError(f"profile.risk_profile must be one of {tuple(RISK_PROFILE_BY_NAME)}")
        validate_utc_timestamp(self.created_at, "profile.created_at")
        validate_utc_timestamp(self.updated_at, "profile.updated_at")
        return self


def user_specific_stake(profile: UserProfileState, recommended_units: float) -> float:
    profile.validate()
    units = validate_units(recommended_units, "recommended_units")
    return dollar_stake(profile.bankroll, profile.risk_profile, units)


def profile_update_preserves_recommendation(
    before: UserProfileState,
    after: UserProfileState,
    *,
    recommended_units: float,
) -> tuple[float, float, float]:
    """Units stay frozen; only the derived dollar stake may change."""
    before.validate()
    after.validate()
    units = validate_units(recommended_units, "recommended_units")
    return units, user_specific_stake(before, units), user_specific_stake(after, units)
