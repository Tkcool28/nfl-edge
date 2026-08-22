import math

from nfl_edge.value.calibration_v3 import (
    calibrated_point_mean,
    fit_logit_pool_calibration,
    fit_price_aware_point_calibration,
    market_implied_mean,
    pooled_probability,
    robust_market_scale,
)


def test_logit_pool_probability_stays_between_market_and_model():
    rows = [(0.70, 0.55, 1)] * 80 + [(0.30, 0.45, 0)] * 80
    state = fit_logit_pool_calibration(rows, minimum_prior=128)
    assert state.supported
    p = pooled_probability(0.70, 0.55, state)
    assert 0.55 <= p <= 0.70


def test_logit_pool_never_reverses_disagreement():
    rows = [(0.65, 0.55, 1)] * 80 + [(0.35, 0.45, 0)] * 80
    state = fit_logit_pool_calibration(rows, minimum_prior=128)
    assert state.supported
    assert pooled_probability(0.65, 0.55, state) >= 0.55
    assert pooled_probability(0.35, 0.45, state) <= 0.45


def test_logit_pool_can_collapse_to_market_when_model_is_bad():
    rows = []
    for i in range(200):
        y = i % 2
        p_market = 0.90 if y else 0.10
        p_model = 0.10 if y else 0.90
        rows.append((p_model, p_market, y))
    state = fit_logit_pool_calibration(rows, minimum_prior=128)
    assert state.supported
    assert state.weight == 0.0


def test_logit_pool_can_use_model_when_model_is_better():
    rows = []
    for i in range(200):
        y = i % 2
        p_model = 0.90 if y else 0.10
        p_market = 0.55 if y else 0.45
        rows.append((p_model, p_market, y))
    state = fit_logit_pool_calibration(rows, minimum_prior=128)
    assert state.supported
    assert state.weight > 0.9


def test_logit_pool_cold_start_fails_closed():
    state = fit_logit_pool_calibration([(0.6, 0.55, 1)] * 127, minimum_prior=128)
    assert not state.supported
    assert state.reason == "insufficient_prior_support"


def test_market_implied_mean_uses_price_not_just_line():
    sigma = 10.0
    fair = market_implied_mean(3.0, 0.50, sigma)
    shaded = market_implied_mean(3.0, 0.60, sigma)
    assert math.isclose(fair, 3.0, abs_tol=1e-12)
    assert shaded > fair


def test_robust_scale_positive_and_deterministic():
    values = [-14, -9, -5, -2, 0, 1, 4, 8, 13] * 20
    a = robust_market_scale(values)
    b = robust_market_scale(values)
    assert a is not None and a > 0
    assert a == b


def test_price_aware_point_calibration_cold_start_fails_closed():
    rows = [(4.0, 3.0, 0.5, 5.0)] * 127
    state = fit_price_aware_point_calibration(rows, minimum_prior=128)
    assert not state.supported
    assert state.reason == "insufficient_prior_support"


def test_price_aware_point_beta_is_bounded():
    rows = []
    for i in range(160):
        threshold = float((i % 7) - 3)
        p_market = 0.50
        model = threshold + 2.0
        actual = threshold + float((i % 11) - 3)
        rows.append((model, threshold, p_market, actual))
    state = fit_price_aware_point_calibration(rows, minimum_prior=128)
    assert state.supported
    assert state.beta is not None
    assert 0.0 <= state.beta <= 1.0


def test_calibrated_point_mean_responds_to_market_price():
    rows = []
    for i in range(160):
        threshold = float((i % 5) - 2)
        model = threshold + 1.0
        actual = threshold + ((i % 9) - 4)
        rows.append((model, threshold, 0.50, actual))
    state = fit_price_aware_point_calibration(rows, minimum_prior=128)
    assert state.supported
    low = calibrated_point_mean(5.0, 3.0, 0.45, state)
    high = calibrated_point_mean(5.0, 3.0, 0.55, state)
    assert high > low
