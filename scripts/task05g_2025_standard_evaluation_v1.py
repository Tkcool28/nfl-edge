#!/usr/bin/env python3
"""Standard frozen 2025 NFL EDGE evaluation entry point.

2025 is treated as an additional evaluation season.  This wrapper changes no
football-model, evaluator, selector, staking, Play Through, candidate, or
product-policy semantics.  It reuses the already-built chronological 2025
orchestration and removes only the legacy one-shot authorization/marker layer.

The default mode is preflight-only.  A real evaluation occurs only when
``--execute`` is supplied explicitly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import polars as pl

from nfl_edge.features.totals_v1.manifest import verify_pbp_artifacts
from nfl_edge.holdout import executor_runtime_2025 as runtime

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PBP_ROOT = ROOT / "data/frozen/task05c_pbp_v1"
DEFAULT_MARKET_ROOT = ROOT / "artifacts/task05g_2025_market_input"
DEFAULT_BOARD = ROOT / "artifacts/task05g_2025_standard/upstream/historical_evaluator_board.parquet"
DEFAULT_OUTPUT_BASE = ROOT / "artifacts/task05g_2025_standard/runs"
CERTIFICATION = ROOT / "data/manifests/2025_all_model_input_certification_v1.json"
PBP_2025 = ROOT / "data/frozen/task05c_pbp_2025_v1/play_by_play_2025.parquet"
OBSERVATIONS_2025 = ROOT / "data/derived/task05c_game_observations_2025_v1/game_observations_2025_v1.jsonl"

EXPECTED_2025_PBP_SHA256 = "c6ecedd6d678cc37ed316b23ef84ee1ec6abb69c514bb11868a7ebd5a367df29"
EXPECTED_OBSERVATIONS_SHA256 = "5a78b506a1d2dc14f4948cd316346d09d863e603c61144716a242252df8f84e3"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class StandardEvaluationError(RuntimeError):
    """Raised when the standard 2025 evaluation contract is not satisfied."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise StandardEvaluationError(f"missing {label}: {path}")
    observed = _sha256(path)
    if observed != expected:
        raise StandardEvaluationError(
            f"{label} SHA-256 drift: observed={observed} expected={expected}"
        )


def _validate_run_id(run_id: str) -> str:
    value = str(run_id)
    if not RUN_ID_RE.fullmatch(value) or value in {".", ".."}:
        raise StandardEvaluationError(f"invalid run id: {value!r}")
    return value


def _certification_summary() -> dict[str, Any]:
    if not CERTIFICATION.is_file():
        raise StandardEvaluationError(f"missing 2025 input certification: {CERTIFICATION}")
    cert = json.loads(CERTIFICATION.read_text(encoding="utf-8"))
    matrix = list(cert.get("certification_matrix") or [])
    if not matrix:
        raise StandardEvaluationError("2025 input certification matrix is empty")
    missing: list[str] = []
    bad_schema: list[str] = []
    bad_compatibility: list[str] = []
    for row in matrix:
        component = str(row.get("component") or "UNKNOWN")
        if row.get("missing_dependencies"):
            missing.append(component)
        if not str(row.get("schema_status") or "").startswith("PASS"):
            bad_schema.append(component)
        if str(row.get("frozen_contract_compatibility") or "") != "PASS":
            bad_compatibility.append(component)
    if missing or bad_schema or bad_compatibility:
        raise StandardEvaluationError(
            "2025 input certification is not fully runnable: "
            f"missing={missing} schema={bad_schema} compatibility={bad_compatibility}"
        )
    return {
        "matrix_components": len(matrix),
        "missing_dependencies": 0,
        "schema_pass": True,
        "frozen_contract_compatibility_pass": True,
    }


def preflight(*, pbp_root: Path, market_root: Path, historical_board: Path) -> dict[str, Any]:
    """Verify every execution dependency without predicting or revealing 2025."""
    verified = verify_pbp_artifacts(pbp_root)
    _require_sha(PBP_2025, EXPECTED_2025_PBP_SHA256, "tracked 2025 PBP")
    _require_sha(OBSERVATIONS_2025, EXPECTED_OBSERVATIONS_SHA256, "2025 GameObservation ledger")

    games = pl.read_parquet(runtime.GAMES)
    season_2025 = games.filter(pl.col("season") == 2025)
    if season_2025.height != runtime.EXPECTED_GAMES:
        raise StandardEvaluationError(
            f"2025 canonical game count={season_2025.height} expected={runtime.EXPECTED_GAMES}"
        )
    if season_2025["game_id"].n_unique() != runtime.EXPECTED_GAMES:
        raise StandardEvaluationError("2025 canonical game IDs are not unique")

    market_path, market_games_path = runtime._market_pair(market_root)
    if not historical_board.is_file():
        raise StandardEvaluationError(f"missing materialized frozen Task05F board: {historical_board}")

    # This is intentionally the same frozen development bootstrap used by the
    # existing 2025 runtime.  No 2025 prediction or outcome is opened here.
    development_state = runtime.prepare_development_state(
        historical_board_path=historical_board
    )

    return {
        "status": "STANDARD_2025_PREFLIGHT_PASS",
        "season": 2025,
        "games": runtime.EXPECTED_GAMES,
        "historical_pbp_seasons": [artifact.season for artifact in verified],
        "historical_pbp_root": str(pbp_root),
        "tracked_2025_pbp_sha256": EXPECTED_2025_PBP_SHA256,
        "game_observations_sha256": EXPECTED_OBSERVATIONS_SHA256,
        "market_path": str(market_path),
        "market_games_path": str(market_games_path),
        "historical_board_sha256": runtime.HISTORICAL_BOARD_SHA256,
        "certification": _certification_summary(),
        "development_state": {
            "historical_product_games": len(development_state["product_games"]),
            "historical_board_rows": len(development_state["prior_board_rows"]),
            "xgb_development_rows": int(development_state["xgb_dev"].height),
            "expected_margin_history_rows": int(development_state["expected_history"].height),
            "totals_training_rows": int(development_state["totals_training"].height),
        },
        "methodology_changed": False,
        "models_changed": False,
        "evaluator_changed": False,
        "selectors_changed": False,
        "staking_changed": False,
        "product_policy_changed": False,
    }


def execute(
    *,
    run_id: str,
    pbp_root: Path,
    market_root: Path,
    historical_board: Path,
    output_base: Path,
) -> Path:
    """Run 2025 chronologically using the frozen components after preflight."""
    run_id = _validate_run_id(run_id)
    output_root = output_base / run_id
    if output_root.exists():
        raise StandardEvaluationError(f"run output already exists: {output_root}")

    # ``prepare_development_state`` resolves the promoted PBP family from its
    # existing canonical artifact roots.  The GitHub workflow stages the exact
    # tracked family at /artifacts/raw/task05c_pbp_v1 before invoking this file.
    summary = preflight(
        pbp_root=pbp_root,
        market_root=market_root,
        historical_board=historical_board,
    )
    development_state = runtime.prepare_development_state(
        historical_board_path=historical_board
    )
    output_root.parent.mkdir(parents=True, exist_ok=True)

    runtime.run_authorized_holdout(
        output_root=output_root,
        market_root=market_root,
        development_state=development_state,
        opened_marker_identity={
            "mode": "STANDARD_2025_EVALUATION",
            "run_id": run_id,
            "legacy_one_shot_authorization_used": False,
            "legacy_spend_marker_used": False,
        },
    )
    (output_root / "STANDARD_EVALUATION_PREFLIGHT.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="2025-standard-eval-v1")
    parser.add_argument("--pbp-root", type=Path, default=DEFAULT_PBP_ROOT)
    parser.add_argument("--market-root", type=Path, default=DEFAULT_MARKET_ROOT)
    parser.add_argument("--historical-board", type=Path, default=DEFAULT_BOARD)
    parser.add_argument("--output-base", type=Path, default=DEFAULT_OUTPUT_BASE)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually run 2025. Without this flag the command is preflight-only.",
    )
    args = parser.parse_args()

    if args.execute:
        output = execute(
            run_id=args.run_id,
            pbp_root=args.pbp_root,
            market_root=args.market_root,
            historical_board=args.historical_board,
            output_base=args.output_base,
        )
        print(f"STANDARD_2025_EVALUATION_COMPLETED={output}")
    else:
        summary = preflight(
            pbp_root=args.pbp_root,
            market_root=args.market_root,
            historical_board=args.historical_board,
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
