"""Evaluator fitting for Task05F.

Every evaluator family carries evaluator-specific uncertainty (chronological
block-bootstrap calibration gap of THAT family's own probability), real prior
stability evidence, and real historical support envelopes — all derived from
PRIOR training scopes only. No family reports a fake 0.0 uncertainty.
"""
from __future__ import annotations
import numpy as np
from sklearn.linear_model import LogisticRegression

from .contracts import EvaluatorState, SupportFeature
from .market_math import normal_cdf
from .reliability import support_feature
from .uncertainty import block_bootstrap_calibration_radius, calibration_stability, stability_from_radius

MIN_TRAIN = 128


def fit_global_lambda(model: list[float], market: list[float], y: list[int]) -> float:
    """Shrinkage formula (preregistered): clip((model-market) . (y-market) / den, 0, 1)."""
    d = np.asarray(model) - np.asarray(market)
    r = np.asarray(y) - np.asarray(market)
    den = float(d @ d)
    return 0.0 if den <= 1e-12 else float(np.clip((d @ r) / den, 0.0, 1.0))


def _lr(X, y, C=0.05):
    m = LogisticRegression(C=C, max_iter=2000, solver="lbfgs").fit(np.asarray(X), np.asarray(y))
    return float(m.intercept_[0]), [float(v) for v in m.coef_[0]]


def _sig(z):
    z = float(z)
    if z >= 700:
        return 1.0
    if z <= -700:
        return 0.0
    return 1.0 / (1.0 + np.exp(-z))


def _ml_pred(family, params, q, x, pin):
    return _ml_pred_core(family, params, float(q), float(x), float(pin))


def _ml_triples(family, params, usable):
    out = []
    for r in usable:
        p = _ml_pred_core(family, params, float(r["qb"]), float(r["xgb"]), float(r["pin"]))
        out.append((str(r["block"]), p, int(r["y"])))
    return out


def _ml_pred_core(family, params, q, x, pin):
    avg = (q + x) / 2.0
    if family == "pinnacle":
        return pin
    if family == "raw_qbelo":
        return q
    if family == "raw_xgb":
        return x
    if family == "exact_avg":
        return avg
    if family == "global_shrinkage":
        return pin + float(params["lambda"]) * (avg - pin)
    if family == "reliability_aware_shrinkage":
        region = "low" if pin < 0.40 else "mid" if pin <= 0.60 else "high"
        band = "small" if abs(avg - pin) < 0.05 else "large"
        lam = float(params.get(f"lambda_{region}_{band}", params["lambda_global"]))
        return pin + lam * (avg - pin)
    if family == "strong_logistic":
        b = params["coef"]
        z = float(params["intercept"]) + b[0] * q + b[1] * x + b[2] * pin + b[3] * abs(q - x) + b[4] * (avg - pin)
        return _sig(z)
    raise ValueError(family)


def _ml_support_features(usable):
    """Support envelope over prior moneyline-training rows."""
    pins = [float(r["pin"]) for r in usable]
    gaps = [float((r["qb"] + r["xgb"]) / 2.0 - r["pin"]) for r in usable]
    disc = [abs(float(r["qb"]) - float(r["xgb"])) for r in usable]
    return (
        support_feature("pin", pins),
        support_feature("avg_pin_gap", gaps),
        support_feature("qb_xgb_gap", disc),
    )


def _ml_state(family, params, usable, version, config_sha):
    n = len(usable)
    triples = _ml_triples(family, params, usable) if n else []
    unc = block_bootstrap_calibration_radius(triples) if n else None
    stable = stability_from_radius(triples, unc if unc is not None else 1.0) if n else False
    return EvaluatorState(
        "moneyline", family, version, n, params,
        uncertainty=unc, config_sha256=config_sha, stable_blocks=stable,
        support_features=_ml_support_features(usable),
    )


def fit_ml_states(rows, version, config_sha):
    usable = [r for r in rows if r.get("qb") is not None and r.get("xgb") is not None and r.get("pin") is not None]
    n = len(usable)
    avg = [(r["qb"] + r["xgb"]) / 2.0 for r in usable]
    pin = [float(r["pin"]) for r in usable]
    y = [int(r["y"]) for r in usable]
    lam = fit_global_lambda(avg, pin, y) if n else 0.0

    base = {
        "pinnacle": _ml_state("pinnacle", {}, usable, version, config_sha),
        "raw_qbelo": _ml_state("raw_qbelo", {}, usable, version, config_sha),
        "raw_xgb": _ml_state("raw_xgb", {}, usable, version, config_sha),
        "exact_avg": _ml_state("exact_avg", {}, usable, version, config_sha),
        "global_shrinkage": _ml_state("global_shrinkage", {"lambda": lam}, usable, version, config_sha),
    }

    pars = {"lambda_global": lam}
    for region, lo, hi in (("low", 0.0, 0.4000001), ("mid", 0.4000001, 0.6000001), ("high", 0.6000001, 1.01)):
        for band in ("small", "large"):
            rr = [
                (a, p_, yy)
                for a, p_, yy in zip(avg, pin, y)
                if lo <= p_ < hi and ((abs(a - p_) < 0.05) == (band == "small"))
            ]
            local = (
                fit_global_lambda([a for a, _, _ in rr], [p_ for _, p_, _ in rr], [yy for _, _, yy in rr])
                if len(rr) >= 64 else lam
            )
            w = len(rr) / (len(rr) + 128)
            pars[f"lambda_{region}_{band}"] = w * local + (1 - w) * lam
    base["reliability_aware_shrinkage"] = _ml_state("reliability_aware_shrinkage", pars, usable, version, config_sha)

    if n >= MIN_TRAIN:
        X = [
            [r["qb"], r["xgb"], r["pin"], abs(r["qb"] - r["xgb"]), (r["qb"] + r["xgb"]) / 2.0 - r["pin"]]
            for r in usable
        ]
        it, co = _lr(X, y)
        base["strong_logistic"] = _ml_state("strong_logistic", {"intercept": it, "coef": co}, usable, version, config_sha)
    return base


def _point_support_features(rows):
    """Orientation-invariant support envelope over prior point-market training rows.

    delta_magnitude = abs(delta) so mirrored sides (away/under) live in the same
    support space as their canonical HOME/OVER counterparts. Probability math still
    uses the signed canonical delta; only the support-distance envelope uses |delta|.
    """
    deltas = [abs(float(r["delta"])) for r in rows]
    lines = [abs(float(r["market_level"])) for r in rows]
    return (
        support_feature("delta_magnitude", deltas),
        support_feature("market_magnitude", lines),
    )


def _point_triples(family, params, rows, sigma):
    out = []
    for r in rows:
        z = float(r["delta"]) / sigma
        if family == "normal_cdf":
            p = normal_cdf(z)
        elif family == "calibrated_normal":
            p = _sig(float(params["intercept"]) + float(params["slope"]) * z)
        elif family == "strong_logistic":
            b = params["coef"]
            p = _sig(float(params["intercept"]) + b[0] * float(r["delta"]) + b[1] * float(r["market_level"]))
        else:
            raise ValueError(family)
        out.append((str(r["block"]), p, int(r["y"])))
    return out


def _point_state(family, params, rows, market_type, version, config_sha, sigma):
    n = len(rows)
    triples = _point_triples(family, params, rows, sigma) if n else []
    unc = block_bootstrap_calibration_radius(triples) if n else None
    stable = stability_from_radius(triples, unc if unc is not None else 1.0) if n else False
    return EvaluatorState(
        market_type, family, version, n, params,
        uncertainty=unc, config_sha256=config_sha, stable_blocks=stable,
        support_features=_point_support_features(rows),
    )


def fit_point_states(rows, market_type, version, config_sha):
    rows = [r for r in rows if r.get("delta") is not None and r.get("market_level") is not None]
    n = len(rows)
    residual = [float(r["residual"]) for r in rows]
    sigma = float(np.std(residual, ddof=1)) if n > 1 else 14.0
    sigma = max(sigma, 1e-6)

    out = {"normal_cdf": _point_state("normal_cdf", {"sigma": sigma}, rows, market_type, version, config_sha, sigma)}
    if n >= MIN_TRAIN:
        z = [float(r["delta"]) / sigma for r in rows]
        y = [int(r["y"]) for r in rows]
        it, co = _lr([[v] for v in z], y)
        out["calibrated_normal"] = _point_state(
            "calibrated_normal", {"sigma": sigma, "intercept": it, "slope": co[0]}, rows, market_type, version, config_sha, sigma
        )
        X = [[float(r["delta"]), float(r["market_level"])] for r in rows]
        it2, co2 = _lr(X, y)
        out["strong_logistic"] = _point_state(
            "strong_logistic", {"sigma": sigma, "intercept": it2, "coef": co2}, rows, market_type, version, config_sha, sigma
        )
    return out