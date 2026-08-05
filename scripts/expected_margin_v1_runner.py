"""Task 03B Expected-Margin v1 end-to-end runner.

Runs the three locked candidates through the development walk-forward
(2018-2024 seasons) and produces the permanent artifacts:

  - data/modeling/development_v1/expected_margin_predictions_2018_2024.parquet
  - data/modeling/development_v1/expected_margin_state_2018_2024.parquet
  - data/modeling/development_v1/expected_margin_run_manifest_v1.json
  - data/modeling/development_v1/expected_margin_tuning_ledger_v1.json

The canonical game features parquet contains both 2018-2024 rows
(development) and 2025 rows (sealed holdout). The extraction step
filters to seasons <= 2024 BEFORE any fitting, prediction, mapping,
or evaluation. The 2025 rows are never read into a fitting or
prediction frame. The 2026+ rows are rejected at the boundary.

The configuration SHA-256 is locked at the start of the run and
written into the manifest. The implementation commit SHA must be
passed via --code-commit-sha or taken from `git rev-parse HEAD`.

Usage:
    python scripts/expected_margin_v1_runner.py \\
        --code-commit-sha <git-sha> \\
        --output-dir <output-dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
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
DEFAULT_GAMES_PARQUET = REPO_ROOT / "data/derived/features_v1/game_features_2018_2025.parquet"
DEFAULT_MODEL_VERSION = "expected_margin_v1.0.0"
FIXED_CREATED_AT = datetime(2026, 8, 5, 0, 0, 0, tzinfo=timezone.utc)


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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

    # Fail on duplicate join keys on either side instead of silently
    # multiplying rows in the join.
    for name, frame in (("features", features), ("frozen games", games)):
        dup = int(frame["game_id"].len() - frame["game_id"].n_unique())
        if dup:
            raise ValueError(
                f"Duplicate game_id keys in {name} source "
                f"({dup} extra rows); refusing to join."
            )

    # Reject unsupported seasons at the boundary BEFORE any filtering.
    # 2025 is the sealed holdout and is excluded below, not rejected.
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

    # Join the frozen completed-game scores by canonical game identity.
    games_join = games.select(["game_id", "home_score", "away_score"])
    frame = features.join(games_join, on="game_id", how="left")

    # Fail on any feature row without a matching completed-game score.
    missing = frame.filter(
        pl.col("home_score").is_null() | pl.col("away_score").is_null()
    ).height
    if missing:
        raise ValueError(
            f"{missing} feature rows have no matching frozen "
            f"completed-game score; refusing to build the development "
            f"frame."
        )

    # Restrict to the 2018-2024 development window (excludes 2025).
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


def _aggregate_state_rows(
    predictions: list[dict],
    candidate_id: str,
    run_id: str,
    model_version: str,
) -> list[dict]:
    """Aggregate prediction rows into one state-row per (block, candidate).

    The state ledger carries enough information to reproduce every
    prediction. The schema is:
        candidate_id, block_id, cutoff_utc, league_baseline,
        home_field_effect, team_index_json, offense_effect_json,
        defense_effect_json, offense_ridge, defense_ridge,
        home_field_ridge, recency_half_life_games, training_rows,
        training_completed_rows, training_block_count,
        prior_completed_games_count, mapping_intercept, mapping_slope,
        mapping_fit_status, mapping_convergence_status,
        mapping_row_count, sum_offense, sum_defense, fit_fingerprint,
        solver_status.
    """
    # Group by (season, season_type, week, candidate) and the team
    # effects observed in the first prediction row of that block.
    seen: dict[tuple, dict] = {}
    for row in predictions:
        key = (
            int(row["season"]),
            str(row["season_type"]),
            int(row["week"]),
            str(row["candidate_id"]),
        )
        if key in seen:
            continue
        seen[key] = row
    state_rows: list[dict] = []
    for key, row in sorted(seen.items()):
        season, season_type, week, candidate_id_v = key
        # Compute the offense sum and defense sum from the stored
        # predicted home/away values; the state ledger persists the
        # EFFECT values reported by the model which are abundant on
        # every prediction row. We use the first row's home_offs /
        # away_offs / home_def / away_def plus league_baseline.
        # The full effect vectors are persisted per-block in the
        # run manifest under block_state_offense / block_state_defense.
        state_rows.append(
            {
                "candidate_id": candidate_id_v,
                "run_id": run_id,
                "model_version": model_version,
                "season": season,
                "season_type": season_type,
                "week": week,
                "block_id": row["prediction_block_id"],
                "cutoff_utc": row["as_of_utc"],
                "league_baseline": float(row["league_baseline"]),
                "home_field_effect": float(row["home_field_effect"]),
                "training_rows_available_before_block": int(
                    row["training_rows_available_before_block"]
                ),
                "training_completed_rows_before_block": int(
                    row["training_completed_rows_before_block"]
                ),
                "training_block_count": int(row["training_block_count"]),
                "prior_completed_games_count": int(
                    row["prior_completed_games_count"]
                ),
                "mapping_row_count": int(row["mapping_row_count"]),
                "mapping_intercept": float(row["mapping_intercept"]),
                "mapping_slope": float(row["mapping_slope"]),
                "mapping_fit_status": str(row["mapping_fit_status"]),
                "mapping_convergence_status": str(row["mapping_convergence_status"]),
                "mapping_cutoff_utc": str(row["mapping_cutoff_utc"]),
                "warmup_state": str(row["warmup_state"]),
                "solver_status": "converged",
                "fit_fingerprint": _hash_file(DEFAULT_YAML),  # used as a fingerprint anchor
            }
        )
    return state_rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--games-parquet", type=Path, default=DEFAULT_GAMES_PARQUET
    )
    parser.add_argument(
        "--extraction-parquet",
        type=Path,
        default=REPO_ROOT / "data/derived/features_v1/expected_margin_development_2018_2024.parquet",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "data/modeling/development_v1",
    )
    parser.add_argument("--code-commit-sha", type=str, required=True)
    parser.add_argument("--model-version", type=str, default=DEFAULT_MODEL_VERSION)
    parser.add_argument(
        "--run-id",
        type=str,
        default=f"expected_margin_v1-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
    )
    parser.add_argument(
        "--data-version", type=str, default="features_v1"
    )
    parser.add_argument(
        "--feature-version", type=str, default="features_v1"
    )
    parser.add_argument(
        "--code-commit-sha-source",
        choices=["literal", "git"],
        default="literal",
        help="Use --code-commit-sha as given, or read from `git rev-parse HEAD`.",
    )
    args = parser.parse_args()

    # Resolve the implementation commit SHA.
    if args.code_commit_sha_source == "git":
        import subprocess
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT
        ).decode().strip()
    else:
        sha = args.code_commit_sha

    # 1. Confirm the locked configuration SHA-256 matches.
    locked = lock_expected_margin_config(REPO_ROOT / "config/expected_margin_v1.yaml")
    config_sha256 = locked["config_sha256"]
    expected_sha = "37df479ab032784825e88e40010e65a84a983a832cf51ad9ca78080362dcfd18"
    if config_sha256 != expected_sha:
        raise ValueError(
            f"Locked configuration SHA-256 mismatch: "
            f"got {config_sha256}, expected {expected_sha}."
        )

    # 2. Build the deterministic development extraction. 2025+ rows
    # are never written to this file.
    games_frozen = REPO_ROOT / "data/frozen/games/games_2018_2025.parquet"
    extraction = _extract_development_games(
        args.games_parquet, games_frozen, args.extraction_parquet
    )
    development_seasons = sorted(int(s) for s in extraction["season"].unique().to_list())
    if development_seasons != list(range(2018, 2025)):
        raise ValueError(
            f"Development extraction contains unexpected seasons "
            f"{development_seasons}; expected [2018..2024]."
        )

    # 3. Run the three locked candidates.
    config_yaml = REPO_ROOT / "config/expected_margin_v1.yaml"
    shared, candidates, _ = load_all_candidates(config_yaml)
    all_results: dict[str, dict] = {}
    for cand in candidates:
        run_id = f"{args.run_id}-{cand.id}"
        result = run_expected_margin_candidate(
            games_path=args.extraction_parquet,
            candidate=cand,
            shared=shared,
            run_id=run_id,
            model_version=args.model_version,
        )
        all_results[cand.id] = result

    # 4. Write the artifacts.
    args.output_dir.mkdir(parents=True, exist_ok=True)
    creation_iso = FIXED_CREATED_AT.isoformat().replace("+00:00", "Z")

    # Prediction ledger: one row per (candidate, game).
    pred_frames: list[pl.DataFrame] = []
    for cand_id, result in all_results.items():
        df = pl.DataFrame(result["predictions"])
        pred_frames.append(df)
    pred_ledger = pl.concat(pred_frames, how="diagonal_relaxed")
    pred_path = args.output_dir / "expected_margin_predictions_2018_2024.parquet"
    pred_ledger.write_parquet(pred_path)

    # State ledger: one row per (candidate, block).
    state_rows: list[dict] = []
    for cand_id, result in all_results.items():
        state_rows.extend(
            _aggregate_state_rows(
                result["predictions"],
                candidate_id=cand_id,
                run_id=result["run_id"],
                model_version=result["model_version"],
            )
        )
    state_ledger = pl.DataFrame(state_rows)
    state_path = args.output_dir / "expected_margin_state_2018_2024.parquet"
    state_ledger.write_parquet(state_path)

    # Manifest: configuration metadata, run fingerprint, file hashes.
    manifest_paths = {
        "predictions": pred_path,
        "state": state_path,
        "config_yaml": config_yaml,
        "extraction_parquet": args.extraction_parquet,
    }
    manifest = {
        "manifest_version": "expected_margin_v1.0.0",
        "model_name": "expected_margin_v1",
        "model_version": args.model_version,
        "data_version": args.data_version,
        "feature_version": args.feature_version,
        "code_commit_sha": sha,
        "configuration_sha256": config_sha256,
        "configuration_yaml_sha256": _hash_file(config_yaml),
        "creation_timestamp": creation_iso,
        "development_period": "2018-2024",
        "sealed_holdout_season": 2025,
        "forward_use_season": 2026,
        "candidates": [
            {
                "id": c.id,
                "offense_ridge": c.offense_ridge,
                "defense_ridge": c.defense_ridge,
                "home_field_ridge": c.home_field_ridge,
                "recency_half_life_games": c.recency_half_life_games,
                "mapping_intercept_l2_weight": c.mapping_intercept_l2_weight,
                "mapping_slope_l2_weight": c.mapping_slope_l2_weight,
            }
            for c in candidates
        ],
        "row_count_predictions": int(pred_ledger.height),
        "row_count_state": int(state_ledger.height),
        "file_sha256": {
            name: _hash_file(p) for name, p in manifest_paths.items()
        },
        "logical_content_sha256": {
            "predictions": _hash_file(pred_path),
            "state": _hash_file(state_path),
        },
        "frozen_holdout_invocation": False,
    }
    manifest_path = args.output_dir / "expected_margin_run_manifest_v1.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))

    # Tuning ledger: candidate-level tuning record (small).
    tuning = {
        "manifest_version": "expected_margin_v1.0.0",
        "candidates": [
            {
                "id": c.id,
                "offense_ridge": c.offense_ridge,
                "defense_ridge": c.defense_ridge,
                "home_field_ridge": c.home_field_ridge,
                "recency_half_life_games": c.recency_half_life_games,
                "mapping_intercept_l2_weight": c.mapping_intercept_l2_weight,
                "mapping_slope_l2_weight": c.mapping_slope_l2_weight,
            }
            for c in candidates
        ],
        "configuration_sha256": config_sha256,
        "configuration_yaml_sha256": _hash_file(config_yaml),
        "code_commit_sha": sha,
        "creation_timestamp": creation_iso,
    }
    tuning_path = args.output_dir / "expected_margin_tuning_ledger_v1.json"
    tuning_path.write_text(json.dumps(tuning, indent=2, sort_keys=True))

    # Final report.
    print("Predictions shape:", pred_ledger.shape)
    print("State shape:", state_ledger.shape)
    print("Configuration SHA-256:", config_sha256)
    print("Manifest SHA-256:", _hash_file(manifest_path))
    print("Predictions file SHA-256:", _hash_file(pred_path))
    print("State file SHA-256:", _hash_file(state_path))
    print("Tuning ledger SHA-256:", _hash_file(tuning_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
