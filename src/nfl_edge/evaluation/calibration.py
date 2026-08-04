"""Calibration diagnostics only. No recalibration is performed in Task 03A.

We compute the reliability (calibration) table and the intercept/slope of
a **logistic** recalibration fit on the development predictions. This is
diagnostic information only; the predictions themselves are not
transformed.

The intercept and slope come from fitting the diagnostic model::

    logit(P(actual_home_win = 1)) = intercept + slope * logit(p_home)

on the binary-scored 2018-2024 dev rows. The fit is done with
deterministic Newton-Raphson / IRLS using the logistic log-likelihood
as the objective. Ties are excluded; 2025 is rejected at the boundary.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

import polars as pl

from .metrics import _assert_development_only, _scored

# ---------------------------------------------------------------------------
# Reliability table
# ---------------------------------------------------------------------------

# Ten non-overlapping buckets that cover the full [0.00, 1.00] range.
# Each row belongs to exactly one bucket. 1.00 falls in the final bucket
# (closed on the right) so the bucket boundaries are mutually exclusive
# and collectively exhaustive.
DEFAULT_BUCKET_EDGES: tuple[float, ...] = (
    0.00, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00,
)


def reliability_table(
    predictions: pl.DataFrame,
    bucket_edges: Sequence[float] = DEFAULT_BUCKET_EDGES,
) -> list[dict[str, Any]]:
    """Bucket the binary-scored predictions and report mean predicted
    probability and actual home-win rate per bucket.  Buckets are
    half-open ``[low, high)`` for the first nine buckets and closed
    ``[0.90, 1.00]`` for the last bucket so ``1.00`` is included.
    """
    _assert_development_only(predictions)
    scored = _scored(predictions)
    rows: list[dict[str, Any]] = []
    edges = list(bucket_edges)
    if len(edges) < 2:
        raise ValueError("bucket_edges must have at least 2 elements")
    total = int(scored.height)
    sum_counts = 0
    for idx in range(len(edges) - 1):
        low = float(edges[idx])
        high = float(edges[idx + 1])
        is_last = idx == len(edges) - 2
        if is_last:
            bucket = scored.filter(
                (pl.col("predicted_home_win_probability") >= low)
                & (pl.col("predicted_home_win_probability") <= high)
            )
        else:
            bucket = scored.filter(
                (pl.col("predicted_home_win_probability") >= low)
                & (pl.col("predicted_home_win_probability") < high)
            )
        if bucket.height == 0:
            rows.append(
                {
                    "bucket_low": low,
                    "bucket_high": high,
                    "count": 0,
                    "mean_predicted_probability": None,
                    "actual_home_win_rate": None,
                }
            )
            continue
        sum_counts += int(bucket.height)
        rows.append(
            {
                "bucket_low": low,
                "bucket_high": high,
                "count": int(bucket.height),
                "mean_predicted_probability": float(
                    bucket["predicted_home_win_probability"].mean()
                ),
                "actual_home_win_rate": float(
                    bucket["actual_home_win"].cast(pl.Float64).mean()
                ),
            }
        )
    if sum_counts != total:
        raise RuntimeError(
            f"reliability bucket sum mismatch: {sum_counts} != {total}"
        )
    return rows


# ---------------------------------------------------------------------------
# Logistic recalibration
# ---------------------------------------------------------------------------

EPS_PROB = 1e-9


def _logit(p: float) -> float:
    p_c = min(1.0 - EPS_PROB, max(EPS_PROB, p))
    return math.log(p_c / (1.0 - p_c))


def _sigmoid(x: float) -> float:
    # numerically stable sigmoid
    if x >= 0.0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def logistic_recalibration(
    predictions: pl.DataFrame,
    *,
    max_iter: int = 100,
    tol: float = 1e-9,
) -> dict[str, Any]:
    """Fit the diagnostic logistic recalibration model and return a
    structured result.

    The fit uses deterministic Newton-Raphson on the logistic
    log-likelihood.  The return value contains the converged or
    last-iter values, the iteration count, convergence flag, and a
    human-readable status.

    Returns::

        {
            "calibration_intercept": float | None,
            "calibration_slope": float | None,
            "calibration_fit_status": str,
            "calibration_iterations": int,
            "calibration_converged": bool,
        }
    """
    _assert_development_only(predictions)
    scored = _scored(predictions)
    n = int(scored.height)

    if n < 2:
        return {
            "calibration_intercept": None,
            "calibration_slope": None,
            "calibration_fit_status": "insufficient_data",
            "calibration_iterations": 0,
            "calibration_converged": False,
            "max_iter": max_iter,
            "tol": tol,
            "calibration_rows_used": n,
        }

    xs: list[float] = [
        _logit(float(p))
        for p in scored["predicted_home_win_probability"].to_list()
    ]
    ys: list[float] = [
        float(int(y))
        for y in scored["actual_home_win"].to_list()
    ]

    # One-class outcome
    n_pos = sum(1 for y in ys if y > 0.5)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return {
            "calibration_intercept": None,
            "calibration_slope": None,
            "calibration_fit_status": "one_class_outcome",
            "calibration_iterations": 0,
            "calibration_converged": False,
            "max_iter": max_iter,
            "tol": tol,
            "calibration_rows_used": n,
        }

    # Constant input probability -> constant logit -> slope undefined
    if max(xs) - min(xs) < 1e-15:
        return {
            "calibration_intercept": None,
            "calibration_slope": None,
            "calibration_fit_status": "constant_input",
            "calibration_iterations": 0,
            "calibration_converged": False,
        }

    # Initialise at (0, 1) (identity in logit space)
    intercept = 0.0
    slope = 1.0
    converged = False
    iterations = 0
    _ = -math.inf  # last log-likelihood (kept for diagnostic logging)

    for it in range(1, max_iter + 1):
        iterations = it
        eta = [intercept + slope * x for x in xs]
        mu = [_sigmoid(e) for e in eta]
        # gradient
        g0 = sum(mu[i] - ys[i] for i in range(n))
        g1 = sum((mu[i] - ys[i]) * xs[i] for i in range(n))
        # hessian
        w = [mu[i] * (1.0 - mu[i]) for i in range(n)]
        h00 = sum(w)
        h01 = sum(w[i] * xs[i] for i in range(n))
        h11 = sum(w[i] * xs[i] * xs[i] for i in range(n))
        det = h00 * h11 - h01 * h01
        if not math.isfinite(det) or abs(det) < 1e-18:
            return {
                "calibration_intercept": intercept,
                "calibration_slope": slope,
                "calibration_fit_status": "singular_hessian",
                "calibration_iterations": iterations,
                "calibration_converged": False,
                "max_iter": max_iter,
                "tol": tol,
                "calibration_rows_used": n,
            }
        # Newton step
        d_intercept = (h11 * g0 - h01 * g1) / det
        d_slope = (h00 * g1 - h01 * g0) / det
        intercept -= d_intercept
        slope -= d_slope
        if not (math.isfinite(intercept) and math.isfinite(slope)):
            return {
                "calibration_intercept": None,
                "calibration_slope": None,
                "calibration_fit_status": "non_finite_step",
                "calibration_iterations": iterations,
                "calibration_converged": False,
                "max_iter": max_iter,
                "tol": tol,
                "calibration_rows_used": n,
            }
        if abs(d_intercept) < tol and abs(d_slope) < tol:
            converged = True
            _ = sum(  # noqa: F841 - retained for diagnostics
                ys[i] * math.log(max(EPS_PROB, mu[i]))
                + (1.0 - ys[i]) * math.log(max(EPS_PROB, 1.0 - mu[i]))
                for i in range(n)
            )
            break
        _ll_value = sum(  # noqa: F841 - retained for diagnostics
            ys[i] * math.log(max(EPS_PROB, mu[i]))
            + (1.0 - ys[i]) * math.log(max(EPS_PROB, 1.0 - mu[i]))
            for i in range(n)
        )

    return {
        "calibration_intercept": float(intercept),
        "calibration_slope": float(slope),
        "calibration_fit_status": "converged" if converged else "max_iter_reached",
        "calibration_iterations": iterations,
        "calibration_converged": converged,
        "max_iter": max_iter,
        "tol": tol,
        "calibration_rows_used": n,
    }


# ---------------------------------------------------------------------------
# Compatibility wrapper
# ---------------------------------------------------------------------------
#
# The wrapper ``calibration_intercept_slope`` is RETIRED. Production
# callers must use ``logistic_recalibration`` directly, which returns a
# structured result whose ``calibration_intercept`` and
# ``calibration_slope`` are ``None`` (not 0.0/1.0) when the fit is
# undefined. The legacy identity-substitution behavior
# ``(0.0, 1.0)`` is removed; scorecard rendering must handle the null
# case explicitly.
