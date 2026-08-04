"""End-to-end PR #4 artifact regenerator.

Runs the full Task 03A pipeline (walk-forward + scorecard) into a
target directory using the canonical YAML configuration and a
fixed logical creation time. Used to prove byte-identical
determinism across two runs.

Usage:
    python scripts/regenerate_pr4_artifacts.py <output_dir>
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from nfl_edge.backtest.walk_forward import run_development_walk_forward
from nfl_edge.evaluation.scorecard import build_development_scorecard
from nfl_edge.models.qb_elo_config import (
    canonical_config_sha256,
    load_qb_elo_canonical_config,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
YAML_PATH = REPO_ROOT / "config/qb_elo_v1.yaml"
FIXED_CREATED_AT = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)


def _hash_bytes(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regenerate(out_dir: Path) -> dict[str, str]:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    run_development_walk_forward(
        games_path=REPO_ROOT / "data/derived/features_v1/game_features_2018_2025.parquet",
        team_features_path=REPO_ROOT / "data/derived/features_v1/team_pregame_features_2018_2025.parquet",
        output_dir=out_dir,
        created_at=FIXED_CREATED_AT,
        project_root=REPO_ROOT,
    )
    pred_path = out_dir / "qb_elo_predictions_2018_2024.parquet"
    state_path = out_dir / "qb_elo_state_transitions_2018_2024.parquet"
    pred = pl.read_parquet(pred_path)
    manifest = json.loads((out_dir / "qb_elo_run_manifest_v1.json").read_text())
    cfg = load_qb_elo_canonical_config(YAML_PATH)
    build_development_scorecard(
        pred, configuration=cfg, manifest=manifest, output_dir=out_dir
    )
    return {
        "predictions": _hash_bytes(pred_path),
        "state": _hash_bytes(state_path),
        "manifest": _hash_bytes(out_dir / "qb_elo_run_manifest_v1.json"),
        "tuning_ledger": _hash_bytes(out_dir / "qb_elo_tuning_ledger_v1.json"),
        "scorecard_json": _hash_bytes(out_dir / "qb_elo_development_scorecard.json"),
        "scorecard_md": _hash_bytes(out_dir / "qb_elo_development_scorecard.md"),
        "reliability_csv": _hash_bytes(out_dir / "qb_elo_reliability_table.csv"),
        "model_config_sha256": canonical_config_sha256(cfg),
    }


def main() -> int:
    out_dir = Path(sys.argv[1]).resolve()
    hashes = regenerate(out_dir)
    for k, v in hashes.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
