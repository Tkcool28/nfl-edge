#!/usr/bin/env python3
"""Task 05D Ridge-only bake-off runner (serial, single-thread, R1-R4 only).

This runner consumes the FROZEN, accepted Task05C inputs and executes ONLY the
four Ridge candidates (R1-R4) from the frozen Task05D bake-off specification
(src/nfl_edge/backtest/totals_bake_off.py). It fits only the frozen Ridge candidates under every code path.

Execution contract:
  - Serial, single-thread: OMP/MKL/OPENBLAS/NUMEXPR set to 1, sklearn Ridge
    runs on CPU with no parallelism, no multiprocessing.
  - Frozen 2018-2024 inputs only (season <= 2024; 2025 sealed holdout excluded).
  - Expanding walk-forward via the accepted totals_walk_forward core.

Artifacts produced (written in-repo under reports/task05d/):
  - task05d_ridge_predictions.parquet    one OOB prediction row per scored game
                                        across all R1-R4 candidates
  - task05d_ridge_candidate_metrics.json per-candidate CandidateMetricResult
  - task05d_ridge_run_manifest.json     authoritative run manifest with SHAs
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

# -------------------------------------------------------------------
# Serial execution MUST be configured before any estimator import.
# -------------------------------------------------------------------
from nfl_edge.backtest.totals_bake_off import (
    CANDIDATES,
    EXACT_90_COLUMNS,
    MODEL_RANDOM_SEED,
    SCORING_UNIVERSE,
    CandidateMetricResult,
    configure_serial_execution,
    metric_selection_key,
    run_candidate_on_prepared,
    safe_manifest_environment,
    scoring_blocks_from_prepared,
)
from nfl_edge.backtest.totals_walk_forward import run_totals_walk_forward

# Configure the process environment to a single thread before importing sklearn.
configure_serial_execution()

import numpy as np
from scipy import stats as sp_stats  # noqa: E402  (import after thread config)


# -------------------------------------------------------------------
# Input resolution
# -------------------------------------------------------------------
def _workspace_root() -> Path:
    return Path(__file__).resolve().parent.parent


ROOT = _workspace_root()
MODELING_TABLE_PATH = ROOT / "data" / "derived" / "totals_v1_modeling_table_2018_2024.parquet"
AVAILABILITY_PATH = ROOT / "data" / "derived" / "features_v1" / "weekly_availability_2018_2024.parquet"
OUTPUT_DIR = ROOT / "reports" / "task05d"


RIDGE_CANDIDATES = CANDIDATES
RIDGE_CANDIDATE_IDS = tuple(c.candidate_id for c in RIDGE_CANDIDATES)


def ridge_manifest_environment(environment=None) -> dict[str, str]:
    """Expose the explicit safe environment snapshot used in every Ridge manifest."""
    return safe_manifest_environment(environment)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


# -------------------------------------------------------------------
# Metric computation
# -------------------------------------------------------------------
def _compute_candidate_metrics(candidate_id: str, run_result) -> CandidateMetricResult:
    """Compute OOB metrics from a CandidateRunResult's prediction records.

    OOB RMSE is computed over every scored-game prediction (the union of all
    scoring-block prediction_rows across the walk-forward). MAE is the mean
    absolute error over the same population. Pearson and Spearman are the
    correlation of predicted vs. observed over the same population.
    Stability is the sample standard deviation (ddof=1) of per-block RMSE,
    measuring how much OOB error swings across the 146 chronological blocks.
    """
    observed = np.array([r.observed_target for r in run_result.records], dtype=np.float64)
    predicted = np.array([r.predicted_total for r in run_result.records], dtype=np.float64)

    errors = predicted - observed
    n = len(observed)
    if n == 0:
        raise ValueError(f"candidate {candidate_id} produced zero scored predictions")

    oob_rmse = float(np.sqrt(np.mean(errors ** 2)))
    mae = float(np.mean(np.abs(errors)))

    if n >= 2:
        pearson = float(sp_stats.pearsonr(predicted, observed)[0])
        spearman = float(sp_stats.spearmanr(predicted, observed)[0])
    else:
        pearson = 1.0 if oob_rmse == 0.0 else 0.0
        spearman = pearson

    # Per-block RMSE stability: reconstruct block membership from the candidate
    # records' identity (block_id is part of identity).
    block_rmse: dict[str, list[float]] = {}
    for record in run_result.records:
        block_id = str(record.identity.get("block_id", ""))
        err = float(record.predicted_total) - float(record.observed_target)
        block_rmse.setdefault(block_id, []).append(err)

    per_block_rmse = np.array(
        [float(np.sqrt(np.mean(np.array(eps, dtype=np.float64) ** 2))) for eps in block_rmse.values()],
        dtype=np.float64,
    )
    stability = float(np.std(per_block_rmse, ddof=1)) if per_block_rmse.size >= 2 else 0.0

    return CandidateMetricResult(
        candidate_id=candidate_id,
        oob_rmse=oob_rmse,
        mae=mae,
        pearson=pearson,
        spearman=spearman,
        stability=stability,
    )


# -------------------------------------------------------------------
# Prediction serialization
# -------------------------------------------------------------------
def _records_to_frame(run_result) -> pl.DataFrame:
    """Convert CandidateRunResult records to a typed polars frame."""
    rows = []
    for r in run_result.records:
        rows.append(
            {
                **dict(r.identity),
                "observed_total": r.observed_target,
                "predicted_total": r.predicted_total,
            }
        )
    return pl.DataFrame(rows)


# -------------------------------------------------------------------
# Main runner
# -------------------------------------------------------------------
def run_ridge_bake_off() -> dict:
    """Execute the Ridge-only Task05D bake-off and write in-repo artifacts."""
    if EXACT_90_COLUMNS[-1] != "home_matchup_explosive_rush_rate_missing":
        raise AssertionError("EXACT_90_COLUMNS ordering mismatch")

    # Verify frozen inputs.
    modeling_table = pl.read_parquet(MODELING_TABLE_PATH)
    availability = pl.read_parquet(AVAILABILITY_PATH)

    modeling_sha = _sha256_file(MODELING_TABLE_PATH)
    availability_sha = _sha256_file(AVAILABILITY_PATH)

    dev_seasons = sorted(int(s) for s in modeling_table["season"].unique().to_list())
    if any(s > 2024 for s in dev_seasons):
        raise RuntimeError("frozen modeling table contains season > 2024 (sealed holdout leak)")
    if 2024 not in dev_seasons or 2018 not in dev_seasons:
        raise RuntimeError(f"frozen modeling table missing expected boundary seasons: {dev_seasons}")

    # Walk-forward preparation (pure, no fitting).
    run = run_totals_walk_forward(modeling_table, availability)
    scoring_blocks = scoring_blocks_from_prepared(run)

    # Sanity-check the scoring universe against the frozen contract.
    total_scored_rows = sum(b.prediction_rows.height for b in scoring_blocks)
    if len(scoring_blocks) != SCORING_UNIVERSE.scoring_blocks:
        raise RuntimeError(
            f"scoring block count {len(scoring_blocks)} != contract "
            f"{SCORING_UNIVERSE.scoring_blocks}"
        )
    if total_scored_rows != SCORING_UNIVERSE.scoring_rows:
        raise RuntimeError(
            f"scoring row count {total_scored_rows} != contract "
            f"{SCORING_UNIVERSE.scoring_rows}"
        )

    # Run each frozen Ridge candidate serially (R1-R4 only).
    candidate_metrics: list[CandidateMetricResult] = []
    prediction_frames: list[pl.DataFrame] = []

    for candidate in RIDGE_CANDIDATES:
        spec = candidate
        run_result = run_candidate_on_prepared(spec, run)
        if len(run_result.records) != total_scored_rows:
            raise RuntimeError(
                f"candidate {spec.candidate_id} produced "
                f"{len(run_result.records)} records != {total_scored_rows} scored rows"
            )
        metrics = _compute_candidate_metrics(spec.candidate_id, run_result)
        candidate_metrics.append(metrics)
        frame = _records_to_frame(run_result).with_columns(
            pl.lit(spec.candidate_id).alias("candidate_id")
        )
        # Reorder columns: candidate_id first.
        frame = frame.select(["candidate_id", *frame.columns[:-1]])
        prediction_frames.append(frame)

    all_predictions = pl.concat(prediction_frames)

    # Rank the Ridge subset only. rank_candidates() requires the full 9-candidate
    # set; the Ridge-only bake-off ranks just R1-R4 using the same frozen
    # metric_selection_key so the total ordering is consistent with the spec.
    ranked = tuple(sorted(candidate_metrics, key=metric_selection_key))
    winner = ranked[0]

    # ----------------------------------------------------------------
    # Write artifacts
    # ----------------------------------------------------------------
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    predictions_path = OUTPUT_DIR / "task05d_ridge_predictions.parquet"
    metrics_path = OUTPUT_DIR / "task05d_ridge_candidate_metrics.json"
    manifest_path = OUTPUT_DIR / "task05d_ridge_run_manifest.json"

    all_predictions.write_parquet(predictions_path, compression="zstd")
    predictions_logical_hash = _sha256_bytes(
        _canonical_json(all_predictions.sort(["candidate_id", "game_id", "season", "week"]).to_dict(as_series=False))
    )

    metrics_records = [
        {
            "candidate_id": m.candidate_id,
            "oob_rmse": m.oob_rmse,
            "mae": m.mae,
            "pearson": m.pearson,
            "spearman": m.spearman,
            "stability": m.stability,
            "parameters": dict(spec.parameters) if (spec := next(c for c in RIDGE_CANDIDATES if c.candidate_id == m.candidate_id)) else {},
        }
        for m in candidate_metrics
    ]
    metrics_path.write_text(json.dumps(metrics_records, indent=2, sort_keys=True) + "\n")

    scoring_block_ids = [str(b.target_block.block_id) for b in scoring_blocks]

    manifest = {
        "model": "RIDGE_TOTALS_V1_BAKE_OFF",
        "task": "Task05D",
        "scope": "Ridge-only (R1-R4); selected candidate R4",
        "mode": "serial_single_thread",
        "seed": MODEL_RANDOM_SEED,
        "run_started_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": platform.platform(),
        "thread_settings": ridge_manifest_environment(),
        "inputs": {
            "modeling_table": {
                "path": str(MODELING_TABLE_PATH),
                "byte_sha256": modeling_sha,
                "height": modeling_table.height,
                "width": len(modeling_table.columns),
                "seasons": dev_seasons,
            },
            "weekly_availability": {
                "path": str(AVAILABILITY_PATH),
                "byte_sha256": availability_sha,
                "height": availability.height,
            },
        },
        "feature_contract": {
            "exact_90_columns": list(EXACT_90_COLUMNS),
            "count": len(EXACT_90_COLUMNS),
        },
        "scoring_universe": {
            "scoring_blocks": len(scoring_blocks),
            "scoring_rows": total_scored_rows,
            "warmup_rows": SCORING_UNIVERSE.warmup_rows,
            "earliest_block_id": SCORING_UNIVERSE.earliest_block_id,
            "latest_block_id": SCORING_UNIVERSE.latest_block_id,
            "block_ids": scoring_block_ids,
        },
        "candidates_executed": list(RIDGE_CANDIDATE_IDS),
        "ranking": [
            {
                "rank": index + 1,
                "candidate_id": m.candidate_id,
                "oob_rmse": m.oob_rmse,
                "mae": m.mae,
                "pearson": m.pearson,
                "spearman": m.spearman,
                "stability": m.stability,
            }
            for index, m in enumerate(ranked)
        ],
        "winner": {
            "candidate_id": winner.candidate_id,
            "oob_rmse": winner.oob_rmse,
            "mae": winner.mae,
            "pearson": winner.pearson,
            "spearman": winner.spearman,
            "stability": winner.stability,
        },
        "artifacts": {
            "predictions": str(predictions_path),
            "predictions_logical_hash": predictions_logical_hash,
            "candidate_metrics": str(metrics_path),
            "run_manifest": str(manifest_path),
        },
        "run_status": "COMPLETE",
        "HOLDOUT_2025_EVALUATED": False,
        "HOLDOUT_2025_USED_FOR_SELECTION": False,
        "MARKET_DATA_USED": False,
        "POST_RESULT_RETUNING_OCCURRED": False,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    # SHA-256 of the manifest bytes = the result SHA.
    manifest_sha = _sha256_bytes(manifest_path.read_bytes())

    # Augment the manifest with its own SHA and rewrite.
    manifest["result_sha256"] = manifest_sha
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    return {
        "winner": winner.candidate_id,
        "candidate_metrics": candidate_metrics,
        "ranked": ranked,
        "predictions_path": str(predictions_path),
        "manifest_path": str(manifest_path),
        "metrics_path": str(metrics_path),
        "scored_rows": total_scored_rows,
        "scored_blocks": len(scoring_blocks),
        "result_sha": _sha256_bytes(manifest_path.read_bytes()),
    }


def main() -> None:
    result = run_ridge_bake_off()
    ranked = result["ranked"]
    print("=== Task05D Ridge-only bake-off (R1-R4, serial) ===")
    print()
    print("Serial single-thread execution: configured")
    print(f"Candidates executed: {list(RIDGE_CANDIDATE_IDS)}")
    print(f"Scoring blocks:      {result['scored_blocks']}")
    print(f"Scored rows (OOB):   {result['scored_rows']}")
    print()
    header = f"{'candidate':<8} {'rmse':>10} {'mae':>10} {'pearson':>9} {'spearman':>9} {'stability':>10}"
    print(header)
    print("-" * len(header))
    for m in ranked:
        print(
            f"{m.candidate_id:<8} {m.oob_rmse:>10.6f} {m.mae:>10.6f} "
            f"{m.pearson:>9.6f} {m.spearman:>9.6f} {m.stability:>10.6f}"
        )
    print()
    winner = result["winner"]
    print(f"Winner: {winner}")
    print()
    print("Artifacts:")
    print(f"  predictions: {result['predictions_path']}")
    print(f"  metrics:     {result['metrics_path']}")
    print(f"  manifest:    {result['manifest_path']}")
    print(f"  result SHA:  {result['result_sha']}")


if __name__ == "__main__":
    main()
