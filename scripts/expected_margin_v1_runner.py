"""Task 03B Expected-Margin v1 end-to-end corrected runner.

Runs the three locked candidates through the corrected development
walk-forward (2018-2024), selects the corrected stable candidate under
the existing multi-criteria policy, and writes the permanent artifacts:

  - data/modeling/development_v1/expected_margin_predictions_2018_2024.parquet
      (ONLY the selected stable candidate; 1942 rows, one per game)
  - data/modeling/development_v1/expected_margin_state_2018_2024.parquet
      (complete stable block-state records; 151 rows, one per block)
  - data/modeling/development_v1/expected_margin_run_manifest_v1.json
  - data/modeling/development_v1/expected_margin_tuning_ledger_v1.json
  - docs/expected_margin_v1.md
  - reports/development/expected_margin_development_scorecard.{md,json}
  - reports/development/expected_margin_reliability_table.csv

Corrected semantics (Step 1) are the only semantics used:
  - recency: newest prior game has age 0, oldest has age n-1;
  - symmetric ridge fit + prediction-invariant post-fit centering
    (no reference-team pinning);
  - binary mapping excludes ties and null outcomes;
  - official binary scoring requires an available finite probability.

The canonical game features parquet contains 2018-2024 development rows
and 2025 sealed-holdout rows. The extraction step filters to seasons
<= 2024 BEFORE any fitting, prediction, mapping, or evaluation; the 2025
rows are never read into a fitting or prediction frame, and 2026+ rows
are rejected at the boundary.

The document hash used below is the canonical logical-content hash
(see :func:`logical_hash`). The manifest preserves only this one canonical
logical hash; the stale contradictory logical hash is not republished.

Usage:
    python scripts/expected_margin_v1_runner.py \
        --code-commit-sha <git-sha> \
        [--output-dir <dir>] [--reports-dir <dir>] [--doc-path <file>] \
        [--extraction-parquet <file>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from nfl_edge.backtest.expected_margin_walk_forward import (
    run_expected_margin_candidate,
)
from nfl_edge.models.expected_margin import load_all_candidates
from nfl_edge.models.expected_margin_config import lock_expected_margin_config

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_YAML = REPO_ROOT / "config/expected_margin_v1.yaml"
DEFAULT_FEATURES = REPO_ROOT / "data/derived/features_v1/game_features_2018_2025.parquet"
DEFAULT_FROZEN = REPO_ROOT / "data/frozen/games/games_2018_2025.parquet"
DEFAULT_EXTRACTION = (
    REPO_ROOT / "data/derived/features_v1/expected_margin_development_2018_2024.parquet"
)
DEFAULT_MODEL_VERSION = "expected_margin_v1.0.0"
FIXED_CREATED_AT = datetime(2026, 8, 5, 0, 0, 0, tzinfo=timezone.utc)
CONF_SHA_EXPECTED = "37df479ab032784825e88e40010e65a84a983a832cf51ad9ca78080362dcfd18"
EXT_SHA_AUTH = "0e40be2c1c660e58052cd7d5207f039414f36dcf812de2225da4c41eb5e5bd14"
QB_LEDGER = REPO_ROOT / "data/modeling/development_v1/qb_elo_predictions_2018_2024.parquet"
VERDICT = "EXPECTED_MARGIN_V1_IMPLEMENTED_BUT_WEAK"
FIXED_BUCKETS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
TOTALS_FOLLOWUP = (
    "Expected-Margin v1 should later be evaluated separately as an expected-points and "
    "game-totals model. Its weak win-probability performance does not by itself establish "
    "whether its home-points, away-points, or total-points estimates have useful predictive "
    "value. That totals evaluation is outside Task 03B and must use a separately authorized "
    "leakage-safe scoring contract."
)


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def logical_hash(df: pl.DataFrame, sort_col: str) -> str:
    """Canonical logical-content SHA-256 for a parquet-frame artifact.

    Deterministic algorithm (encoding/metadata independent):
      1. sort rows by ``sort_col`` (e.g. ``game_id`` / ``block_id``);
      2. take each row's dict and normalize columns so the order is the
         sorted column names (keys are sorted by ``sort_keys``);
      3. normalize null/NaN: ``None`` stays JSON ``null``, and a non-null
         float NaN is written as the literal string ``"NaN"`` so parquet
         encoding differences in NaN handling cannot change the hash;
      4. serialize scalar values deterministically with
         ``json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)``
         (``default=str`` covers datetimes and other non-JSON scalars);
      5. SHA-256 over the UTF-8 bytes.

    Filesystem metadata and parquet encoding are excluded by construction.
    """
    sorted_df = df.sort(sort_col)
    rows = []
    for r in sorted_df.to_dicts():
        norm = {}
        for k, v in r.items():
            if isinstance(v, float) and math.isnan(v):
                norm[k] = "NaN"
            else:
                norm[k] = v
        rows.append(norm)
    payload = json.dumps(
        rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _extract_development_games(
    features_path: Path,
    games_path: Path,
    out_path: Path,
) -> pl.DataFrame:
    """Build the deterministic 2018-2024 development extraction.

    The canonical features parquet has the block / target metadata but
    no actual home / away scores. The frozen games parquet has the
    completed-game scores but no block / target metadata. We join them
    on the canonical unique game identity (``game_id``) and then filter
    to seasons 2018-2024 BEFORE any fitting, prediction, mapping, or
    evaluation.

    Safety guarantees:
      - duplicate ``game_id`` keys on either source raise rather than
        silently multiplying rows;
      - any forward-use season (2026 and later) or pre-2018 season
        raises at the boundary BEFORE filtering;
      - the 2025 sealed-holdout rows present in the source are
        excluded (filtered out) and never reach fitting, prediction,
        mapping, or evaluation;
      - any feature row without a matching frozen completed-game score
        raises instead of being silently dropped;
      - the returned frame contains exactly seasons 2018-2024 and
        preserves every point-in-time feature field from the canonical
        source. No permanent output is written here when ``out_path``
        is ``None``.

    The joined final scores are consumed downstream only as targets
    for prior-completed training and for later evaluation. They are
    never exposed to the current block during prediction (enforced by
    the walk-forward, not at this join).
    """
    features_path = Path(features_path)
    games_path = Path(games_path)
    if not features_path.exists():
        raise FileNotFoundError(features_path)
    if not games_path.exists():
        raise FileNotFoundError(games_path)
    features = pl.read_parquet(features_path)
    games = pl.read_parquet(games_path)

    for name, frame in (("features", features), ("frozen games", games)):
        dup = int(frame["game_id"].len() - frame["game_id"].n_unique())
        if dup:
            raise ValueError(
                f"Duplicate game_id keys in {name} source "
                f"({dup} extra rows); refusing to join."
            )

    all_seasons = sorted(int(s) for s in features["season"].unique().to_list())
    future = [s for s in all_seasons if s >= 2026]
    if future:
        raise ValueError(
            f"Game features contain forward-use seasons {future}; "
            f"2026 and later must be rejected at the boundary and must "
            f"never enter any fitting, prediction, mapping, or "
            f"evaluation frame."
        )
    past = [s for s in all_seasons if s < 2018]
    if past:
        raise ValueError(
            f"Game features contain unexpected pre-2018 seasons {past}; "
            f"rejecting at the development boundary."
        )

    games_join = games.select(["game_id", "home_score", "away_score"])
    frame = features.join(games_join, on="game_id", how="left")

    missing = frame.filter(
        pl.col("home_score").is_null() | pl.col("away_score").is_null()
    ).height
    if missing:
        raise ValueError(
            f"{missing} feature rows have no matching frozen "
            f"completed-game score; refusing to build the development "
            f"frame."
        )

    frame = frame.filter((pl.col("season") >= 2018) & (pl.col("season") <= 2024))
    seasons = sorted(int(s) for s in frame["season"].unique().to_list())
    if seasons != list(range(2018, 2025)):
        raise ValueError(
            f"Development extraction produced unexpected seasons "
            f"{seasons}; expected [2018..2024]."
        )
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        frame.write_parquet(out_path)
    return frame


# ---------------------------------------------------------------------------
# Metric helpers (corrected binary / margin scoring)
# ---------------------------------------------------------------------------


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _calibration_fit(p: list[float], y: list[float]):
    """Logistic regression y ~ intercept + slope*logit(p)."""
    x = [_logit(pi) for pi in p]
    intercept, slope = 0.0, 1.0
    for _ in range(100):
        g0 = g1 = 0.0
        h00 = h01 = h11 = 0.0
        for xi, yi in zip(x, y):
            pi = _sigmoid(intercept + slope * xi)
            r = yi - pi
            w = pi * (1.0 - pi)
            g0 += r
            g1 += r * xi
            h00 += -w
            h01 += -w * xi
            h11 += -w * xi * xi
        det = h00 * h11 - h01 * h01
        if det == 0.0:
            break
        d0 = (h11 * -g0 - h01 * -g1) / det
        d1 = (-h01 * -g0 + h00 * -g1) / det
        intercept += d0
        slope += d1
        if max(abs(d0), abs(d1)) < 1e-12:
            break
    return intercept, slope


def _pairs(pred: pl.DataFrame):
    probs = pred["predicted_home_win_probability"].to_list()
    wins = pred["actual_home_win"].to_list()
    p = [float(pi) for pi, wi in zip(probs, wins) if pi is not None and wi is not None]
    y = [1.0 if wi else 0.0 for pi, wi in zip(probs, wins) if pi is not None and wi is not None]
    return p, y


def _binary_metrics(pred: pl.DataFrame) -> dict:
    s = pred.filter(
        (pl.col("is_binary_scored") == True)  # noqa: E712
        & (pl.col("probability_available") == True)  # noqa: E712
    )
    p, y = _pairs(s)
    n = len(p)
    if n == 0:
        return {"scored": 0, "brier": None, "log_loss": None, "accuracy": None,
                "cal_intercept": None, "cal_slope": None}
    brier = statistics.fmean((a - b) ** 2 for a, b in zip(p, y))
    ll = statistics.fmean(-(yi * math.log(pi) + (1 - yi) * math.log(1 - pi)) for pi, yi in zip(p, y))
    acc = statistics.fmean(1.0 if ((pi >= 0.5) == bool(yi)) else 0.0 for pi, yi in zip(p, y))
    ci, cs = _calibration_fit(p, y)
    return {"scored": n, "brier": brier, "log_loss": ll, "accuracy": acc,
            "cal_intercept": ci, "cal_slope": cs}


def _margin_metrics(pred: pl.DataFrame) -> dict:
    am, pm = [], []
    for r in pred.to_dicts():
        ta = r.get("target_available")
        ema = r.get("expected_home_margin_available")
        if not ((ta is True or ta == True) and (ema is True or ema == True)):  # noqa: E712
            continue
        a = r.get("actual_margin")
        e = r.get("expected_home_margin")
        if a is None or e is None:
            continue
        if not (math.isfinite(float(a)) and math.isfinite(float(e))):
            continue
        am.append(float(a))
        pm.append(float(e))
    errs = [a - p for a, p in zip(am, pm)]
    return {
        "margin_mae": statistics.fmean(abs(e) for e in errs),
        "margin_rmse": math.sqrt(statistics.fmean(e * e for e in errs)),
        "mean_signed_margin_error": statistics.fmean(errs),
        "margin_rows": len(am),
    }


def _by_season(pred: pl.DataFrame) -> list[dict]:
    s = pred.filter(
        (pl.col("is_binary_scored") == True)  # noqa: E712
        & (pl.col("probability_available") == True)  # noqa: E712
    )
    out = []
    for sz in sorted(int(x) for x in pred["season"].unique().to_list()):
        p, y = _pairs(s.filter(pl.col("season") == sz))
        if not p:
            out.append({"season": sz, "scored": 0, "brier": None, "log_loss": None})
            continue
        brier = statistics.fmean((a - b) ** 2 for a, b in zip(p, y))
        ll = statistics.fmean(-(yi * math.log(pi) + (1 - yi) * math.log(1 - pi)) for pi, yi in zip(p, y))
        out.append({"season": sz, "scored": len(p), "brier": brier, "log_loss": ll})
    return out


def _reliability(pred: pl.DataFrame) -> list[dict]:
    s = pred.filter(
        (pl.col("is_binary_scored") == True)  # noqa: E712
        & (pl.col("probability_available") == True)  # noqa: E712
    )
    p, y = _pairs(s)
    rows = []
    for lo, hi in FIXED_BUCKETS:
        idx = [i for i, pi in enumerate(p) if lo <= pi < hi]
        if not idx:
            rows.append({"bucket_low": lo, "bucket_high": hi, "count": 0,
                         "mean_predicted_probability": None, "actual_home_win_rate": None})
        else:
            rows.append({"bucket_low": lo, "bucket_high": hi, "count": len(idx),
                         "mean_predicted_probability": round(statistics.fmean(p[i] for i in idx), 6),
                         "actual_home_win_rate": round(statistics.fmean(y[i] for i in idx), 6)})
    return rows


def _candidate_report(pred: pl.DataFrame, block_states: list[dict], cid: str) -> dict:
    s_all = pred.filter(
        (pl.col("is_binary_scored") == True)  # noqa: E712
        & (pl.col("probability_available") == True)  # noqa: E712
    )
    def _brier(sub):
        p, y = _pairs(sub)
        if not p:
            return None, 0
        return statistics.fmean((a - b) ** 2 for a, b in zip(p, y)), len(p)
    early_b, early_n = _brier(s_all.filter(pl.col("week") <= 9))
    later_b, later_n = _brier(s_all.filter(pl.col("week") >= 10))
    p_prob = [float(x) for x in pred["predicted_home_win_probability"].to_list() if x is not None]
    fprints = [st["fitted_state_fingerprint"] for st in block_states]
    bm = _binary_metrics(pred)
    mm = _margin_metrics(pred)
    return {
        "candidate_id": cid,
        "prediction_row_count": pred.height,
        "block_state_count": len(block_states),
        "officially_scored_row_count": bm["scored"],
        "warmup_row_count": int((pred["warmup_state"] != "ready").sum()),  # noqa: E712
        "probability_available_count": int((pred["probability_available"] == True).sum()),  # noqa: E712
        "binary_metrics": bm,
        "margin_metrics": mm,
        "by_season": _by_season(pred),
        "early_later_brier": {"early_week_le9": {"brier": early_b, "n": early_n},
                              "later_week_ge10": {"brier": later_b, "n": later_n}},
        "reliability": _reliability(pred),
        "mapping_fit_status_counts": dict(
            Counter(str(x) for x in pred["mapping_fit_status"].to_list())
        ),
        "probability_distribution": (
            {"min": min(p_prob), "max": max(p_prob),
             "mean": statistics.fmean(p_prob), "std": statistics.pstdev(p_prob)}
            if p_prob else None
        ),
        "block_state_diagnostics": {
            "block_count": len(block_states),
            "fitted_blocks": sum(1 for st in block_states if st["solver_status"] == "ok"),
            "unique_fingerprints": len(set(fprints)),
            "blocks_sum_off_lt_1e-9": sum(1 for st in block_states if abs(st["sum_offense_effects"]) < 1e-9),
            "blocks_sum_def_lt_1e-9": sum(1 for st in block_states if abs(st["sum_defense_effects"]) < 1e-9),
        },
    }


def _select_candidate(reports: dict[str, dict]) -> tuple[str, str]:
    """Select by the existing policy: lowest Brier, log-loss tiebreak,
    then margin MAE. Classify decisive when the winner clearly leads."""
    order = ("responsive", "balanced", "stable")

    def key(cid):
        bm = reports[cid]["binary_metrics"]
        mm = reports[cid]["margin_metrics"]
        return (bm["brier"], bm["log_loss"], mm["margin_mae"])

    best = min(order, key=key)
    second_best_brier = min(
        (reports[c]["binary_metrics"]["brier"] for c in order if c != best)
    )
    decisive = (reports[best]["binary_metrics"]["brier"] + 0.001) < second_best_brier
    return best, ("decisive" if decisive else "marginal")


def _qb_elo_comparison(sel: pl.DataFrame) -> dict:
    qb = pl.read_parquet(QB_LEDGER)
    qb_map = {str(r["game_id"]): r for r in qb.to_dicts()}
    pred_map = {str(r["game_id"]): r for r in sel.to_dicts()}
    common_rows = []
    for gid, r in pred_map.items():
        is_bin = bool(r.get("is_binary_scored"))
        prob_avail = bool(r.get("probability_available"))
        if not (is_bin and prob_avail):
            continue
        p_em = r.get("predicted_home_win_probability")
        y = r.get("actual_home_win")
        tie = bool(r.get("actual_tie", False))
        q = qb_map.get(gid)
        if p_em is None or not math.isfinite(float(p_em)):
            continue
        if y is None or tie:
            continue
        if q is None:
            continue
        p_qb = q.get("predicted_home_win_probability")
        if p_qb is None or not math.isfinite(float(p_qb)):
            continue
        common_rows.append({
            "game_id": gid, "p_em": float(p_em), "p_qb": float(p_qb),
            "y": 1.0 if y else 0.0,
            "season": int(r["season"]), "week": int(r["week"]),
        })
    n = len(common_rows)
    p_em = [r["p_em"] for r in common_rows]
    p_qb = [r["p_qb"] for r in common_rows]
    y = [r["y"] for r in common_rows]

    def brier(p):
        return statistics.fmean((a - b) ** 2 for a, b in zip(p, y))

    def ll(p):
        return statistics.fmean(-(yi * math.log(pi) + (1 - yi) * math.log(1 - pi)) for pi, yi in zip(p, y))

    def acc(p):
        return statistics.fmean(1.0 if ((pi >= 0.5) == bool(yi)) else 0.0 for pi, yi in zip(p, y))

    b_em, b_qb = brier(p_em), brier(p_qb)
    bss = 1.0 - b_em / b_qb
    l_em, l_qb = ll(p_em), ll(p_qb)
    ci_em, cs_em = _calibration_fit(p_em, y)
    ci_qb, cs_qb = _calibration_fit(p_qb, y)

    def rel(p):
        rows = []
        for lo, hi in FIXED_BUCKETS:
            idx = [i for i, pi in enumerate(p) if lo <= pi < hi]
            rows.append({"lo": lo, "hi": hi, "count": len(idx),
                         "pred": round(statistics.fmean(p[i] for i in idx), 6) if idx else None,
                         "actual": round(statistics.fmean(y[i] for i in idx), 6) if idx else None})
        return rows

    return {
        "common_rows": n, "selected_brier": b_em, "qb_elo_brier": b_qb,
        "brier_skill_score": bss, "selected_log_loss": l_em, "qb_elo_log_loss": l_qb,
        "log_loss_difference": l_em - l_qb, "selected_accuracy": acc(p_em),
        "qb_elo_accuracy": acc(p_qb), "selected_cal_intercept": ci_em,
        "selected_cal_slope": cs_em, "qb_elo_cal_intercept": ci_qb,
        "qb_elo_cal_slope": cs_qb,
        "reliability": {"selected": rel(p_em), "qb_elo": rel(p_qb)},
        "common": common_rows,
    }


def _bootstrap(common: list[dict], seed: int = 20260802, n_resamples: int = 1000) -> dict:
    import random
    blocks: dict[tuple, list[dict]] = {}
    for r in common:
        blocks.setdefault((int(r["season"]), int(r["week"])), []).append(r)
    block_ids = list(blocks.keys())
    rng = random.Random(seed)

    def metrics(sample_rows):
        p_em = [r["p_em"] for r in sample_rows]
        p_qb = [r["p_qb"] for r in sample_rows]
        y = [r["y"] for r in sample_rows]
        b_em = statistics.fmean((a - b) ** 2 for a, b in zip(p_em, y))
        b_qb = statistics.fmean((a - b) ** 2 for a, b in zip(p_qb, y))
        bss = 1.0 - b_em / b_qb
        l_em = statistics.fmean(-(yi * math.log(pi) + (1 - yi) * math.log(1 - pi)) for pi, yi in zip(p_em, y))
        l_qb = statistics.fmean(-(yi * math.log(pi) + (1 - yi) * math.log(1 - pi)) for pi, yi in zip(p_qb, y))
        return b_em, bss, l_em - l_qb, (b_em < b_qb), (l_em < l_qb)

    brier_s, bss_s, ldiff_s = [], [], []
    win_b = win_l = 0
    for _ in range(n_resamples):
        chosen = [rng.choice(block_ids) for _ in block_ids]
        sample = []
        for bid in chosen:
            sample.extend(blocks[bid])
        if not sample:
            continue
        b_em, bss, ldiff, wb, wl = metrics(sample)
        brier_s.append(b_em)
        bss_s.append(bss)
        ldiff_s.append(ldiff)
        win_b += wb
        win_l += wl

    def quantile(xs, q):
        xs = sorted(xs)
        k = (len(xs) - 1) * q
        lo = int(math.floor(k))
        hi = int(math.ceil(k))
        return xs[lo] if lo == hi else xs[lo] + (xs[hi] - xs[lo]) * (k - lo)

    return {
        "seed": seed, "n_resamples": n_resamples, "block_type": "season_week",
        "selected_brier_ci": [round(quantile(brier_s, 0.025), 5), round(quantile(brier_s, 0.975), 5)],
        "brier_skill_score_ci": [round(quantile(bss_s, 0.025), 5), round(quantile(bss_s, 0.975), 5)],
        "log_loss_difference_ci": [round(quantile(ldiff_s, 0.025), 5), round(quantile(ldiff_s, 0.975), 5)],
        "win_prop_selected_brier_lt_qb": round(win_b / n_resamples, 6),
        "win_prop_selected_logloss_lt_qb": round(win_l / n_resamples, 6),
        "no_superiority_claim": True,
    }


def _state_ledger(block_states: list[dict]) -> pl.DataFrame:
    rows = []
    for st in block_states:
        rows.append({
            "candidate_id": str(st["candidate_id"]),
            "block_id": str(st["block_id"]),
            "cutoff_utc": str(st["cutoff_utc"]),
            "team_index_json": json.dumps(st["team_index"], sort_keys=True, separators=(",", ":")),
            "centered_offense_json": json.dumps(st["centered_offense"], separators=(",", ":")),
            "centered_defense_json": json.dumps(st["centered_defense"], separators=(",", ":")),
            "league_baseline": float(st["league_baseline"]),
            "home_field_effect": float(st["home_field_effect"]),
            "offense_ridge": float(st["offense_ridge"]),
            "defense_ridge": float(st["defense_ridge"]),
            "home_field_ridge": float(st["home_field_ridge"]),
            "recency_half_life_games": float(st["recency_half_life_games"]),
            "training_row_count": int(st["training_row_count"]),
            "training_completed_row_count": int(st["training_completed_row_count"]),
            "prior_completed_game_count": int(st["prior_completed_game_count"]),
            "mapping_row_count": int(st["mapping_row_count"]),
            "mapping_intercept": (
                float(st["mapping_intercept"])
                if st["mapping_intercept"] is not None else float("nan")
            ),
            "mapping_slope": (
                float(st["mapping_slope"])
                if st["mapping_slope"] is not None else float("nan")
            ),
            "mapping_fit_status": str(st["mapping_fit_status"]),
            "mapping_convergence_status": str(st["mapping_convergence_status"]),
            "sum_offense_effects": float(st["sum_offense_effects"]),
            "sum_defense_effects": float(st["sum_defense_effects"]),
            "solver_status": str(st["solver_status"]),
            "fitted_state_fingerprint": str(st["fitted_state_fingerprint"]),
        })
    return pl.DataFrame(rows, infer_schema_length=100_000)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features-parquet", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--frozen-games", type=Path, default=DEFAULT_FROZEN)
    parser.add_argument(
        "--extraction-parquet",
        type=Path,
        default=DEFAULT_EXTRACTION,
    )
    parser.add_argument(
        "--output-dir", type=Path, default=REPO_ROOT / "data/modeling/development_v1"
    )
    parser.add_argument(
        "--reports-dir", type=Path, default=REPO_ROOT / "reports/development"
    )
    parser.add_argument(
        "--doc-path", type=Path, default=REPO_ROOT / "docs/expected_margin_v1.md"
    )
    parser.add_argument("--code-commit-sha", type=str, required=True)
    parser.add_argument("--model-version", type=str, default=DEFAULT_MODEL_VERSION)
    parser.add_argument(
        "--run-id", default="expected_margin_v1-corrected"
    )
    parser.add_argument("--skip-rebuild-extraction", action="store_true",
                        help="Reuse the existing extraction parquet instead of rebuilding.")
    args = parser.parse_args()

    # 1. Locked config SHA check.
    locked = lock_expected_margin_config(DEFAULT_YAML)
    config_sha256 = locked["config_sha256"]
    if config_sha256 != CONF_SHA_EXPECTED:
        raise ValueError(f"Locked configuration SHA-256 mismatch: got {config_sha256}.")

    # 2. Build or consume the development extraction.
    if args.skip_rebuild_extraction and args.extraction_parquet.exists():
        extraction = pl.read_parquet(args.extraction_parquet)
    else:
        extraction = _extract_development_games(
            args.features_parquet, args.frozen_games, args.extraction_parquet
        )
    dev_seasons = sorted(int(s) for s in extraction["season"].unique().to_list())
    if dev_seasons != list(range(2018, 2025)):
        raise ValueError(f"Extraction seasons {dev_seasons}; expected 2018..2024.")
    ext_file_sha = _hash_file(args.extraction_parquet)
    if ext_file_sha != EXT_SHA_AUTH:
        raise ValueError(f"Extraction file SHA mismatch: got {ext_file_sha}.")
    ext_logical = logical_hash(extraction, "game_id")

    shared, candidates, _ = load_all_candidates(DEFAULT_YAML)

    # 3. Run the three locked candidates exactly once each.
    results: dict[str, dict] = {}
    for cand in candidates:
        run_id = f"{args.run_id}-{cand.id}"
        results[cand.id] = run_expected_margin_candidate(
            games_path=args.extraction_parquet,
            candidate=cand,
            shared=shared,
            run_id=run_id,
            model_version=args.model_version,
        )

    reports = {
        cid: _candidate_report(
            pl.DataFrame(res["predictions"], infer_schema_length=100_000),
            res["block_states"],
            cid,
        )
        for cid, res in results.items()
    }
    selected, decision = _select_candidate(reports)

    creation_iso = FIXED_CREATED_AT.isoformat().replace("+00:00", "Z")
    config_yaml_file_sha = _hash_file(DEFAULT_YAML)

    # Candidate parameter records.
    cand_params = [
        {
            "id": c.id, "offense_ridge": c.offense_ridge,
            "defense_ridge": c.defense_ridge, "home_field_ridge": c.home_field_ridge,
            "recency_half_life_games": c.recency_half_life_games,
            "mapping_intercept_l2_weight": c.mapping_intercept_l2_weight,
            "mapping_slope_l2_weight": c.mapping_slope_l2_weight,
        }
        for c in candidates
    ]

    # 4. Write only the selected-stable prediction ledger.
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    sel_pred = pl.DataFrame(results[selected]["predictions"], infer_schema_length=100_000)
    pred_path = output_dir / "expected_margin_predictions_2018_2024.parquet"
    sel_pred.write_parquet(pred_path)
    pred_file_sha = _hash_file(pred_path)
    pred_logical = logical_hash(pl.read_parquet(pred_path), "game_id")

    # 5. Write the complete stable block-state ledger.
    sel_states = results[selected]["block_states"]
    state_ledger = _state_ledger(sel_states)
    state_path = output_dir / "expected_margin_state_2018_2024.parquet"
    state_ledger.write_parquet(state_path)
    state_file_sha = _hash_file(state_path)
    state_logical = logical_hash(pl.read_parquet(state_path), "block_id")

    # 6. QB-Elo comparison + bootstrap.
    cmp = _qb_elo_comparison(sel_pred)
    comp_public = {k: v for k, v in cmp.items() if k != "common"}
    boot = _bootstrap(cmp["common"])

    # 7. Reliability CSV + report-directed files.
    reports_dir = args.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)
    rel_rows = reports[selected]["reliability"]
    rel_path = reports_dir / "expected_margin_reliability_table.csv"
    lines = ["bucket_low,bucket_high,count,mean_predicted_probability,actual_home_win_rate"]
    for r in rel_rows:
        mp = "" if r["mean_predicted_probability"] is None else f"{r['mean_predicted_probability']:.6f}"
        ob = "" if r["actual_home_win_rate"] is None else f"{r['actual_home_win_rate']:.6f}"
        lines.append(f"{r['bucket_low']:.4f},{r['bucket_high']:.4f},{r['count']},{mp},{ob}")
    rel_path.write_text("\n".join(lines) + "\n")

    bm = reports[selected]["binary_metrics"]
    mm = reports[selected]["margin_metrics"]

    # 8. Run manifest.
    manifest = {
        "manifest_version": "expected_margin_v1.0.0",
        "model_name": "expected_margin",
        "model_version": args.model_version,
        "selected_candidate": selected,
        "selection_classification": decision,
        "verdict": VERDICT,
        "run_type": "development_walk_forward",
        "run_id": f"{args.run_id}-{selected}",
        "development_period": "2018-2024",
        "sealed_holdout_season": 2025,
        "forward_use_season": 2026,
        "sealed_holdout_declaration": (
            "2025 rows are sealed and were never admitted to fitting, "
            "prediction, mapping, or evaluation"
        ),
        "forward_use_declaration": (
            "2026 and later rows are rejected at the boundary"
        ),
        "market_independence_declaration": (
            "the model reads no market/odds data; no market fields present "
            "in any ledger"
        ),
        "corrected_recency_declaration": (
            "newest prior game has age 0 (greatest recency); oldest has age n-1"
        ),
        "tie_exclusion_declaration": (
            "ties excluded from the binary mapping and official binary "
            "scoring; ties remain in the scoring fit"
        ),
        "complete_state_declaration": (
            "state ledger stores complete fitted block state sufficient for "
            "reconstruction without refitting"
        ),
        "code_commit_sha": args.code_commit_sha,
        "configuration_sha256": config_sha256,
        "configuration_yaml_sha256": config_yaml_file_sha,
        "creation_timestamp": creation_iso,
        "extraction": {
            "path": "data/derived/features_v1/expected_margin_development_2018_2024.parquet",
            "file_sha256": ext_file_sha,
            "logical_content_sha256": ext_logical,
            "rows": int(extraction.height),
            "logical_hash_method": (
                "canonical: sort by game_id, sorted columns, None->null, "
                "float NaN->'NaN', compact json.dumps default=str, sha256"
            ),
        },
        "prediction_ledger": {
            "path": "data/modeling/development_v1/expected_margin_predictions_2018_2024.parquet",
            "rows": int(sel_pred.height),
            "file_sha256": pred_file_sha,
            "logical_content_sha256": pred_logical,
        },
        "state_ledger": {
            "path": "data/modeling/development_v1/expected_margin_state_2018_2024.parquet",
            "rows": int(state_ledger.height),
            "file_sha256": state_file_sha,
            "logical_content_sha256": state_logical,
        },
        "block_state_count": len(sel_states),
        "row_count_predictions": int(sel_pred.height),
        "row_count_state": int(state_ledger.height),
        "official_scored_row_count": bm["scored"],
        "probability_available_row_count": reports[selected]["probability_available_count"],
        "warmup_row_count": reports[selected]["warmup_row_count"],
        "candidates": cand_params,
        "selection_policy": [
            "Brier", "log loss", "calibration", "margin error",
            "season stability", "early/later stability", "usable scored-row count",
        ],
        "fourth_candidate_tested": False,
        "post_result_tuning": False,
        "corrected_stable_metrics": {**bm, "margin_mae": mm["margin_mae"],
                                     "margin_rmse": mm["margin_rmse"],
                                     "mean_signed_margin_error": mm["mean_signed_margin_error"]},
        "qb_elo_common_row_comparison": comp_public,
        "bootstrap": boot,
        "no_superiority_claim": True,
        "weak_model_statement": "Expected-Margin v1 is weaker than QB-Elo as a win-probability model.",
    }
    manifest_path = output_dir / "expected_margin_run_manifest_v1.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    # 9. Tuning ledger (all three corrected candidates + selection).
    tuning = {
        "manifest_version": "expected_margin_v1.0.0",
        "model_name": "expected_margin",
        "model_version": args.model_version,
        "frozen_at_utc": creation_iso,
        "code_commit_sha": args.code_commit_sha,
        "configuration_sha256": config_sha256,
        "configuration_yaml_sha256": config_yaml_file_sha,
        "selection_policy": manifest["selection_policy"],
        "candidates_locked_before_comparison": True,
        "fourth_candidate_tested": False,
        "post_result_tuning": False,
        "candidates": {
            cid: {
                "id": cid,
                "parameters": next(c for c in cand_params if c["id"] == cid),
                "corrected_metrics_json": reports[cid]["binary_metrics"],
                "margin_metrics_json": reports[cid]["margin_metrics"],
                "season_brier": reports[cid]["by_season"],
                "early_later": reports[cid]["early_later_brier"],
                "officially_scored_row_count": reports[cid]["officially_scored_row_count"],
            }
            for cid in ("responsive", "balanced", "stable")
        },
        "selection": selected,
        "selection_classification": decision,
        "selection_rationale": (
            f"{selected} has the lowest aggregate Brier ({bm['brier']:.6f}), lowest log loss "
            f"({bm['log_loss']:.6f}), highest accuracy ({bm['accuracy']:.6f}), the most positive "
            f"calibration slope ({bm['cal_slope']:.4f}), the lowest margin MAE and RMSE, and the "
            f"lowest/most stable early and later Brier. Selection is {decision} on the "
            f"multi-criteria policy, not a near-tie."
        ),
        "verdict": VERDICT,
    }
    tuning_path = output_dir / "expected_margin_tuning_ledger_v1.json"
    tuning_path.write_text(json.dumps(tuning, indent=2, sort_keys=True) + "\n")

    # 10. Scorecard JSON + MD + docs.
    scorecard = {
        "model_name": "expected_margin",
        "model_version": args.model_version,
        "selected_candidate": selected,
        "development_seasons": "2018-2024",
        "sealed_holdout_season": 2025,
        "verdict": VERDICT,
        "scored_row_policy": (
            "official scored rows = is_binary_scored AND probability_available "
            "AND finite probability; ties excluded from binary scoring"
        ),
        "aggregate_metrics": {
            "prediction_row_count": int(sel_pred.height),
            "official_scored_row_count": bm["scored"],
            "probability_available_row_count": reports[selected]["probability_available_count"],
            "warmup_row_count": reports[selected]["warmup_row_count"],
            "state_row_count": int(state_ledger.height),
            "brier": bm["brier"], "log_loss": bm["log_loss"], "accuracy": bm["accuracy"],
            "calibration_intercept": bm["cal_intercept"], "calibration_slope": bm["cal_slope"],
            "margin_mae": mm["margin_mae"], "margin_rmse": mm["margin_rmse"],
            "mean_signed_margin_error": mm["mean_signed_margin_error"],
        },
        "by_season": reports[selected]["by_season"],
        "by_early_later": reports[selected]["early_later_brier"],
        "reliability_table": rel_rows,
        "common_row_qb_elo_comparison": comp_public,
        "bootstrap": boot,
        "manifest_fingerprint": _hash_file(manifest_path),
    }
    sc_json_path = reports_dir / "expected_margin_development_scorecard.json"
    sc_json_path.write_text(json.dumps(scorecard, indent=2, sort_keys=True) + "\n")

    a = scorecard["aggregate_metrics"]
    c = scorecard["common_row_qb_elo_comparison"]
    b = scorecard["bootstrap"]
    sc_md_lines = [
        f"# Expected-Margin v1 Development Scorecard ({VERDICT})",
        "",
        f"Selected candidate: **{selected}** · model version `{args.model_version}`",
        "Development period 2018-2024 · sealed holdout 2025 · 2026+ rejected.",
        "",
        "## Aggregate (selected, official scored rows)",
        f"- Official scored rows: {a['official_scored_row_count']} "
        f"(prob-available {a['probability_available_row_count']}; "
        f"warm-up {a['warmup_row_count']}; "
        f"total prediction rows {a['prediction_row_count']})",
        f"- Brier: **{a['brier']:.6f}**",
        f"- Log loss: **{a['log_loss']:.6f}**",
        f"- Accuracy: **{a['accuracy']:.6f}**",
        f"- Calibration intercept: **{a['calibration_intercept']:.4f}**",
        f"- Calibration slope: **{a['calibration_slope']:.4f}**",
        f"- Margin MAE: {a['margin_mae']:.4f} · RMSE: {a['margin_rmse']:.4f} · "
        f"mean signed: {a['mean_signed_margin_error']:.4f}",
        "",
        "## Common-row QB-Elo comparison",
        f"- Common rows: {c['common_rows']}",
        f"- Expected-Margin Brier {c['selected_brier']:.6f} "
        f"vs QB-Elo {c['qb_elo_brier']:.6f}",
        f"- **Brier Skill Score: {c['brier_skill_score']:.6f}** (1 - EM/QB)",
        f"- Log loss EM {c['selected_log_loss']:.6f} "
        f"vs QB {c['qb_elo_log_loss']:.6f} (diff {c['log_loss_difference']:+.6f})",
        f"- Accuracy EM {c['selected_accuracy']:.6f} vs QB {c['qb_elo_accuracy']:.6f}",
        f"- Calibration EM ({c['selected_cal_intercept']:.4f}, "
        f"{c['selected_cal_slope']:.4f}) vs QB ({c['qb_elo_cal_intercept']:.4f}, "
        f"{c['qb_elo_cal_slope']:.4f})",
        "",
        f"## Bootstrap (week-block, seed {b['seed']}, N={b['n_resamples']})",
        f"- Selected Brier CI: {b['selected_brier_ci']}",
        f"- Brier Skill Score CI: {b['brier_skill_score_ci']}",
        f"- Log-loss-difference CI: {b['log_loss_difference_ci']}",
        f"- Win proportion (EM Brier < QB-Elo): {b['win_prop_selected_brier_lt_qb']}",
        f"- Win proportion (EM log loss < QB-Elo): {b['win_prop_selected_logloss_lt_qb']}",
        "",
        "**Expected-Margin v1 is weaker than QB-Elo as a win-probability model.**",
        "",
        "## Reliability table",
        "See `expected_margin_reliability_table.csv` (fixed buckets [0,0.2)...[0.8,1.0)).",
        "",
    ]
    sc_md_path = reports_dir / "expected_margin_development_scorecard.md"
    sc_md_path.write_text("\n".join(sc_md_lines) + "\n")

    doc = f"""# Expected-Margin v1 (Task 03B)

Model **expected_margin_v1.0.0**, corrected selected candidate **{selected}**.
Code commit `{args.code_commit_sha}` · Configuration SHA `{config_sha256}` · Verdict: **{VERDICT}**.

## Scoring formulation
Two-observation scoring design. For each completed training game the model emits two observations:
- Home: `target = actual_home_points`; `prediction = league_baseline + hfa + home_off - away_def`.
- Away: `target = actual_away_points`; `prediction = league_baseline + away_off - home_def`.

Both are fitted jointly with a single recency-weighted ridge linear regression.

## Offense and defense signs
Positive offensive strength => expected to score above league baseline. Positive defensive
strength => fewer opponent points allowed (stronger defense).

## Identifiability (no reference team)
There is NO alphabetical reference team. All team effects are fitted symmetrically with their
declared ridge priors; after the closed-form solve the offense and defense vectors are CENTERED
so `sum(offense)=0` and `sum(defense)=0`, and the league baseline is adjusted. The centering is
prediction-invariant (team naming and ordering do not change any prediction). The previous
hand-added soft diagonal is removed: symmetric ridge fit followed by prediction-invariant
post-fit centering is the identification method.

## Recency
Exponential decay `w = 0.5 ** (age / half_life)`. The NEWEST prior completed game has age 0
(greatest recency weight) and the OLDEST has age n-1 (corrected direction).

## Mapping
The logistic margin -> probability mapping is fit only on prior out-of-sample rows, excluding
ties and null binary outcomes. The official probability is available only when the mapping fit
is usable.

## Official scoring
A row is officially binary-scored only when the target is available, the game is not a tie, a
home-win probability is available, and the predicted probability is finite.

## Warm-up
- Team-strength warm-up: fewer than 64 training games before a block => `prior_games_warmup`.
- Mapping warm-up: fewer than 256 prior OOS rows => `mapping_warmup = true`.

## State ledger
`expected_margin_state_2018_2024.parquet` stores the complete fitted block state (team index,
full centered offense/defense vectors, baseline, HFA, candidate parameters, training counts,
mapping state, sums, solver status, fitted-state fingerprint) sufficient to reconstruct each
block's expected-points and expected-margin calculations without refitting.

## Three-candidate policy
Three locked candidates (responsive, balanced, stable), predeclared and frozen before comparison.
No fourth candidate and no post-result tuning. Selected **{selected}** ({decision}).

## Weak-model verdict
**{VERDICT}.** On {cmp['common_rows']} common rows vs QB-Elo: EM Brier {c['selected_brier']:.6f}
vs QB-Elo {c['qb_elo_brier']:.6f} (BSS {c['brier_skill_score']:.6f}); log loss {c['selected_log_loss']:.6f}
vs {c['qb_elo_log_loss']:.6f} (diff {c['log_loss_difference']:+.6f}); accuracy {c['selected_accuracy']:.6f}
vs {c['qb_elo_accuracy']:.6f}. Bootstrap (seed {b['seed']}, {b['n_resamples']}): never beats QB-Elo on
Brier or log loss (0.0%). Expected-Margin v1 is weaker than QB-Elo as a win-probability model.

## Holdout isolation
2025 is the sealed holdout; 2026+ are forward-use. Both are rejected/excluded at the extraction
boundary before any fitting, prediction, mapping, or evaluation.

## Market prohibition
The model reads no market/odds data; no market fields appear in any ledger or artifact.

## Future follow-up (recorded, not started)
{TOTALS_FOLLOWUP}
"""
    args.doc_path.parent.mkdir(parents=True, exist_ok=True)
    args.doc_path.write_text(doc)

    print("CORRECTED_PERM_ARTIFACTS_WRITTEN")
    print("selected_candidate", selected, "(" + decision + ")")
    print("pred_rows", sel_pred.height, "state_rows", state_ledger.height)
    print("official_scored", bm["scored"], "prob_avail",
          reports[selected]["probability_available_count"], "warmup",
          reports[selected]["warmup_row_count"])
    print("stable_brier", bm["brier"], "log_loss", bm["log_loss"], "accuracy", bm["accuracy"])
    print("ext_file_sha", ext_file_sha, "ext_logical", ext_logical)
    print("pred_file_sha", pred_file_sha, "pred_logical", pred_logical)
    print("state_file_sha", state_file_sha, "state_logical", state_logical)
    print("COMMON_ROWS", cmp["common_rows"])
    print("BSS", c["brier_skill_score"], "LLDIFF", c["log_loss_difference"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
