"""Account-level staking state for NFL EDGE.

The account chooses one global staking strategy. Wager-specific math lives in
``nfl_edge.value.staking``; this module only validates user-owned settings.

Contract: config/task05f_staking_v1.yaml
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


class StakingStrategy(str, Enum):
    HALF_KELLY = "HALF_KELLY"
    QUARTER_KELLY = "QUARTER_KELLY"
    FLAT = "FLAT"


class FlatStakeMode(str, Enum):
    BANKROLL_DERIVED = "BANKROLL_DERIVED"
    MANUAL = "MANUAL"


@dataclass(frozen=True)
class UserStakingProfile:
    bankroll: float
    staking_strategy: StakingStrategy
    flat_stake_mode: FlatStakeMode = FlatStakeMode.BANKROLL_DERIVED
    manual_flat_stake: float | None = None

    def __post_init__(self) -> None:
        bankroll = float(self.bankroll)
        if not math.isfinite(bankroll) or bankroll <= 0.0:
            raise ValueError("bankroll must be finite and positive")

        strategy = StakingStrategy(self.staking_strategy)
        flat_mode = FlatStakeMode(self.flat_stake_mode)
        object.__setattr__(self, "staking_strategy", strategy)
        object.__setattr__(self, "flat_stake_mode", flat_mode)

        manual = self.manual_flat_stake
        if strategy is not StakingStrategy.FLAT:
            if manual is not None:
                raise ValueError("manual flat stake is only valid with FLAT strategy")
            return

        if flat_mode is FlatStakeMode.BANKROLL_DERIVED:
            if manual is not None:
                raise ValueError("manual flat stake must be omitted in BANKROLL_DERIVED mode")
            return

        if manual is None:
            raise ValueError("MANUAL flat mode requires manual_flat_stake")
        amount = float(manual)
        if not math.isfinite(amount) or amount <= 0.0:
            raise ValueError("manual flat stake must be finite and positive")
        if amount > bankroll:
            raise ValueError("manual flat stake cannot exceed bankroll")
