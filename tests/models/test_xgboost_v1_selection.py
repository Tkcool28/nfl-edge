"""Focused tests for Task 03C-5: XGBoost V1 selected-candidate freeze.

Verifies the selection artifact, scorecard, and lock reference the exact frozen
evidence: conservative is selected, parameter hashes are exact, flags are
correct, and calibration terminology labels match the actual computation.
These tests do NOT force future model performance.
"""
from __future__ import annotations

import json
from pathlib import Path

WORKSPACE = Path("/root/workspaces/nfl-edge-xgboost-v1")
DEV_DIR = WORKSPACE / "data" / "modeling" / "development_v1"

SELECTED_PARAM_HASH = "a044ba76fd138bde1a52e364fd7fce5de042a2ddfdb6cdac22e592d4819ed58b"
CANONICAL_CONFIG_SHA = "6aa585239ea20c7cd43da5837128101c83c5ce25645c8769e391a4dfc175a3be"


def _load(name: str):
    return json.loads((DEV_DIR / name).read_text())


def test_selected_candidate_is_conservative():
    sel = _load("xgboost_selected_candidate_v1.json")
    assert sel["status"] == "SELECTED_DEVELOPMENT_CANDIDATE"
    assert sel["selected_candidate"] == "conservative"


def test_selection_cannot_be_balanced_or_expressive():
    sel = _load("xgboost_selected_candidate_v1.json")
    assert sel["selected_candidate"] not in ("balanced", "expressive")


def test_selected_parameter_hash_exact():
    sel = _load("xgboost_selected_candidate_v1.json")
    assert sel["hashes"]["selected_parameter_hash"] == SELECTED_PARAM_HASH


def test_selection_artifact_has_no_2025_or_market():
    sel = _load("xgboost_selected_candidate_v1.json")
    assert sel["flags"]["2025_HOLDOUT_ACCESSED"] is False
    assert sel["flags"]["MARKET_DATA_USED"] is False
    assert sel["flags"]["POST_RESULT_RETUNING_OCCURRED"] is False


def test_selection_artifact_cannot_name_other_candidate_as_selected():
    sel = _load("xgboost_selected_candidate_v1.json")
    # The frozen metrics dict must still contain all three candidates for context,
    # but the selection must be conservative only.
    assert set(sel["frozen_candidate_metrics"].keys()) == {
        "conservative", "balanced", "expressive"
    }
    assert sel["selected_candidate"] == "conservative"


def test_scorecard_identity_exact():
    sc = _load("xgboost_v1_scorecard.json")
    assert sc["identity"]["model"] == "XGBoost V1"
    assert sc["identity"]["selected_candidate"] == "conservative"
    assert sc["identity"]["scored_rows"] == 1651
    assert sc["identity"]["binary_scored_rows"] == 1651
    assert sc["identity"]["warmup_rows"] == 288
    assert sc["identity"]["tie_or_nonbinary_rows"] == 3
    assert sc["identity"]["total_rows"] == 1942
    assert sc["identity"]["total_extraction_rows"] == 1942
    assert sc["identity"]["features"] == 132


def test_scorecard_common_row_count_exact():
    sc = _load("xgboost_v1_scorecard.json")
    assert sc["qb_elo_comparison"]["common_rows"] == 1651


def test_scorecard_qb_elo_comparison_exact():
    sc = _load("xgboost_v1_scorecard.json")
    q = sc["qb_elo_comparison"]["qb_elo_metrics"]
    assert q["brier_score"] == 0.222546
    assert q["logloss"] == 0.636666
    assert q["accuracy"] == 0.637795
    assert q["roc_auc"] == 0.689392


def test_scorecard_calibration_terminology_accurate():
    sc = _load("xgboost_v1_scorecard.json")
    cal = sc["calibration"]
    # Primary calibration evidence is ECE + reliability bins.
    assert "expected_calibration_error (ECE)" in cal["primary_calibration_evidence"]
    assert "reliability_bins" in cal["primary_calibration_evidence"]
    # Descriptive OLS stats are labeled by their actual meaning, not as
    # conventional calibration intercept/slope.
    ols = cal["descriptive_ols_statistics"]
    assert "ols_outcome_on_logit_slope" in ols
    assert "ols_outcome_on_logit_intercept" in ols
    assert "calibration_intercept" not in ols
    assert "calibration_slope" not in ols
    assert "NOT conventional logistic calibration" in ols["clarification"]


def test_scorecard_selected_parameter_hash_exact():
    sc = _load("xgboost_v1_scorecard.json")
    assert sc["selected_parameter_hash"] == SELECTED_PARAM_HASH
    # Conservative frozen params
    assert sc["selected_parameters"]["max_depth"] == 2
    assert sc["selected_parameters"]["learning_rate"] == 0.05
    assert sc["selected_parameters"]["max_rounds"] == 200


def test_scorecard_flags_correct():
    sc = _load("xgboost_v1_scorecard.json")
    assert sc["flags"]["2025_HOLDOUT_ACCESSED"] is False
    assert sc["flags"]["MARKET_DATA_USED"] is False
    assert sc["flags"]["POST_RESULT_RETUNING_OCCURRED"] is False


def test_scorecard_has_future_v2_and_blend_notes():
    sc = _load("xgboost_v1_scorecard.json")
    assert sc["future_v2_research_not_implemented"]["label"] == "FUTURE_V2_RESEARCH_NOT_IMPLEMENTED"
    assert sc["future_blend_research_not_implemented"]["label"] == "FUTURE_BLEND_RESEARCH_NOT_IMPLEMENTED"


def test_lock_manifest_refers_to_conservative():
    lock = json.loads(
        (DEV_DIR / "xgboost_selected_v1_lock" / "SELECTED_V1_LOCK_MANIFEST.json").read_text()
    )
    assert lock["selected_candidate"] == "conservative"
    assert lock["lock_type"] == "SELECTED_DEVELOPMENT_CANDIDATE_POST_ADJUDICATION"
    assert lock["refers_to_artifacts"]["selected_parameter_hash"] == SELECTED_PARAM_HASH
    assert lock["refers_to_artifacts"]["canonical_config_sha256"] == CANONICAL_CONFIG_SHA


def test_preserved_evidence_hashes_in_selection_artifact():
    sel = _load("xgboost_selected_candidate_v1.json")
    h = sel["hashes"]
    assert h["prediction_artifact_sha256"] == "aa13da5fe2056fdb483c95e4a4568506fd2a36b059983c4556d2680124919b6e"
    assert h["block_state_artifact_sha256"] == "0b229ffdce058081004390fd0a5bbbba73e838a190edd217c4aa54e2dba40365"
