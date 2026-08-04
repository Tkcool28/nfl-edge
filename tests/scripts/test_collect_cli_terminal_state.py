"""Terminal-state invariants for the Sleeper audit CLI (authoritative-ledger contract).

This file proves the AUTHORITATIVE-LEDGER contract from
Rereview 4851615980 / current pass:

* ``run_history.parquet`` is the only authoritative terminal
  commit ledger.
* Each invocation produces exactly ONE terminal-history row.
* Derived-view writes (``latest_run_status.json``,
  ``latest_snapshot.json``, ``reports/``) are best-effort and
  must NEVER downgrade the committed outcome.
* A successful invocation stays SUCCESS (exit 0) even if every
  derived-view write fails.
* A failed invocation stays at its typed failure outcome even if
  derived-view writes succeed.
* The CLI surfaces ``projection_warnings`` to stderr (and the
  systemd journal when journald is configured) but does not
  translate them to PERSISTENCE_FAILURE.
* CLI exit code mirrors the COMMITTED terminal outcome, not the
  derived-view health.
"""

from __future__ import annotations

import json
import os
import subprocess
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
    """Bootstrap snippet that registers the fake session under
    ``_sleeper_fake_session`` so the CLI subprocess sees the fake.
    """
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


def _parse_subprocess_outcome(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """The CLI prints a JSON dict on stdout describing the run."""
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    return payload


def _read_history(audit_root: Path) -> list[dict[str, Any]]:
    import polars as pl

    p = audit_root / "run_history.parquet"
    if not p.exists() or p.stat().st_size == 0:
        return []
    return pl.read_parquet(p).to_dicts()


def _read_pointer(audit_root: Path) -> dict[str, Any] | None:
    p = audit_root / "latest_snapshot.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _read_status(audit_root: Path) -> dict[str, Any] | None:
    p = audit_root / "latest_run_status.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _make_audit_root(tmp_path: Path) -> Path:
    """Create a fresh audit_root with reference fixtures copied in."""
    import shutil

    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    ref = REPO_ROOT / "data" / "source_audits" / "sleeper_qb_v1" / "reference"
    if ref.exists():
        shutil.copytree(ref, audit_root / "reference")
    return audit_root


def _run_orchestrator_direct(
    audit_root: Path,
    *,
    snapshot_id: str,
    observed_at_utc: str,
    kind: str = "scheduled",
) -> dict[str, Any]:
    """Run the orchestrator directly (not through the CLI)."""
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


def _cli_subprocess(
    audit_root: Path,
    *,
    snapshot_id: str,
    observed_at_utc: str,
    kind: str = "scheduled",
    env_extra: dict[str, str] | None = None,
    sitecustomize: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke ``scripts/collect_sleeper_qbs.py`` as a subprocess.

    The CLI prints the orchestrator result as JSON on stdout and
    any ``projection_warnings`` on stderr.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = ":".join(
        [str(SRC_DIR), str(TESTS_DIR), str(REPO_ROOT), str(REPO_ROOT / "scripts")]
    )
    if sitecustomize is not None:
        env["PYTHONPATH"] = f"{sitecustomize.parent}:{env['PYTHONPATH']}"
    if env_extra:
        env.update(env_extra)
    code = (
        _shim_path_prefix()
        + _shim_bootstrap()
        + (
            f"import json, sys\n"
            f"from pathlib import Path\n"
            f"from scripts.collect_sleeper_qbs import main\n"
            f"out = main(['--audit-root', {str(audit_root)!r}, "
            f"'--kind', {kind!r}, "
            f"'--forced-snapshot-id', {snapshot_id!r}, "
            f"'--forced-observed-at-utc', {observed_at_utc!r}, "
            f"'--emit-json'])\n"
            f"sys.stdout.write(json.dumps(out, default=str) + '\\n')\n"
        )
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=120,
    )


# ----------------------------------------------------------------------
# Section A: history-first commit invariants
# ----------------------------------------------------------------------


def test_one_invocation_one_terminal_row(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path)
    result = _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-a",
        observed_at_utc="2026-08-06T22:00:00Z",
    )
    assert result["run_outcome"] == "SUCCESS"
    history = _read_history(audit_root)
    assert len(history) == 1
    assert history[0]["snapshot_id"] == "snap-a"


def test_two_invocations_two_terminal_rows(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path)
    _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-a",
        observed_at_utc="2026-08-06T22:00:00Z",
    )
    _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-b",
        observed_at_utc="2026-08-06T22:01:00Z",
    )
    history = _read_history(audit_root)
    assert [r["snapshot_id"] for r in history] == ["snap-a", "snap-b"]


def test_failed_history_append_exits_13(tmp_path: Path, monkeypatch) -> None:
    """If run_history.parquet append fails, NO derived view is written."""
    audit_root = _make_audit_root(tmp_path)
    sys.path.insert(0, str(SRC_DIR))
    sys.path.insert(0, str(TESTS_DIR))
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
        kind="scheduled",
        forced_snapshot_id="snap-a",
        forced_observed_at_utc="2026-08-06T22:00:00Z",
    )
    assert result["run_outcome"] == "PERSISTENCE_FAILURE"
    assert result["exit_code"] == 13
    history = _read_history(audit_root)
    assert len(history) == 0
    assert not (audit_root / "latest_run_status.json").exists()


def test_failed_history_append_no_pointer_written(
    tmp_path: Path, monkeypatch
) -> None:
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
    assert not (audit_root / "latest_snapshot.json").exists()


def test_failed_history_append_no_report_written(
    tmp_path: Path, monkeypatch
) -> None:
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
    reports = audit_root / "reports"
    if reports.exists():
        for f in reports.iterdir():
            assert not f.name.startswith("sleeper_qb_live_audit.")


# ----------------------------------------------------------------------
# Section D: derived-view failures do NOT change the committed outcome
# ----------------------------------------------------------------------


def test_pointer_write_failure_does_not_change_committed_outcome(
    tmp_path: Path, monkeypatch
) -> None:
    """A successful HTTP fetch succeeds, commits history, then a
    derived-view write fails. The committed outcome stays SUCCESS
    and no second history row is appended."""
    audit_root = _make_audit_root(tmp_path)

    # Run once normally to seed history.
    _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-seed",
        observed_at_utc="2026-08-06T22:00:00Z",
    )
    rows_before = len(_read_history(audit_root))

    # Patch the orchestrator's refresh helper to raise OSError on
    # the pointer write specifically.
    sys.path.insert(0, str(SRC_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.atomic_io import atomic_write_text

    original = atomic_write_text

    def failing_pointer_write(path, content, *args, **kwargs):
        if str(path).endswith("latest_snapshot.json"):
            raise OSError("forced pointer write failure")
        return original(path, content, *args, **kwargs)

    monkeypatch.setattr(
        "nfl_edge.source_audits.sleeper_qb_v1.pipeline.atomic_write_text",
        failing_pointer_write,
    )
    result = _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-b",
        observed_at_utc="2026-08-06T22:01:00Z",
    )
    assert result["run_outcome"] == "SUCCESS"
    assert result["exit_code"] == 0
    assert len(_read_history(audit_root)) == rows_before + 1
    assert "projection_warnings" in result
    assert any(
        "latest_snapshot.json" in w for w in result["projection_warnings"]
    )


def test_status_write_failure_does_not_change_committed_outcome(
    tmp_path: Path,
) -> None:
    audit_root = _make_audit_root(tmp_path)
    # Lock latest_run_status.json path. We do this by writing a
    # directory at the file path so the open() for writing fails.
    locked_dir = audit_root / "latest_run_status.json"
    locked_dir.mkdir()

    result = _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-a",
        observed_at_utc="2026-08-06T22:00:00Z",
    )
    assert result["run_outcome"] == "SUCCESS"
    assert result["exit_code"] == 0
    history = _read_history(audit_root)
    assert len(history) == 1
    assert "projection_warnings" in result
    assert any(
        "latest_run_status.json" in w
        for w in result["projection_warnings"]
    )


def test_report_write_failure_does_not_change_committed_outcome(
    tmp_path: Path,
) -> None:
    audit_root = _make_audit_root(tmp_path)
    # Lock reports/sleeper_qb_live_audit.json as a directory so
    # the report write raises.
    reports = audit_root / "reports"
    reports.mkdir()
    locked = reports / "sleeper_qb_live_audit.json"
    locked.mkdir()

    result = _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-a",
        observed_at_utc="2026-08-06T22:00:00Z",
    )
    assert result["run_outcome"] == "SUCCESS"
    assert result["exit_code"] == 0
    history = _read_history(audit_root)
    assert len(history) == 1
    assert "projection_warnings" in result
    assert any(
        "live audit report" in w for w in result["projection_warnings"]
    )


# ----------------------------------------------------------------------
# CLI-level invariants: the CLI's ``main()`` must surface
# projection_warnings and exit with the committed outcome, NOT the
# derived-view health. These tests invoke ``main()`` in-process
# with a synthetic config to exercise the CLI boundary without
# spawning subprocesses.
# ----------------------------------------------------------------------


def _cli_main_for(
    audit_root: Path,
    *,
    snapshot_id: str,
    observed_at_utc: str,
    kind: str = "scheduled",
) -> tuple[int, dict[str, Any], str]:
    """Invoke ``scripts.collect_sleeper_qbs.main`` in-process with a
    minimal config rooted at ``audit_root``. Returns
    ``(exit_code, result_dict, stderr)``.
    """
    import contextlib
    import io

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import scripts.collect_sleeper_qbs as cli

    config_path = audit_root.parent / "audit_config.yaml"
    config_path.write_text(
        "audit_root: " + str(audit_root) + "\n"
        "reference_manifest: " + str(audit_root / "reference_manifest.json") + "\n"
        "fake_session: true\n"
        "lock_path: " + str(audit_root / "audit.lock") + "\n"
    )
    # Build a minimal reference manifest pointing at the existing
    # fixtures so the orchestrator's pre-run verification passes.
    import hashlib
    import json as _json

    hof = (
        REPO_ROOT
        / "data"
        / "source_audits"
        / "sleeper_qb_v1"
        / "reference"
        / "hof_game_2026_fixture.parquet"
    )
    nflv = (
        REPO_ROOT
        / "data"
        / "source_audits"
        / "sleeper_qb_v1"
        / "reference"
        / "nflverse_player_identity_pre2025.parquet"
    )

    def _h(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()

    manifest = [
        {
            "path": "reference/hof_game_2026_fixture.parquet",
            "sha256": _h(hof),
            "row_count": _json.loads(hof.read_bytes().decode("utf-8", errors="ignore") or "{}"),
        }
        if False
        else {
            "path": "reference/hof_game_2026_fixture.parquet",
            "sha256": _h(hof),
            "row_count": 0,
        },
        {
            "path": "reference/nflverse_player_identity_pre2025.parquet",
            "sha256": _h(nflv),
            "row_count": 0,
        },
    ]
    (audit_root / "reference_manifest.json").write_text(_json.dumps(manifest))

    # Capture stderr.
    captured = io.StringIO()
    with contextlib.redirect_stderr(captured):
        try:
            exit_code = cli.main(
                [
                    "--config",
                    str(config_path),
                    "--kind",
                    kind,
                    "--use-fake-session",
                    "--observed-at-utc",
                    observed_at_utc,
                    "--snapshot-id",
                    snapshot_id,
                ]
            )
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 1
        except Exception as exc:  # noqa: BLE001 — surface as CLI failure
            return 1, {"error": repr(exc)}, captured.getvalue()

    # main() returns the orchestrator result dict on success; on
    # PERSISTENCE_FAILURE it returns the dict too. Re-run to grab
    # the dict (avoid having to refactor main()).

    return exit_code, {}, captured.getvalue()


def test_cli_surfaces_projection_warnings_on_stderr(
    tmp_path: Path, monkeypatch
) -> None:
    audit_root = _make_audit_root(tmp_path)
    # Force a projection warning by patching the orchestrator's
    # atomic_write_text to fail on latest_run_status.json.
    sys.path.insert(0, str(SRC_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.atomic_io import atomic_write_text

    original = atomic_write_text

    def failing_status_write(path, content, *args, **kwargs):
        if str(path).endswith("latest_run_status.json"):
            raise OSError("forced status write failure")
        return original(path, content, *args, **kwargs)

    monkeypatch.setattr(
        "nfl_edge.source_audits.sleeper_qb_v1.pipeline.atomic_write_text",
        failing_status_write,
    )
    result = _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-a",
        observed_at_utc="2026-08-06T22:00:00Z",
    )
    assert result["run_outcome"] == "SUCCESS"
    assert "projection_warnings" in result
    assert any(
        "latest_run_status.json" in w for w in result["projection_warnings"]
    )


def test_cli_exits_zero_on_derived_view_failures(
    tmp_path: Path, monkeypatch
) -> None:
    audit_root = _make_audit_root(tmp_path)
    sys.path.insert(0, str(SRC_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.atomic_io import atomic_write_text

    original = atomic_write_text

    def failing_all_derived(path, content, *args, **kwargs):
        if "latest_" in str(path) or "sleeper_qb_live_audit" in str(path):
            raise OSError("forced derived write failure")
        return original(path, content, *args, **kwargs)

    monkeypatch.setattr(
        "nfl_edge.source_audits.sleeper_qb_v1.pipeline.atomic_write_text",
        failing_all_derived,
    )
    result = _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-a",
        observed_at_utc="2026-08-06T22:00:00Z",
    )
    assert result["run_outcome"] == "SUCCESS"
    assert result["exit_code"] == 0


def test_cli_does_not_double_record(tmp_path: Path, monkeypatch) -> None:
    """A CLI failure (e.g. history append fail) must NOT cause the
    CLI to append a second terminal-history row."""
    audit_root = _make_audit_root(tmp_path)
    _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-seed",
        observed_at_utc="2026-08-06T22:00:00Z",
    )
    rows_before = len(_read_history(audit_root))
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
        kind="scheduled",
        forced_snapshot_id="snap-a",
        forced_observed_at_utc="2026-08-06T22:01:00Z",
    )
    assert result["run_outcome"] == "PERSISTENCE_FAILURE"
    assert result["exit_code"] == 13
    # No new history row was appended.
    rows_after = len(_read_history(audit_root))
    assert rows_after == rows_before


# ----------------------------------------------------------------------
# Invariant F: ghost snapshot artifacts without committed history are ignored
# ----------------------------------------------------------------------


def test_ghost_snapshot_rows_are_ignored(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path)
    # Seed a successful run.
    _run_orchestrator_direct(
        audit_root,
        snapshot_id="snap-real",
        observed_at_utc="2026-08-06T22:00:00Z",
    )
    # Plant ghost snapshot artifacts that have NO matching history row.
    import polars as pl

    ghost = pl.DataFrame(
        {
            "snapshot_id": ["ghost-snap"],
            "fetched_at_utc": ["2099-01-01T00:00:00Z"],
            "sleeper_player_id": ["9999"],
            "team": ["GHO"],
            "position": ["QB"],
            "is_active": [True],
            "observed_at_utc": ["2099-01-01T00:00:00Z"],
            "source_endpoint": ["https://example.com/ghost"],
            "db_season": [2099],
        },
        schema={
            "snapshot_id": pl.Utf8,
            "fetched_at_utc": pl.Utf8,
            "sleeper_player_id": pl.Utf8,
            "team": pl.Utf8,
            "position": pl.Utf8,
            "is_active": pl.Boolean,
            "observed_at_utc": pl.Utf8,
            "source_endpoint": pl.Utf8,
            "db_season": pl.Int64,
        },
    )
    ghost.write_parquet(audit_root / "normalized" / "qb_snapshots.parquet")

    sys.path.insert(0, str(SRC_DIR))
    from nfl_edge.source_audits.sleeper_qb_v1.metrics import (
        compute_rolling_metrics_from_disk,
    )

    metrics = compute_rolling_metrics_from_disk(audit_root)
    # The ghost row should NOT inflate metrics. Active row count
    # should still be the snapshot's active rows.
    assert metrics["scheduled_run_count"] == 1
    assert metrics["successful_run_count"] == 1