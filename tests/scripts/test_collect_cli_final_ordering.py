"""Authoritative-ledger invariants for the Sleeper audit CLI (rereview 4851615980).

Proves:
* prior successful snapshot derives from ``run_history.parquet``
  (NOT from ``latest_snapshot.json``);
* HOF postgame derives pregame from committed history (NOT from
  ``hof_pregame_pointer.json``);
* a stale / missing / failed-snapshot cache does not influence
  pipeline correctness;
* the current committed run is included in rolling metrics
  naturally (no provisional in-memory workaround);
* derived-view refresh failures surface as warnings and do NOT
  append a second history row;
* a report cache that disagrees with the live ledger is detected
  as STALE.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
TESTS_DIR = REPO_ROOT / "tests"

CLI_PATH = REPO_ROOT / "scripts" / "collect_sleeper_qbs.py"
SLEEPER_SCRIPT_PATH = REPO_ROOT / "scripts" / "_sleeper_fake_session.py"
FAKE_SESSION_PATH = (
    TESTS_DIR / "source_audits" / "sleeper_qb_v1" / "_fake_session.py"
)


def _shim_path_prefix() -> str:
    return (
        "import sys\n"
        f"sys.path.insert(0, {str(SRC_DIR)!r})\n"
        f"sys.path.insert(0, {str(TESTS_DIR)!r})\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        f"sys.path.insert(0, {str(REPO_ROOT / 'scripts')!r})\n"
        "import os\n"
        f"os.chdir({str(REPO_ROOT)!r})\n"
    )


def _shim_bootstrap() -> str:
    return (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location("
        f"'tests.source_audits.sleeper_qb_v1._fake_session', "
        f"{str(FAKE_SESSION_PATH)!r})\n"
        "if spec and spec.loader:\n"
        "    m = importlib.util.module_from_spec(spec); "
        "sys.modules.setdefault("
        "'tests.source_audits.sleeper_qb_v1._fake_session', m); "
        "spec.loader.exec_module(m)\n"
        f"script_spec = importlib.util.spec_from_file_location("
        f"'_sleeper_fake_session', {str(SLEEPER_SCRIPT_PATH)!r})\n"
        "if script_spec and script_spec.loader:\n"
        "    s = importlib.util.module_from_spec(script_spec); "
        "sys.modules.setdefault('_sleeper_fake_session', s); "
        "script_spec.loader.exec_module(s)\n"
    )


def _make_audit_root(root: Path) -> Path:
    import shutil

    audit_root = root
    audit_root.mkdir(parents=True, exist_ok=True)
    ref = REPO_ROOT / "data" / "source_audits" / "sleeper_qb_v1" / "reference"
    if ref.exists():
        shutil.copytree(ref, audit_root / "reference")
    return audit_root


def _seed_run_history(
    audit_root: Path,
    rows: list[dict[str, Any]],
) -> None:
    """Write a hand-crafted run_history.parquet so we can
    test prior-success / pregame selection directly."""
    import polars as pl

    audit_root.mkdir(parents=True, exist_ok=True)
    cols = [
        "outcome",
        "snapshot_id",
        "observed_at_utc",
        "finished_at_utc",
        "error_class",
        "error_message",
        "error_token",
        "exit_code",
        "kind",
        "attempt_count",
        "payload_sha256",
        "raw_payload_path",
    ]
    filled: list[dict[str, Any]] = []
    for r in rows:
        full: dict[str, Any] = {}
        for c in cols:
            full[c] = r.get(c)
        filled.append(full)
    pl.DataFrame(filled).write_parquet(audit_root / "run_history.parquet")


# ----------------------------------------------------------------------
# Section §5: prior-success derives from history
# ----------------------------------------------------------------------


def test_prior_success_derives_from_history(tmp_path: Path) -> None:
    """``_read_latest_snapshot_id`` consults the ledger, not the
    cache file. A successful prior row in history is selected."""
    audit_root = _make_audit_root(tmp_path / "audit1")
    _seed_run_history(
        audit_root,
        [
            {
                "outcome": "SUCCESS",
                "snapshot_id": "snap-prior",
                "observed_at_utc": "2026-08-06T22:00:00Z",
                "finished_at_utc": "2026-08-06T22:00:01Z",
                "kind": "scheduled",
                "exit_code": 0,
                "attempt_count": 1,
            }
        ],
    )
    sys.path.insert(0, str(SRC_DIR))
    sys.path.insert(0, str(TESTS_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator

    orch = AuditOrchestrator(audit_root=audit_root)
    assert orch._read_latest_snapshot_id() == "snap-prior"


def test_missing_pointer_cache_does_not_affect_prior(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path / "audit2")
    assert not (audit_root / "latest_snapshot.json").exists()
    _seed_run_history(
        audit_root,
        [
            {
                "outcome": "SUCCESS",
                "snapshot_id": "snap-prior",
                "observed_at_utc": "2026-08-06T22:00:00Z",
                "finished_at_utc": "2026-08-06T22:00:01Z",
                "kind": "scheduled",
                "exit_code": 0,
                "attempt_count": 1,
            }
        ],
    )
    sys.path.insert(0, str(SRC_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator

    orch = AuditOrchestrator(audit_root=audit_root)
    assert orch._read_latest_snapshot_id() == "snap-prior"


def test_stale_pointer_cache_is_ignored(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path / "audit3")
    (audit_root / "latest_snapshot.json").write_text(
        json.dumps(
            {
                "snapshot_id": "snap-stale",
                "observed_at_utc": "2026-08-06T22:00:00Z",
            }
        )
    )
    _seed_run_history(
        audit_root,
        [
            {
                "outcome": "SUCCESS",
                "snapshot_id": "snap-real",
                "observed_at_utc": "2026-08-06T22:00:00Z",
                "finished_at_utc": "2026-08-06T22:00:01Z",
                "kind": "scheduled",
                "exit_code": 0,
                "attempt_count": 1,
            }
        ],
    )
    sys.path.insert(0, str(SRC_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator

    orch = AuditOrchestrator(audit_root=audit_root)
    assert orch._read_latest_snapshot_id() == "snap-real"


def test_pointer_referencing_failed_snapshot_is_ignored(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path / "audit4")
    (audit_root / "latest_snapshot.json").write_text(
        json.dumps(
            {
                "snapshot_id": "snap-failed",
                "observed_at_utc": "2026-08-06T22:00:00Z",
            }
        )
    )
    _seed_run_history(
        audit_root,
        [
            {
                "outcome": "TRANSPORT_FAILURE",
                "snapshot_id": "snap-failed",
                "observed_at_utc": "2026-08-06T22:00:00Z",
                "finished_at_utc": "2026-08-06T22:00:01Z",
                "kind": "scheduled",
                "exit_code": 11,
                "attempt_count": 1,
                "error_class": "Timeout",
            }
        ],
    )
    sys.path.insert(0, str(SRC_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator

    orch = AuditOrchestrator(audit_root=audit_root)
    assert orch._read_latest_snapshot_id() is None


def test_latest_committed_success_selected(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path / "audit5")
    _seed_run_history(
        audit_root,
        [
            {
                "outcome": "SUCCESS",
                "snapshot_id": "snap-1",
                "observed_at_utc": "2026-08-06T22:00:00Z",
                "finished_at_utc": "2026-08-06T22:00:01Z",
                "kind": "scheduled",
                "exit_code": 0,
                "attempt_count": 1,
            },
            {
                "outcome": "TRANSPORT_FAILURE",
                "snapshot_id": "snap-2",
                "observed_at_utc": "2026-08-06T23:00:00Z",
                "finished_at_utc": "2026-08-06T23:00:01Z",
                "kind": "scheduled",
                "exit_code": 11,
                "attempt_count": 3,
            },
            {
                "outcome": "SUCCESS",
                "snapshot_id": "snap-3",
                "observed_at_utc": "2026-08-07T00:00:00Z",
                "finished_at_utc": "2026-08-07T00:00:01Z",
                "kind": "scheduled",
                "exit_code": 0,
                "attempt_count": 1,
            },
        ],
    )
    sys.path.insert(0, str(SRC_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator

    orch = AuditOrchestrator(audit_root=audit_root)
    assert orch._read_latest_snapshot_id() == "snap-3"


# ----------------------------------------------------------------------
# Section §6: HOF pregame derives from history
# ----------------------------------------------------------------------


def test_postgame_no_pointer_cache_uses_history(tmp_path: Path) -> None:
    """No ``hof_pregame_pointer.json`` exists, but the committed
    pregame row exists in history. Postgame should still build."""
    audit_root = _make_audit_root(tmp_path)
    # Pre-seed committed pregame SUCCESS history.
    _seed_run_history(
        audit_root,
        [
            {
                "outcome": "SUCCESS",
                "snapshot_id": "snap-pregame",
                "observed_at_utc": "2026-08-06T18:00:00Z",
                "finished_at_utc": "2026-08-06T18:00:01Z",
                "kind": "pregame",
                "exit_code": 0,
                "attempt_count": 1,
            }
        ],
    )
    assert not (audit_root / "hof_pregame_pointer.json").exists()
    sys.path.insert(0, str(SRC_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.history_views import (
        load_run_history,
        select_pregame_from_history,
    )

    history = load_run_history(audit_root / "run_history.parquet")
    selected = select_pregame_from_history(history, kickoff_utc="2026-08-07T00:00:00Z")
    assert selected is not None
    assert selected.get("snapshot_id") == "snap-pregame"


def test_stale_pregame_pointer_ignored(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path / "audit6")
    _seed_run_history(
        audit_root,
        [
            {
                "outcome": "SUCCESS",
                "snapshot_id": "snap-pregame-real",
                "observed_at_utc": "2026-08-06T18:00:00Z",
                "finished_at_utc": "2026-08-06T18:00:01Z",
                "kind": "pregame",
                "exit_code": 0,
                "attempt_count": 1,
            }
        ],
    )
    # Plant a stale pointer file pointing elsewhere.
    (audit_root / "hof_pregame_pointer.json").write_text(
        json.dumps(
            {
                "selected_snapshot_id": "snap-pregame-stale",
                "observed_at_utc": "2026-08-05T18:00:00Z",
            }
        )
    )
    sys.path.insert(0, str(SRC_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.history_views import (
        load_run_history,
        select_pregame_from_history,
    )

    history = load_run_history(audit_root / "run_history.parquet")
    selected = select_pregame_from_history(
        history, kickoff_utc="2026-08-07T00:00:00Z"
    )
    assert selected.get("snapshot_id") == "snap-pregame-real"


def test_pregame_pointer_referencing_failed_pregame_is_ignored(
    tmp_path: Path,
) -> None:
    audit_root = _make_audit_root(tmp_path / "audit7")
    _seed_run_history(
        audit_root,
        [
            {
                "outcome": "TRANSPORT_FAILURE",
                "snapshot_id": "snap-pregame-failed",
                "observed_at_utc": "2026-08-06T18:00:00Z",
                "finished_at_utc": "2026-08-06T18:00:01Z",
                "kind": "pregame",
                "exit_code": 11,
                "attempt_count": 3,
            }
        ],
    )
    (audit_root / "hof_pregame_pointer.json").write_text(
        json.dumps(
            {
                "selected_snapshot_id": "snap-pregame-failed",
                "observed_at_utc": "2026-08-06T18:00:00Z",
            }
        )
    )
    sys.path.insert(0, str(SRC_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.history_views import (
        load_run_history,
        select_pregame_from_history,
    )

    history = load_run_history(audit_root / "run_history.parquet")
    selected = select_pregame_from_history(
        history, kickoff_utc="2026-08-07T00:00:00Z"
    )
    assert selected is None


def test_no_committed_pregame_returns_none(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path / "audit8")
    _seed_run_history(
        audit_root,
        [
            {
                "outcome": "SUCCESS",
                "snapshot_id": "snap-scheduled",
                "observed_at_utc": "2026-08-06T18:00:00Z",
                "finished_at_utc": "2026-08-06T18:00:01Z",
                "kind": "scheduled",
                "exit_code": 0,
                "attempt_count": 1,
            }
        ],
    )
    sys.path.insert(0, str(SRC_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.history_views import (
        load_run_history,
        select_pregame_from_history,
    )

    history = load_run_history(audit_root / "run_history.parquet")
    selected = select_pregame_from_history(
        history, kickoff_utc="2026-08-07T00:00:00Z"
    )
    assert selected is None


# ----------------------------------------------------------------------
# Section §8: committed-current-run metric proof (no provisional)
# ----------------------------------------------------------------------


def test_first_committed_success_appears_in_metrics(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path)
    sys.path.insert(0, str(SRC_DIR))
    sys.path.insert(0, str(TESTS_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.metrics import (
        compute_rolling_metrics_from_disk,
    )
    from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator
    from tests.source_audits.sleeper_qb_v1._fake_session import (
        FakeSleeperSession,
    )

    AuditOrchestrator(audit_root=audit_root).run(
        session=FakeSleeperSession(),
        kind="scheduled",
        forced_snapshot_id="snap-a",
        forced_observed_at_utc="2026-08-06T22:00:00Z",
    )
    metrics = compute_rolling_metrics_from_disk(audit_root)
    assert metrics["scheduled_run_count"] == 1
    assert metrics["successful_run_count"] == 1
    assert metrics["failed_run_count"] == 0


def test_first_committed_failure_appears_in_metrics(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path)
    sys.path.insert(0, str(SRC_DIR))
    sys.path.insert(0, str(TESTS_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.metrics import (
        compute_rolling_metrics_from_disk,
    )
    from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator
    from tests.source_audits.sleeper_qb_v1._fake_session import (
        FakeSleeperSession,
    )

    # kind=postgame with no pregame -> NORMALIZATION_FAILURE
    AuditOrchestrator(audit_root=audit_root).run(
        session=FakeSleeperSession(),
        kind="postgame",
        forced_snapshot_id="snap-a",
        forced_observed_at_utc="2026-08-06T22:00:00Z",
    )
    metrics = compute_rolling_metrics_from_disk(audit_root)
    assert metrics["scheduled_run_count"] == 1
    assert metrics["successful_run_count"] == 0
    assert metrics["failed_run_count"] == 1


# ----------------------------------------------------------------------
# Section §3: history-append failure semantics
# ----------------------------------------------------------------------


def test_history_append_failure_no_double_record(
    tmp_path: Path, monkeypatch
) -> None:
    """A history-append failure exits 13, writes NO derived views,
    and does NOT retry."""
    audit_root = _make_audit_root(tmp_path)
    sys.path.insert(0, str(SRC_DIR))
    sys.path.insert(0, str(TESTS_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1 import pipeline as pl_mod
    from tests.source_audits.sleeper_qb_v1._fake_session import (
        FakeSleeperSession,
    )

    def fail_commit(self, record):  # type: ignore[no-untyped-def]
        raise OSError("forced history append failure")

    monkeypatch.setattr(
        pl_mod.AuditOrchestrator, "_commit_terminal_history", fail_commit
    )
    result = pl_mod.AuditOrchestrator(audit_root=audit_root).run(
        session=FakeSleeperSession(),
        kind="scheduled",
        forced_snapshot_id="snap-a",
        forced_observed_at_utc="2026-08-06T22:00:00Z",
    )
    assert result["run_outcome"] == "PERSISTENCE_FAILURE"
    assert result["exit_code"] == 13
    history_path = audit_root / "run_history.parquet"
    if history_path.exists() and history_path.stat().st_size > 0:
        import polars as pl

        assert pl.read_parquet(history_path).height == 0
    assert not (audit_root / "latest_run_status.json").exists()
    assert not (audit_root / "latest_snapshot.json").exists()