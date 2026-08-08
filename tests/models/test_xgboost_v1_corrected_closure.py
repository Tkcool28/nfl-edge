"""Task 03C-5R/03C-6R corrected selection-closure checks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl

from nfl_edge.models.run_xgboost_v1 import (
    AUTHORIZED_V1_CANDIDATE,
    SELECTED_LOCK_SHA,
    XgboostV1CanonicalRunner,
)

ROOT = Path(__file__).resolve().parents[2]
CORRECTED = ROOT / "data" / "modeling" / "development_v1" / "chronology_corrected"


def _load(name: str) -> dict:
    return json.loads((CORRECTED / name).read_text())


def test_corrected_selection_and_lock_are_authoritative() -> None:
    selected = _load("xgboost_v1_chronology_corrected_selected_candidate.json")
    assert selected["selected_candidate"] == AUTHORIZED_V1_CANDIDATE == "conservative"
    assert selected["status"] == "XGBOOST_V1_CONSERVATIVE_SELECTED_AFTER_CHRONOLOGY_CORRECTION"
    assert selected["row_accounting"]["identity"] == "1655 + 284 + 3 = 1942"

    runner = XgboostV1CanonicalRunner(workspace_root=ROOT)
    checks = runner.verify_authority(require_scorecard=True)
    assert checks["selected_lock"] == SELECTED_LOCK_SHA
    assert checks["chronology_audit"] == "33e7b8fb026a4af7daa665ce42336519fd10ed22e0daeac7890861faa5f02d1a"
    assert "SELECTED_V1_LOCK_MANIFEST.json" not in str(runner.selected_lock_path)


def test_old_selected_lock_is_rejected_as_current_authority() -> None:
    runner = XgboostV1CanonicalRunner(workspace_root=ROOT)
    old_lock = ROOT / "data" / "modeling" / "development_v1" / "xgboost_selected_v1_lock"
    runner.selected_lock_path = old_lock / "SELECTED_V1_LOCK_MANIFEST.json"
    try:
        runner.verify_authority()
    except ValueError:
        return
    raise AssertionError("Old selected lock was accepted as current authority")


def test_corrected_scorecard_and_metrics() -> None:
    scorecard = _load("xgboost_v1_chronology_corrected_scorecard.json")
    assert scorecard["identity"] == {
        "binary_scored_rows": 1655,
        "fitted_blocks": 119,
        "identity": "1655 + 284 + 3 = 1942",
        "tie_or_nonbinary_rows": 3,
        "total_extraction_rows": 1942,
        "warmup_blocks": 32,
        "warmup_rows": 284,
    }
    assert scorecard["aggregate_metrics"] == {
        "accuracy": 0.607855,
        "brier_score": 0.232639,
        "logloss": 0.657508,
        "max_probability": 0.921787,
        "mean_probability": 0.556618,
        "min_probability": 0.121301,
        "roc_auc": 0.649541,
        "scored_rows": 1655,
        "std_probability": 0.130179,
        "warmup_rows": 0,
    }
    assert scorecard["expected_calibration_error"] == 0.026433
    assert "| 2024 | 250 |" in (CORRECTED / "xgboost_v1_chronology_corrected_scorecard.md").read_text()


def test_all_candidates_remain_preserved_for_future_research() -> None:
    future = _load("xgboost_future_stack_candidates_v1.json")
    assert future["STANDALONE_SELECTION_DOES_NOT_AUTHORIZE_ENSEMBLE_INPUT_SELECTION"]
    assert future["candidates"]["conservative"]["status"] == "SELECTED_XGBOOST_V1_STANDALONE"
    assert future["candidates"]["balanced"]["status"] == "FUTURE_BLEND_CANDIDATE_PRESERVED_NOT_SELECTED_STANDALONE"
    assert future["candidates"]["expressive"]["status"] == "FUTURE_BLEND_CANDIDATE_PRESERVED_NOT_SELECTED_STANDALONE"
    assert future["future_stack_experiment"]["FUTURE_BLEND_RESEARCH_NOT_IMPLEMENTED"]
    assert future["future_feature_overlap_research"]["FUTURE_FEATURE_OVERLAP_RESEARCH_NOT_IMPLEMENTED"]


def test_corrected_canonical_output_matches_corrected_conservative_evidence() -> None:
    out = CORRECTED / "canonical_runner"
    expected = pl.read_parquet(CORRECTED / "xgboost_candidate_predictions_2018_2024.parquet").filter(
        pl.col("candidate_id") == "conservative"
    )
    actual = pl.read_parquet(out / "xgboost_v1_predictions.parquet")
    assert actual.sort("game_id").equals(expected.sort("game_id"))
    manifest = _load("canonical_runner/xgboost_v1_run_manifest.json")
    assert manifest["verification_metrics"] == {
        "accuracy": 0.607855,
        "brier": 0.232639,
        "logloss": 0.657508,
        "roc_auc": 0.649541,
    }
    assert manifest["2025_ROWS_USED_BY_CANONICAL_MODEL_RUNNER"] is False
    assert manifest["MARKET_DATA_USED"] is False
    assert manifest["PRODUCTION_DEPLOYED"] is False
    lock_path = CORRECTED / "SELECTED_V1_CHRONOLOGY_CORRECTED_LOCK_MANIFEST.json"
    assert hashlib.sha256(lock_path.read_bytes()).hexdigest() == SELECTED_LOCK_SHA
