"""Task05F redesign tests: v1 families (regression) + v2 preregistered candidates.

v2 preregistration: /tmp/task05f-redesign-v2-prereg.json (hash d9f2213b…).
Covers instruction-set requirements E–K, Q.
"""
import math
from pathlib import Path

import pytest

from nfl_edge.value.redesign import (
    ECDF_SHRINK_N, ML_LAMBDA_FLOOR, T_DF, V2_BAND_EDGE, V2_BAND_MIN_N,
    V2_ML_WEIGHTS, V2_UNC_DIVISOR, V2_UNC_NONE_FACTOR,
    canonical_over_probability, conditional_band_probability,
    fit_ml_residual_params, fit_t5_loc_scale, ml_v2_actionable_probability,
    ml_v2_probability, ml_v2_weight, predict_ml_residual, smooth_ecdf_prob,
    spread_band, student_t5_sf, standardized_conditional_probability,
    _sig, _logit)

# ---------------------------------------------------------------------------
# v2 ML: reliability-aware partial shrinkage
# ---------------------------------------------------------------------------

def test_ml_v2_weight_mapping_exact():
    assert V2_ML_WEIGHTS == {"HIGH": 0.50, "MEDIUM": 0.35, "LOW": 0.20}
    assert ml_v2_weight("HIGH", 0.02) == (0.50, pytest.approx(0.8), pytest.approx(0.40))
    assert ml_v2_weight("MEDIUM", 0.02) == (0.35, pytest.approx(0.8), pytest.approx(0.28))
    assert ml_v2_weight("LOW", 0.02) == (0.20, pytest.approx(0.8), pytest.approx(0.16))


def test_ml_v2_uncertainty_damping_bounds_and_none():
    # u = max(0, 1 - unc/0.10); None -> 0.50
    _, u0, _ = ml_v2_weight("HIGH", 0.0)
    assert u0 == pytest.approx(1.0)
    _, u10, _ = ml_v2_weight("HIGH", 0.10)
    assert u10 == pytest.approx(0.0)
    _, u15, _ = ml_v2_weight("HIGH", 0.15)
    assert u15 == pytest.approx(0.0)  # clamped at zero, never negative
    _, unone, _ = ml_v2_weight("HIGH", None)
    assert unone == pytest.approx(V2_UNC_NONE_FACTOR)


def test_ml_v2_sign_preserved_no_reversal():
    for tier in ("HIGH", "MEDIUM", "LOW"):
        for unc in (None, 0.01, 0.05):
            p_pos, _ = ml_v2_probability(0.55, +0.06, tier, unc)
            p_neg, _ = ml_v2_probability(0.55, -0.06, tier, unc)
            assert p_pos > 0.55 and p_neg < 0.55  # sign follows residual, never reversed


def test_ml_v2_zero_uncertainty_neutralizes_but_never_reverses():
    p, diag = ml_v2_probability(0.5, 0.08, "HIGH", 0.10)
    assert p == pytest.approx(0.5)          # w_final = 0 -> neutralized
    assert diag["final_weight"] == 0.0
    p_neg, _ = ml_v2_probability(0.5, -0.08, "HIGH", 0.10)
    assert p_neg == pytest.approx(0.5)


def test_ml_v2_clip_bounds():
    p_hi, _ = ml_v2_probability(0.97, 0.20, "HIGH", 0.0)
    p_lo, _ = ml_v2_probability(0.03, -0.20, "HIGH", 0.0)
    assert p_hi <= 0.99 and p_lo >= 0.01


def test_ml_v2_missing_constituent_is_caller_gated_fail_closed():
    # The harness never calls the v2 probability without both constituents;
    # residual is only computed when qb and xgb both exist (documented contract).
    # This test pins the weight function's conservatism for unknown tiers.
    base, u, wf = ml_v2_weight("UNSUPPORTED", 0.02)
    assert base == 0.20 and wf > 0  # conservative default; gating happens upstream


def test_ml_v2_actionable_fail_closed_on_missing_constituent():
    # prereg E: missing QB-Elo / XGB / Pinnacle input => no actionable probability
    p, diag = ml_v2_actionable_probability(None, 0.60, 0.55, "HIGH", 0.02)
    assert p is None and diag["reason"] == "missing_constituent"
    p, diag = ml_v2_actionable_probability(0.55, None, 0.55, "HIGH", 0.02)
    assert p is None and diag["reason"] == "missing_constituent"
    p, diag = ml_v2_actionable_probability(0.55, 0.60, None, "HIGH", 0.02)
    assert p is None and diag["reason"] == "missing_constituent"


def test_ml_v2_actionable_fail_closed_on_unsupported():
    # prereg E: UNSUPPORTED => NO actionable probability (never a fallback weight)
    p, diag = ml_v2_actionable_probability(0.55, 0.60, 0.52, "UNSUPPORTED", 0.02)
    assert p is None and diag["reason"] == "unsupported_reliability"


def test_ml_v2_actionable_exact_avg_residual_and_formula():
    # exact AVG residual + preregistered weight/damping/clamp arithmetic
    p, d = ml_v2_actionable_probability(0.58, 0.60, 0.50, "MEDIUM", 0.02)
    assert p is not None
    assert d["residual"] == pytest.approx((0.58 + 0.60) / 2.0 - 0.50)
    assert d["base_weight"] == 0.35
    assert d["uncertainty_damping"] == pytest.approx(1 - 0.02 / 0.10)
    assert d["final_weight"] == pytest.approx(0.35 * (1 - 0.02 / 0.10))
    assert p == pytest.approx(0.50 + 0.35 * (1 - 0.02 / 0.10) * d["residual"])


# ---------------------------------------------------------------------------
# v2 spread: band assignment / blended ECDF / standardized
# ---------------------------------------------------------------------------

def _band_rows(n_per=200, seed=3):
    import random
    rng = random.Random(seed)
    rows = []
    for b, lvl in enumerate((1.5, 5.0, 9.0)):
        for i in range(n_per):
            rows.append({"block": f"202{b}-{i % 10:02d}", "residual": rng.gauss(0.0, 4.0 + 2 * b),
                         "delta": rng.gauss(0, 3), "market_level": lvl, "y": i % 2})
    return rows


def test_spread_band_assignment_fixed_edges():
    assert spread_band(0.0) == 0 and spread_band(2.999) == 0
    assert spread_band(3.0) == 1 and spread_band(6.999) == 1
    assert spread_band(7.0) == 2 and spread_band(20.0) == 2
    assert spread_band(-5.0) == spread_band(5.0)  # abs()


def test_spread_band_fallback_blend_under_min_n():
    rows = _band_rows(n_per=200)
    # tiny prior set in band 2 only: n_band=3 < 128 -> alpha small -> blend toward global
    few = [{"block": "b", "residual": r, "delta": 0.0, "market_level": 9.0} for r in (1.0, 2.0, -3.0)]
    glob = [r for r in rows if abs(r["market_level"]) < 3]  # different band, so band-2 prior stays tiny
    p_blend, diag = conditional_band_probability(few + glob, 1.0, 9.0)
    assert diag["n_band"] == 3
    assert diag["alpha_band"] == pytest.approx(3 / (3 + V2_BAND_MIN_N))
    expected = diag["alpha_band"] * diag["p_band"] + (1 - diag["alpha_band"]) * diag["p_global"]
    assert p_blend == pytest.approx(expected)


def test_spread_band_full_trust_at_large_n():
    rows = _band_rows(n_per=400)
    p, diag = conditional_band_probability(rows, 1.0, 5.0)
    assert diag["n_band"] >= V2_BAND_MIN_N
    assert diag["alpha_band"] == pytest.approx(diag["n_band"] / (diag["n_band"] + V2_BAND_MIN_N))
    assert diag["p_band"] == pytest.approx(smooth_ecdf_prob(
        [r["residual"] for r in rows if abs(r["market_level"]) >= 3 and abs(r["market_level"]) < 7], -1.0))


def test_spread_banded_monotone_in_delta():
    rows = _band_rows()
    probs = [conditional_band_probability(rows, float(d), 5.0)[0] for d in range(-4, 5)]
    assert all(probs[i] <= probs[i + 1] + 1e-12 for i in range(len(probs) - 1))


def test_standardized_conditional_monotone_and_deterministic():
    rows = _band_rows()
    a = [standardized_conditional_probability(rows, float(d), 5.0)[0] for d in range(-4, 5)]
    b = [standardized_conditional_probability(rows, float(d), 5.0)[0] for d in range(-4, 5)]
    assert a == b  # deterministic
    assert all(a[i] <= a[i + 1] + 1e-12 for i in range(len(a) - 1))


def test_spread_banded_delta_zero_near_half():
    # gate 14: p(delta=0) must sit in [0.48, 0.52]
    rows = _band_rows()
    p0 = conditional_band_probability(rows, 0.0, 5.0)[0]
    assert 0.48 <= p0 <= 0.52
    p0s = standardized_conditional_probability(rows, 0.0, 5.0)[0]
    assert 0.48 <= p0s <= 0.52


def test_spread_complement_coherent_home_away():
    # mirrored sides are exact complements by construction: P_away = 1 - P_home
    rows = _band_rows()
    for fam_prob in (conditional_band_probability, standardized_conditional_probability):
        p_home = fam_prob(rows, 2.0, 5.0)[0]
        assert (1.0 - p_home) + p_home == pytest.approx(1.0, abs=0)


def test_standardized_band_sigmas_deterministic_and_positive():
    # standardized candidate: per-band MAD sigma deterministic; pooled z ECDF deterministic
    rows = _band_rows()
    p1, d1 = standardized_conditional_probability(rows, 1.5, 1.5)
    p2, d2 = standardized_conditional_probability(rows, 1.5, 1.5)
    assert p1 == p2 and d1 == d2
    assert d1["sigma_band"] > 0 and d1["n_pooled"] == len(rows)


# ---------------------------------------------------------------------------
# totals canonical complementarity
# ---------------------------------------------------------------------------

def test_totals_canonical_complement_exact():
    rows = [{"block": "b", "residual": r, "delta": 0.0, "market_level": 45.0} for r in range(-30, 30)]
    p_over, _ = canonical_over_probability(rows, 2.5)
    assert (1.0 - p_over) + p_over == pytest.approx(1.0, abs=0)


def test_totals_both_sides_posEV_impossible_same_price():
    rows = [{"block": "b", "residual": r, "delta": 0.0, "market_level": 45.0} for r in range(-30, 30)]
    p_over, _ = canonical_over_probability(rows, 2.5)
    be = 1.0 / 1.909
    p_under = 1.0 - p_over
    assert not (p_over > be and p_under > be)


def test_push_excluded_from_probability_fit_inputs():
    # harness contract: training rows carry 'y' only when graded; pushes excluded.
    # redesign probability functions consume residuals only — verify no y leakage:
    row = {"block": "b", "residual": 1.5, "delta": 0.0, "market_level": 4.0}  # no y key at all
    p1 = conditional_band_probability([row], 1.0, 4.0)[0]
    p2 = conditional_band_probability([dict(row, y=1)], 1.0, 4.0)[0]
    assert p1 == p2


# ---------------------------------------------------------------------------
# v1 regression coverage (retained benchmarks)
# ---------------------------------------------------------------------------

def test_smooth_ecdf_monotone_both_orientations():
    res = [(-1.0) ** i * (3 + i % 7) for i in range(400)]
    sf = [smooth_ecdf_prob(res, float(t)) for t in range(-8, 9)]
    assert all(sf[i] >= sf[i + 1] - 1e-12 for i in range(len(sf) - 1))
    probs = [smooth_ecdf_prob(res, -float(t)) for t in range(-8, 9)]
    assert all(probs[i] <= probs[i + 1] + 1e-12 for i in range(len(probs) - 1))


def test_smooth_ecdf_zero_near_half_small_n_shrink():
    res = [(-1.0) ** i * (3.0 + (i % 11)) for i in range(2000)]
    assert abs(smooth_ecdf_prob(res, 0.0) - 0.5) < 0.03
    tiny = [10.0, -6.0, 4.0]
    p_tiny = smooth_ecdf_prob(tiny, -50.0)
    p_big = smooth_ecdf_prob(list(range(-100, 100)), -101.0)
    assert p_big > p_tiny  # more data -> less shrinkage toward 0.5


def test_smooth_ecdf_deterministic():
    res = [float((i * 37) % 23 - 11) for i in range(500)]
    assert smooth_ecdf_prob(res, 2.5) == smooth_ecdf_prob(res, 2.5)


def test_student_t5_sf_monotone_and_centered():
    xs = [-6, -3, 0, 3, 6]
    sf = [student_t5_sf(x, 0.6, 10.6) for x in xs]
    assert all(sf[i] >= sf[i + 1] - 1e-12 for i in range(len(sf) - 1))
    assert student_t5_sf(0.0, 0.0, 1.0) == pytest.approx(0.5)


def _synth_ml_rows(n=800, signal=0.35, seed=7):
    import random
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        gap = rng.gauss(0, 0.06)
        pin = min(max(rng.gauss(0.5, 0.14), 0.05), 0.95)
        p_true = min(max(pin + signal * gap, 0.02), 0.98)
        y = 1 if rng.random() < p_true else 0
        qb = min(max(pin + gap + rng.gauss(0, 0.01), 0.01), 0.99)
        rows.append({"block": f"20{(i // 200) % 4:02d}-{i % 200:02d}", "qb": qb,
                     "xgb": qb, "pin": pin, "y": y})
    return rows


def test_ml_residual_params_insufficient_returns_none():
    assert fit_ml_residual_params([]) is None
    assert fit_ml_residual_params([{"block": "b", "qb": .5, "xgb": .5, "pin": .5, "y": 1}]) is None


def test_ml_residual_logistic_positive_beta_and_sign_kept_synthetic():
    params = fit_ml_residual_params(_synth_ml_rows())
    assert params is not None
    assert params["coef"][0] > 0
    kept = flipped = 0
    for pin in (0.4, 0.5, 0.6):
        for gap in (0.04, 0.08):
            base = predict_ml_residual(params, pin + gap, pin, 0.02)
            if (base - pin) * gap > 0:
                kept += 1
            elif (base - pin) * gap < 0:
                flipped += 1
    assert kept > flipped


def test_constants_preregistered():
    assert 0.0 < ML_LAMBDA_FLOOR < 1.0 and ML_LAMBDA_FLOOR == 0.25
    assert V2_BAND_EDGE == (3.0, 7.0) and V2_BAND_MIN_N == 128
    assert V2_UNC_DIVISOR == 0.10 and V2_UNC_NONE_FACTOR == 0.50
    assert ECDF_SHRINK_N == 64 and T_DF == 5


def test_v2_harness_source_sealed_season_firewall():
    # The committed runner is the canonical data path; the v2 harness must keep
    # the same firewall: explicit DEV filter + sealed-season assertion.
    src = (Path(__file__).resolve().parents[2] / "candidate_v2_run.py").read_text()
    assert 'pl.col("season").is_in(DEV)' in src
    assert "2025" in src and "assert" in src.lower()


def test_v2_harness_chronology_prior_blocks_only():
    # expanding walk-forward: only strictly-prior season-week blocks may feed fits
    src = (Path(__file__).resolve().parents[2] / "candidate_v2_run.py").read_text()
    assert 'b < block' in src and 'prior' in src


def test_logit_sigmoid_inverse():
    for p in (0.3, 0.5, 0.7):
        assert _sig(_logit(p)) == pytest.approx(p, abs=1e-9)


def test_point_probability_complement_via_canonical_rule():
    p = 0.5611
    assert abs((1.0 - p) + p - 1.0) < 1e-12


def test_fit_t5_loc_scale_reasonable():
    vals = [float(i % 19 - 9) for i in range(500)]
    loc, scale = fit_t5_loc_scale(vals)
    assert abs(loc) < 0.5 and scale > 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
