"""Test the +EV calculator and Pinnacle-color logic."""
from nfl_edge.edge import (
    expected_value, kelly_fraction, best_pick_from_games, color_vs_pinnacle
)
import pandas as pd


def test_expected_value_positive():
    # 60% win prob at +100 (decimal 2.0): EV = 0.6*1 - 0.4 = 0.2
    ev = expected_value(0.60, 2.0)
    assert abs(ev - 0.20) < 1e-6


def test_expected_value_negative():
    # 40% win prob at +100 (decimal 2.0): EV = 0.4*1 - 0.6 = -0.2
    ev = expected_value(0.40, 2.0)
    assert abs(ev - (-0.20)) < 1e-6


def test_kelly_caps_at_zero():
    f = kelly_fraction(0.40, 2.0)
    assert f == 0.0


def test_kelly_under_one():
    f = kelly_fraction(0.60, 2.0)
    assert 0.0 < f < 1.0


def test_color_vs_pinnacle_better():
    # DK at -105, Pinnacle at -115 -> DK should be green (better for bettor)
    out = color_vs_pinnacle(-105, -110, -115)
    assert out["dk"][0] == "green"


def test_color_vs_pinnacle_worse():
    # DK at -125, Pinnacle at -110 -> DK should be red (worse)
    out = color_vs_pinnacle(-125, -120, -110)
    assert out["dk"][0] == "red"
