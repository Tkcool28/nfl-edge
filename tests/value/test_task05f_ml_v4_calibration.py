from nfl_edge.value.calibration_v4 import (
    calibrated_market_probability,
    final_ml_probability,
    fit_ml_v4_calibration,
)


def test_ml_v4_cold_start_fails_closed():
    state = fit_ml_v4_calibration([(0.6, 0.55, 1)] * 127, minimum_prior=128)
    assert not state.supported
    assert state.reason == "insufficient_prior_support"


def test_ml_v4_market_calibration_is_monotone():
    rows = []
    for i in range(240):
        y = i % 2
        p_market = 0.75 if y else 0.25
        p_model = 0.70 if y else 0.30
        rows.append((p_model, p_market, y))
    state = fit_ml_v4_calibration(rows, minimum_prior=128)
    assert state.supported
    assert calibrated_market_probability(0.70, state) > calibrated_market_probability(0.30, state)


def test_ml_v4_final_probability_stays_between_calibrated_market_and_model():
    rows = []
    for i in range(240):
        y = i % 2
        p_market = 0.65 if y else 0.35
        p_model = 0.80 if y else 0.20
        rows.append((p_model, p_market, y))
    state = fit_ml_v4_calibration(rows, minimum_prior=128)
    assert state.supported
    p_market_cal = calibrated_market_probability(0.60, state)
    p_final = final_ml_probability(0.75, 0.60, state)
    assert min(p_market_cal, 0.75) <= p_final <= max(p_market_cal, 0.75)


def test_ml_v4_zero_model_weight_leaves_calibrated_market_intact():
    rows = []
    for i in range(240):
        y = i % 2
        p_market = 0.90 if y else 0.10
        p_model = 0.10 if y else 0.90
        rows.append((p_model, p_market, y))
    state = fit_ml_v4_calibration(rows, minimum_prior=128)
    assert state.supported
    assert state.pool.weight == 0.0
    p_market_cal = calibrated_market_probability(0.70, state)
    p_final = final_ml_probability(0.20, 0.70, state)
    assert p_final == p_market_cal
