import math

from nfl_edge.value.market_math import break_even_probability
from nfl_edge.value.play_through import (
    assess_play_through,
    confidence_multiplier,
    play_through_limit,
)


def test_play_through_confidence_uses_locked_reliability_and_uncertainty_haircuts():
    assert math.isclose(confidence_multiplier("HIGH", 0.0), 1.0, abs_tol=1e-12)
    assert math.isclose(confidence_multiplier("MEDIUM", 0.05), 0.35, abs_tol=1e-12)
    assert math.isclose(confidence_multiplier("LOW", None), 0.0, abs_tol=1e-12)
    assert math.isclose(confidence_multiplier("UNSUPPORTED", 0.0), 0.0, abs_tol=1e-12)


def test_maximum_confidence_grants_exactly_one_percentage_point_break_even_concession():
    confidence, concession, q_play, _ = play_through_limit(0.55, "HIGH", 0.0)
    assert math.isclose(confidence, 1.0, abs_tol=1e-12)
    assert math.isclose(concession, 0.01, abs_tol=1e-12)
    assert math.isclose(q_play, 0.56, abs_tol=1e-12)


def test_displayed_play_through_american_price_is_conservative():
    _, _, q_play, price = play_through_limit(0.55, "HIGH", 0.0)
    assert break_even_probability(price) <= q_play + 1e-12
    # One integer worse is no longer guaranteed to satisfy the mathematical limit.
    assert break_even_probability(price - 1) > q_play


def test_positive_ev_is_always_value_not_playable():
    result = assess_play_through(
        supported=True,
        strict_expected_value=0.001,
        conditional_nonpush_probability=0.55,
        current_break_even_probability=0.54,
        reliability="HIGH",
        uncertainty_radius=0.0,
    )
    assert result.status == "VALUE"


def test_small_negative_ev_inside_confidence_envelope_is_playable():
    result = assess_play_through(
        supported=True,
        strict_expected_value=-0.005,
        conditional_nonpush_probability=0.55,
        current_break_even_probability=0.556,
        reliability="HIGH",
        uncertainty_radius=0.0,
    )
    assert result.status == "PLAYABLE"
    assert result.play_through_break_even_probability == 0.56


def test_negative_ev_outside_envelope_is_lean():
    result = assess_play_through(
        supported=True,
        strict_expected_value=-0.02,
        conditional_nonpush_probability=0.55,
        current_break_even_probability=0.57,
        reliability="HIGH",
        uncertainty_radius=0.0,
    )
    assert result.status == "LEAN"


def test_low_confidence_gets_smaller_play_through_concession():
    high = assess_play_through(
        supported=True,
        strict_expected_value=-0.005,
        conditional_nonpush_probability=0.55,
        current_break_even_probability=0.553,
        reliability="HIGH",
        uncertainty_radius=0.0,
    )
    low = assess_play_through(
        supported=True,
        strict_expected_value=-0.005,
        conditional_nonpush_probability=0.55,
        current_break_even_probability=0.553,
        reliability="LOW",
        uncertainty_radius=0.05,
    )
    assert high.status == "PLAYABLE"
    assert low.status == "LEAN"
    assert high.break_even_concession > low.break_even_concession


def test_unsupported_is_pass():
    result = assess_play_through(
        supported=False,
        strict_expected_value=None,
        conditional_nonpush_probability=None,
        current_break_even_probability=None,
        reliability="UNSUPPORTED",
        uncertainty_radius=None,
    )
    assert result.status == "PASS"
    assert result.play_through_price_american is None


def test_nonpositive_ev_can_never_be_labeled_value():
    for current_be in (0.54, 0.55, 0.556, 0.60):
        result = assess_play_through(
            supported=True,
            strict_expected_value=-1e-9,
            conditional_nonpush_probability=0.55,
            current_break_even_probability=current_be,
            reliability="HIGH",
            uncertainty_radius=0.0,
        )
        assert result.status != "VALUE"
