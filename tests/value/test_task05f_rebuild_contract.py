from __future__ import annotations

import pytest

from nfl_edge.value.wager_economics import (
    OutcomeProbabilities,
    PriceStatus,
    Settlement,
    classify_price,
    empirical_spread_probabilities,
    empirical_total_probabilities,
    expected_value_three_way,
    moneyline_settlement,
    spread_residual_threshold,
    total_residual_threshold,
)


def test_three_way_probability_contract_and_ev_push_zero():
    p = OutcomeProbabilities(p_win=0.50, p_push=0.05, p_loss=0.45)
    # +100: +1 on win, 0 on push, -1 on loss => +0.05 EV.
    assert expected_value_three_way(p, 100) == pytest.approx(0.05)


def test_strict_value_is_any_positive_ev_not_minimum_threshold():
    # At -110, this is only a small positive EV; it still qualifies as VALUE.
    p = OutcomeProbabilities(p_win=0.525, p_push=0.0, p_loss=0.475)
    a = classify_price(p, -110)
    assert a.expected_value > 0.0
    assert a.strict_positive_value is True
    assert a.status is PriceStatus.VALUE


def test_play_through_never_relabels_negative_ev_as_value():
    p = OutcomeProbabilities(p_win=0.50, p_push=0.0, p_loss=0.50)
    a = classify_price(p, -108, play_through_price_american=-110)
    assert a.expected_value < 0.0
    assert a.strict_positive_value is False
    assert a.status is PriceStatus.PLAYABLE


def test_outside_play_through_is_lean_not_value():
    p = OutcomeProbabilities(p_win=0.50, p_push=0.0, p_loss=0.50)
    a = classify_price(p, -115, play_through_price_american=-110)
    assert a.strict_positive_value is False
    assert a.status is PriceStatus.LEAN


def test_unsupported_offer_is_pass_even_if_price_math_positive():
    p = OutcomeProbabilities(p_win=0.60, p_push=0.0, p_loss=0.40)
    a = classify_price(p, -110, supported=False, play_through_price_american=-200)
    assert a.expected_value > 0.0
    assert a.status is PriceStatus.PASS


def test_moneyline_tie_is_push_not_loss():
    assert moneyline_settlement("home", 20, 20) is Settlement.PUSH
    assert moneyline_settlement("away", 20, 20) is Settlement.PUSH
    assert moneyline_settlement("home", 21, 20) is Settlement.WIN
    assert moneyline_settlement("away", 21, 20) is Settlement.LOSS


def test_spread_threshold_is_offer_specific():
    # Expected home margin +3.
    # HOME -3: threshold residual 0 (win when residual > 0).
    # AWAY +3.5: threshold residual +0.5 (win when residual < +0.5).
    # They are NOT exact complements because both can win when 0 < residual < .5.
    assert spread_residual_threshold(3.0, "home", -3.0) == pytest.approx((0.0, "gt"))
    assert spread_residual_threshold(3.0, "away", +3.5) == pytest.approx((0.5, "lt"))


def test_asymmetric_shopped_spreads_are_not_forced_complements():
    residuals = [-2.0, -1.0, 0.0, 0.25, 0.75, 1.0, 2.0]
    home = empirical_spread_probabilities(residuals, 3.0, "home", -3.0)
    away = empirical_spread_probabilities(residuals, 3.0, "away", +3.5)
    assert home.p_win == pytest.approx(4 / 7)
    assert home.p_push == pytest.approx(1 / 7)
    assert away.p_win == pytest.approx(4 / 7)
    assert away.p_push == 0.0
    assert home.p_win + away.p_win > 1.0  # legitimate overlap, not incoherence


def test_exact_mirrored_integer_spreads_include_push_mass():
    residuals = [-1.0, 0.0, 1.0]
    home = empirical_spread_probabilities(residuals, 3.0, "home", -3.0)
    away = empirical_spread_probabilities(residuals, 3.0, "away", +3.0)
    assert home.p_win == pytest.approx(1 / 3)
    assert away.p_win == pytest.approx(1 / 3)
    assert home.p_push == pytest.approx(1 / 3)
    assert away.p_push == pytest.approx(1 / 3)
    assert home.p_win + away.p_win + home.p_push == pytest.approx(1.0)


def test_total_threshold_is_exact_line_specific():
    assert total_residual_threshold(45.0, "over", 44.5) == pytest.approx((-0.5, "gt"))
    assert total_residual_threshold(45.0, "under", 45.5) == pytest.approx((0.5, "lt"))


def test_asymmetric_shopped_totals_are_not_forced_complements():
    residuals = [-1.0, -0.25, 0.0, 0.25, 1.0]
    over = empirical_total_probabilities(residuals, 45.0, "over", 44.5)
    under = empirical_total_probabilities(residuals, 45.0, "under", 45.5)
    assert over.p_win == pytest.approx(4 / 5)
    assert under.p_win == pytest.approx(4 / 5)
    assert over.p_win + under.p_win > 1.0  # both wagers can win when final total is in the middle


def test_probability_object_rejects_missing_mass():
    with pytest.raises(ValueError):
        OutcomeProbabilities(0.5, 0.1, 0.3)
