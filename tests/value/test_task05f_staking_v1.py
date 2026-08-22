import pytest

from nfl_edge.user.staking_profile import FlatStakeMode, StakingStrategy, UserStakingProfile
from nfl_edge.value.staking import (
    KELLY_HARD_CAP_FRACTION,
    MANUAL_FLAT_CAUTION,
    full_kelly_fraction,
    recommend_stake,
)


def _candidate(
    *,
    status: str = "VALUE",
    reliability: str = "MEDIUM",
    supported: bool = True,
    strict_value: bool | None = None,
    staking_probability: float = 0.55,
    actionable_probability: float = 0.55,
    decimal_price: float = 2.0,
):
    if strict_value is None:
        strict_value = status == "VALUE"
    return {
        "supported": supported,
        "reliability": reliability,
        "price_status": status,
        "strict_positive_value": strict_value,
        "staking_probability": staking_probability,
        "actionable_probability": actionable_probability,
        "actionable_decimal_price": decimal_price,
    }


def _profile(
    strategy: StakingStrategy,
    bankroll: float = 100.0,
    *,
    flat_mode: FlatStakeMode = FlatStakeMode.BANKROLL_DERIVED,
    manual: float | None = None,
):
    return UserStakingProfile(
        bankroll=bankroll,
        staking_strategy=strategy,
        flat_stake_mode=flat_mode,
        manual_flat_stake=manual,
    )


def test_known_full_kelly_example():
    assert full_kelly_fraction(2.0, 0.55) == pytest.approx(0.10)


def test_half_kelly_is_half_full_kelly_before_cap():
    rec = recommend_stake(_candidate(staking_probability=0.53), _profile(StakingStrategy.HALF_KELLY))
    assert rec.full_kelly_fraction == pytest.approx(0.06)
    assert rec.fractional_kelly_before_cap == pytest.approx(0.03)
    assert rec.recommended_stake == pytest.approx(3.00)
    assert rec.cap_applied is False


def test_quarter_kelly_is_quarter_full_kelly_before_cap():
    rec = recommend_stake(_candidate(staking_probability=0.55), _profile(StakingStrategy.QUARTER_KELLY))
    assert rec.full_kelly_fraction == pytest.approx(0.10)
    assert rec.fractional_kelly_before_cap == pytest.approx(0.025)
    assert rec.recommended_stake == pytest.approx(2.50)


def test_five_percent_hard_cap_is_enforced():
    rec = recommend_stake(_candidate(staking_probability=0.80), _profile(StakingStrategy.HALF_KELLY, 200.0))
    assert rec.fractional_kelly_before_cap == pytest.approx(0.30)
    assert rec.recommended_stake == pytest.approx(10.00)
    assert rec.recommended_stake_fraction == pytest.approx(KELLY_HARD_CAP_FRACTION)
    assert rec.cap_applied is True


def test_cent_rounding_cannot_breach_five_percent_cap():
    rec = recommend_stake(_candidate(staking_probability=0.80), _profile(StakingStrategy.HALF_KELLY, 0.10))
    assert rec.reason == "ROUNDED_TO_ZERO"
    assert rec.recommended_stake == 0.0
    assert rec.cap_applied is True


def test_kelly_zero_when_full_kelly_nonpositive():
    rec = recommend_stake(_candidate(staking_probability=0.49), _profile(StakingStrategy.QUARTER_KELLY))
    assert rec.full_kelly_fraction < 0.0
    assert rec.recommended_stake == 0.0
    assert rec.reason == "NO_POSITIVE_STAKING_EDGE"


def test_kelly_zero_on_playable_even_if_math_would_be_positive():
    candidate = _candidate(status="PLAYABLE", strict_value=False, staking_probability=0.80)
    rec = recommend_stake(candidate, _profile(StakingStrategy.HALF_KELLY))
    assert rec.reason == "PLAYABLE_NOT_KELLY_VALUE"
    assert rec.recommended_stake == 0.0


def test_kelly_requires_strict_value():
    candidate = _candidate(status="VALUE", strict_value=False, staking_probability=0.70)
    rec = recommend_stake(candidate, _profile(StakingStrategy.HALF_KELLY))
    assert rec.reason == "NOT_STRICT_VALUE"
    assert rec.recommended_stake == 0.0


def test_flat_bankroll_derived_is_one_percent():
    rec = recommend_stake(_candidate(), _profile(StakingStrategy.FLAT, bankroll=250.0))
    assert rec.recommended_stake == pytest.approx(2.50)
    assert rec.recommended_stake_fraction == pytest.approx(0.01)
    assert rec.reason == "STAKE_RECOMMENDED"


def test_flat_manual_override_is_exact_and_always_warns():
    profile = _profile(
        StakingStrategy.FLAT,
        bankroll=250.0,
        flat_mode=FlatStakeMode.MANUAL,
        manual=5.0,
    )
    rec = recommend_stake(_candidate(), profile)
    assert rec.recommended_stake == pytest.approx(5.00)
    assert rec.manual_flat_caution == MANUAL_FLAT_CAUTION


def test_manual_flat_cannot_exceed_bankroll():
    with pytest.raises(ValueError, match="cannot exceed bankroll"):
        _profile(
            StakingStrategy.FLAT,
            bankroll=10.0,
            flat_mode=FlatStakeMode.MANUAL,
            manual=10.01,
        )


def test_profile_rejects_nonpositive_bankroll():
    with pytest.raises(ValueError, match="bankroll"):
        _profile(StakingStrategy.FLAT, bankroll=0.0)


def test_nonflat_profile_rejects_manual_flat_stake():
    with pytest.raises(ValueError, match="only valid with FLAT"):
        _profile(StakingStrategy.HALF_KELLY, manual=1.0)


def test_low_reliability_gets_zero_stake():
    rec = recommend_stake(_candidate(reliability="LOW"), _profile(StakingStrategy.FLAT))
    assert rec.reason == "LOW_RELIABILITY"
    assert rec.recommended_stake == 0.0


def test_unsupported_gets_zero_stake():
    rec = recommend_stake(_candidate(supported=False), _profile(StakingStrategy.FLAT))
    assert rec.reason == "UNSUPPORTED"
    assert rec.recommended_stake == 0.0


@pytest.mark.parametrize("status", ["LEAN", "PASS"])
def test_lean_and_pass_get_zero_stake(status):
    rec = recommend_stake(_candidate(status=status, strict_value=False), _profile(StakingStrategy.FLAT))
    assert rec.reason == "STATUS_NOT_ACTIONABLE"
    assert rec.recommended_stake == 0.0


def test_flat_same_amount_for_value_and_playable():
    profile = _profile(StakingStrategy.FLAT, bankroll=500.0)
    value = recommend_stake(_candidate(status="VALUE"), profile)
    playable = recommend_stake(_candidate(status="PLAYABLE", strict_value=False), profile)
    assert value.recommended_stake == pytest.approx(5.00)
    assert playable.recommended_stake == pytest.approx(5.00)
    assert value.reason == playable.reason == "STAKE_RECOMMENDED"


def test_staking_probability_not_actionable_probability_drives_kelly():
    candidate = _candidate(
        status="VALUE",
        strict_value=True,
        staking_probability=0.49,
        actionable_probability=0.70,
        decimal_price=2.0,
    )
    rec = recommend_stake(candidate, _profile(StakingStrategy.HALF_KELLY))
    assert rec.reason == "NO_POSITIVE_STAKING_EDGE"
    assert rec.recommended_stake == 0.0


def test_deterministic_half_up_currency_rounding():
    rec = recommend_stake(_candidate(), _profile(StakingStrategy.FLAT, bankroll=1.5))
    assert rec.recommended_stake == pytest.approx(0.02)


def test_tiny_positive_flat_that_rounds_to_zero_gets_zero():
    rec = recommend_stake(_candidate(), _profile(StakingStrategy.FLAT, bankroll=0.40))
    assert rec.recommended_stake == 0.0
    assert rec.reason == "ROUNDED_TO_ZERO"
