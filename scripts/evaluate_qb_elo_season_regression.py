"""Task 04D bounded season-regression evaluation runner.

Builds on the validated Task04C walk-forward engine with the frozen oracle-QB
resolver. Only ``season_mean_reversion_fraction`` differs across candidate
configurations.

Usage (from the Task04D worktree root, using the main checkout's venv):

    PYTHONPATH=src /root/nfl-edge/.venv/bin/python scripts/evaluate_qb_elo_season_regression.py \
        --project-root . \
        --identity

    PYTHONPATH=src /root/nfl-edge/.venv/bin/python scripts/evaluate_qb_elo_season_regression.py \
        --project-root . \
        --run-candidate regression_000 --out /tmp/qb_elo_sr_reg000

Chunk 2 scope: only the ``--identity`` gate (and, if needed, a disposable
candidate run) is exercised. The full five-run official experiment belongs to
Chunk 3. No candidate selection is made here.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from nfl_edge.backtest.task04c_paired_evaluation import OracleQBAdjustments
from nfl_edge.backtest.task04d_season_regression_evaluation import (
    CANDIDATE_FRACTIONS,
    CANDIDATE_LABELS,
    REGRESSION_CENTER,
    TASK04C_REFERENCE_FRACTION,
    build_candidate_config,
    build_season_boundary_audit,
    load_canonical_config,
    metrics_for,
    week1_4_metrics_for,
)
from nfl_edge.backtest.walk_forward import run_development_walk_forward


def relative(root: str | Path, *parts: str) -> Path:
    return Path(root).joinpath(*parts)


def run_candidate_fraction(
    *,
    project_root: str | Path,
    games_path: str | Path,
    team_path: str | Path,
    oracle_path: str | Path,
    fraction: float,
    output_dir: str | Path,
    candidate_label: str,
    created_at: datetime | None = None,
) -> dict:
    """Run one regression-fraction candidate through the engine and emit its
    prediction/state ledgers plus the season-boundary audit ledger."""
    root = Path(project_root)
    base_config = load_canonical_config(root)
    cfg = build_candidate_config(base_config, fraction)
    oracle = OracleQBAdjustments(oracle_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    run_development_walk_forward(
        games_path=Path(games_path),
        team_features_path=Path(team_path),
        output_dir=out,
        config=cfg,
        created_at=created_at,
        project_root=root,
        qb_adjustment_resolver=oracle,
    )
    predictions = pl.read_parquet(out / "qb_elo_predictions_2018_2024.parquet")
    state = pl.read_parquet(out / "qb_elo_state_transitions_2018_2024.parquet")
    audit = build_season_boundary_audit(
        predictions, state, fraction, candidate_label=candidate_label
    )
    audit.write_parquet(out / f"season_boundary_audit_{candidate_label}.parquet")
    meta = {
        "candidate_label": candidate_label,
        "season_mean_reversion_fraction": float(fraction),
        "canonical_center": REGRESSION_CENTER,
        "prediction_rows": int(predictions.height),
        "state_rows": int(state.height),
        "audit_rows": int(audit.height),
        "metrics": metrics_for(predictions),
        "week1_4_metrics": week1_4_metrics_for(predictions),
    }
    (out / f"summary_{candidate_label}.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n"
    )
    return meta


def verify_task04c_identity(
    *,
    project_root: str | Path,
    games_path: str | Path,
    team_path: str | Path,
    oracle_path: str | Path,
    baseline_oracle_predictions: str | Path,
    tol: float = 1e-6,
) -> dict:
    """Run the 33.3% Task04C reference and compare predictor-by-predictor to
    the existing Task04C oracle output. Strongest gate: ordered game IDs and
    per-game predicted probabilities must match."""
    with tempfile.TemporaryDirectory(prefix="task04d_identity_") as td:
        run_candidate_fraction(
            project_root=project_root,
            games_path=games_path,
            team_path=team_path,
            oracle_path=oracle_path,
            fraction=TASK04C_REFERENCE_FRACTION,
            output_dir=td,
            candidate_label="task04c_reference_0333",
            created_at=datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
        )
        mine = pl.read_parquet(Path(td) / "qb_elo_predictions_2018_2024.parquet")
    theirs = pl.read_parquet(baseline_oracle_predictions)

    mine_sorted = mine.sort("game_id")
    theirs_sorted = theirs.sort("game_id")
    assert mine_sorted.height == theirs_sorted.height == 1942, (
        mine_sorted.height, theirs_sorted.height
    )
    assert mine_sorted["game_id"].to_list() == theirs_sorted["game_id"].to_list()

    compare_cols = [
        "home_elo_before",
        "away_elo_before",
        "home_qb_adjustment",
        "away_qb_adjustment",
        "predicted_home_win_probability",
    ]
    max_diff = 0.0
    worst_col = None
    for col in compare_cols:
        a = mine_sorted[col].to_list()
        b = theirs_sorted[col].to_list()
        d = max(abs(x - y) for x, y in zip(a, b))
        if d > max_diff:
            max_diff = d
            worst_col = col

    my_metrics = metrics_for(mine)
    accepted = {
        "brier": 0.221918210006,
        "log_loss": 0.635506991355,
        "accuracy": 0.647785787848,
    }
    metric_ok = all(
        math.isclose(my_metrics[k], v, rel_tol=tol * 10, abs_tol=tol * 10)
        for k, v in accepted.items()
    )
    order_ok = mine_sorted["game_id"].to_list() == theirs_sorted["game_id"].to_list()
    pred_diff = max(
        abs(x - y)
        for x, y in zip(
            mine_sorted["predicted_home_win_probability"].to_list(),
            theirs_sorted["predicted_home_win_probability"].to_list(),
        )
    )
    preds_ok = pred_diff <= tol
    passed = order_ok and preds_ok and max_diff <= tol and metric_ok
    result = {
        "identity_passed": bool(passed),
        "game_id_order_identical": bool(order_ok),
        "predicted_probability_identical": bool(preds_ok),
        "max_diff_any_compare_col": float(max_diff),
        "worst_col": worst_col,
        "compare_columns": compare_cols,
        "my_metrics": my_metrics,
        "accepted_metrics": accepted,
        "metric_match": bool(metric_ok),
        "tol": tol,
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--run-candidate", choices=list(CANDIDATE_LABELS))
    parser.add_argument("--out")
    parser.add_argument("--identity", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.project_root).resolve()
    games = relative(root, "data/derived/features_v1/game_features_2018_2025.parquet")
    team = relative(root, "data/derived/features_v1/team_pregame_features_2018_2025.parquet")
    oracle = relative(
        root,
        "data/derived/oracle_qb_entering_state_v2"
        "/oracle_qb_pregame_adjustments_by_game_2018_2024_v2.parquet",
    )
    baseline_preds = relative(
        root,
        "data/derived/qb_elo_oracle_comparison_v1"
        "/qb_elo_oracle_predictions_2018_2024.parquet",
    )

    if args.run_candidate:
        if not args.out:
            parser.error("--run-candidate requires --out")
        meta = run_candidate_fraction(
            project_root=root,
            games_path=games,
            team_path=team,
            oracle_path=oracle,
            fraction=CANDIDATE_FRACTIONS[args.run_candidate],
            output_dir=args.out,
            candidate_label=args.run_candidate,
        )
        print(json.dumps(meta, indent=2, sort_keys=True))
        return 0

    if args.identity:
        result = verify_task04c_identity(
            project_root=root,
            games_path=games,
            team_path=team,
            oracle_path=oracle,
            baseline_oracle_predictions=baseline_preds,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["identity_passed"] else 1

    parser.error("nothing to do: pass --run-candidate or --identity")
    return 2


if __name__ == "__main__":
    sys.exit(main())
