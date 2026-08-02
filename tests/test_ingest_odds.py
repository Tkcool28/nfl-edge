"""Test the Odds API client helpers (no live network call)."""
from nfl_edge.ingest_odds import american_to_decimal, american_to_implied, remove_vig_proportional


def test_american_to_decimal_positive():
    assert american_to_decimal(150) == 2.5
    assert american_to_decimal(100) == 2.0


def test_american_to_decimal_negative():
    assert american_to_decimal(-200) == 1.5
    assert american_to_decimal(-110) == 1.0 + 100/110


def test_american_to_implied():
    assert abs(american_to_implied(-110) - 110/210) < 1e-6
    assert abs(american_to_implied(150) - 100/250) < 1e-6


def test_remove_vig_symmetric():
    # At -110/-110, implied is 52.38% each, total 104.76%, no-vig should be 50/50
    p_h, p_a = remove_vig_proportional(-110, -110)
    assert abs(p_h - 0.5) < 0.01
    assert abs(p_a - 0.5) < 0.01


def test_remove_vig_favorite():
    # Favorite at -200, dog at +175
    p_h, p_a = remove_vig_proportional(-200, 175)
    assert p_h + p_a == 1.0
    assert p_h > 0.5
