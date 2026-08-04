"""Build the development scorecard (Markdown + JSON) from the prediction ledger.

The scorecard is descriptive only. No 2025 data is permitted. The function
hard-fails if the prediction frame contains any season > 2024.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import polars as pl

from ..backtest.blocks import DEVELOPMENT_SEASON_MAX
from ..common.errors import SealedHoldoutAccessError
from .calibration import (
    logistic_recalibration,
    reliability_table,
)
from .metrics import (
    _assert_development_only,
    brier_score,
    descriptive_accuracy,
    log_loss,
)


def _fmt(value: float | None, places: int = 4) -> str:
    """Format a nullable float with a fixed number of decimal places.

    Returns "NA" when the value is None. This helper replaces the broken
    inline-conditional format specifiers that were used in the first
    version of the scorecard; a numeric format specifier does not accept
    a conditional expression, so the value is formatted outside the
    specifier.
    """
    if value is None:
        return "NA"
    return f"{value:.{places}f}"


def _season_counts(predictions: pl.DataFrame) -> list[dict[str, Any]]:
    """Return per-season aggregates."""
    rows: list[dict[str, Any]] = []
    for season in sorted(int(s) for s in predictions["season"].unique().to_list()):
        subset = predictions.filter(pl.col("season") == season)
        scored = subset.filter(
            pl.col("target_available") & pl.col("actual_home_win").is_not_null()
        )
        ties = int(subset.filter(pl.col("actual_tie") == True).height)  # noqa: E712
        if scored.height == 0:
            rows.append({
                "season": season,
                "predicted": int(subset.height),
                "scored": 0,
                "ties": ties,
                "accuracy": None,
                "log_loss": None,
                "brier": None,
            })
            continue
        rows.append({
            "season": season,
            "predicted": int(subset.height),
            "scored": int(scored.height),
            "ties": ties,
            "accuracy": descriptive_accuracy(scored),
            "log_loss": log_loss(scored),
            "brier": brier_score(scored),
        })
    return rows


def _weekly_counts(predictions: pl.DataFrame) -> list[dict[str, Any]]:
    """Return per-week (season, week) aggregates."""
    rows: list[dict[str, Any]] = []
    for (season, week) in sorted(
        {(int(s), int(w)) for s, w in zip(
            predictions["season"].to_list(), predictions["week"].to_list()
        )}
    ):
        subset = predictions.filter(
            (pl.col("season") == season) & (pl.col("week") == week)
        )
        scored = subset.filter(
            pl.col("target_available") & pl.col("actual_home_win").is_not_null()
        )
        if scored.height == 0:
            continue
        rows.append({
            "season": season,
            "week": week,
            "predicted": int(subset.height),
            "scored": int(scored.height),
            "accuracy": descriptive_accuracy(scored),
            "log_loss": log_loss(scored),
        })
    return rows


def _qb_certainty_counts(predictions: pl.DataFrame) -> list[dict[str, Any]]:
    """Return per QB-certainty bucket aggregates."""
    rows: list[dict[str, Any]] = []
    for certainty in sorted(set(predictions["qb_certainty_state"].to_list())):
        subset = predictions.filter(pl.col("qb_certainty_state") == certainty)
        scored = subset.filter(
            pl.col("target_available") & pl.col("actual_home_win").is_not_null()
        )
        if scored.height == 0:
            rows.append({
                "qb_certainty_state": certainty,
                "predicted": int(subset.height),
                "scored": 0,
                "accuracy": None,
                "log_loss": None,
                "brier": None,
            })
            continue
        rows.append({
            "qb_certainty_state": certainty,
            "predicted": int(subset.height),
            "scored": int(scored.height),
            "accuracy": descriptive_accuracy(scored),
            "log_loss": log_loss(scored),
            "brier": brier_score(scored),
        })
    return rows


def _worst_predictions(predictions: pl.DataFrame, n: int = 10) -> list[dict[str, Any]]:
    """Return the n worst log-loss predictions (highest log loss)."""
    scored = predictions.filter(
        pl.col("target_available") & pl.col("actual_home_win").is_not_null()
    )
    if scored.height == 0:
        return []
    rows = scored.to_dicts()
    eps = 1e-15
    for r in rows:
        p = max(eps, min(1.0 - eps, float(r["predicted_home_win_probability"])))
        y = 1.0 if r["actual_home_win"] else 0.0
        r["_log_loss"] = -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
    rows.sort(key=lambda r: r["_log_loss"], reverse=True)
    out = []
    for r in rows[:n]:
        out.append({
            "game_id": r["game_id"],
            "season": r["season"],
            "week": r["week"],
            "home_team": r["home_team"],
            "away_team": r["away_team"],
            "predicted_home_win_probability": round(r["predicted_home_win_probability"], 4),
            "actual_home_win": r["actual_home_win"],
            "log_loss": round(r["_log_loss"], 4),
        })
    return out


def _missingness(predictions: pl.DataFrame) -> dict[str, Any]:
    """Report missingness in the relevant numeric columns."""
    key_cols = [
        "home_elo_before",
        "away_elo_before",
        "home_field_adjustment",
        "home_qb_adjustment",
        "away_qb_adjustment",
        "predicted_home_win_probability",
    ]
    out: dict[str, Any] = {}
    for c in key_cols:
        if c in predictions.columns:
            out[c] = int(predictions[c].null_count())
    return out


def build_development_scorecard(
    predictions: pl.DataFrame,
    *,
    configuration: dict[str, Any],
    manifest: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Assemble the development scorecard from the prediction ledger.

    Writes:
        - reports/development/qb_elo_development_scorecard.json
        - reports/development/qb_elo_development_scorecard.md
        - reports/development/qb_elo_reliability_table.csv
    """
    _assert_development_only(predictions)

    # Always filter one more time to be safe
    dev = predictions.filter(pl.col("season") <= DEVELOPMENT_SEASON_MAX)
    max_season = int(dev["season"].max()) if dev.height else -1
    if max_season > DEVELOPMENT_SEASON_MAX:
        raise SealedHoldoutAccessError(
            max_season, "build_development_scorecard", "season > 2024 detected"
        )

    total_predicted = int(dev.height)
    # Spec terminology:
    #   predicted_games: every prediction row in the development window.
    #   target_unavailable_games: prediction rows whose target was not
    #     available at the as_of_utc boundary (no outcome).
    #   binary_scored_games: prediction rows with a non-tie, available
    #     target (the denominator for descriptive accuracy, Brier, log
    #     loss, and calibration).
    #   ties_excluded_from_binary_metrics: prediction rows whose target
    #     was a tie (margin == 0). Ties are predictions with available
    #     outcomes, but they are excluded from the binary home-win
    #     metrics by design.
    #   warmup_excluded_games: prediction rows excluded as warm-up.
    #     For this Elo baseline the warm-up policy is "all predictions
    #     scored; no warmup required" so this count is 0.
    target_unavailable = dev.filter(pl.col("target_available") == False)  # noqa: E712
    ties_df = dev.filter(pl.col("actual_tie") == True)  # noqa: E712
    binary_scored = dev.filter(
        (pl.col("target_available") == True)  # noqa: E712
        & (pl.col("actual_tie") == False)  # noqa: E712
    )
    warmup_excluded = 0

    brier = brier_score(binary_scored)
    ll = log_loss(binary_scored)
    accuracy = descriptive_accuracy(binary_scored)
    cal_result = logistic_recalibration(binary_scored)
    cal_intercept = cal_result["calibration_intercept"]
    cal_slope = cal_result["calibration_slope"]
    reliability = reliability_table(binary_scored)

    scorecard = {
        "model_name": "qb_elo",
        "model_version": "v1.0.0",
        "run_id": manifest.get("run_id"),
        "configuration": configuration,
        "sealed_holdout_season": 2025,
        "development_seasons": "2018-2024",
        "totals": {
            "predicted_games": total_predicted,
            "target_unavailable_games": int(target_unavailable.height),
            "binary_scored_games": int(binary_scored.height),
            "ties_excluded_from_binary_metrics": int(ties_df.height),
            "warmup_excluded_games": int(warmup_excluded),
        },
        "aggregate_metrics": {
            "brier_score": brier,
            "log_loss": ll,
            "descriptive_accuracy": accuracy,
            "calibration_intercept": cal_intercept,
            "calibration_slope": cal_slope,
            "calibration_fit_status": cal_result["calibration_fit_status"],
            "calibration_iterations": cal_result["calibration_iterations"],
            "calibration_converged": cal_result["calibration_converged"],
        },
        "by_season": _season_counts(dev),
        "by_week": _weekly_counts(dev),
        "by_qb_certainty": _qb_certainty_counts(dev),
        "reliability_table": reliability,
        "worst_log_loss_predictions": _worst_predictions(dev),
        "missingness": _missingness(dev),
        "warm_up_policy": (
            "all development predictions scored; no warmup exclusion. "
            "warmup_excluded_games = 0"
        ),
        "scored_row_policy": (
            "scored = target_available AND actual_home_win is not null. "
            "Ties are predicted outcomes with available targets but are "
            "excluded from binary home-win metrics by design."
        ),
        "manifest_fingerprint": {
            "model_config_sha256": manifest.get("model_config_sha256"),
            "backtest_config_sha256": manifest.get("backtest_config_sha256"),
            "model_code_fingerprint": manifest.get("model_code_fingerprint"),
            "feature_code_fingerprint": manifest.get("feature_code_fingerprint"),
            "backtest_code_fingerprint": manifest.get("backtest_code_fingerprint"),
        },
    }

    # Markdown
    cal_int = cal_result["calibration_intercept"]
    cal_sl = cal_result["calibration_slope"]
    md_lines = [
        "# QB-Elo Development Scorecard",
        "",
        f"- **Model:** {scorecard['model_name']} {scorecard['model_version']}",
        f"- **Run ID:** {scorecard['run_id']}",
        f"- **Development seasons:** {scorecard['development_seasons']}",
        f"- **Sealed holdout season:** {scorecard['sealed_holdout_season']} (not scored)",
        "",
        "## Totals",
        "",
        f"- Predicted games: {scorecard['totals']['predicted_games']}",
        f"- Binary-scored games: {scorecard['totals']['binary_scored_games']}",
        f"- Ties (excluded from binary metrics): {scorecard['totals']['ties_excluded_from_binary_metrics']}",
        f"- Target-unavailable games: {scorecard['totals']['target_unavailable_games']}",
        f"- Warm-up excluded games: {scorecard['totals']['warmup_excluded_games']}",
        "",
        "## Aggregate Metrics",
        "",
        f"- Brier score: {brier:.4f}",
        f"- Log loss: {ll:.4f}",
        f"- Descriptive accuracy: {accuracy:.4f}",
        f"- Calibration intercept: {cal_int if cal_int is not None else 'NA'}",
        f"- Calibration slope: {cal_sl if cal_sl is not None else 'NA'}",
        f"- Calibration fit status: {cal_result['calibration_fit_status']}",
        f"- Calibration iterations: {cal_result['calibration_iterations']}",
        f"- Calibration converged: {cal_result['calibration_converged']}",
        f"- Calibration max_iter: {cal_result['max_iter']}",
        "",
        "## Results by Season",
        "",
        "| Season | Predicted | Binary-Scored | Ties | Accuracy | Log loss | Brier |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in scorecard["by_season"]:
        md_lines.append(
            f"| {r['season']} | {r['predicted']} | {r['scored']} | {r['ties']} | "
            f"{_fmt(r['accuracy'])} | "
            f"{_fmt(r['log_loss'])} | "
            f"{_fmt(r['brier'])} |"
        )
    md_lines += [
        "",
        "## Results by QB Certainty",
        "",
        "| Certainty | Predicted | Scored | Accuracy | Log loss | Brier |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in scorecard["by_qb_certainty"]:
        md_lines.append(
            f"| {r['qb_certainty_state']} | {r['predicted']} | {r['scored']} | "
            f"{_fmt(r['accuracy'])} | "
            f"{_fmt(r['log_loss'])} | "
            f"{_fmt(r['brier'])} |"
        )
    md_lines += [
        "",
        "## Reliability Table",
        "",
        "| Bucket | Count | Mean Predicted | Actual Home-Win Rate |",
        "| --- | --- | --- | --- |",
    ]
    for r in reliability:
        mean_p = (
            f"{r['mean_predicted_probability']:.4f}"
            if r["mean_predicted_probability"] is not None
            else "n/a"
        )
        rate = (
            f"{r['actual_home_win_rate']:.4f}"
            if r["actual_home_win_rate"] is not None
            else "n/a"
        )
        md_lines.append(
            f"| {r['bucket_low']:.2f}–{r['bucket_high']:.2f} | {r['count']} | "
            f"{mean_p} | {rate} |"
        )
    md_lines += [
        "",
        "## Missingness",
        "",
    ]
    for c, n in scorecard["missingness"].items():
        md_lines.append(f"- {c}: {n} nulls")
    md_lines += [
        "",
        "## Worst Log-Loss Predictions",
        "",
        "| Game | Season | Week | Home | Away | Pred P(home) | Home Win | Log Loss |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in scorecard["worst_log_loss_predictions"]:
        md_lines.append(
            f"| {r['game_id']} | {r['season']} | {r['week']} | "
            f"{r['home_team']} | {r['away_team']} | "
            f"{r['predicted_home_win_probability']:.4f} | {r['actual_home_win']} | "
            f"{r['log_loss']:.4f} |"
        )
    md_lines += [
        "",
        "## Configuration",
        "",
        "```json",
        json.dumps(configuration, indent=2, sort_keys=True),
        "```",
        "",
        "## Manifest Fingerprint",
        "",
        f"- model_config_sha256: `{scorecard['manifest_fingerprint']['model_config_sha256']}`",
        f"- backtest_config_sha256: `{scorecard['manifest_fingerprint']['backtest_config_sha256']}`",
        f"- model_code_fingerprint: `{scorecard['manifest_fingerprint']['model_code_fingerprint']}`",
        f"- feature_code_fingerprint: `{scorecard['manifest_fingerprint']['feature_code_fingerprint']}`",
        f"- backtest_code_fingerprint: `{scorecard['manifest_fingerprint']['backtest_code_fingerprint']}`",
        "",
        "_No 2025 predictions, scores, or calibration included._",
        "",
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "qb_elo_development_scorecard.json"
    md_path = output_dir / "qb_elo_development_scorecard.md"
    csv_path = output_dir / "qb_elo_reliability_table.csv"

    json_path.write_text(json.dumps(scorecard, indent=2, sort_keys=True) + "\n")
    md_path.write_text("\n".join(md_lines))

    # CSV reliability table — empty buckets write `null` for the
    # averaging columns.
    csv_lines = ["bucket_low,bucket_high,count,mean_predicted_probability,actual_home_win_rate"]
    for r in reliability:
        mean_p = (
            f"{r['mean_predicted_probability']:.6f}"
            if r["mean_predicted_probability"] is not None
            else "null"
        )
        rate = (
            f"{r['actual_home_win_rate']:.6f}"
            if r["actual_home_win_rate"] is not None
            else "null"
        )
        csv_lines.append(
            f"{r['bucket_low']:.4f},{r['bucket_high']:.4f},{r['count']},{mean_p},{rate}"
        )
    csv_path.write_text("\n".join(csv_lines) + "\n")

    return scorecard
