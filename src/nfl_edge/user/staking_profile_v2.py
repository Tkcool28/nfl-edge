"""Account-level risk style for Task05F evaluator-unit staking V2.

The user controls bankroll and one global risk style. The evaluator controls
wager units; users cannot override a candidate's unit rating.

Contract: config/task05f_staking_v2_units_prereg.yaml
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


class RiskStyle(str, Enum):
    CAUTIOUS = "CAUTIOUS"
    CONSERVATIVE = "CONSERVATIVE"
    STANDARD = "STANDARD"
    AGGRESSIVE = "AGGRESSIVE"
    VERY_AGGRESSIVE = "VERY_AGGRESSIVE"


UNIT_FRACTION = {
    RiskStyle.CAUTIOUS: 0.005,
    RiskStyle.CONSERVATIVE: 0.0075,
    RiskStyle.STANDARD: 0.01,
    RiskStyle.AGGRESSIVE: 0.015,
    RiskStyle.VERY_AGGRESSIVE: 0.025,
}

OPEN_SLATE_EXPOSURE_CAP = {
    RiskStyle.CAUTIOUS: 0.03,
    RiskStyle.CONSERVATIVE: 0.05,
    RiskStyle.STANDARD: 0.07,
    RiskStyle.AGGRESSIVE: 0.10,
    RiskStyle.VERY_AGGRESSIVE: 0.15,
}

STYLE_WARNING = {
    RiskStyle.CAUTIOUS: None,
    RiskStyle.CONSERVATIVE: None,
    RiskStyle.STANDARD: None,
    RiskStyle.AGGRESSIVE: (
        "Aggressive staking increases bankroll swings. Wager quality and unit ratings "
        "do not improve because a larger risk style is selected."
    ),
    RiskStyle.VERY_AGGRESSIVE: (
        "Very Aggressive staking can place up to 5% of bankroll on one exceptional "
        "wager and materially increases drawdown risk. It does not make a wager more "
        "likely to win."
    ),
}


@dataclass(frozen=True)
class UserRiskProfile:
    bankroll: float
    risk_style: RiskStyle = RiskStyle.STANDARD

    def __post_init__(self) -> None:
        bankroll = float(self.bankroll)
        if not math.isfinite(bankroll) or bankroll <= 0.0:
            raise ValueError("bankroll must be finite and positive")
        object.__setattr__(self, "bankroll", bankroll)
        object.__setattr__(self, "risk_style", RiskStyle(self.risk_style))

    @property
    def fraction_of_bankroll_per_unit(self) -> float:
        return UNIT_FRACTION[self.risk_style]

    @property
    def open_slate_exposure_cap_fraction(self) -> float:
        return OPEN_SLATE_EXPOSURE_CAP[self.risk_style]

    @property
    def style_warning(self) -> str | None:
        return STYLE_WARNING[self.risk_style]
