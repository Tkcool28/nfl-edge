"""User-level Task05F staking engine.

This module sizes an already-evaluated wager for one validated account profile.
It is downstream of the evaluator, Play Through, reliability, and selectors.
It cannot create Value or change any upstream candidate field.

Contract: config/task05f_staking_v1.yaml
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
import math
from typing import Any, Mapping

from nfl_edge.user.staking_profile import FlatStakeMode, StakingStrategy, UserStakingProfile


ALLOWED_RELIABILITY = frozenset({"HIGH", "MEDIUM"})
ACTIONABLE_STATUSES = frozenset({"VALUE", "PLAYABLE"})
FLAT_BANKROLL_FRACTION = 0.01
KELLY_HARD_CAP_FRACTION = 0.05
KELLY_MULTIPLIER = {
    StakingStrategy.HALF_KELLY: 0.50,
    StakingStrategy.QUARTER_KELLY: 0.25,
}
MANUAL_FLAT_CAUTION = (
    "Manual flat stake overrides bankroll-based sizing. Larger fixed stakes can "
    "create greater bankroll drawdowns than the default bankroll-based amount."
)


@dataclass(frozen=True)
class StakeRecommendation:
    strategy: str
    bankroll: float
    recommended_stake: float
    recommended_stake_fraction: float
    reason: str
    full_kelly_fraction: float | None
    fractional_kelly_before_cap: float | None
    cap_applied: bool
    manual_flat_caution: str | None
    staking_probability: float | None
    actionable_decimal_price: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finite(value: Any) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _decimal(value: float) -> Decimal:
    return Decimal(str(float(value)))


def _round_currency(value: float) -> float:
    """Nearest cent using decimal ROUND_HALF_UP, independent of binary ties."""
    return float(_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _round_currency_with_ceiling(value: float, ceiling: float) -> tuple[float, bool]:
    """Nearest cent unless that would violate a hard dollar ceiling.

    If nearest-cent rounding would exceed the ceiling, use the greatest whole
    cent not above the ceiling. If no positive cent fits, return zero.
    """
    target = _decimal(value)
    limit = _decimal(ceiling)
    if limit < 0:
        raise ValueError("currency ceiling cannot be negative")
    rounded = target.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rounded <= limit:
        return float(rounded), False
    floored_limit = limit.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return float(floored_limit), True


def full_kelly_fraction(decimal_price: float, probability: float) -> float:
    """Standard Kelly fraction using conditional non-push staking probability."""
    price = float(decimal_price)
    p = float(probability)
    if not math.isfinite(price) or price <= 1.0:
        raise ValueError("actionable decimal price must be finite and > 1")
    if not math.isfinite(p) or not 0.0 <= p <= 1.0:
        raise ValueError("staking probability must be finite and in [0,1]")
    b = price - 1.0
    q = 1.0 - p
    return (b * p - q) / b


def _zero(
    profile: UserStakingProfile,
    candidate: Mapping[str, Any],
    reason: str,
    *,
    full_kelly: float | None = None,
    fractional_before_cap: float | None = None,
    manual_caution: str | None = None,
    cap_applied: bool = False,
) -> StakeRecommendation:
    p = candidate.get("staking_probability")
    price = candidate.get("actionable_decimal_price")
    return StakeRecommendation(
        strategy=profile.staking_strategy.value,
        bankroll=float(profile.bankroll),
        recommended_stake=0.0,
        recommended_stake_fraction=0.0,
        reason=reason,
        full_kelly_fraction=full_kelly,
        fractional_kelly_before_cap=fractional_before_cap,
        cap_applied=cap_applied,
        manual_flat_caution=manual_caution,
        staking_probability=None if not _finite(p) else float(p),
        actionable_decimal_price=None if not _finite(price) else float(price),
    )


def recommend_stake(
    candidate: Mapping[str, Any],
    profile: UserStakingProfile,
) -> StakeRecommendation:
    """Return one deterministic recommended stake for a candidate/profile pair."""
    if not bool(candidate.get("supported")):
        return _zero(profile, candidate, "UNSUPPORTED")

    reliability = str(candidate.get("reliability", ""))
    if reliability not in ALLOWED_RELIABILITY:
        return _zero(profile, candidate, "LOW_RELIABILITY")

    status = str(candidate.get("price_status", ""))
    if status not in ACTIONABLE_STATUSES:
        return _zero(profile, candidate, "STATUS_NOT_ACTIONABLE")

    strategy = profile.staking_strategy
    bankroll = float(profile.bankroll)

    if strategy is StakingStrategy.FLAT:
        caution = None
        if profile.flat_stake_mode is FlatStakeMode.MANUAL:
            amount = float(profile.manual_flat_stake)  # validated by profile
            caution = MANUAL_FLAT_CAUTION
        else:
            amount = bankroll * FLAT_BANKROLL_FRACTION

        rounded, constrained = _round_currency_with_ceiling(amount, bankroll)
        if rounded <= 0.0:
            return _zero(
                profile,
                candidate,
                "ROUNDED_TO_ZERO",
                manual_caution=caution,
            )
        return StakeRecommendation(
            strategy=strategy.value,
            bankroll=bankroll,
            recommended_stake=rounded,
            recommended_stake_fraction=float(rounded / bankroll),
            reason="STAKE_RECOMMENDED",
            full_kelly_fraction=None,
            fractional_kelly_before_cap=None,
            cap_applied=constrained,
            manual_flat_caution=caution,
            staking_probability=(
                None
                if not _finite(candidate.get("staking_probability"))
                else float(candidate["staking_probability"])
            ),
            actionable_decimal_price=(
                None
                if not _finite(candidate.get("actionable_decimal_price"))
                else float(candidate["actionable_decimal_price"])
            ),
        )

    # Kelly account modes deliberately refuse PLAYABLE rows. Play Through is a
    # casual actionability concession, not a positive-growth claim.
    if status == "PLAYABLE":
        return _zero(profile, candidate, "PLAYABLE_NOT_KELLY_VALUE")

    if candidate.get("strict_positive_value") is not True:
        return _zero(profile, candidate, "NOT_STRICT_VALUE")

    p = candidate.get("staking_probability")
    price = candidate.get("actionable_decimal_price")
    if not _finite(p) or not _finite(price):
        return _zero(profile, candidate, "NO_POSITIVE_STAKING_EDGE")

    full = full_kelly_fraction(float(price), float(p))
    if full <= 0.0:
        return _zero(profile, candidate, "NO_POSITIVE_STAKING_EDGE", full_kelly=full)

    multiplier = KELLY_MULTIPLIER[strategy]
    fractional = multiplier * full
    capped = min(fractional, KELLY_HARD_CAP_FRACTION)
    dollar_cap = bankroll * KELLY_HARD_CAP_FRACTION
    rounded, rounding_constrained = _round_currency_with_ceiling(bankroll * capped, dollar_cap)
    cap_applied = fractional > KELLY_HARD_CAP_FRACTION or rounding_constrained
    if rounded <= 0.0:
        return _zero(
            profile,
            candidate,
            "ROUNDED_TO_ZERO",
            full_kelly=full,
            fractional_before_cap=fractional,
            cap_applied=cap_applied,
        )

    return StakeRecommendation(
        strategy=strategy.value,
        bankroll=bankroll,
        recommended_stake=rounded,
        recommended_stake_fraction=float(rounded / bankroll),
        reason="STAKE_RECOMMENDED",
        full_kelly_fraction=float(full),
        fractional_kelly_before_cap=float(fractional),
        cap_applied=cap_applied,
        manual_flat_caution=None,
        staking_probability=float(p),
        actionable_decimal_price=float(price),
    )
