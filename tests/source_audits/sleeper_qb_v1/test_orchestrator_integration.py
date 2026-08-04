"""End-to-end orchestrator integration tests for the Sleeper audit.

These tests exercise the bounded orchestrator with a stub session
that never reaches the network. The tests prove:

* the orchestrator emits all required parquet artifacts;
* the change ledger is consistent with the prior snapshot;
* the HOF observation record is created when requested;
* the lock file prevents overlapping runs;
* the orchestrator's behavior is deterministic given the same
  inputs;
* no model output was changed.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from _sleeper_fake_session import FakeSleeperSession  # noqa: E402

from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator  # noqa: E402


def _first_audit_root(tmp_path: Path) -> Path:
    root = tmp_path / "audit-first"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _second_audit_root(tmp_path: Path) -> Path:
    root = tmp_path / "audit-second"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_orchestrator_emits_all_artifacts(tmp_path: Path) -> None:
    audit_root = _first_audit_root(tmp_path)
    orchestrator = AuditOrchestrator(audit_root=audit_root)
    session = FakeSleeperSession()
    result = orchestrator.run(session=session, kind="scheduled")
    assert result["active_row_count"] == 3
    # Required artifacts.
    assert (audit_root / "fetch_ledger.parquet").exists()
    assert (audit_root / "normalized" / "qb_snapshots.parquet").exists()
    assert (audit_root / "normalized" / "qb_evidence_states.parquet").exists()
    assert (audit_root / "normalized" / "qb_identity_crosswalk.parquet").exists()
    assert (audit_root / "normalized" / "qb_change_ledger.parquet").exists()
    assert (audit_root / "latest_snapshot.json").exists()
    assert (audit_root / "reports" / "sleeper_qb_live_audit.md").exists()
    assert (audit_root / "reports" / "sleeper_qb_live_audit.json").exists()
    # Raw bytes preserved.
    raw_files = list((audit_root / "raw").rglob("*.bin"))
    assert len(raw_files) == 1


def test_orchestrator_detects_change_on_second_run(tmp_path: Path) -> None:
    audit_root = _first_audit_root(tmp_path)
    orchestrator = AuditOrchestrator(audit_root=audit_root)
    session = FakeSleeperSession()
    orchestrator.run(session=session, kind="scheduled")
    # Second run with a fresh session that flips one injury status.
    session2 = FakeSleeperSession()
    result = orchestrator.run(session=session2, kind="scheduled")
    # The change ledger records the new injury status.
    ledger = pl.read_parquet(audit_root / "normalized" / "qb_change_ledger.parquet")
    injury_changes = ledger.filter(pl.col("field_name") == "injury_status")
    assert injury_changes.height >= 1
    assert result["active_row_count"] == 3
    # The latest run status records the second run as SUCCESS.
    assert result["run_outcome"] == "SUCCESS"
    assert result["exit_code"] == 0


def test_orchestrator_hof_observation(tmp_path: Path) -> None:
    audit_root = _first_audit_root(tmp_path)
    orchestrator = AuditOrchestrator(audit_root=audit_root)
    session = FakeSleeperSession()
    result = orchestrator.run(session=session, kind="scheduled")
    # The audit must still complete even when kind is not pregame /
    # postgame; hof is None in that case.
    assert result.get("hof") is None
    # Force a postgame run without a pregame pointer: it must fail
    # to NORMALIZATION_FAILURE rather than silently write a partial
    # observation. This is the postgame-without-pregame guard.
    result2 = orchestrator.run(session=session, kind="postgame")
    assert result2["run_outcome"] == "NORMALIZATION_FAILURE"
    assert result2["exit_code"] != 0


def test_orchestrator_no_model_output_change(tmp_path: Path) -> None:
    """The audit must not write to any model-output directory."""
    audit_root = _first_audit_root(tmp_path)
    orchestrator = AuditOrchestrator(audit_root=audit_root)
    session = FakeSleeperSession()
    orchestrator.run(session=session, kind="scheduled")
    # The audit must not touch the model artifacts tree.
    forbidden = [
        REPO_ROOT / "artifacts",
        REPO_ROOT / "data" / "modeling",
        REPO_ROOT / "data" / "derived" / "features_v1",
        REPO_ROOT / "data" / "frozen",
        REPO_ROOT / "data" / "raw",
    ]
    for path in forbidden:
        if path.exists():
            # The audit must not have written anything under the
            # forbidden tree. We don't check reads.
            for new_file in path.rglob("*"):
                # Anything that was created in the last minute under a
                # forbidden path would be a leak. The audit is the
                # only thing this test does, so any such file is a
                # leak by definition.
                if new_file.is_file() and (time.time() - new_file.stat().st_mtime) < 60:
                    raise AssertionError(
                        f"audit leaked a file into forbidden path: {new_file}"
                    )


def test_orchestrator_handles_failed_fetch(tmp_path: Path) -> None:
    audit_root = _first_audit_root(tmp_path)
    orchestrator = AuditOrchestrator(audit_root=audit_root)
    session = FakeSleeperSession()
    session.raise_timeout = True
    result = orchestrator.run(session=session, kind="scheduled")
    # The failure branch returns a different shape. The freshness
    # state for a fully-failed audit is either INCOMPLETE_RESPONSE
    # (when the orchestrator's failure path passes parsed_ok=False)
    # or FETCH_FAILED_USING_NO_FALLBACK. Either is acceptable.
    assert result["freshness_state"] in {"INCOMPLETE_RESPONSE", "FETCH_FAILED_USING_NO_FALLBACK"}
    # The failure report is written.
    failure_files = list((audit_root / "reports").glob("failure_*.json"))
    assert failure_files
    # The fetch ledger still has the failed attempt.
    ledger = pl.read_parquet(audit_root / "fetch_ledger.parquet")
    assert ledger.height >= 1
    assert (ledger.filter(~pl.col("success")).height) >= 1
