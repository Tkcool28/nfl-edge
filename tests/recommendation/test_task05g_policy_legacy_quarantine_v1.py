"""Regression guard for Task05G legacy policy-path quarantine."""
from __future__ import annotations

import nfl_edge.recommendation as recommendation
import nfl_edge.recommendation.final_selectors_v2 as selectors
import nfl_edge.recommendation.policy as legacy_policy
import nfl_edge.recommendation.staking_v1 as staking


def test_policy_module_exposes_no_competing_selectors_or_staking() -> None:
    forbidden = {
        "select_hit_rate",
        "select_balanced",
        "select_value",
        "select_headlines",
        "recommended_units",
        "dollar_stake",
        "cap_slate_stakes",
        "RiskProfile",
        "RISK_PROFILES",
        "RISK_PROFILE_BY_NAME",
    }
    present = sorted(name for name in forbidden if hasattr(legacy_policy, name))
    assert present == []


def test_package_exports_are_canonical_not_legacy() -> None:
    assert recommendation.select_hit_rate is selectors.select_hit_rate
    assert recommendation.select_balanced is selectors.select_balanced
    assert recommendation.select_value is selectors.select_value
    assert recommendation.select_headlines is selectors.select_headlines
    assert recommendation.recommended_units is staking.recommended_units
    assert recommendation.dollar_stake is staking.dollar_stake
    assert recommendation.cap_slate_stakes is staking.cap_slate_stakes
    assert recommendation.RISK_PROFILES is staking.RISK_PROFILES


def test_only_frozen_risk_profile_names_exist() -> None:
    assert tuple(profile.name for profile in recommendation.RISK_PROFILES) == (
        "Cautious",
        "Conservative",
        "Normal",
        "Aggressive",
        "Ultra",
    )
    legacy_names = {"Steady", "Balanced", "Bold", "High Gear"}
    assert not legacy_names.intersection(profile.name for profile in recommendation.RISK_PROFILES)


def test_policy_retains_only_shared_adapter_surface() -> None:
    assert legacy_policy.NO_HIT_RATE_PLAY == "NO_HIT_RATE_PLAY"
    assert legacy_policy.NO_BALANCED_PLAY == "NO_BALANCED_PLAY"
    assert legacy_policy.NO_VALUE_PLAY == "NO_VALUE_PLAY"
    assert callable(legacy_policy.shop_exact_offers)
    assert callable(legacy_policy.evaluate_policy_offer)
