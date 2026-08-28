from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ACCEPT = ROOT / "config" / "task05g_2025_acceptance_v1.yaml"
FREEZE = ROOT / "config" / "task05g_pre2025_holdout_freeze_v1.yaml"
RUNNER = ROOT / "scripts" / "task05g_2025_holdout_one_shot_v1.py"
AUDIT = ROOT / "scripts" / "task05g_pre2025_freeze_audit_v1.py"


def _yaml(path: Path):
    return yaml.safe_load(path.read_text())


def test_prefreeze_contract_is_blocked_and_sealed():
    freeze = _yaml(FREEZE)
    assert freeze["schema_version"] == "task05g_pre2025_holdout_freeze_v1"
    assert freeze["status"] == "PRE2025_PRODUCT_FREEZE_PARTIAL"
    assert freeze["sealed_holdout_season"] == 2025
    assert freeze["authorization_ready"] is False
    assert freeze["next_allowed_verdict"] == "NOT_READY_TO_OPEN_2025"
    assert len(freeze["blockers"]) >= 2


def test_acceptance_contract_has_no_tuning_surface():
    cfg = _yaml(ACCEPT)
    assert cfg["holdout_season"] == 2025
    assert cfg["execution"]["ready"] is False
    assert cfg["execution"]["tuning_flags_allowed"] is False
    assert cfg["chronology"]["same_block_outcomes_available_to_predictions"] is False
    assert cfg["chronology"]["retroactive_knowledge"] == "prohibited"
    assert cfg["interpretation"]["post_result_retuning"] == "prohibited"
    assert cfg["interpretation"]["methodology_change_from_2025_results"] == "prohibited"


def test_authorization_phrase_is_hash_locked():
    cfg = _yaml(ACCEPT)
    digest = hashlib.sha256(b"MASTER_APPROVED_OPEN_2025_ONCE").hexdigest()
    assert digest == cfg["authorization"]["exact_phrase_sha256"]


def test_prefreeze_audit_uses_git_metadata_for_sealed_files():
    text = AUDIT.read_text()
    assert 'git", "ls-files", "-s"' in text
    assert "pl.read_parquet" not in text
    assert "pandas" not in text
    assert "pyarrow" not in text
    assert "sealed_data_bytes_read" in text


def test_one_shot_runner_has_no_2025_data_reader_while_blocked():
    text = RUNNER.read_text()
    for forbidden in ("read_parquet", "scan_parquet", "read_csv", "open_dataset", "pyarrow"):
        assert forbidden not in text
    assert "HOLDOUT_EXECUTOR_NOT_FROZEN" in text
    assert "execution.ready=true without a frozen executor implementation" in text


def test_preflight_passes_without_opening_holdout(tmp_path):
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--preflight"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "SEALED_PREFLIGHT_PASS"
    assert payload["holdout_season"] == 2025
    assert payload["2025_data_read"] is False
    assert payload["execution_ready"] is False


def test_wrong_authorization_fails_closed_before_holdout_read():
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--authorization", "WRONG"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 2
    assert "authorization mismatch" in completed.stderr


def test_correct_authorization_still_fails_while_executor_unfrozen():
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--authorization", "MASTER_APPROVED_OPEN_2025_ONCE"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 2
    assert "HOLDOUT_EXECUTOR_NOT_FROZEN" in completed.stderr
    assert "no 2025 read occurred" in completed.stderr


def test_existing_production_freeze_remains_no_semantic_changes():
    freeze = _yaml(ROOT / "config" / "task05g_final_product_freeze_v1.yaml")
    assert freeze["semantic_changes_after_freeze_allowed"] is False
    assert 2025 in [int(x) for x in freeze["sealed_boundary"]["not_opened_not_run"]]


def test_acceptance_spec_rejects_roi_only_decision():
    text = (ROOT / "docs" / "PRE2025_HOLDOUT_ACCEPTANCE_SPEC_V1.md").read_text()
    assert "There is no single arbitrary ROI hurdle" in text
    assert "A profitable 2025 season does not prove durable edge" in text
    assert "A losing 2025 season does not by itself prove an implementation defect" in text
