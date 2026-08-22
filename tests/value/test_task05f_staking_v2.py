import pytest

from nfl_edge.user.staking_profile_v2 import RiskStyle, UserRiskProfile
from nfl_edge.value.staking_v2 import evaluator_units, playable_units, recommend_stake_v2, value_units


def _candidate(
    *,
    status: str = "VALUE",
    reliability: str = "MEDIUM",
    supported: bool = True,
    actionable_probability: float = 0.60,
    break_even_probability: float = 0.58,
    through_probability: float = 0.62,
    edge: float = 0.02,
    confidence: float = 0.50,
    concession: float = 0.01,
    staking_probability: float = 0.58,
    decimal_price: float = 2.0,
    season: int = 2024,
):
    return {
        "candidate_id": "g|spread|home",
        "game_id": "g",
        "season": season,
        "market_type": "spread",
        "selection": "home",
        "supported": supported,
        "reliability": reliability,
        "price_status": status,
        "strict_positive_value": status == "VALUE" and edge > 0.0,
        "actionable_probability": actionable_probability,
        "break_even_probability": break_even_probability,
        "play_through_break_even_probability": through_probability,
        "evaluated_edge_probability": edge,
        "play_through_confidence_multiplier": confidence,
        "play_through_break_even_concession": concession,
        "staking_probability": staking_probability,
        "actionable_decimal_price": decimal_price,
    }


def test_playable_at_fair_boundary_is_one_unit():
    row = _candidate(
        status="PLAYABLE",
        actionable_probability=0.60,
        break_even_probability=0.60,
        through_probability=0.62,
        edge=-0.001,
    )
    assert playable_units(row) == pytest.approx(1.0)


def test_playable_at_play_through_limit_is_half_unit():
    row = _candidate(
        status="PLAYABLE",
        actionable_probability=0.60,
        break_even_probability=0.62,
        through_probability=0.62,
        edge=-0.01,
    )
    assert playable_units(row) == pytest.approx(0.5)


def test_playable_mid_corridor_interpolates_continuously():
    row = _candidate(
        status="PLAYABLE",
        actionable_probability=0.60,
        break_even_probability=0.61,
        through_probability=0.62,
        edge=-0.005,
    )
    assert playable_units(row) == pytest.approx(0.75)


def test_playable_still_gets_nonzero_stake_when_internal_kelly_is_negative():
    row = _candidate(
        status="PLAYABLE",
        actionable_probability=0.60,
        break_even_probability=0.61,
        through_probability=0.62,
        edge=-0.005,
        staking_probability=0.49,
        decimal_price=2.0,
    )
    rec = recommend_stake_v2(row, UserRiskProfile(100.0, RiskStyle.STANDARD))
    assert rec.internal_full_kelly_fraction < 0.0
    assert rec.recommended_units == pytest.approx(0.75)
    assert rec.recommended_stake == pytest.approx(0.75)
    assert rec.unit_reason == "STAKE_RECOMMENDED_PLAYABLE"


def test_value_is_at_least_one_unit_and_never_above_two():
    low = _candidate(edge=0.0001, confidence=0.0, concession=0.01)
    high = _candidate(edge=1.0, confidence=1.0, concession=0.0)
    assert value_units(low) == pytest.approx(1.0)
    assert value_units(high) == pytest.approx(2.0)


def test_value_units_increase_with_confidence_and_relative_edge():
    base = _candidate(edge=0.01, confidence=0.25, concession=0.02)
    more_confident = _candidate(edge=0.01, confidence=0.75, concession=0.02)
    larger_edge = _candidate(edge=0.04, confidence=0.75, concession=0.02)
    assert value_units(base) < value_units(more_confident) < value_units(larger_edge)


def test_lean_pass_low_and_unsupported_are_zero_units():
    for row in (
        _candidate(status="LEAN", edge=-0.02),
        _candidate(status="PASS", edge=-0.04),
        _candidate(reliability="LOW"),
        _candidate(supported=False),
    ):
        units, _ = evaluator_units(row)
        assert units == 0.0


def test_user_cannot_override_evaluator_units_and_styles_only_change_dollar_scale():
    row = _candidate(edge=0.0001, confidence=0.0, concession=0.01)
    recs = [recommend_stake_v2(row, UserRiskProfile(100.0, style)) for style in RiskStyle]
    assert {rec.recommended_units for rec in recs} == {1.0}
    assert [rec.recommended_stake for rec in recs] == pytest.approx([0.50, 0.75, 1.00, 1.50, 2.50])
    with pytest.raises(TypeError):
        UserRiskProfile(100.0, RiskStyle.STANDARD, recommended_units=2.0)  # type: ignore[call-arg]


def test_five_risk_styles_have_expected_one_unit_bankroll_fractions():
    row = _candidate(edge=0.0001, confidence=0.0, concession=0.01)
    expected = {
        RiskStyle.CAUTIOUS: 0.005,
        RiskStyle.CONSERVATIVE: 0.0075,
        RiskStyle.STANDARD: 0.01,
        RiskStyle.AGGRESSIVE: 0.015,
        RiskStyle.VERY_AGGRESSIVE: 0.025,
    }
    for style, fraction in expected.items():
        rec = recommend_stake_v2(row, UserRiskProfile(100.0, style))
        assert rec.recommended_stake_fraction == pytest.approx(fraction)


def test_very_aggressive_never_exceeds_five_percent_per_wager():
    row = _candidate(edge=1.0, confidence=1.0, concession=0.0)
    rec = recommend_stake_v2(row, UserRiskProfile(100.0, RiskStyle.VERY_AGGRESSIVE))
    assert rec.recommended_units == pytest.approx(2.0)
    assert rec.recommended_stake == pytest.approx(5.0)
    assert rec.recommended_stake_fraction == pytest.approx(0.05)


def test_exposure_cap_reduces_stake_to_remaining_capacity():
    row = _candidate(edge=0.0001, confidence=0.0, concession=0.01)
    profile = UserRiskProfile(100.0, RiskStyle.STANDARD)  # 7% slate cap
    rec = recommend_stake_v2(row, profile, current_open_exposure_amount=6.50)
    assert rec.recommended_units == pytest.approx(1.0)
    assert rec.recommended_stake == pytest.approx(0.50)
    assert rec.exposure_cap_applied is True
    assert rec.exposure_capacity_remaining == pytest.approx(0.50)


def test_exposure_cap_reached_returns_zero_without_changing_unit_rating():
    row = _candidate(edge=0.0001, confidence=0.0, concession=0.01)
    profile = UserRiskProfile(100.0, RiskStyle.STANDARD)
    rec = recommend_stake_v2(row, profile, current_open_exposure_amount=7.00)
    assert rec.recommended_units == pytest.approx(1.0)
    assert rec.recommended_stake == 0.0
    assert rec.unit_reason == "EXPOSURE_CAP_REACHED"


def test_missing_exposure_state_does_not_change_unit_rating():
    row = _candidate(
        status="PLAYABLE",
        actionable_probability=0.60,
        break_even_probability=0.61,
        through_probability=0.62,
        edge=-0.005,
    )
    profile = UserRiskProfile(100.0, RiskStyle.AGGRESSIVE)
    no_state = recommend_stake_v2(row, profile)
    with_state = recommend_stake_v2(row, profile, current_open_exposure_amount=0.0)
    assert no_state.recommended_units == pytest.approx(with_state.recommended_units)
    assert no_state.recommended_stake == pytest.approx(with_state.recommended_stake)


def test_very_aggressive_profile_exposes_strong_warning():
    warning = UserRiskProfile(100.0, RiskStyle.VERY_AGGRESSIVE).style_warning
    assert warning is not None
    assert "5%" in warning
    assert "drawdown" in warning


def test_outcome_fields_and_2025_are_rejected():
    outcome = _candidate()
    outcome["settlement"] = "WIN"
    with pytest.raises(RuntimeError, match="forbidden outcome fields"):
        recommend_stake_v2(outcome, UserRiskProfile(100.0))
    with pytest.raises(RuntimeError, match="sealed season 2025"):
        recommend_stake_v2(_candidate(season=2025), UserRiskProfile(100.0))


def test_deterministic_currency_rounding_and_cap_never_overshoots():
    row = _candidate(edge=1.0, confidence=1.0, concession=0.0)
    profile = UserRiskProfile(1.01, RiskStyle.VERY_AGGRESSIVE)
    rec = recommend_stake_v2(row, profile)
    assert rec.recommended_stake <= 1.01 * 0.05 + 1e-12
