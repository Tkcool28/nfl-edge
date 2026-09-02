from __future__ import annotations

import nfl_edge.recommendation as frozen_package
import nfl_edge.recommendation.final_selectors_v1 as v1
import nfl_edge.recommendation.final_selectors_v2 as v2
import nfl_edge.recommendation.live_v2 as live
import nfl_edge.recommendation.staking_v1 as staking


def test_frozen_package_root_remains_v1_for_historical_replay_contract():
    assert frozen_package.select_hit_rate is v1.select_hit_rate
    assert frozen_package.select_balanced is v1.select_balanced
    assert frozen_package.select_value is v1.select_value
    assert frozen_package.select_headlines is v1.select_headlines


def test_forward_live_api_routes_to_v2_selectors():
    assert live.select_hit_rate is v2.select_hit_rate
    assert live.select_balanced is v2.select_balanced
    assert live.select_value is v2.select_value
    assert live.select_headlines is v2.select_headlines


def test_forward_live_api_preserves_frozen_staking_surface():
    assert live.recommended_units is staking.recommended_units
    assert live.dollar_stake is staking.dollar_stake
    assert live.cap_slate_stakes is staking.cap_slate_stakes
    assert live.RISK_PROFILES is staking.RISK_PROFILES
