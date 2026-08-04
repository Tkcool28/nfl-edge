"""Final-ordering closure tests for the Sleeper audit.

These tests prove the two remaining defects called out in review
``4858328151`` are closed:

1. The live rolling report includes the current invocation's
   provisional terminal outcome (Rereview §2).

2. ``latest_snapshot.json`` is written **before** terminal
   history/status are committed; a pointer-write failure
   downgrades the outcome to PERSISTENCE_FAILURE with exactly
   one terminal-history row and leaves the prior pointer file
   byte-identical (Rereview §3).

The tests use ``--use-fake-session`` and inject failures via a
``sitecustomize.py`` shim that wraps ``atomic_append_run_history``,
``atomic_write_text``, and the orchestrator's pointer-write path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SRC_DIR = REPO_ROOT / "src"
TESTS_DIR = REPO_ROOT / "tests"

SHIPPED_REFERENCE_DIR = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "source_audits"
    / "sleeper_qb_v1"
    / "reference"
)


def _stage_reference_into_audit_root(audit_root: Path) -> Path:
    import hashlib
    import shutil

    ref_dir = audit_root / "reference"
    ref_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = ref_dir / "manifest.json"
    artifacts: list[dict[str, object]] = []
    for name in (
        "hof_game_2026_fixture.parquet",
        "nflverse_player_identity_pre2025.parquet",
    ):
        src = SHIPPED_REFERENCE_DIR / name
        dst = ref_dir / name
        shutil.copyfile(src, dst)
        sha = hashlib.sha256(dst.read_bytes()).hexdigest()
        rc = pl.read_parquet(dst).height
        artifacts.append({"path": name, "sha256": sha, "row_count": rc})
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "description": "Test-clone manifest for the Sleeper audit.",
                "artifacts": artifacts,
            }
        )
    )
    return manifest_path


def _write_config(
    audit_root: Path,
    config_path: Path,
    *,
    reference_manifest: Path,
) -> None:
    lines = [
        f"audit_root: {audit_root.as_posix()}",
        "endpoint: https://api.sleeper.app/v1/players/nfl",
        "staleness_threshold_seconds: 21600",
        f"reference_manifest: {reference_manifest.as_posix()}",
    ]
    config_path.write_text("\n".join(lines) + "\n")


def _read_history(audit_root: Path) -> pl.DataFrame:
    path = audit_root / "run_history.parquet"
    if not path.exists():
        return pl.DataFrame()
    return pl.read_parquet(path)


def _read_status(audit_root: Path) -> dict[str, object] | None:
    path = audit_root / "latest_run_status.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _read_pointer(audit_root: Path) -> dict[str, object] | None:
    path = audit_root / "latest_snapshot.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _read_report_metrics(audit_root: Path) -> dict[str, object]:
    """Read the live-audit JSON report and return its metrics block."""
    path = audit_root / "reports" / "sleeper_qb_live_audit.json"
    return json.loads(path.read_text())["metrics"]


def _parse_subprocess_outcome(proc: subprocess.CompletedProcess) -> dict[str, object]:
    if not proc.stdout.strip():
        return {"outcome": None, "exit_code": proc.returncode}
    line = proc.stdout.strip().splitlines()[-1]
    return json.loads(line)


def _shim_path_prefix() -> str:
    return (
        "import sys\n"
        f"sys.path.insert(0, {str(SRC_DIR)!r})\n"
        f"sys.path.insert(0, {str(TESTS_DIR)!r})\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
    )


def _shim_bootstrap() -> str:
    return (
        "import sys, importlib.util\n"
        f"_spec = importlib.util.spec_from_file_location(\n"
        f"    '_sleeper_fake_session',\n"
        f"    {str(TESTS_DIR / 'source_audits' / 'sleeper_qb_v1' / '_fake_session.py')!r},\n"
        f")\n"
        f"_mod = importlib.util.module_from_spec(_spec)\n"
        f"_spec.loader.exec_module(_mod)\n"
        f"sys.modules['_sleeper_fake_session'] = _mod\n"
    )


def _shim_full() -> str:
    return _shim_path_prefix() + _shim_bootstrap()


# ---------------------------------------------------------------------------
# §2 — Current-run-inclusive rolling metrics
# ---------------------------------------------------------------------------


def test_first_success_appears_in_its_own_report(tmp_path: Path) -> None:
    """A first successful run's live report must show the current
    invocation in the metrics (1 success, 0 failures, 1 scheduled).
    """
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    sys.path.insert(0, str(TESTS_DIR))
    sys.path.insert(0, str(SRC_DIR))
    from _sleeper_fake_session import FakeSleeperSession

    from nfl_edge.source_audits.sleeper_qb_v1.pipeline import (
        AuditOrchestrator,
    )
    result = AuditOrchestrator(audit_root=audit_root).run(
        session=FakeSleeperSession(),
        kind="scheduled",
        forced_snapshot_id="snap-first-success",
        forced_observed_at_utc="2026-08-06T22:00:00+00:00",
    )
    assert result["run_outcome"] == "SUCCESS"
    metrics = _read_report_metrics(audit_root)
    assert metrics["scheduled_run_count"] == 1, metrics
    assert metrics["successful_run_count"] == 1, metrics
    assert metrics["failed_run_count"] == 0, metrics
    assert metrics["attempted_fetch_count"] == metrics[
        "successful_attempt_count"
    ] + metrics["failed_attempt_count"]


def test_first_hof_failure_appears_in_its_own_report(tmp_path: Path) -> None:
    """A first HOF-failed run's live report must show the current
    invocation in the metrics (0 successes, 1 failure, 1 scheduled).
    """
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    sys.path.insert(0, str(TESTS_DIR))
    sys.path.insert(0, str(SRC_DIR))
    # Stage reference fixtures so the orchestrator can construct.
    import hashlib
    import shutil
    ref_dir = audit_root / "reference"
    ref_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "hof_game_2026_fixture.parquet",
        "nflverse_player_identity_pre2025.parquet",
    ):
        src = SHIPPED_REFERENCE_DIR / name
        dst = ref_dir / name
        shutil.copyfile(src, dst)
    from nfl_edge.source_audits.sleeper_qb_v1.atomic_io import (
        ReferenceArtifact,
    )
    manifest_artifacts: list[ReferenceArtifact] = []
    for name in (
        "hof_game_2026_fixture.parquet",
        "nflverse_player_identity_pre2025.parquet",
    ):
        dst = ref_dir / name
        sha = hashlib.sha256(dst.read_bytes()).hexdigest()
        rc = pl.read_parquet(dst).height
        manifest_artifacts.append(
            ReferenceArtifact(path=name, sha256=sha, row_count=rc)
        )
    from _sleeper_fake_session import FakeSleeperSession

    from nfl_edge.source_audits.sleeper_qb_v1.pipeline import (
        AuditOrchestrator,
    )
    orchestrator = AuditOrchestrator(
        audit_root=audit_root,
        reference_manifest=manifest_artifacts,
    )
    # postgame with no pregame pointer -> HOF returns
    # NORMALIZATION_FAILURE; the live report must include the
    # current failed run.
    result = orchestrator.run(
        session=FakeSleeperSession(),
        kind="postgame",
    )
    assert result["run_outcome"] == "NORMALIZATION_FAILURE", (
        f"got {result['run_outcome']!r}"
    )
    metrics = _read_report_metrics(audit_root)
    assert metrics["scheduled_run_count"] == 1, metrics
    assert metrics["successful_run_count"] == 0, metrics
    assert metrics["failed_run_count"] == 1, metrics


def test_prior_success_plus_current_failure_reconciles(tmp_path: Path) -> None:
    """One prior SUCCESS plus one current HOF failure must show
    in the metrics as 1 success, 1 failure, 2 scheduled.
    """
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    sys.path.insert(0, str(TESTS_DIR))
    sys.path.insert(0, str(SRC_DIR))
    import hashlib
    import shutil
    ref_dir = audit_root / "reference"
    ref_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "hof_game_2026_fixture.parquet",
        "nflverse_player_identity_pre2025.parquet",
    ):
        src = SHIPPED_REFERENCE_DIR / name
        dst = ref_dir / name
        shutil.copyfile(src, dst)
    from nfl_edge.source_audits.sleeper_qb_v1.atomic_io import (
        ReferenceArtifact,
    )
    manifest_artifacts: list[ReferenceArtifact] = []
    for name in (
        "hof_game_2026_fixture.parquet",
        "nflverse_player_identity_pre2025.parquet",
    ):
        dst = ref_dir / name
        sha = hashlib.sha256(dst.read_bytes()).hexdigest()
        rc = pl.read_parquet(dst).height
        manifest_artifacts.append(
            ReferenceArtifact(path=name, sha256=sha, row_count=rc)
        )
    from _sleeper_fake_session import FakeSleeperSession

    from nfl_edge.source_audits.sleeper_qb_v1.pipeline import (
        AuditOrchestrator,
    )
    orchestrator = AuditOrchestrator(
        audit_root=audit_root,
        reference_manifest=manifest_artifacts,
    )
    # Prior SUCCESS
    orchestrator.run(
        session=FakeSleeperSession(),
        kind="scheduled",
        forced_snapshot_id="snap-prior-success",
        forced_observed_at_utc="2026-08-06T22:00:00+00:00",
    )
    prior_history = _read_history(audit_root)
    assert prior_history.height == 1
    # Current HOF failure (postgame without pregame pointer)
    result = orchestrator.run(
        session=FakeSleeperSession(),
        kind="postgame",
    )
    assert result["run_outcome"] == "NORMALIZATION_FAILURE"
    metrics = _read_report_metrics(audit_root)
    assert metrics["scheduled_run_count"] == 2, metrics
    assert metrics["successful_run_count"] == 1, metrics
    assert metrics["failed_run_count"] == 1, metrics
    # attempt reconciliation still holds
    assert metrics["attempted_fetch_count"] == (
        metrics["successful_attempt_count"]
        + metrics["failed_attempt_count"]
    )


# ---------------------------------------------------------------------------
# §3 — latest_snapshot write failure
# ---------------------------------------------------------------------------


def test_pointer_write_failure_returns_exit_13(tmp_path: Path) -> None:
    """A forced failure of the latest_snapshot.json write must
    surface as exit code 13 (PERSISTENCE_FAILURE).
    """
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    sys.path.insert(0, str(TESTS_DIR))
    sys.path.insert(0, str(SRC_DIR))
    from _sleeper_fake_session import FakeSleeperSession

    from nfl_edge.source_audits.sleeper_qb_v1.pipeline import (
        AuditOrchestrator,
    )
    AuditOrchestrator(audit_root=audit_root).run(
        session=FakeSleeperSession(),
        kind="scheduled",
        forced_snapshot_id="snap-prior",
        forced_observed_at_utc="2026-08-06T22:00:00+00:00",
    )
    # Inject: every atomic_write_text call targeting
    # latest_snapshot.json raises OSError. The report writes
    # (which also go through atomic_write_text but target
    # sleeper_qb_live_audit.*) are still allowed.
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "\n".join(
            [
                "from nfl_edge.source_audits.sleeper_qb_v1 import atomic_io",
                "_orig = atomic_io.atomic_write_text",
                "def _patched(path, data):",
                "    s = str(path)",
                "    if s.endswith('latest_snapshot.json'):",
                "        raise OSError('injected: pointer write failed')",
                "    return _orig(path, data)",
                "atomic_io.atomic_write_text = _patched",
                "import nfl_edge.source_audits.sleeper_qb_v1.pipeline as _p",
                "_p.atomic_write_text = _patched",
            ]
        )
        + "\n"
    )
    code = (
        _shim_full()
        + "from _sleeper_fake_session import FakeSleeperSession\n"
        "from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator\n"
        f"o = AuditOrchestrator(audit_root={str(audit_root)!r})\n"
        "r = o.run(session=FakeSleeperSession(), kind='scheduled',\n"
        "          forced_snapshot_id='snap-pointer-fail',\n"
        "          forced_observed_at_utc='2026-08-07T05:00:00+00:00')\n"
        "import json; print(json.dumps({'outcome': r['run_outcome'], 'exit_code': r['exit_code']}))\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{tmp_path}:{SRC_DIR}:{TESTS_DIR}:{REPO_ROOT}:"
        f"{env.get('PYTHONPATH', '')}"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=60,
    )
    outcome = _parse_subprocess_outcome(proc)
    assert outcome["exit_code"] == 13, (
        f"rc={proc.returncode} stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )


def test_pointer_failure_appends_exactly_one_row(tmp_path: Path) -> None:
    """A forced latest_snapshot.json write failure must append
    exactly one terminal-history row for the invocation.
    """
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    sys.path.insert(0, str(TESTS_DIR))
    sys.path.insert(0, str(SRC_DIR))
    from _sleeper_fake_session import FakeSleeperSession

    from nfl_edge.source_audits.sleeper_qb_v1.pipeline import (
        AuditOrchestrator,
    )
    AuditOrchestrator(audit_root=audit_root).run(
        session=FakeSleeperSession(),
        kind="scheduled",
        forced_snapshot_id="snap-prior",
        forced_observed_at_utc="2026-08-06T22:00:00+00:00",
    )
    prior_history = _read_history(audit_root)
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "\n".join(
            [
                "from nfl_edge.source_audits.sleeper_qb_v1 import atomic_io",
                "_orig = atomic_io.atomic_write_text",
                "def _patched(path, data):",
                "    if str(path).endswith('latest_snapshot.json'):",
                "        raise OSError('injected')",
                "    return _orig(path, data)",
                "atomic_io.atomic_write_text = _patched",
                "import nfl_edge.source_audits.sleeper_qb_v1.pipeline as _p",
                "_p.atomic_write_text = _patched",
            ]
        )
        + "\n"
    )
    code = (
        _shim_full()
        + "from _sleeper_fake_session import FakeSleeperSession\n"
        "from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator\n"
        f"o = AuditOrchestrator(audit_root={str(audit_root)!r})\n"
        "r = o.run(session=FakeSleeperSession(), kind='scheduled',\n"
        "          forced_snapshot_id='snap-pointer-fail-2',\n"
        "          forced_observed_at_utc='2026-08-07T05:00:00+00:00')\n"
        "import json; print(json.dumps({'outcome': r['run_outcome'], 'exit_code': r['exit_code']}))\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{tmp_path}:{SRC_DIR}:{TESTS_DIR}:{REPO_ROOT}:"
        f"{env.get('PYTHONPATH', '')}"
    )
    proc = subprocess.run(  # noqa: F841 — retained for debugging
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=60,
    )
    new_history = _read_history(audit_root)
    assert new_history.height == prior_history.height + 1, (
        f"history grew by {new_history.height - prior_history.height}; "
        "expected exactly 1"
    )
    last = new_history.row(new_history.height - 1, named=True)
    assert last["outcome"] == "PERSISTENCE_FAILURE", (
        f"row outcome={last['outcome']!r}; expected PERSISTENCE_FAILURE"
    )


def test_pointer_failure_status_is_persistence_failure(tmp_path: Path) -> None:
    """After a forced latest_snapshot.json write failure, the
    final ``latest_run_status.json`` outcome is PERSISTENCE_FAILURE.
    """
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    sys.path.insert(0, str(TESTS_DIR))
    sys.path.insert(0, str(SRC_DIR))
    from _sleeper_fake_session import FakeSleeperSession

    from nfl_edge.source_audits.sleeper_qb_v1.pipeline import (
        AuditOrchestrator,
    )
    AuditOrchestrator(audit_root=audit_root).run(
        session=FakeSleeperSession(),
        kind="scheduled",
        forced_snapshot_id="snap-prior",
        forced_observed_at_utc="2026-08-06T22:00:00+00:00",
    )
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "\n".join(
            [
                "from nfl_edge.source_audits.sleeper_qb_v1 import atomic_io",
                "_orig = atomic_io.atomic_write_text",
                "def _patched(path, data):",
                "    if str(path).endswith('latest_snapshot.json'):",
                "        raise OSError('injected')",
                "    return _orig(path, data)",
                "atomic_io.atomic_write_text = _patched",
                "import nfl_edge.source_audits.sleeper_qb_v1.pipeline as _p",
                "_p.atomic_write_text = _patched",
            ]
        )
        + "\n"
    )
    code = (
        _shim_full()
        + "from _sleeper_fake_session import FakeSleeperSession\n"
        "from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator\n"
        f"o = AuditOrchestrator(audit_root={str(audit_root)!r})\n"
        "r = o.run(session=FakeSleeperSession(), kind='scheduled',\n"
        "          forced_snapshot_id='snap-pointer-fail-3',\n"
        "          forced_observed_at_utc='2026-08-07T05:00:00+00:00')\n"
        "import json; print(json.dumps({'outcome': r['run_outcome'], 'exit_code': r['exit_code']}))\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{tmp_path}:{SRC_DIR}:{TESTS_DIR}:{REPO_ROOT}:"
        f"{env.get('PYTHONPATH', '')}"
    )
    proc = subprocess.run(  # noqa: F841 — retained for debugging
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=60,
    )
    status = _read_status(audit_root)
    assert status is not None
    assert status["outcome"] == "PERSISTENCE_FAILURE", (
        f"status outcome={status['outcome']!r}; expected PERSISTENCE_FAILURE"
    )


def test_pointer_failure_no_success_row_for_invocation(tmp_path: Path) -> None:
    """A forced latest_snapshot.json write failure must not leave
    a SUCCESS row for the invocation in run_history.parquet.
    """
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    sys.path.insert(0, str(TESTS_DIR))
    sys.path.insert(0, str(SRC_DIR))
    from _sleeper_fake_session import FakeSleeperSession

    from nfl_edge.source_audits.sleeper_qb_v1.pipeline import (
        AuditOrchestrator,
    )
    AuditOrchestrator(audit_root=audit_root).run(
        session=FakeSleeperSession(),
        kind="scheduled",
        forced_snapshot_id="snap-prior",
        forced_observed_at_utc="2026-08-06T22:00:00+00:00",
    )
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "\n".join(
            [
                "from nfl_edge.source_audits.sleeper_qb_v1 import atomic_io",
                "_orig = atomic_io.atomic_write_text",
                "def _patched(path, data):",
                "    if str(path).endswith('latest_snapshot.json'):",
                "        raise OSError('injected')",
                "    return _orig(path, data)",
                "atomic_io.atomic_write_text = _patched",
                "import nfl_edge.source_audits.sleeper_qb_v1.pipeline as _p",
                "_p.atomic_write_text = _patched",
            ]
        )
        + "\n"
    )
    code = (
        _shim_full()
        + "from _sleeper_fake_session import FakeSleeperSession\n"
        "from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator\n"
        f"o = AuditOrchestrator(audit_root={str(audit_root)!r})\n"
        "r = o.run(session=FakeSleeperSession(), kind='scheduled',\n"
        "          forced_snapshot_id='snap-no-success-row',\n"
        "          forced_observed_at_utc='2026-08-07T05:00:00+00:00')\n"
        "import json; print(json.dumps({'outcome': r['run_outcome'], 'exit_code': r['exit_code']}))\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{tmp_path}:{SRC_DIR}:{TESTS_DIR}:{REPO_ROOT}:"
        f"{env.get('PYTHONPATH', '')}"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=60,
    )
    history = _read_history(audit_root)
    # The current invocation is snap-no-success-row; no SUCCESS
    # row may exist for that snapshot_id.
    bad = history.filter(pl.col("snapshot_id") == "snap-no-success-row")
    assert bad.height == 1, (
        f"expected exactly one row for snap-no-success-row, got {bad.height}"
    )
    row = bad.row(0, named=True)
    assert row["outcome"] != "SUCCESS", (
        f"snap-no-success-row has outcome={row['outcome']!r}; "
        "must not be SUCCESS"
    )


def test_pointer_failure_prior_pointer_byte_identical(tmp_path: Path) -> None:
    """A forced latest_snapshot.json write failure must leave the
    prior ``latest_snapshot.json`` content byte-identical (the
    atomic rename failed before completion).
    """
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    sys.path.insert(0, str(TESTS_DIR))
    sys.path.insert(0, str(SRC_DIR))
    from _sleeper_fake_session import FakeSleeperSession

    from nfl_edge.source_audits.sleeper_qb_v1.pipeline import (
        AuditOrchestrator,
    )
    AuditOrchestrator(audit_root=audit_root).run(
        session=FakeSleeperSession(),
        kind="scheduled",
        forced_snapshot_id="snap-prior",
        forced_observed_at_utc="2026-08-06T22:00:00+00:00",
    )
    prior_pointer_bytes = (audit_root / "latest_snapshot.json").read_bytes()
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "\n".join(
            [
                "from nfl_edge.source_audits.sleeper_qb_v1 import atomic_io",
                "_orig = atomic_io.atomic_write_text",
                "def _patched(path, data):",
                "    if str(path).endswith('latest_snapshot.json'):",
                "        raise OSError('injected')",
                "    return _orig(path, data)",
                "atomic_io.atomic_write_text = _patched",
                "import nfl_edge.source_audits.sleeper_qb_v1.pipeline as _p",
                "_p.atomic_write_text = _patched",
            ]
        )
        + "\n"
    )
    code = (
        _shim_full()
        + "from _sleeper_fake_session import FakeSleeperSession\n"
        "from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator\n"
        f"o = AuditOrchestrator(audit_root={str(audit_root)!r})\n"
        "r = o.run(session=FakeSleeperSession(), kind='scheduled',\n"
        "          forced_snapshot_id='snap-pointer-fail-4',\n"
        "          forced_observed_at_utc='2026-08-07T05:00:00+00:00')\n"
        "import json; print(json.dumps({'outcome': r['run_outcome'], 'exit_code': r['exit_code']}))\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{tmp_path}:{SRC_DIR}:{TESTS_DIR}:{REPO_ROOT}:"
        f"{env.get('PYTHONPATH', '')}"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=60,
    )
    after_pointer_bytes = (audit_root / "latest_snapshot.json").read_bytes()
    assert after_pointer_bytes == prior_pointer_bytes, (
        "latest_snapshot.json was modified despite pointer write failure"
    )


# ---------------------------------------------------------------------------
# §4 — CLI no-double-record after orchestrator-finalized pointer failure
# ---------------------------------------------------------------------------


def test_cli_does_not_append_second_row_after_pointer_failure(
    tmp_path: Path,
) -> None:
    """If the orchestrator returns PERSISTENCE_FAILURE for a
    pointer-write failure, the CLI must NOT call _terminate()
    (which would attempt a second history append).
    """
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    config_path = tmp_path / "cfg.yaml"
    manifest_path = _stage_reference_into_audit_root(audit_root)
    _write_config(
        audit_root, config_path, reference_manifest=manifest_path
    )
    # Run a prior successful run so the prior pointer is set.
    sitecustomize_init = tmp_path / "sitecustomize.py"
    sitecustomize_init.write_text("")  # no-op shim
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{tmp_path}:{SRC_DIR}:{TESTS_DIR}:{REPO_ROOT}:"
        f"{env.get('PYTHONPATH', '')}"
    )
    r0 = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "collect_sleeper_qbs.py"),
            "--config",
            str(config_path),
            "--use-fake-session",
            "--kind=scheduled",
            "--observed-at-utc=2026-08-06T22:00:00Z",
            "--snapshot-id=snap-cli-prior",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=60,
    )
    assert r0.returncode == 0, f"prior rc={r0.returncode}"
    prior_history = _read_history(audit_root)
    # Now run with pointer failure injection.
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "\n".join(
            [
                "from nfl_edge.source_audits.sleeper_qb_v1 import atomic_io",
                "_orig = atomic_io.atomic_write_text",
                "def _patched(path, data):",
                "    if str(path).endswith('latest_snapshot.json'):",
                "        raise OSError('injected: pointer write failed')",
                "    return _orig(path, data)",
                "atomic_io.atomic_write_text = _patched",
                "import nfl_edge.source_audits.sleeper_qb_v1.pipeline as _p",
                "_p.atomic_write_text = _patched",
            ]
        )
        + "\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{tmp_path}:{SRC_DIR}:{TESTS_DIR}:{REPO_ROOT}:"
        f"{env.get('PYTHONPATH', '')}"
    )
    r1 = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "collect_sleeper_qbs.py"),
            "--config",
            str(config_path),
            "--use-fake-session",
            "--kind=scheduled",
            "--observed-at-utc=2026-08-07T05:00:00Z",
            "--snapshot-id=snap-cli-pointer-fail",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=60,
    )
    assert r1.returncode == 13, (
        f"rc={r1.returncode} stderr={r1.stderr!r}"
    )
    # CLI must NOT have appended a SECOND row: only one row for
    # the current invocation (snap-cli-pointer-fail), and that
    # row's outcome is PERSISTENCE_FAILURE (the orchestrator
    # already finalized it).
    new_history = _read_history(audit_root)
    assert new_history.height == prior_history.height + 1, (
        f"history grew by {new_history.height - prior_history.height}; "
        "expected exactly 1 (no double-record)"
    )
    last = new_history.row(new_history.height - 1, named=True)
    assert last["outcome"] == "PERSISTENCE_FAILURE", (
        f"row outcome={last['outcome']!r}"
    )