"""Task 03C-6A: row-accounting reconciliation tests.

Proves the accepted conservative slice encodes 1651 binary-scored / 288 warm-up /
3 tie-or-non-binary rows, that the 3 tie rows are NOT counted as binary losses,
and that current permanent reporting artifacts record the corrected accounting
(288, not the 291 shorthand) while model outputs/metrics/selection are unchanged.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl

WORKSPACE = Path(__file__).resolve().parents[2]
DEV_DIR = WORKSPACE / "data" / "modeling" / "development_v1"
ACCEPTED_PRED = DEV_DIR / "xgboost_candidate_predictions_2018_2024.parquet"
ACCEPTED_PRED_SHA = "aa13da5fe2056fdb483c95e4a4568506fd2a36b059983c4556d2680124919b6e"
SELECTED = "conservative"
SELECTED_PARAM_HASH = "a044ba76fd138bde1a52e364fd7fce5de042a2ddfdb6cdac22e592d4819ed58b"

TIE_GAME_IDS = {"2020_03_CIN_PHI", "2021_10_DET_PIT", "2022_13_WAS_NYG"}

# Pre-correction original 03C-4B raw evidence SHAs (must stay unchanged).
BLOCK_STATE_SHA = "0b229ffdce058081004390fd0a5bbbba73e838a190edd217c4aa54e2dba40365"
METRICS_SHA = "01484bba99ef3e32fffd0bd7f60bbf4aa081871eb1ad5bb017a763db019abad1"
BOOTSTRAP_SHA = "481eda0459829ad78b16a304a94f232607480681d264acba1673b03b2617adb5"
FIRST_RUN_PRES_SHA = "ef5615a058df51f6fdc419d61222e243608bdc0e0230fc2a55baa634a4788bc3"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _conservative_slice() -> pl.DataFrame:
    return pl.read_parquet(ACCEPTED_PRED).filter(pl.col("candidate_id") == SELECTED)


def test_exact_row_accounting() -> None:
    c = _conservative_slice()
    assert c.height == 1942
    assert c.filter(pl.col("binary_score_eligible")).height == 1651
    assert c.filter(pl.col("warmup")).height == 288
    tie = c.filter(~pl.col("binary_score_eligible") & ~pl.col("warmup"))
    assert tie.height == 3
    # categories sum to total
    assert 1651 + 288 + 3 == 1942


def test_binary_scored_rows_have_valid_binary_target_and_probability() -> None:
    c = _conservative_slice()
    scored = c.filter(pl.col("binary_score_eligible"))
    assert scored.filter(pl.col("target").is_null()).height == 0
    assert scored.filter(pl.col("prediction_probability").is_null()).height == 0
    # warmup rows are excluded from the binary scored set entirely
    assert scored.filter(pl.col("warmup")).height == 0


def test_exact_three_tie_rows_are_not_binary_losses() -> None:
    c = _conservative_slice()
    tie = c.filter(~pl.col("binary_score_eligible") & ~pl.col("warmup"))
    assert set(tie["game_id"].to_list()) == TIE_GAME_IDS
    # none of the 3 carried a warm-up flag
    assert tie.filter(pl.col("warmup")).height == 0
    assert tie["target"].is_null().all()
    # they are not counted as binary losses (they have a prediction but no binary target)
    assert tie.filter(pl.col("binary_score_eligible")).height == 0
    # and they are NOT silently scored against a binary outcome
    assert tie.filter(pl.col("target") == False).height == 0  # noqa: E712
    assert tie.filter(pl.col("target") == True).height == 0  # noqa: E712


def test_scorecard_records_288_not_291() -> None:
    s = json.loads((DEV_DIR / "xgboost_v1_scorecard.json").read_text())
    ident = s["identity"]
    assert ident["total_rows"] == 1942
    assert ident["binary_scored_rows"] == 1651
    assert ident["warmup_rows"] == 288
    assert ident["tie_or_nonbinary_rows"] == 3
    md = (DEV_DIR / "xgboost_v1_scorecard.md").read_text()
    assert "| Total rows | 1942 |" in md
    assert "| Binary scored rows | 1651 |" in md
    assert "| Warm-up rows | 288 |" in md
    assert "| Tie/non-binary rows | 3 |" in md
    # the accounting table must not carry the incorrect 291 shorthand
    assert "| Warm-up rows | 291 |" not in md
    # 291 may appear only inside the explanatory note (a historical explanation),
    # not in the recorded accounting fields themselves.
    recorded = {k: ident[k] for k in ("total_rows", "binary_scored_rows", "warmup_rows", "tie_or_nonbinary_rows")}
    assert "291" not in json.dumps(recorded)
    assert "producing 291" in md
    assert "producing 291" in ident["row_accounting_note"]


def test_selected_candidate_records_correct_row_accounting() -> None:
    s = json.loads((DEV_DIR / "xgboost_selected_candidate_v1.json").read_text())
    assert s["selected_candidate"] == SELECTED
    # scored/common row count is 1651 (binary scored) - correct
    assert s["selection_basis"]["common_row_count"] == 1651
    assert s["frozen_candidate_metrics"][SELECTED]["scored_rows"] == 1651
    assert "291" not in json.dumps(s)


def test_selected_candidate_and_param_hash_unchanged() -> None:
    s = json.loads((DEV_DIR / "xgboost_selected_candidate_v1.json").read_text())
    assert s["selected_candidate"] == SELECTED
    # selected parameter hash stays frozen
    lock_v2 = json.loads(
        (DEV_DIR / "xgboost_selected_v1_lock" / "SELECTED_V1_LOCK_MANIFEST_V2.json").read_text()
    )
    assert lock_v2["selected_parameter_hash"] == SELECTED_PARAM_HASH
    assert lock_v2["row_accounting"] == {
        "total_rows": 1942,
        "binary_scored_rows": 1651,
        "warmup_rows": 288,
        "tie_or_nonbinary_rows": 3,
    }


def test_performance_metrics_unchanged() -> None:
    s = json.loads((DEV_DIR / "xgboost_v1_scorecard.json").read_text())
    m = s["aggregate_metrics"]
    assert abs(m["brier_score"] - 0.232614) < 1e-9
    assert abs(m["logloss"] - 0.657516) < 1e-9
    assert abs(m["accuracy"] - 0.614779) < 1e-9
    assert abs(m["roc_auc"] - 0.648708) < 1e-9


def test_original_04b_raw_prediction_sha_unchanged() -> None:
    assert _sha256(ACCEPTED_PRED) == ACCEPTED_PRED_SHA


def test_authoritative_model_evidence_unchanged() -> None:
    assert _sha256(DEV_DIR / "xgboost_block_state_2018_2024.parquet") == BLOCK_STATE_SHA
    assert _sha256(DEV_DIR / "xgboost_candidate_metrics_v1.json") == METRICS_SHA
    assert _sha256(DEV_DIR / "xgboost_blocked_bootstrap_v1.json") == BOOTSTRAP_SHA
    assert _sha256(DEV_DIR / "xgboost_03c4b_first_run_preservation_manifest.json") == FIRST_RUN_PRES_SHA


def test_erratum_exists_and_records_corrected_accounting() -> None:
    e = json.loads((DEV_DIR / "xgboost_v1_row_accounting_erratum.json").read_text())
    assert e["issue"] == "NON_SCORED_ROWS_PREVIOUSLY_MISLABELED_AS_WARMUP"
    assert e["corrected_accounting"]["total_rows"] == 1942
    assert e["corrected_accounting"]["binary_scored_rows"] == 1651
    assert e["corrected_accounting"]["warmup_rows"] == 288
    assert e["corrected_accounting"]["tie_or_nonbinary_rows"] == 3
    assert e["corrected_accounting"]["sum_check"] == "1651 + 288 + 3 = 1942"
    assert set(e["tie_or_nonbinary_game_ids"]) == TIE_GAME_IDS
    assert e["flags"]["MODEL_OUTPUT_CHANGED"] is False
    assert e["flags"]["CANDIDATE_SELECTION_CHANGED"] is False
    assert e["flags"]["METRICS_CHANGED"] is False
    assert e["flags"]["2025_HOLDOUT_ACCESSED"] is False
    # erratum references the authoritative raw prediction SHA
    assert e["authoritative_raw_prediction_sha256"] == ACCEPTED_PRED_SHA


def test_selected_lock_v2_references_erratum_and_corrected_artifacts() -> None:
    lock_v2 = json.loads(
        (DEV_DIR / "xgboost_selected_v1_lock" / "SELECTED_V1_LOCK_MANIFEST_V2.json").read_text()
    )
    assert lock_v2["selected_candidate"] == SELECTED
    refs = lock_v2["refers_to_artifacts"]
    # corrected scorecard JSON SHA
    scorecard_sha = _sha256(DEV_DIR / "xgboost_v1_scorecard.json")
    assert refs["scorecard_sha256"] == scorecard_sha
    # erratum SHA matches on-disk
    erratum_sha = _sha256(DEV_DIR / "xgboost_v1_row_accounting_erratum.json")
    assert refs["row_accounting_erratum_sha256"] == erratum_sha
    # prediction artifact SHA unchanged
    assert refs["prediction_artifact_sha256"] == ACCEPTED_PRED_SHA
