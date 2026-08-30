from __future__ import annotations

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
WORKFLOW = ROOT / ".github" / "workflows" / "pre2025-product-freeze-v1.yml"


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


def test_final_acceptance_contract_is_authorized_ready_without_tuning_surface():
    cfg = _yaml(ACCEPT)
    assert cfg["holdout_season"] == 2025
    assert cfg["status"] == "READY_FOR_SINGLE_AUTHORIZED_2025_HOLDOUT_EXECUTION"
    assert cfg["remaining_missing_2025_input_surfaces"] == []
    assert cfg["execution"]["ready"] is True
    assert cfg["execution"]["tuning_flags_allowed"] is False
    assert cfg["chronology"]["same_block_outcomes_available_to_predictions"] is False
    assert cfg["chronology"]["retroactive_knowledge"] == "prohibited"
    assert cfg["interpretation"]["post_result_retuning"] == "prohibited"
    assert cfg["interpretation"]["methodology_change_from_2025_results"] == "prohibited"


def test_authorization_is_hash_only_and_external_to_repository():
    cfg = _yaml(ACCEPT)
    auth = cfg["authorization"]
    expected_sha256 = "f32f7b3a4316dc2f1154bb531b1c496b9958b33291e9e95a95b99767a1190f0a"
    assert auth["exact_phrase_sha256"] == expected_sha256
    assert auth["plaintext_stored_in_repository"] is False
    assert "$NFL_EDGE_2025_AUTHORIZATION" in cfg["execution"]["canonical_command"]
    runner_text = RUNNER.read_text()
    assert "AUTHORIZATION_PHRASE" not in runner_text
    assert expected_sha256 in runner_text
    assert "hashlib.sha256(value.encode()).hexdigest() != AUTHORIZATION_SHA256" in runner_text


def test_holdout_market_book_contract_preserves_raw_and_product_scopes():
    cfg = _yaml(ACCEPT)["execution"]["required_future_executor_contract"]
    assert cfg["raw_acquisition_books"] == [
        "draftkings",
        "fanduel",
        "pinnacle",
        "betmgm",
        "williamhill_us",
        "caesars",
        "betrivers",
        "pointsbetus",
        "wynnbet",
        "unibet_us",
    ]
    assert cfg["product_preserved_books"] == ["draftkings", "fanduel", "pinnacle"]


def test_prefreeze_audit_uses_immutable_git_metadata_for_sealed_files():
    text = AUDIT.read_text()
    assert "IMMUTABLE_FREEZE_ANCHOR_SHA" in text
    assert "IMMUTABLE_REFERENCE_MAIN_SHA" in text
    assert '"ls-files", "-s", "--", path' in text
    assert '"ls-tree", commit, "--", path' in text
    assert "freeze manifest drift from immutable anchor" in text
    assert "contract file changed after contract_git_sha" in text
    assert "pl.read_parquet" not in text
    assert "pandas" not in text
    assert "pyarrow" not in text
    assert "sealed_data_bytes_read" in text


def test_prefreeze_audit_rejects_dirty_executable_paths_without_diffing_sealed_data():
    text = AUDIT.read_text()
    assert "unstaged protected-file drift" in text
    assert "staged protected-file drift" in text
    assert "_assert_clean_executable_path(path)" in text
    sealed_loop = text.split("sealed_metadata: dict[str, str] = {}", 1)[1].split(
        "guards =", 1
    )[0]
    assert "_assert_clean_executable_path" not in sealed_loop


def test_freeze_workflow_runs_for_every_pull_request_and_uses_invalid_auth():
    text = WORKFLOW.read_text()
    assert "  pull_request:\n  workflow_dispatch:" in text
    assert "paths:" not in text.split("permissions:", 1)[0]
    assert "CI_INTENTIONALLY_INVALID_AUTHORIZATION" in text
    assert "$NFL_EDGE_2025_AUTHORIZATION" not in text


def test_one_shot_runner_retains_fail_closed_authorization_gate():
    text = RUNNER.read_text()
    assert "HOLDOUT_EXECUTOR_NOT_FROZEN" in text
    assert "authorization mismatch; 2025 remains sealed" in text
    assert "IRREVERSIBLE_BEFORE_FIRST_2025_INPUT_READ" in text


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
    assert payload["execution_ready"] is True


def test_wrong_authorization_fails_closed_before_holdout_read():
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--authorization", "CI_TEST_INVALID"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 2
    assert "authorization mismatch" in completed.stderr


def test_existing_production_freeze_remains_no_semantic_changes():
    freeze = _yaml(ROOT / "config" / "task05g_final_product_freeze_v1.yaml")
    assert freeze["semantic_changes_after_freeze_allowed"] is False
    assert 2025 in [int(x) for x in freeze["sealed_boundary"]["not_opened_not_run"]]


def test_acceptance_spec_rejects_roi_only_decision():
    text = (ROOT / "docs" / "PRE2025_HOLDOUT_ACCEPTANCE_SPEC_V1.md").read_text()
    assert "There is no single arbitrary ROI hurdle" in text
    assert "A profitable 2025 season does not prove durable edge" in text
    assert "A losing 2025 season does not by itself prove an implementation defect" in text
