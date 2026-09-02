"""Base-runtime access to the hash-frozen Task05G staking policy V1.

The authoritative implementation remains the immutable
``nfl_edge/recommendation/staking_v1.py`` source.  Contracts load that exact
source file under a private module name so Python does not execute
``nfl_edge.recommendation.__init__`` and optional model-development imports are
not pulled into the base production contract/publication path.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_FROZEN_MODULE_NAME = "nfl_edge._frozen_staking_policy_v1"
_FROZEN_PATH = Path(__file__).with_name("recommendation") / "staking_v1.py"


def _load_frozen_staking_policy() -> ModuleType:
    existing = sys.modules.get(_FROZEN_MODULE_NAME)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(_FROZEN_MODULE_NAME, _FROZEN_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load frozen staking policy from {_FROZEN_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_FROZEN_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(_FROZEN_MODULE_NAME, None)
        raise
    return module


_frozen = _load_frozen_staking_policy()

ALLOWED_STAKING_RELIABILITY = _frozen.ALLOWED_STAKING_RELIABILITY
MINIMUM_STAKE_DOLLARS = _frozen.MINIMUM_STAKE_DOLLARS
PER_WAGER_BANKROLL_CAP_PCT = _frozen.PER_WAGER_BANKROLL_CAP_PCT
RISK_PROFILES = _frozen.RISK_PROFILES
RISK_PROFILE_BY_NAME = _frozen.RISK_PROFILE_BY_NAME
ROUNDING_QUANTUM_DOLLARS = _frozen.ROUNDING_QUANTUM_DOLLARS
SLATE_BANKROLL_CAP_PCT = _frozen.SLATE_BANKROLL_CAP_PCT
ULTRA_CAUTION = _frozen.ULTRA_CAUTION
UNIT_LADDER = _frozen.UNIT_LADDER
RiskProfile = _frozen.RiskProfile
cap_slate_stakes = _frozen.cap_slate_stakes
dollar_stake = _frozen.dollar_stake
recommended_units = _frozen.recommended_units
risk_profile = _frozen.risk_profile
unit_dollars = _frozen.unit_dollars
user_wager_view = _frozen.user_wager_view

__all__ = [
    "ALLOWED_STAKING_RELIABILITY",
    "MINIMUM_STAKE_DOLLARS",
    "PER_WAGER_BANKROLL_CAP_PCT",
    "RISK_PROFILES",
    "RISK_PROFILE_BY_NAME",
    "ROUNDING_QUANTUM_DOLLARS",
    "RiskProfile",
    "SLATE_BANKROLL_CAP_PCT",
    "ULTRA_CAUTION",
    "UNIT_LADDER",
    "cap_slate_stakes",
    "dollar_stake",
    "recommended_units",
    "risk_profile",
    "unit_dollars",
    "user_wager_view",
]
