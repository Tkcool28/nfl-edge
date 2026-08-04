"""Projection-closure invariants for the Sleeper audit (Rereview 4859475614).

Proves the four bounded fixes from this pass:

* **Defect 2.1** — empty-authority ghost filtering. When
  ``run_history.parquet`` is empty, planted snapshot / fetch /
  crosswalk / change rows must NOT affect metrics.
* **Defect 3.1** — HOF pregame pointer cache is written ONLY after
  the authoritative commit. A history-append failure leaves no
  pointer cache behind.
* **Defect 3.2** — HOF postgame report cache is written ONLY after
  the authoritative commit. Same guarantee for the
  ``sleeper_hof_game_observation.{md,json}`` pair.
* **Defect 4** — ``report_sleeper_qb_audit.py --report live``
  rejects cached reports whose ``source_history`` provenance
  disagrees with the live ledger (exit 2, ``STALE_DERIVED_REPORT``).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import polars as pl
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
TESTS_DIR = REPO_ROOT / "tests"
SCRIPTS_DIR = REPO_ROOT / "scripts"

PYTHONPATH_PARTS = [
    str(SRC_DIR),
    str(TESTS_DIR),
    str(REPO_ROOT / "tests"),
    str(REPO_ROOT),
]


def _make_audit_root(root: Path) -> Path:
    audit_root = root
    audit_root.mkdir(parents=True, exist_ok=True)
    ref = REPO_ROOT / "data" / "source_audits" / "sleeper_qb_v1" / "reference"
    if ref.exists():
        for child in ref.iterdir():
            target = audit_root / "reference" / child.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if child.is_file():
                shutil.copy(child, target)
            else:
                shutil.copytree(child, target)
    return audit_root


def _write_history(audit_root: Path, rows: list[dict[str, Any]]) -> None:
    path = audit_root / "run_history.parquet"
    if rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(rows).write_parquet(path)


def _run_orchestrator_direct(
    audit_root: Path,
    *,
    snapshot_id: str,
    observed_at_utc: str,
    kind: str = "scheduled",
) -> dict[str, Any]:
    sys.path.insert(0, str(SRC_DIR))
    sys.path.insert(0, str(TESTS_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator
    from tests.source_audits.sleeper_qb_v1._fake_session import (
        FakeSleeperSession,
    )

    return AuditOrchestrator(audit_root=audit_root).run(
        session=FakeSleeperSession(),
        kind=kind,
        forced_snapshot_id=snapshot_id,
        forced_observed_at_utc=observed_at_utc,
    )


def _plant_ghost_rows(
    audit_root: Path,
    *,
    snapshot_id: str,
    observed_at_utc: str,
) -> None:
    """Plant snapshot/crosswalk/change/fetch ghost rows whose
    snapshot_id is NOT in any committed history row."""
    normalized = audit_root / "normalized"
    normalized.mkdir(parents=True, exist_ok=True)
    # qb_snapshots (active)
    pl.DataFrame(
        [
            {
                "snapshot_id": snapshot_id,
                "fetched_at_utc": observed_at_utc,
                "sleeper_player_id": "1",
                "player_name": "Ghost QB",
                "team": "GHO",
                "position": "QB",
                "depth_chart_order": 1,
                "depth_chart_position": "QB",
                "injury_status": None,
                "injury_start_date": None,
                "practice_participation": None,
                "espn_id": None,
                "gsis_id": None,
            }
        ]
    ).write_parquet(normalized / "qb_snapshots.parquet")
    # qb_identity_crosswalk
    pl.DataFrame(
        [
            {
                "snapshot_id": snapshot_id,
                "sleeper_player_id": "1",
                "is_matched": False,
                "match_method": None,
                "nflverse_id": None,
                "espn_id": None,
                "gsis_id": None,
                "review_required": False,
            }
        ]
    ).write_parquet(normalized / "qb_identity_crosswalk.parquet")
    # qb_change_ledger
    pl.DataFrame(
        [
            {
                "snapshot_id": snapshot_id,
                "prior_snapshot_id": None,
                "sleeper_player_id": "1",
                "field_name": "team",
                "old_value": "OLD",
                "new_value": "GHO",
                "observed_at_utc": observed_at_utc,
            }
        ]
    ).write_parquet(normalized / "qb_change_ledger.parquet")
    # qb_evidence_states
    pl.DataFrame(
        [
            {
                "snapshot_id": snapshot_id,
                "sleeper_player_id": "1",
                "evidence_state": "DEPTH_CHART_NO_REPORT",
                "observed_at_utc": observed_at_utc,
            }
        ]
    ).write_parquet(normalized / "qb_evidence_states.parquet")
    # fetch_ledger
    fetch = audit_root / "fetch_ledger.parquet"
    pl.DataFrame(
        [
            {
                "snapshot_id": snapshot_id,
                "endpoint": "https://example.invalid",
                "request_started_at_utc": observed_at_utc,
                "response_received_at_utc": observed_at_utc,
                "duration_ms": 100,
                "http_status": 200,
                "success": True,
                "response_bytes": 16,
                "sha256": "a" * 64,
                "etag": None,
                "last_modified": None,
                "content_type": "application/json",
                "attempt_number": 1,
                "error_class": None,
                "error_message": None,
                "raw_payload_path": "/dev/null",
                "observed_at_utc": observed_at_utc,
            }
        ]
    ).write_parquet(fetch)


def _build_metrics_for_root(audit_root: Path) -> dict[str, Any]:
    sys.path.insert(0, str(SRC_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.metrics import (
        build_runs_from_disk,
        compute_reliability_metrics,
    )

    runs, change_ledger = build_runs_from_disk(audit_root)
    return compute_reliability_metrics(runs=runs, change_ledger=change_ledger)


# ----------------------------------------------------------------------
# Defect 2.1 — empty-authority ghost filtering
# ----------------------------------------------------------------------


def test_empty_history_with_planted_active_rows_keeps_active_zero(
    tmp_path: Path,
) -> None:
    """Empty run_history.parquet + planted active rows → metrics
    show zero active rows touched (ghost filter applied even when
    committed set is empty)."""
    audit_root = _make_audit_root(tmp_path)
    _write_history(audit_root, [])  # no committed rows
    _plant_ghost_rows(
        audit_root,
        snapshot_id="snap-ghost",
        observed_at_utc="2026-08-06T22:00:00Z",
    )
    metrics = _build_metrics_for_root(audit_root)
    assert metrics["scheduled_run_count"] == 0
    assert metrics["successful_run_count"] == 0
    assert metrics["failed_run_count"] == 0
    assert metrics["attempted_fetch_count"] == 0
    assert metrics["field_change_events"] == 0


def test_empty_history_with_planted_crosswalk_rows_yields_zero(
    tmp_path: Path,
) -> None:
    """Empty run_history.parquet + planted crosswalk rows →
    no crosswalk counts influence metrics."""
    audit_root = _make_audit_root(tmp_path)
    _write_history(audit_root, [])
    _plant_ghost_rows(
        audit_root,
        snapshot_id="snap-ghost",
        observed_at_utc="2026-08-06T22:00:00Z",
    )
    metrics = _build_metrics_for_root(audit_root)
    assert metrics["scheduled_run_count"] == 0
    assert metrics["successful_run_count"] == 0
    assert metrics["field_change_events"] == 0


def test_empty_history_with_planted_change_rows_yields_zero(
    tmp_path: Path,
) -> None:
    audit_root = _make_audit_root(tmp_path)
    _write_history(audit_root, [])
    _plant_ghost_rows(
        audit_root,
        snapshot_id="snap-ghost",
        observed_at_utc="2026-08-06T22:00:00Z",
    )
    metrics = _build_metrics_for_root(audit_root)
    assert metrics["field_change_events"] == 0


def test_empty_history_with_planted_fetch_rows_yields_zero(
    tmp_path: Path,
) -> None:
    audit_root = _make_audit_root(tmp_path)
    _write_history(audit_root, [])
    _plant_ghost_rows(
        audit_root,
        snapshot_id="snap-ghost",
        observed_at_utc="2026-08-06T22:00:00Z",
    )
    metrics = _build_metrics_for_root(audit_root)
    assert metrics["attempted_fetch_count"] == 0


def test_committed_plus_ghost_only_counts_committed(
    tmp_path: Path,
) -> None:
    """One committed snapshot + one ghost snapshot → metrics
    reflect only the committed rows."""
    audit_root = _make_audit_root(tmp_path)
    # Plant ghost rows FIRST so they're on disk.
    _plant_ghost_rows(
        audit_root,
        snapshot_id="snap-ghost",
        observed_at_utc="2026-08-06T21:00:00Z",
    )
    # Then run a successful scheduled run that commits snap-real.
    _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-real",
        observed_at_utc="2026-08-06T22:00:00Z",
    )
    metrics = _build_metrics_for_root(audit_root)
    # The successful run added real attempts and counts. Ghost
    # rows must not have doubled anything.
    assert metrics["scheduled_run_count"] == 1
    assert metrics["successful_run_count"] == 1
    assert metrics["failed_run_count"] == 0
    # The committed run is the only contributor.
    assert metrics["attempted_fetch_count"] == 1


# ----------------------------------------------------------------------
# Defect 3.1 — HOF pregame pointer cache post-commit
# ----------------------------------------------------------------------


def test_pregame_history_append_failure_leaves_no_pointer_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit_root = _make_audit_root(tmp_path)
    sys.path.insert(0, str(SRC_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1 import pipeline as pl_mod

    def fail_commit(self, record):  # type: ignore[no-untyped-def]
        raise OSError("forced history append failure")

    monkeypatch.setattr(
        pl_mod.AuditOrchestrator, "_commit_terminal_history", fail_commit
    )
    from tests.source_audits.sleeper_qb_v1._fake_session import (
        FakeSleeperSession,
    )

    result = pl_mod.AuditOrchestrator(audit_root=audit_root).run(
        session=FakeSleeperSession(),
        kind="pregame",
        forced_snapshot_id="snap-pre-a",
        forced_observed_at_utc="2026-08-06T22:00:00Z",
    )
    assert result["run_outcome"] == "PERSISTENCE_FAILURE"
    assert result["exit_code"] == 13
    pointer_path = audit_root / "hof_pregame_pointer.json"
    assert not pointer_path.exists()


def test_pregame_successful_commit_refreshes_pointer_cache(
    tmp_path: Path,
) -> None:
    audit_root = _make_audit_root(tmp_path)
    _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-pre-a",
        observed_at_utc="2026-08-06T22:00:00Z",
        kind="pregame",
    )
    pointer_path = audit_root / "hof_pregame_pointer.json"
    assert pointer_path.exists()
    payload = json.loads(pointer_path.read_text())
    assert payload["selected_snapshot_id"] == "snap-pre-a"


# ----------------------------------------------------------------------
# Defect 3.2 — HOF postgame report cache post-commit
# ----------------------------------------------------------------------


def test_postgame_history_append_failure_leaves_no_report_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit_root = _make_audit_root(tmp_path)
    # Seed a committed pregame so postgame can run.
    _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-pre-a",
        observed_at_utc="2026-08-06T22:00:00Z",
        kind="pregame",
    )
    sys.path.insert(0, str(SRC_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1 import pipeline as pl_mod

    def fail_commit(self, record):  # type: ignore[no-untyped-def]
        raise OSError("forced history append failure")

    monkeypatch.setattr(
        pl_mod.AuditOrchestrator, "_commit_terminal_history", fail_commit
    )
    from tests.source_audits.sleeper_qb_v1._fake_session import (
        FakeSleeperSession,
    )

    # Wipe any prior postgame cache so the test is unambiguous.
    for name in (
        "sleeper_hof_game_observation.md",
        "sleeper_hof_game_observation.json",
    ):
        path = audit_root / "reports" / name
        if path.exists():
            path.unlink()

    result = pl_mod.AuditOrchestrator(audit_root=audit_root).run(
        session=FakeSleeperSession(),
        kind="postgame",
        forced_snapshot_id="snap-post-a",
        forced_observed_at_utc="2026-08-06T23:30:00Z",
    )
    assert result["run_outcome"] == "PERSISTENCE_FAILURE"
    assert result["exit_code"] == 13
    for name in (
        "sleeper_hof_game_observation.md",
        "sleeper_hof_game_observation.json",
    ):
        assert not (audit_root / "reports" / name).exists()


def test_postgame_successful_commit_refreshes_report_cache(
    tmp_path: Path,
) -> None:
    audit_root = _make_audit_root(tmp_path)
    _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-pre-a",
        observed_at_utc="2026-08-06T22:00:00Z",
        kind="pregame",
    )
    _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-post-a",
        observed_at_utc="2026-08-07T03:30:00Z",
        kind="postgame",
    )
    json_path = audit_root / "reports" / "sleeper_hof_game_observation.json"
    md_path = audit_root / "reports" / "sleeper_hof_game_observation.md"
    assert json_path.exists()
    assert md_path.exists()
    payload = json.loads(json_path.read_text())
    assert payload["schema_version"] == "sleeper-hof-game-observation-v1"
    assert "observation" in payload


# ----------------------------------------------------------------------
# Defect 3.3 — HOF projection failure does NOT mutate outcome
# ----------------------------------------------------------------------


def test_hof_pointer_projection_failure_is_warning_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the post-commit pointer write fails, the committed
    outcome stays SUCCESS and projection_warnings is populated."""
    audit_root = _make_audit_root(tmp_path)
    sys.path.insert(0, str(SRC_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.atomic_io import atomic_write_text

    original = atomic_write_text

    def failing_pointer_write(path, content, *args, **kwargs):
        if str(path).endswith("hof_pregame_pointer.json"):
            raise OSError("forced pointer write failure")
        return original(path, content, *args, **kwargs)

    monkeypatch.setattr(
        "nfl_edge.source_audits.sleeper_qb_v1.pipeline.atomic_write_text",
        failing_pointer_write,
    )
    result = _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-pre-a",
        observed_at_utc="2026-08-06T22:00:00Z",
        kind="pregame",
    )
    assert result["run_outcome"] == "SUCCESS"
    assert result["exit_code"] == 0
    assert any(
        "hof_pregame_pointer.json" in w for w in result["projection_warnings"]
    )


def test_hof_report_projection_failure_is_warning_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit_root = _make_audit_root(tmp_path)
    _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-pre-a",
        observed_at_utc="2026-08-06T22:00:00Z",
        kind="pregame",
    )
    sys.path.insert(0, str(SRC_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.report import atomic_write_text as report_atomic_write_text

    original_report = report_atomic_write_text

    def failing_hof_report_write(path, content, *args, **kwargs):
        if str(path).endswith("sleeper_hof_game_observation.json"):
            raise OSError("forced HOF report write failure")
        return original_report(path, content, *args, **kwargs)

    monkeypatch.setattr(
        "nfl_edge.source_audits.sleeper_qb_v1.report.atomic_write_text",
        failing_hof_report_write,
    )
    result = _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-post-a",
        observed_at_utc="2026-08-07T03:30:00Z",
        kind="postgame",
    )
    print("DEBUG outcome:", result["run_outcome"], "warnings:", result["projection_warnings"])
    assert result["run_outcome"] == "SUCCESS"
    assert result["exit_code"] == 0
    assert any(
        "sleeper_hof_game_observation" in w
        for w in result["projection_warnings"]
    )


def test_hof_projection_failure_does_not_double_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful commit + failing HOF report write → exactly
    one history row, projection_warning populated, no second row."""
    audit_root = _make_audit_root(tmp_path)
    _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-pre-a",
        observed_at_utc="2026-08-06T22:00:00Z",
        kind="pregame",
    )
    rows_before = int(
        pl.read_parquet(audit_root / "run_history.parquet").height
    )
    sys.path.insert(0, str(SRC_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.report import atomic_write_text as report_atomic_write_text

    original_report = report_atomic_write_text

    def failing_hof_report_write(path, content, *args, **kwargs):
        if "sleeper_hof_game_observation" in str(path):
            raise OSError("forced HOF report write failure")
        return original_report(path, content, *args, **kwargs)

    monkeypatch.setattr(
        "nfl_edge.source_audits.sleeper_qb_v1.report.atomic_write_text",
        failing_hof_report_write,
    )
    _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-post-a",
        observed_at_utc="2026-08-07T03:30:00Z",
        kind="postgame",
    )
    rows_after = int(
        pl.read_parquet(audit_root / "run_history.parquet").height
    )
    assert rows_after == rows_before + 1


# ----------------------------------------------------------------------
# Defect 4 — stale-derived-report detection
# ----------------------------------------------------------------------


def _seed_live_report(
    audit_root: Path,
    provenance: dict[str, Any] | None,
) -> Path:
    """Write a fake sleeper_qb_live_audit.json with the given
    (or absent) source_history provenance block."""
    reports = audit_root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    report_path = reports / "sleeper_qb_live_audit.json"
    payload: dict[str, Any] = {
        "schema_version": "sleeper-qb-live-audit-v1",
        "generated_at_utc": "2026-08-06T22:00:00Z",
        "metrics": {
            "scheduled_run_count": 1,
            "successful_run_count": 1,
            "failed_run_count": 0,
        },
        "observations": [],
    }
    if provenance is not None:
        payload["source_history"] = dict(provenance)
    report_path.write_text(json.dumps(payload, indent=2))
    return report_path


def _cli_subprocess(
    audit_root: Path,
    *,
    report: str = "live",
) -> subprocess.CompletedProcess:
    """Invoke ``scripts/report_sleeper_qb_audit.py`` against a
    synthetic config rooted at ``audit_root``."""
    config_path = audit_root.parent / "audit_config.yaml"
    config_path.write_text(f"audit_root: {audit_root}\n")
    env = dict(os.environ)
    env["PYTHONPATH"] = ":".join(PYTHONPATH_PARTS + [str(SCRIPTS_DIR)])
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "report_sleeper_qb_audit.py"),
            "--config",
            str(config_path),
            "--report",
            report,
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_matching_provenance_prints_and_exits_zero(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path)
    # Seed history with one row.
    _write_history(
        audit_root,
        [
            {
                "outcome": "SUCCESS",
                "snapshot_id": "snap-r",
                "observed_at_utc": "2026-08-06T22:00:00Z",
                "finished_at_utc": "2026-08-06T22:00:01Z",
                "kind": "scheduled",
                "exit_code": 0,
                "attempt_count": 1,
            }
        ],
    )
    _seed_live_report(
        audit_root,
        {
            "source_history_row_count": 1,
            "source_history_last_finished_at_utc": "2026-08-06T22:00:01Z",
            "source_history_last_snapshot_id": "snap-r",
        },
    )
    proc = _cli_subprocess(audit_root)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == "sleeper-qb-live-audit-v1"


def test_row_count_mismatch_returns_stale(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path)
    _write_history(
        audit_root,
        [
            {
                "outcome": "SUCCESS",
                "snapshot_id": "snap-r",
                "observed_at_utc": "2026-08-06T22:00:00Z",
                "finished_at_utc": "2026-08-06T22:00:01Z",
                "kind": "scheduled",
                "exit_code": 0,
                "attempt_count": 1,
            }
        ],
    )
    _seed_live_report(
        audit_root,
        {
            "source_history_row_count": 5,  # mismatch
            "source_history_last_finished_at_utc": "2026-08-06T22:00:01Z",
            "source_history_last_snapshot_id": "snap-r",
        },
    )
    proc = _cli_subprocess(audit_root)
    assert proc.returncode == 2
    assert "STALE_DERIVED_REPORT" in proc.stdout
    assert "source_history_row_count" in proc.stderr


def test_last_finished_mismatch_returns_stale(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path)
    _write_history(
        audit_root,
        [
            {
                "outcome": "SUCCESS",
                "snapshot_id": "snap-r",
                "observed_at_utc": "2026-08-06T22:00:00Z",
                "finished_at_utc": "2026-08-06T22:00:01Z",
                "kind": "scheduled",
                "exit_code": 0,
                "attempt_count": 1,
            }
        ],
    )
    _seed_live_report(
        audit_root,
        {
            "source_history_row_count": 1,
            "source_history_last_finished_at_utc": "2026-08-07T00:00:00Z",
            "source_history_last_snapshot_id": "snap-r",
        },
    )
    proc = _cli_subprocess(audit_root)
    assert proc.returncode == 2
    assert "STALE_DERIVED_REPORT" in proc.stdout
    assert "source_history_last_finished_at_utc" in proc.stderr


def test_last_snapshot_mismatch_returns_stale(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path)
    _write_history(
        audit_root,
        [
            {
                "outcome": "SUCCESS",
                "snapshot_id": "snap-r",
                "observed_at_utc": "2026-08-06T22:00:00Z",
                "finished_at_utc": "2026-08-06T22:00:01Z",
                "kind": "scheduled",
                "exit_code": 0,
                "attempt_count": 1,
            }
        ],
    )
    _seed_live_report(
        audit_root,
        {
            "source_history_row_count": 1,
            "source_history_last_finished_at_utc": "2026-08-06T22:00:01Z",
            "source_history_last_snapshot_id": "snap-other",
        },
    )
    proc = _cli_subprocess(audit_root)
    assert proc.returncode == 2
    assert "STALE_DERIVED_REPORT" in proc.stdout
    assert "source_history_last_snapshot_id" in proc.stderr


def test_missing_source_history_returns_stale(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path)
    _write_history(
        audit_root,
        [
            {
                "outcome": "SUCCESS",
                "snapshot_id": "snap-r",
                "observed_at_utc": "2026-08-06T22:00:00Z",
                "finished_at_utc": "2026-08-06T22:00:01Z",
                "kind": "scheduled",
                "exit_code": 0,
                "attempt_count": 1,
            }
        ],
    )
    _seed_live_report(audit_root, None)  # no source_history block
    proc = _cli_subprocess(audit_root)
    assert proc.returncode == 2
    assert "STALE_DERIVED_REPORT" in proc.stdout
    assert "source_history" in proc.stderr


def test_missing_run_history_with_nonempty_cache_returns_stale(
    tmp_path: Path,
) -> None:
    audit_root = _make_audit_root(tmp_path)
    # No run_history.parquet on disk.
    _seed_live_report(
        audit_root,
        {
            "source_history_row_count": 1,
            "source_history_last_finished_at_utc": "2026-08-06T22:00:01Z",
            "source_history_last_snapshot_id": "snap-x",
        },
    )
    proc = _cli_subprocess(audit_root)
    assert proc.returncode == 2
    assert "STALE_DERIVED_REPORT" in proc.stdout


def test_empty_history_with_matching_empty_provenance_accepted(
    tmp_path: Path,
) -> None:
    audit_root = _make_audit_root(tmp_path)
    # Empty history (0 rows, all-None provenance).
    _write_history(audit_root, [])
    _seed_live_report(
        audit_root,
        {
            "source_history_row_count": 0,
            "source_history_last_finished_at_utc": None,
            "source_history_last_snapshot_id": None,
        },
    )
    proc = _cli_subprocess(audit_root)
    assert proc.returncode == 0, proc.stderr


def test_stale_detection_does_not_modify_audit_artifacts(
    tmp_path: Path,
) -> None:
    """The CLI must not write to any audit artifact — only print."""
    audit_root = _make_audit_root(tmp_path)
    _write_history(
        audit_root,
        [
            {
                "outcome": "SUCCESS",
                "snapshot_id": "snap-r",
                "observed_at_utc": "2026-08-06T22:00:00Z",
                "finished_at_utc": "2026-08-06T22:00:01Z",
                "kind": "scheduled",
                "exit_code": 0,
                "attempt_count": 1,
            }
        ],
    )
    _seed_live_report(
        audit_root,
        {
            "source_history_row_count": 99,  # mismatch
            "source_history_last_finished_at_utc": "x",
            "source_history_last_snapshot_id": "y",
        },
    )
    history_path = audit_root / "run_history.parquet"
    report_path = audit_root / "reports" / "sleeper_qb_live_audit.json"
    history_before = history_path.read_bytes()
    report_before = report_path.read_bytes()
    proc = _cli_subprocess(audit_root)
    assert proc.returncode == 2
    assert history_path.read_bytes() == history_before
    assert report_path.read_bytes() == report_before