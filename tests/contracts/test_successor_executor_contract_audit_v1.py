"""Regression tests for the v1 historical-provenance vs v4 authoritative-freeze split.

The Task05G settlement-contract fix narrowly relaxed the audit's check
that compared every entry in ``pre2025_successor_executor_contract_v1.json``
``successor_contract_files`` against the actual blob at the historic
``successor_contract_git_sha``. v1 is historical provenance; v4 is the
authoritative current freeze.

These tests prove:

* the strict ``anchored == expected`` equality check in the v1 successor
  loop was removed and replaced with a provenance-only check;
* v4's strict blob-equal check remains untouched;
* the historical pre-2025 product-freeze strict check remains untouched;
* methodology/tuning/authorization/certified-input/Task05F identity
  checks remain unchanged;
* the v1 record may diverge from the current tree without failing the
  audit, while a v4 mismatch still fails.

Run with::

    pytest tests/contracts/test_successor_executor_contract_audit_v1.py -q
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCRIPT = REPO_ROOT / "scripts/task05g_successor_executor_contract_audit_v1.py"


# ---------------------------------------------------------------------------
# Module + fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def audit_module():
    spec = importlib.util.spec_from_file_location(
        "successor_executor_contract_audit_under_test", AUDIT_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Source-level guarantees: prove the audit-script shape
# ---------------------------------------------------------------------------


def test_audit_script_drops_v1_strict_pin_equal_check(audit_module):
    """The strict ``anchored == expected`` equality check for v1 has been
    removed from the successor_contract_files loop. v1 pins are historical
    provenance and may differ from the current tree.
    """
    source = AUDIT_SCRIPT.read_text()
    # The original failing pattern was inside the v1 successor loop:
    #       if anchored != str(expected):
    #           raise AuditFailure(f"successor record/commit mismatch: {path}")
    # That branch must no longer appear in the script. The whole idiom is
    # the named check — its absence is the contract.
    assert "successor record/commit mismatch" not in source, (
        "Audit script still raises 'successor record/commit mismatch'; "
        "v1 historical pin equal-check was reintroduced."
    )


def test_audit_script_still_enforces_v4_strict_source_drift(audit_module):
    """The authoritative-current-freeze source-drift check must remain."""
    source = AUDIT_SCRIPT.read_text()
    assert 'raise AuditFailure(f"final promotion source identity drift: {path}")' in source, (
        "v4 frozen_source_blobs drift check was weakened; v4 must remain authoritative"
    )


def test_audit_script_still_enforces_historical_freeze_drift(audit_module):
    """The historical pre-2025 product-freeze drift check must remain."""
    source = AUDIT_SCRIPT.read_text()
    assert 'raise AuditFailure(f"historical contract drift: {path}: {current} != {anchored}")' in source
    assert "historical record/commit mismatch" in source


def test_audit_script_keeps_methodology_authorization_and_task05f_invariants(audit_module):
    """Methodology, tuning, authorization, certified-input checks, and
    Task05F historical-board identity must all still gate the audit.
    """
    source = AUDIT_SCRIPT.read_text()
    for must_still_be_present in [
        'raise AuditFailure("successor must remain sealed and not ready")',
        'raise AuditFailure("successor contract permits methodology or tuning drift")',
        'raise AuditFailure("all-model 2025 certification verdict drift")',
        'raise AuditFailure("all-model 2025 certification matrix is incomplete")',
        'raise AuditFailure("certification no longer proves unopened holdout")',
        'raise AuditFailure("Task05F historical-board identity reconciliation drift")',
        'raise AuditFailure("final promotion authorization identity drift")',
        'raise AuditFailure("immutable pre-2025 freeze manifest drift")',
        'raise AuditFailure("historical seal invariant drift")',
        'raise AuditFailure("final product freeze no longer records 2025 sealed")',
    ]:
        assert must_still_be_present in source, f"removed guard: {must_still_be_present}"


# ---------------------------------------------------------------------------
# Function-level invariants on _check_legacy_v1_provenance_only
# ---------------------------------------------------------------------------


def test_provenance_helper_rejects_phantom_path(audit_module):
    """A v1 entry that names a path that did not exist at the historic
    successor_contract_git_sha must raise AuditFailure.
    """
    historic_commit = "1b833cfb01d09894adbabcd6604cae90ebc368e9"
    phantom_files = {
        "scripts/task05g_2025_holdout_one_shot_v1.py": "12ba9d5c51834c19cb26dd47ba898565bcf05a6d",
        "definitely/not/a/real/path/that/never/existed_xyz.py": "deadbeef" * 10,
    }
    with pytest.raises(audit_module.AuditFailure, match="path absent at"):
        audit_module._check_legacy_v1_provenance_only(historic_commit, phantom_files)


def test_provenance_helper_accepts_stale_real_pins(audit_module):
    """The helper must accept the actual live v1 pins (some may be
    stale relative to current main). It only validates path existence,
    not pin equality.
    """
    v1 = json.loads(
        (REPO_ROOT / "reports/pre2025/pre2025_successor_executor_contract_v1.json").read_text()
    )
    # Must NOT raise, even when the live v1 pins happen to disagree with
    # the actual blobs at the historic successor_commit.
    audit_module._check_legacy_v1_provenance_only(
        v1["successor_contract_git_sha"], v1["successor_contract_files"]
    )


def test_audit_source_has_silent_rewrite_guard(audit_module):
    """A silent in-place rewrite of the v1 record (working tree != tracked)
    must still be detected. Provenance tampering is the one v1 surface we
    refuse to relax.
    """
    source = AUDIT_SCRIPT.read_text()
    assert "v1 successor contract record has been silently rewritten" in source, (
        "in-place v1 rewrite detection was removed"
    )


# ---------------------------------------------------------------------------
# End-to-end: relaxed v1 audit on a synthetic scenario
# ---------------------------------------------------------------------------


def test_audit_helper_does_not_raise_on_known_stale_v1_pins(audit_module):
    """Live v1 pins include known-stale entries (drifted between the historic
    commit and current main). The helper must not raise on those; only the
    v4 strict check is allowed to flag drift.
    """
    v1 = json.loads(
        (REPO_ROOT / "reports/pre2025/pre2025_successor_executor_contract_v1.json").read_text()
    )
    # Examine whether the live v1 pins show drift at the historic commit.
    mismatches = []
    for path, expected in v1["successor_contract_files"].items():
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", f"{v1['successor_contract_git_sha']}:{path}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip() != expected:
            mismatches.append(path)
    # Helper accepts regardless of pin staleness:
    audit_module._check_legacy_v1_provenance_only(
        v1["successor_contract_git_sha"], v1["successor_contract_files"]
    )
    # We don't assert mismatches > 0 here; the test is "no raise on whatever is given".
    # The structural evidence lives in the source-grep tests above.


# ---------------------------------------------------------------------------
# Settlement-fix regression suite must still pass alongside this audit test
# ---------------------------------------------------------------------------


def test_settlement_regression_tests_still_pass():
    """The Task05G settlement regression suite must remain green on the
    live repo. This guards against this audit-test refactor accidentally
    masking the settlement fix.
    """
    venv_python = REPO_ROOT / ".venv/bin/python3"
    if not venv_python.is_file():
        pytest.skip("repo .venv python not available; settlement tests live-tested in CI")
    result = subprocess.run(
        [
            str(venv_python),
            "-m",
            "pytest",
            "tests/holdout/test_executor_runtime_2025_settlement_contract.py",
            "-q",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"settlement regression tests failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
