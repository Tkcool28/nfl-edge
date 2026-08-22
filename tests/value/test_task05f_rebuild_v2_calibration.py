from __future__ import annotations

import math

import pytest

from nfl_edge.value.calibration_v2 import (
    calibrated_point_mean,
    calibrated_probability,
    fit_anchor_slope_calibration,
    fit_monotone_logit_calibration,
)


def test_monotone_logit_requires_minimum_prior_support():
    state = fit_monotone_logit_calibration([(0.6, 1)] * 127, minimum_prior=128)
    assert not state.supported
    assert state.reason == "insufficient_prior_support"


def test_monotone_logit_fails_closed_on_single_class():
    state = fit_monotone_logit_calibration([(0.6, 1)] * 128)
    assert not state.supported
    assert state.reason == "single_class_prior"


def test_monotone_logit_preserves_probability_order():
    rows = []
    # Deterministic synthetic calibration set with increasing win frequency.
    for p, wins in [(0.2, 4), (0.4, 8), (0.6, 12), (0.8, 16)]:
        rows.extend([(p, 1)] * wins)
        rows.extend([(p, 0)] * (20 - wins))
    rows *= 2
    state = fit_monotone_logit_calibration(rows, minimum_prior=128, C=1.0)
    assert state.supported
    assert state.slope is not None and state.slope > 0
    preds = [calibrated_probability(p, state) for p in (0.2, 0.4, 0.6, 0.8)]
    assert preds == sorted(preds)
    assert all(0.0 < p < 1.0 for p in preds)


def test_monotone_logit_rejects_reversed_signal():
    rows = []
    for p, wins in [(0.2, 16), (0.4, 12), (0.6, 8), (0.8, 4)]:
        rows.extend([(p, 1)] * wins)
        rows.extend([(p, 0)] * (20 - wins))
    rows *= 2
    state = fit_monotone_logit_calibration(rows, minimum_prior=128, C=1.0)
    assert not state.supported
    assert state.reason == "nonpositive_calibration_slope"


def test_anchor_slope_requires_minimum_prior_support():
    state = fit_anchor_slope_calibration([(3.0, 2.0, 2.5)] * 127, minimum_prior=128)
    assert not state.supported
    assert state.reason == "insufficient_prior_support"


def test_anchor_slope_recovers_linear_incremental_signal():
    rows = []
    for i in range(128):
        market = float((i % 11) - 5)
        d = float((i % 7) - 3)
        model = market + d
        actual = market + 0.4 * d
        rows.append((model, market, actual))
    state = fit_anchor_slope_calibration(rows, minimum_prior=128)
    assert state.supported
    assert state.beta == pytest.approx(0.4, abs=1e-12)
    assert max(abs(x) for x in state.residuals) < 1e-12


def test_anchor_slope_clips_amplification_to_one():
    rows = [(2.0, 0.0, 4.0)] * 128
    state = fit_anchor_slope_calibration(rows, minimum_prior=128)
    assert state.supported
    assert state.beta_raw == pytest.approx(2.0)
    assert state.beta == pytest.approx(1.0)


def test_anchor_slope_clips_reversal_to_zero():
    rows = [(2.0, 0.0, -2.0)] * 128
    state = fit_anchor_slope_calibration(rows, minimum_prior=128)
    assert state.supported
    assert state.beta_raw == pytest.approx(-1.0)
    assert state.beta == pytest.approx(0.0)


def test_calibrated_point_mean_is_convex_model_market_blend():
    rows = [(10.0, 0.0, 5.0)] * 128
    state = fit_anchor_slope_calibration(rows, minimum_prior=128)
    assert state.beta == pytest.approx(0.5)
    assert calibrated_point_mean(8.0, 2.0, state) == pytest.approx(5.0)


def test_calibration_uses_no_price_argument():
    # Contract-level regression: public signatures contain only model/market/outcome
    # calibration material, never sportsbook price or ROI.
    import inspect
    from nfl_edge.value import calibration_v2

    assert "price" not in inspect.signature(calibration_v2.fit_anchor_slope_calibration).parameters
    assert "roi" not in inspect.signature(calibration_v2.fit_anchor_slope_calibration).parameters
    assert "price" not in inspect.signature(calibration_v2.fit_monotone_logit_calibration).parameters


def test_calibrated_probability_is_finite():
    rows = [(0.1 + 0.8 * (i / 199.0), int(i >= 100)) for i in range(200)]
    state = fit_monotone_logit_calibration(rows, minimum_prior=128)
    assert state.supported
    for raw in (0.0, 0.01, 0.5, 0.99, 1.0):
        out = calibrated_probability(raw, state)
        assert math.isfinite(out)
        assert 0.0 < out < 1.0
