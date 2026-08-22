import pytest

from nfl_edge.value.wager_economics import (
    empirical_spread_probabilities,
    empirical_total_probabilities,
    line_allows_push,
)


def test_exact_mirrored_integer_spreads_share_push_cell():
    residuals = [-1.0, 0.0, 1.0]
    home = empirical_spread_probabilities(residuals, 3.0, "home", -3.0)
    away = empirical_spread_probabilities(residuals, 3.0, "away", 3.0)
    assert home.p_win == pytest.approx(1 / 3)
    assert away.p_win == pytest.approx(1 / 3)
    assert home.p_push == pytest.approx(1 / 3)
    assert away.p_push == pytest.approx(1 / 3)


def test_half_point_spread_cannot_push():
    residuals = [-1.0, 0.0, 1.0]
    home = empirical_spread_probabilities(residuals, 3.0, "home", -2.5)
    assert home.p_push == 0.0
    assert home.p_win + home.p_loss == pytest.approx(1.0)
    assert not line_allows_push(-2.5)


def test_exact_integer_total_shares_push_cell():
    residuals = [-1.0, 0.0, 1.0]
    over = empirical_total_probabilities(residuals, 45.0, "over", 45.0)
    under = empirical_total_probabilities(residuals, 45.0, "under", 45.0)
    assert over.p_win == pytest.approx(1 / 3)
    assert under.p_win == pytest.approx(1 / 3)
    assert over.p_push == pytest.approx(1 / 3)
    assert under.p_push == pytest.approx(1 / 3)


def test_asymmetric_shopped_lines_are_evaluated_as_distinct_wagers():
    residuals = [-2.0, -1.0, 0.0, 1.0, 2.0]
    home = empirical_spread_probabilities(residuals, 3.0, "home", -2.5)
    away = empirical_spread_probabilities(residuals, 3.0, "away", 3.5)
    assert home.p_push == 0.0
    assert away.p_push == 0.0
    assert home.p_win + away.p_win > 1.0
