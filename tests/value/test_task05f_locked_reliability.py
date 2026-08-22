import math

from nfl_edge.value.locked_reliability import (
    cap_reliability,
    conditional_nonpush_probability,
    conservative_staking_probability,
    expected_value_from_decimal,
    fit_candidate_uncertainty,
    staking_outcome_probabilities,
    uncertainty_factor,
)


def _history(n: int = 160):
    rows = []
    for i in range(n):
        block = f"2020-{(i // 8) + 1:02d}"
        p = 0.55 if i % 2 == 0 else 0.45
        y = 1 if i % 2 == 0 else 0
        rows.append((block, p, y))
    return rows


def test_conditional_nonpush_probability_excludes_push_mass():
    q = conditional_nonpush_probability(0.52, 0.04, 0.44)
    assert math.isclose(q, 0.52 / 0.96, abs_tol=1e-12)


def test_candidate_uncertainty_cold_start_is_low_with_null_radius():
    state = fit_candidate_uncertainty(_history(127), minimum_rows=128)
    assert state.radius is None
    assert state.support_n == 127
    assert state.tier == "LOW"
    assert state.stable is False


def test_candidate_uncertainty_is_deterministic():
    rows = _history(240)
    a = fit_candidate_uncertainty(rows)
    b = fit_candidate_uncertainty(rows)
    assert a == b
    assert a.radius is not None
    assert a.radius >= 0.0


def test_final_reliability_can_never_upgrade_base_tier():
    assert cap_reliability("LOW", "HIGH") == "LOW"
    assert cap_reliability("MEDIUM", "HIGH") == "MEDIUM"
    assert cap_reliability("HIGH", "MEDIUM") == "MEDIUM"
    assert cap_reliability("HIGH", "LOW") == "LOW"
    assert cap_reliability("UNSUPPORTED", "HIGH") == "UNSUPPORTED"


def test_missing_uncertainty_collapses_staking_probability_to_market_anchor():
    q = conservative_staking_probability(0.62, 0.55, "HIGH", None)
    assert math.isclose(q, 0.55, abs_tol=1e-12)


def test_staking_probability_stays_between_market_anchor_and_evaluator():
    q = conservative_staking_probability(0.62, 0.55, "MEDIUM", 0.02)
    assert 0.55 <= q <= 0.62
    q2 = conservative_staking_probability(0.42, 0.50, "LOW", 0.03)
    assert 0.42 <= q2 <= 0.50


def test_uncertainty_factor_is_bounded_and_monotone():
    assert uncertainty_factor(None) == 0.0
    assert uncertainty_factor(0.0) == 1.0
    assert math.isclose(uncertainty_factor(0.05), 0.5, abs_tol=1e-12)
    assert uncertainty_factor(0.10) == 0.0
    assert uncertainty_factor(0.50) == 0.0


def test_staking_outcomes_preserve_push_mass_and_sum_to_one():
    p_win, p_push, p_loss = staking_outcome_probabilities(0.60, 0.04)
    assert math.isclose(p_push, 0.04, abs_tol=1e-12)
    assert math.isclose(p_win, 0.576, abs_tol=1e-12)
    assert math.isclose(p_loss, 0.384, abs_tol=1e-12)
    assert math.isclose(p_win + p_push + p_loss, 1.0, abs_tol=1e-12)


def test_three_way_staking_ev_known_example():
    # 57.6% win, 4% push, 38.4% loss at decimal 2.00.
    ev = expected_value_from_decimal(0.576, 0.384, 2.00)
    assert math.isclose(ev, 0.192, abs_tol=1e-12)
