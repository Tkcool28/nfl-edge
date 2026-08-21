"""Task05F redesign candidate families.

v1 (prereg /tmp/task05f-redesign-prereg.json):
  ML   residual_logistic, partial_shrinkage_floor
  PT   empirical_residual_cdf, student_t_residual (canonical HOME / OVER orientation)

v2 (prereg /tmp/task05f-redesign-v2-prereg.json):
  ML   reliability_aware_shrinkage_v2  p = pin + w(tier)*u(uncertainty)*(avg - pin)
  SP   conditional_band_ecdf          band-blended residual CDF by abs(market spread)
  SP   standardized_conditional_ecdf  pooled ECDF over z = delta / sigma_band(MAD)
  TOT  canonical_over_ecdf            P_under = 1 - P_over exactly

Push handling: fits/scoring use continuous residuals; cover labels exclude pushes.
All fits are prior-block-only; deterministic; no outcome-tuned parameters.

Contract notes (v2):
- UNSUPPORTED rows get NO actionable probability: callers must gate before
  invoking ml_v2_probability and treat the result as unavailable (fail closed).
  V2_ML_WEIGHT_DEFAULT exists only as a conservative guard for unexpected tier
  strings reaching this module; it never overrides caller-side UNSUPPORTED gating.
- Reliability tier/uncertainty/support inputs are the existing Task05F modules
  (reliability.py tier(), uncertainty.py bootstrap radius, support envelopes);
  this module owns only the preregistered weight/damping/clamp arithmetic.
"""
from __future__ import annotations

import math

import numpy as np

from .market_math import normal_cdf

# --- v1 constants (retained; v1 families remain available as benchmarks) ---
ECDF_ALPHA = 1.0
ECDF_SHRINK_N = 64
T_DF = 5
ML_LAMBDA_FLOOR = 0.25
ML_LOGISTIC_C = 0.05

# --- v2 constants (preregistered; NOT outcome-tuned) ---
V2_ML_WEIGHTS = {"HIGH": 0.50, "MEDIUM": 0.35, "LOW": 0.20}
V2_ML_WEIGHT_DEFAULT = 0.20          # any unexpected tier string -> most conservative
V2_UNC_DIVISOR = 0.10
V2_UNC_NONE_FACTOR = 0.50
V2_BAND_EDGE = (3.0, 7.0)            # abs(market spread) bands: [0,3) [3,7) [7,inf)
V2_BAND_MIN_N = 128                  # same-band minimum before full trust
V2_MAD_SCALE = 1.4826                # MAD -> sigma consistency factor


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _sig(z: float) -> float:
    z = float(z)
    if z >= 700:
        return 1.0
    if z <= -700:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def _logit(p: float) -> float:
    p = min(max(float(p), 1e-9), 1 - 1e-9)
    return math.log(p / (1.0 - p))


def smooth_ecdf_from_sorted(sorted_residuals, threshold: float) -> float:
    """Fast path of smooth_ecdf_prob for a PRE-SORTED ascending 1-D array.

    Identical math to smooth_ecdf_prob (midrank smoothing + n/(n+64) shrink);
    the sort is hoisted so callers evaluating many thresholds against the same
    prior scope pay the sort once. Empty input -> 0.5.
    """
    n = len(sorted_residuals)
    if n == 0:
        return 0.5
    idx = np.searchsorted(sorted_residuals, float(threshold), side="right")  # #{r <= t}
    f_hat = (idx + ECDF_ALPHA * 0.5) / (n + ECDF_ALPHA)  # midrank-smoothed CDF
    p_ecdf = 1.0 - f_hat
    w = n / (n + ECDF_SHRINK_N)
    return float(w * p_ecdf + (1.0 - w) * 0.5)


def smooth_ecdf_prob(residuals, threshold: float) -> float:
    """P(residual > threshold): survival function of the midrank-smoothed ECDF,
    shrunk toward 0.5 with weight n/(n+ECDF_SHRINK_N). Monotone decreasing in
    `threshold`; deterministic.
    """
    r = np.sort(np.asarray([float(x) for x in residuals], dtype=float))
    return smooth_ecdf_from_sorted(r, threshold)


def student_t5_sf(x: float, loc: float, scale: float) -> float:
    """Survival function of Student-t(df=5): P(T > x)."""
    try:
        from scipy import stats as _s
        return float(_s.t.sf((float(x) - loc) / scale, T_DF))
    except Exception:
        v = T_DF / (T_DF - 2.0)
        return 0.5 * math.erfc(((float(x) - loc) / (scale * math.sqrt(v))) / math.sqrt(2.0))


def fit_t5_loc_scale(values) -> tuple[float, float]:
    a = np.asarray([float(v) for v in values], dtype=float)
    loc = float(a.mean()) if len(a) else 0.0
    sd = float(a.std(ddof=1)) if len(a) > 1 else 10.0
    scale = sd * math.sqrt(3.0 / T_DF)
    return loc, max(scale, 1e-6)


# ---------------------------------------------------------------------------
# v2 ML: reliability-aware partial shrinkage
# ---------------------------------------------------------------------------
def ml_v2_weight(reliability: str, uncertainty: float | None) -> tuple[float, float, float]:
    """Return (base_w, u, w_final). Preregistered mapping; no tuning."""
    base = V2_ML_WEIGHTS.get(reliability, V2_ML_WEIGHT_DEFAULT)
    if uncertainty is None:
        u = V2_UNC_NONE_FACTOR
    else:
        u = max(0.0, 1.0 - float(uncertainty) / V2_UNC_DIVISOR)
    return base, u, base * u


def ml_v2_probability(p_market: float, residual: float, reliability: str,
                      uncertainty: float | None) -> tuple[float, dict]:
    """p = clip(p_market + w_final*residual, .01, .99). Sign preserved (w_final >= 0)."""
    base, u, w_final = ml_v2_weight(reliability, uncertainty)
    p = min(0.99, max(0.01, float(p_market) + w_final * float(residual)))
    return p, {"base_weight": base, "uncertainty_damping": u, "final_weight": w_final}


def ml_v2_actionable_probability(qb_side: float | None, xgb_side: float | None,
                                 p_market: float | None, reliability: str,
                                 uncertainty: float | None) -> tuple[float | None, dict]:
    """Fail-closed v2 entry point (prereg E).

    Returns (None, reason) when any required input is missing (QB-Elo / XGB /
    Pinnacle no-vig) or when reliability is UNSUPPORTED -- i.e. no actionable
    probability exists for unsupported rows. Otherwise p_model is the exact AVG
    of the two selected-side constituent probabilities, residual =
    p_model - p_market, and the preregistered weighted/clamped probability.
    """
    if qb_side is None or xgb_side is None or p_market is None:
        return None, {"reason": "missing_constituent"}
    if reliability == "UNSUPPORTED":
        return None, {"reason": "unsupported_reliability"}
    avg = (float(qb_side) + float(xgb_side)) / 2.0
    residual = avg - float(p_market)
    p, diag = ml_v2_probability(float(p_market), residual, reliability, uncertainty)
    return p, {"residual": residual, **diag}


# ---------------------------------------------------------------------------
# v2 spread: band helpers
# ---------------------------------------------------------------------------
def spread_band(abs_market_spread: float) -> int:
    """0 = [0,3), 1 = [3,7), 2 = [7,inf). Ex-ante market structure only."""
    s = abs(float(abs_market_spread))
    if s < V2_BAND_EDGE[0]:
        return 0
    if s < V2_BAND_EDGE[1]:
        return 1
    return 2


def _band_residuals(rows, band: int):
    """Prior rows whose own abs(market spread) falls in `band`."""
    return [float(r["residual"]) for r in rows
            if r.get("market_level") is not None and spread_band(abs(float(r["market_level"]))) == band]


def conditional_band_probability(rows, delta: float, market_level: float) -> tuple[float, dict]:
    """P(home cover) = alpha*CDF_band(-delta) + (1-alpha)*CDF_global(-delta)."""
    b = spread_band(market_level)
    band_res = _band_residuals(rows, b)
    all_res = [float(r["residual"]) for r in rows]
    n_band = len(band_res)
    p_band = smooth_ecdf_prob(band_res, -float(delta))
    p_glob = smooth_ecdf_prob(all_res, -float(delta))
    alpha = n_band / (n_band + V2_BAND_MIN_N)
    p = alpha * p_band + (1.0 - alpha) * p_glob
    return float(p), {"band": b, "n_band": n_band, "alpha_band": alpha, "p_band": p_band, "p_global": p_glob}


def _mad_sigma(values) -> float:
    a = np.asarray([float(v) for v in values], dtype=float)
    if len(a) < 2:
        return 1e-6
    med = float(np.median(a))
    mad = float(np.median(np.abs(a - med)))
    sigma = V2_MAD_SCALE * mad
    if sigma <= 1e-9:
        sigma = float(a.std(ddof=1)) if len(a) > 1 else 1e-6
    return max(sigma, 1e-6)


def standardized_conditional_probability(rows, delta: float, market_level: float) -> tuple[float, dict]:
    """P(home cover) via pooled ECDF over z = delta / sigma_band(current)."""
    b = spread_band(market_level)
    zs = []
    for r in rows:
        if r.get("market_level") is None:
            continue
        rb = spread_band(abs(float(r["market_level"])))
        band_vals = _band_residuals(rows, rb)
        sig = _mad_sigma(band_vals) if len(band_vals) >= 2 else _mad_sigma([float(x["residual"]) for x in rows])
        zs.append(float(r["residual"]) / sig)
    sig_cur = _mad_sigma(_band_residuals(rows, b)) if len(_band_residuals(rows, b)) >= 2 \
        else _mad_sigma([float(x["residual"]) for x in rows])
    z_cur = float(delta) / sig_cur
    p = smooth_ecdf_prob(zs, -z_cur)
    return float(p), {"band": b, "sigma_band": sig_cur, "z": z_cur, "n_pooled": len(zs)}


# ---------------------------------------------------------------------------
# v2 totals: canonical over probability
# ---------------------------------------------------------------------------
def canonical_over_probability(total_residual_rows, over_delta: float) -> tuple[float, dict]:
    """P_over = smooth_ecdf(total residuals, -over_delta); P_under = 1 - P_over."""
    res = [float(r["residual"]) for r in total_residual_rows]
    p_over = smooth_ecdf_prob(res, -float(over_delta))
    return float(p_over), {"n": len(res)}


# ---------------------------------------------------------------------------
# v1 ML residual logistic (benchmark family retained)
# ---------------------------------------------------------------------------
def fit_ml_residual_params(rows) -> dict | None:
    usable = [r for r in rows if r.get("qb") is not None and r.get("xgb") is not None and r.get("pin") is not None]
    if len(usable) < 128:
        return None
    resid = np.asarray([(r["qb"] + r["xgb"]) / 2.0 - float(r["pin"]) for r in usable])
    disag = np.abs(np.asarray([float(r["qb"]) - float(r["xgb"]) for r in usable]))
    y = np.asarray([int(r["y"]) for r in usable])
    mu = [float(resid.mean()), float((resid * disag).mean()), float(disag.mean())]
    sd = [max(float(resid.std(ddof=1)), 1e-6), max(float((resid * disag).std(ddof=1)), 1e-6),
          max(float(disag.std(ddof=1)), 1e-6)]
    X = np.column_stack([
        (resid - mu[0]) / sd[0],
        (resid * disag - mu[1]) / sd[1],
        (disag - mu[2]) / sd[2],
    ])
    try:
        from sklearn.linear_model import LogisticRegression
        m = LogisticRegression(penalty="l2", C=ML_LOGISTIC_C, max_iter=2000, solver="lbfgs", fit_intercept=True)
        m.fit(X, y)
    except Exception:
        return None
    return {"coef": [float(v) for v in np.asarray(m.coef_).ravel()],
            "intercept": float(np.asarray(m.intercept_).ravel()[0]),
            "mu": mu, "sd": sd}


def predict_ml_residual(params: dict, avg: float, pin: float, disag: float) -> float:
    z = (_logit(pin) - params["intercept"]
         + params["coef"][0] * ((avg - pin) - params["mu"][0]) / params["sd"][0]
         + params["coef"][1] * ((avg - pin) * disag - params["mu"][1]) / params["sd"][1]
         + params["coef"][2] * (disag - params["mu"][2]) / params["sd"][2])
    return _sig(z)
