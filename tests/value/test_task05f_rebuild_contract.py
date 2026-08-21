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
    fair_american_three_way,
    fair_decimal_three_way,
    line_allows_push,
    moneyline_settlement,
    spread_residual_threshold,
    total_residual_threshold,
)


def test_three_way_probability_contract_and_ev_push_zero():
    p = OutcomeProbabilities(p_win=0.50, p_push=0.05, p_loss=0.45)
    # +100: +1 on win, 0 on push, -1 on loss => +0.05 EV.
    assert expected_value_three_way(p, 100) == pytest.approx(0.05)


def test_three_way_fair_price_accounts_for_push_mass():
    p = OutcomeProbabilities(p_win=0.50, p_push=0.05, p_loss=0.45)
    # Zero-EV decimal = 1 + p_loss/p_win = 1.90, i.e. about -111 American.
    assert fair_decimal_three_way(p) == pytest.approx(1.9)
    assert fair_american_three_way(p) == -111
    assert expected_value_three_way(p, fair_american_three_way(p)) == pytest.approx(0.0, abs=0.001)


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


def test_point_line_push_eligibility_uses_integer_score_lattice():
    assert line_allows_push(-3.0)
    assert line_allows_push(45.0)
    assert not line_allows_push(-3.5)
    assert not line_allows_push(45.5)


def test_spread_threshold_is_offer_specific():
    t_home, d_home = spread_residual_threshold(3.0, "home", -2.5)
    t_away, d_away = spread_residual_threshold(3.0, "away", +3.5)
    assert t_home == pytest.approx(-0.5)
    assert d_home == "gt"
    assert t_away == pytest.approx(+0.5)
    assert d_away == "lt"


def test_asymmetric_shopped_spreads_are_evaluated_at_their_own_lines():
    # HOME -2.5 and AWAY +3.5 are not a mirrored pair. Both wagers win if the
    # actual home margin is exactly 3, represented here by residual 0.
    residuals = [-2.0, -1.0, 0.0, 1.0, 2.0]
    home = empirical_spread_probabilities(residuals, 3.0, "home", -2.5)
    away = empirical_spread_probabilities(residuals, 3.0, "away", +3.5)
    assert home.p_push == 0.0
    assert away.p_push == 0.0
    # Jeffreys Beta(1/2,1/2): raw 3/5 becomes 3.5/6.
    assert home.p_win == pytest.approx(3.5 / 6.0)
    assert away.p_win == pytest.approx(3.5 / 6.0)
    assert home.p_win + away.p_win > 1.0  # legitimate middle, not evaluator incoherence


def test_exact_mirrored_integer_spreads_include_push_mass():
    # Integer line allows a push. The continuity cell around residual threshold 0
    # represents the single integer margin equal to 3. Symmetric Jeffreys smoothing
    # preserves 1/3 for the balanced 1/1/1 count case.
    residuals = [-1.0, 0.0, 1.0]
    home = empirical_spread_probabilities(residuals, 3.0, "home", -3.0)
    away = empirical_spread_probabilities(residuals, 3.0, "away", +3.0)
    assert home.p_win == pytest.approx(1 / 3)
    assert away.p_win == pytest.approx(1 / 3)
    assert home.p_push == pytest.approx(1 / 3)
    assert away.p_push == pytest.approx(1 / 3)
    assert home.p_win + away.p_win + home.p_push == pytest.approx(1.0)


def test_total_threshold_is_exact_line_specific():
    t_over, d_over = total_residual_threshold(45.0, "over", 44.5)
    t_under, d_under = total_residual_threshold(45.0, "under", 45.5)
    assert t_over == pytest.approx(-0.5)
    assert d_over == "gt"
    assert t_under == pytest.approx(+0.5)
    assert d_under == "lt"


def test_asymmetric_shopped_totals_are_not_forced_complements():
    residuals = [-1.0, -0.25, 0.0, 0.25, 1.0]
    over = empirical_total_probabilities(residuals, 45.0, "over", 44.5)
    under = empirical_total_probabilities(residuals, 45.0, "under", 45.5)
    # Raw 4/5 with fixed Jeffreys Beta smoothing -> 4.5/6.
    assert over.p_win == pytest.approx(4.5 / 6.0)
    assert under.p_win == pytest.approx(4.5 / 6.0)
    assert over.p_push == 0.0
    assert under.p_push == 0.0
    assert over.p_win + under.p_win > 1.0  # both wagers can win when final total is 45


def test_integer_total_line_estimates_push_mass_from_lattice_cell():
    residuals = [-1.0, 0.0, 1.0]
    over = empirical_total_probabilities(residuals, 45.0, "over", 45.0)
    under = empirical_total_probabilities(residuals, 45.0, "under", 45.0)
    assert over.p_push == pytest.approx(1 / 3)
    assert under.p_push == pytest.approx(1 / 3)
    assert over.p_win == pytest.approx(1 / 3)
    assert under.p_win == pytest.approx(1 / 3)


def test_probability_object_rejects_missing_mass():
    with pytest.raises(ValueError):
        OutcomeProbabilities(0.5, 0.1, 0.3)
