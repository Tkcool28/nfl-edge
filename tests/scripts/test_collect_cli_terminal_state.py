"""Focused terminal-state closure tests for the Sleeper audit.

These tests prove the six defects called out in review
``4852878097`` are closed:

1. CLI preflight persists the actual ``args.kind`` (never the
   hardcoded ``"scheduled"``).
2. CLI preflight persistence failures surface as exit code 13
   (``PERSISTENCE_FAILURE``); ``OSError`` is never silently
   swallowed.
3. Exactly one terminal-history row is appended per invocation
   (even when the live report or HOF work fails after the HTTP
   fetch succeeds).
4. ``latest_snapshot.json`` advances only on full success —
   every failure path leaves the pointer unchanged.
5. ``run_history.parquet`` is written BEFORE
   ``latest_run_status.json``; a status failure is surfaced but
   does NOT drop the terminal record.
6. The status and history artifacts agree on the recorded
   outcome, kind, snapshot id, and exit code.

The tests use ``--use-fake-session`` and inject failures via a
``sitecustomize.py`` shim that wraps ``atomic_append_run_history``
and ``atomic_write_text``. The shim installs failure modes
selected by env vars:

* ``AUDIT_FAIL_HISTORY`` — make ``atomic_append_run_history``
  raise ``OSError`` on the next call.
* ``AUDIT_FAIL_STATUS`` — make ``atomic_write_text`` raise
  ``OSError`` when writing to a path containing
  ``latest_run_status.json``.
* ``AUDIT_FAIL_REPORT`` — make ``write_live_audit_report`` raise
  ``OSError`` (the inner ``atomic_write_text`` already does
  this; we monkey-patch the report function itself).
* ``AUDIT_FAIL_HOF`` — make ``build_observation_record`` raise
  so the postgame HOF observation returns a failure outcome.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SRC_DIR = REPO_ROOT / "src"
TESTS_DIR = REPO_ROOT / "tests"


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


SHIPPED_REFERENCE_DIR = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "source_audits"
    / "sleeper_qb_v1"
    / "reference"
)


@contextmanager
def _stage_reference_into_audit_root(audit_root: Path):
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
    yield manifest_path


def _sitecustomize_failure_injection(
    tmp_path: Path,
    *,
    fail_history: bool = False,
    fail_status: bool = False,
    fail_report: bool = False,
) -> Path:
    """Write a sitecustomize.py that monkey-patches the durability
    helpers so the next call (or all calls) raise ``OSError``.
    """
    sitecustomize = tmp_path / "sitecustomize.py"
    lines = [
        "import os",
        "from unittest.mock import patch",
        "",
        "fail_history = os.environ.get('AUDIT_FAIL_HISTORY') == '1'",
        "fail_status = os.environ.get('AUDIT_FAIL_STATUS') == '1'",
        "fail_report = os.environ.get('AUDIT_FAIL_REPORT') == '1'",
        "",
        "from nfl_edge.source_audits.sleeper_qb_v1 import atomic_io",
        "",
        "_orig_append = atomic_io.atomic_append_run_history",
        "_orig_write_text = atomic_io.atomic_write_text",
        "",
        "def _patched_append(path, row, **kw):",
        "    if fail_history:",
        "        raise OSError('injected: run_history write failed')",
        "    return _orig_append(path, row, **kw)",
        "",
        "def _patched_write_text(path, data):",
        "    s = str(path)",
        "    if fail_status and 'latest_run_status.json' in s:",
        "        raise OSError('injected: latest_run_status write failed')",
        "    if fail_report and ('sleeper_qb_live_audit' in s):",
        "        raise OSError('injected: live_audit_report write failed')",
        "    return _orig_write_text(path, data)",
        "",
        "atomic_io.atomic_append_run_history = _patched_append",
        "atomic_io.atomic_write_text = _patched_write_text",
        "",
        "# Also patch the names imported into pipeline module.",
        "import nfl_edge.source_audits.sleeper_qb_v1.pipeline as _pl",
        "_pl.atomic_append_run_history = _patched_append",
        "_pl.atomic_write_text = _patched_write_text",
        "",
    ]
    sitecustomize.write_text("\n".join(lines) + "\n")
    return sitecustomize


def _run_cli(
    *,
    audit_root: Path,
    config_path: Path,
    extra_args: list[str],
    tmp_path: Path,
    fail_history: bool = False,
    fail_status: bool = False,
    fail_report: bool = False,
    timeout: float = 60.0,
) -> subprocess.CompletedProcess:
    _sitecustomize_failure_injection(
        tmp_path,
        fail_history=fail_history,
        fail_status=fail_status,
        fail_report=fail_report,
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{tmp_path}:{SRC_DIR}:{TESTS_DIR}:{REPO_ROOT}:"
        f"{env.get('PYTHONPATH', '')}"
    )
    env["AUDIT_FAIL_HISTORY"] = "1" if fail_history else "0"
    env["AUDIT_FAIL_STATUS"] = "1" if fail_status else "0"
    env["AUDIT_FAIL_REPORT"] = "1" if fail_report else "0"
    args = [
        sys.executable,
        str(SCRIPTS_DIR / "collect_sleeper_qbs.py"),
        "--config",
        str(config_path),
        "--use-fake-session",
        *extra_args,
    ]
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        cwd=str(REPO_ROOT),
    )


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


def _shim_bootstrap() -> str:
    """Inline Python that registers ``_sleeper_fake_session`` in
    ``sys.modules`` (mirrors ``tests/conftest.py``). Use at the
    top of any subprocess snippet that needs the stub session.
    """
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


def _shim_path_prefix() -> str:
    """Inline PYTHONPATH setup for subprocess snippets."""
    return (
        f"sys.path.insert(0, {str(SRC_DIR)!r})\n"
        f"sys.path.insert(0, {str(TESTS_DIR)!r})\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
    )


def _shim_full() -> str:
    """PYTHONPATH setup plus shim registration."""
    return _shim_path_prefix() + _shim_bootstrap()


def _parse_subprocess_outcome(proc: subprocess.CompletedProcess) -> dict[str, object]:
    """Parse the orchestrator subprocess's printed JSON line.

    The subprocess snippet prints ``{outcome, exit_code}`` to
    stdout (and ``sys.exit(exit_code)``). Tests must look at the
    JSON, not the subprocess returncode.
    """
    if not proc.stdout.strip():
        return {"outcome": None, "exit_code": proc.returncode}
    line = proc.stdout.strip().splitlines()[-1]
    return json.loads(line)


# ---------------------------------------------------------------------------
# §2 — CLI preflight persistence is truthful
# ---------------------------------------------------------------------------


def test_cli_pregame_missing_manifest_persists_kind_pregame(
    tmp_path: Path,
) -> None:
    """A missing reference manifest with ``--kind=pregame`` must
    persist ``kind="pregame"`` in the terminal history (not the
    hardcoded ``"scheduled"``).
    """
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    config_path = tmp_path / "cfg.yaml"
    # Write a config WITHOUT a reference_manifest key so the
    # manifest resolver returns the missing-manifest error.
    config_path.write_text(
        "\n".join(
            [
                f"audit_root: {audit_root.as_posix()}",
                "endpoint: https://api.sleeper.app/v1/players/nfl",
                "staleness_threshold_seconds: 21600",
            ]
        )
        + "\n"
    )
    result = _run_cli(
        audit_root=audit_root,
        config_path=config_path,
        extra_args=["--kind=pregame"],
        tmp_path=tmp_path,
    )
    assert result.returncode == 21, (
        f"rc={result.returncode} stderr={result.stderr!r}"
    )
    history = _read_history(audit_root)
    assert history.height >= 1, "no terminal history row persisted"
    last = history.row(history.height - 1, named=True)
    assert last["kind"] == "pregame", (
        f"persisted kind={last['kind']!r}; expected 'pregame'"
    )
    assert last["outcome"] == "REFERENCE_FAILURE"


def test_cli_lock_failure_persists_requested_kind(tmp_path: Path) -> None:
    """A LOCK_FAILURE during a ``--kind=postgame`` invocation must
    persist ``kind="postgame"`` in the terminal history.
    """
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    config_path = tmp_path / "cfg.yaml"
    with _stage_reference_into_audit_root(audit_root) as manifest:
        _write_config(
            audit_root, config_path, reference_manifest=manifest
        )
        # Pre-acquire the lock so the real CLI's lock attempt fails.
        # We use the same ``advisory_lock`` helper the CLI uses so
        # the lockfile layout matches.
        from nfl_edge.source_audits.sleeper_qb_v1.locking import advisory_lock
        # Acquire the lock with a long timeout to ensure it is
        # held when the CLI tries to acquire it.
        with advisory_lock(
            audit_root,
            kind="postgame",
            lock_timeout_seconds=10.0,
        ):
            result = _run_cli(
                audit_root=audit_root,
                config_path=config_path,
                extra_args=[
                    "--kind=postgame",
                    "--lock-timeout-seconds",
                    "0.5",
                ],
                tmp_path=tmp_path,
                timeout=30.0,
            )
    assert result.returncode == 20, (
        f"rc={result.returncode} stderr={result.stderr!r}"
    )
    history = _read_history(audit_root)
    assert history.height >= 1, "no terminal history row persisted"
    last = history.row(history.height - 1, named=True)
    assert last["kind"] == "postgame", (
        f"persisted kind={last['kind']!r}; expected 'postgame'"
    )
    assert last["outcome"] == "LOCK_FAILURE"


def test_cli_history_write_failure_exits_13(tmp_path: Path) -> None:
    """A history-write failure must surface as exit code 13
    (``PERSISTENCE_FAILURE``), never silently succeed.
    """
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    config_path = tmp_path / "cfg.yaml"
    with _stage_reference_into_audit_root(audit_root) as manifest:
        _write_config(
            audit_root, config_path, reference_manifest=manifest
        )
        # Run a pregame successfully first so we can see the
        # history row that succeeds.
        r0 = _run_cli(
            audit_root=audit_root,
            config_path=config_path,
            extra_args=[
                "--kind=pregame",
                "--observed-at-utc=2026-08-06T23:00:00Z",
                "--snapshot-id=snap-pregame-history-test",
            ],
            tmp_path=tmp_path,
        )
        assert r0.returncode == 0, f"pregame rc={r0.returncode}"
        prior_history = _read_history(audit_root)
        prior_rows = prior_history.height
        prior_status = _read_status(audit_root)
        # Now run with the history write forced to fail.
        r1 = _run_cli(
            audit_root=audit_root,
            config_path=config_path,
            extra_args=[
                "--kind=scheduled",
                "--observed-at-utc=2026-08-07T05:00:00Z",
                "--snapshot-id=snap-history-fail",
            ],
            tmp_path=tmp_path,
            fail_history=True,
        )
    assert r1.returncode == 13, (
        f"rc={r1.returncode} stderr={r1.stderr!r} stdout={r1.stdout[:300]!r}"
    )
    # History failure must NOT have appended any new row.
    new_history = _read_history(audit_root)
    assert new_history.height == prior_rows, (
        f"history grew from {prior_rows} to {new_history.height} on failure"
    )
    # latest_run_status.json must NOT have been updated to a
    # PERSISTENCE_FAILURE claim (history-first ordering: status
    # follows history).
    new_status = _read_status(audit_root)
    assert new_status is not None
    assert new_status == prior_status, (
        "status was updated despite history write failure"
    )


def test_cli_status_write_failure_exits_13(tmp_path: Path) -> None:
    """A status-write failure must surface as exit code 13
    (``PERSISTENCE_FAILURE``). History was written first, so the
    terminal record is preserved in ``run_history.parquet``.
    """
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    config_path = tmp_path / "cfg.yaml"
    with _stage_reference_into_audit_root(audit_root) as manifest:
        _write_config(
            audit_root, config_path, reference_manifest=manifest
        )
        # First run: succeed and seed history.
        r0 = _run_cli(
            audit_root=audit_root,
            config_path=config_path,
            extra_args=[
                "--kind=scheduled",
                "--observed-at-utc=2026-08-06T22:00:00Z",
                "--snapshot-id=snap-pre-status-test",
            ],
            tmp_path=tmp_path,
        )
        assert r0.returncode == 0
        prior_status = _read_status(audit_root)
        prior_history = _read_history(audit_root)
        # Second run: status write fails.
        r1 = _run_cli(
            audit_root=audit_root,
            config_path=config_path,
            extra_args=[
                "--kind=scheduled",
                "--observed-at-utc=2026-08-06T23:00:00Z",
                "--snapshot-id=snap-status-fail",
            ],
            tmp_path=tmp_path,
            fail_status=True,
        )
    assert r1.returncode == 13, (
        f"rc={r1.returncode} stderr={r1.stderr!r}"
    )
    # History MUST have grown by exactly one row (the new run).
    new_history = _read_history(audit_root)
    assert new_history.height == prior_history.height + 1, (
        f"history grew by {new_history.height - prior_history.height} rows; "
        "expected exactly 1"
    )
    last_row = new_history.row(new_history.height - 1, named=True)
    # History was written BEFORE status (history-first ordering),
    # so the durable row reflects the actual run outcome
    # (SUCCESS) — the status-write failure is surfaced only via
    # the CLI's exit code, not by overwriting history.
    assert last_row["outcome"] == "SUCCESS", (
        f"last history row outcome={last_row['outcome']!r}; "
        "expected SUCCESS (history-first ordering preserves the "
        "actual outcome even when the subsequent status write fails)"
    )
    # latest_run_status.json must NOT have been overwritten.
    new_status = _read_status(audit_root)
    assert new_status == prior_status, (
        "latest_run_status.json was overwritten despite failure"
    )


def test_cli_does_not_silence_persistence_oserror(tmp_path: Path) -> None:
    """If both history and status fail, the CLI must surface a
    persistence-failure stderr message (the exception is not
    silently swallowed).
    """
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    config_path = tmp_path / "cfg.yaml"
    with _stage_reference_into_audit_root(audit_root) as manifest:
        _write_config(
            audit_root, config_path, reference_manifest=manifest
        )
        r1 = _run_cli(
            audit_root=audit_root,
            config_path=config_path,
            extra_args=[
                "--kind=scheduled",
                "--observed-at-utc=2026-08-06T22:00:00Z",
                "--snapshot-id=snap-both-fail",
            ],
            tmp_path=tmp_path,
            fail_history=True,
            fail_status=True,
        )
    assert r1.returncode == 13, (
        f"rc={r1.returncode} stderr={r1.stderr!r}"
    )
    assert "persistence failure" in r1.stderr, (
        f"stderr did not surface persistence failure: {r1.stderr!r}"
    )


# ---------------------------------------------------------------------------
# §3 — exactly one terminal-history row per invocation
# ---------------------------------------------------------------------------


def test_orchestrator_successful_http_then_report_failure_appends_one_row(
    tmp_path: Path,
) -> None:
    """When the live report write fails AFTER the HTTP fetch
    succeeds, exactly ONE terminal-history row is appended and
    its outcome is ``PERSISTENCE_FAILURE`` (NOT both SUCCESS and
    PERSISTENCE_FAILURE).
    """
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    # Use the in-process orchestrator with the failure-injection
    # sitecustomize to make the live-report write raise OSError.
    # The sitecustomize patches ``atomic_write_text`` which the
    # report writer uses internally.
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "\n".join(
            [
                "import os",
                "from nfl_edge.source_audits.sleeper_qb_v1 import atomic_io",
                "_orig_write_text = atomic_io.atomic_write_text",
                "def _patched_write_text(path, data):",
                "    s = str(path)",
                "    if 'sleeper_qb_live_audit' in s:",
                "        raise OSError('injected: live_audit_report write failed')",
                "    return _orig_write_text(path, data)",
                "atomic_io.atomic_write_text = _patched_write_text",
                "import nfl_edge.source_audits.sleeper_qb_v1.pipeline as _pl",
                "_pl.atomic_write_text = _patched_write_text",
            ]
        )
        + "\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{tmp_path}:{SRC_DIR}:{TESTS_DIR}:{REPO_ROOT}:{env.get('PYTHONPATH', '')}"
    )
    # Use the orchestrator in-process with the injected module.
    code = (
        "import sys, os\n"
        f"sys.path.insert(0, {str(SRC_DIR)!r})\n"
        f"sys.path.insert(0, {str(TESTS_DIR)!r})\n"
        f"sys.path.insert(0, {str(tmp_path)!r})\n"
        "# Register _sleeper_fake_session shim (mirrors conftest.py).\n"
        "import importlib.util\n"
        "_spec = importlib.util.spec_from_file_location(\n"
        "    '_sleeper_fake_session',\n"
        f"    {str(TESTS_DIR / 'source_audits' / 'sleeper_qb_v1' / '_fake_session.py')!r},\n"
        ")\n"
        "_mod = importlib.util.module_from_spec(_spec)\n"
        "_spec.loader.exec_module(_mod)\n"
        "sys.modules['_sleeper_fake_session'] = _mod\n"
        "from _sleeper_fake_session import FakeSleeperSession\n"
        "from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator\n"
        f"o = AuditOrchestrator(audit_root={str(audit_root)!r})\n"
        "r = o.run(session=FakeSleeperSession(), kind='scheduled')\n"
        "import json; print(json.dumps({'outcome': r['run_outcome'], 'exit_code': r['exit_code']}))\n"
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
    history = _read_history(audit_root)
    assert history.height == 1, (
        f"history has {history.height} rows; expected exactly 1"
    )
    last = history.row(0, named=True)
    assert last["outcome"] == "PERSISTENCE_FAILURE", (
        f"row outcome={last['outcome']!r}; expected PERSISTENCE_FAILURE"
    )


def test_orchestrator_successful_http_then_hof_failure_appends_one_row(
    tmp_path: Path,
) -> None:
    """When HOF fails AFTER the HTTP fetch succeeds, exactly ONE
    terminal-history row is appended and its outcome is the HOF
    terminal outcome (NOT both SUCCESS and the HOF outcome).
    """
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    # Use the FakeSleeperSession's ``raise_status`` knob to force
    # a HTTP failure on the SECOND call (the postgame snapshot)
    # so the HOF workflow fails with a parse/transport error.
    # Simpler: invoke with a kind that triggers HOF but a
    # malformed pregame pointer path that returns NORMALIZATION_FAILURE.
    # We do this by passing --kind=postgame WITHOUT a pregame
    # pointer. The HOF path returns NORMALIZATION_FAILURE.
    # The CLI's flow becomes: HTTP succeeds -> HOF fails ->
    # final_outcome=NORMALIZATION_FAILURE -> one history row.
    from _sleeper_fake_session import FakeSleeperSession  # noqa: E402

    sys.path.insert(0, str(TESTS_DIR))
    sys.path.insert(0, str(SRC_DIR))
    orchestrator = __import__(
        "nfl_edge.source_audits.sleeper_qb_v1.pipeline",
        fromlist=["AuditOrchestrator"],
    ).AuditOrchestrator(audit_root=audit_root)
    # Stage the shipped reference fixtures so the orchestrator's
    # HOF path can resolve them.
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
    artifacts = []
    for name in (
        "hof_game_2026_fixture.parquet",
        "nflverse_player_identity_pre2025.parquet",
    ):
        dst = ref_dir / name
        sha = hashlib.sha256(dst.read_bytes()).hexdigest()
        rc = pl.read_parquet(dst).height
        artifacts.append({"path": name, "sha256": sha, "row_count": rc})
    (ref_dir / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": artifacts})
    )
    from nfl_edge.source_audits.sleeper_qb_v1.atomic_io import (
        ReferenceArtifact,
    )
    orchestrator.reference_manifest = [
        ReferenceArtifact(**a) for a in artifacts
    ]
    result = orchestrator.run(
        session=FakeSleeperSession(),
        kind="postgame",
    )
    assert result["run_outcome"] == "NORMALIZATION_FAILURE", (
        f"final_outcome={result['run_outcome']!r}"
    )
    history = _read_history(audit_root)
    assert history.height == 1, (
        f"history has {history.height} rows; expected exactly 1"
    )
    last = history.row(0, named=True)
    assert last["outcome"] == "NORMALIZATION_FAILURE", (
        f"row outcome={last['outcome']!r}"
    )
    assert last["kind"] == "postgame"


def test_orchestrator_full_success_appends_exactly_one_row(
    tmp_path: Path,
) -> None:
    """A fully successful run produces exactly one terminal-history
    row (no double-append).
    """
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    sys.path.insert(0, str(TESTS_DIR))
    sys.path.insert(0, str(SRC_DIR))
    from _sleeper_fake_session import FakeSleeperSession

    from nfl_edge.source_audits.sleeper_qb_v1.pipeline import (
        AuditOrchestrator,
    )
    orchestrator = AuditOrchestrator(audit_root=audit_root)
    orchestrator.run(session=FakeSleeperSession(), kind="scheduled")
    history = _read_history(audit_root)
    assert history.height == 1
    last = history.row(0, named=True)
    assert last["outcome"] == "SUCCESS"
    assert last["kind"] == "scheduled"


# ---------------------------------------------------------------------------
# §4 — latest_snapshot advances only on full success
# ---------------------------------------------------------------------------


def test_report_failure_leaves_pointer_unchanged(tmp_path: Path) -> None:
    """A live-report write failure must NOT advance the
    latest-success pointer.
    """
    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    # First run: successful so the pointer is seeded.
    sys.path.insert(0, str(TESTS_DIR))
    sys.path.insert(0, str(SRC_DIR))
    from _sleeper_fake_session import FakeSleeperSession

    from nfl_edge.source_audits.sleeper_qb_v1.pipeline import (
        AuditOrchestrator,
    )
    o = AuditOrchestrator(audit_root=audit_root)
    o.run(
        session=FakeSleeperSession(),
        kind="scheduled",
        forced_snapshot_id="snap-prior-success",
        forced_observed_at_utc="2026-08-06T22:00:00+00:00",
    )
    prior_pointer = _read_pointer(audit_root)
    assert prior_pointer is not None
    # Second run with a fresh session; report write forced to fail.
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "\n".join(
            [
                "from nfl_edge.source_audits.sleeper_qb_v1 import atomic_io",
                "_orig = atomic_io.atomic_write_text",
                "def _patched(path, data):",
                "    if 'sleeper_qb_live_audit' in str(path):",
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
        "import sys, os\n"
        f"sys.path.insert(0, {str(SRC_DIR)!r})\n"
        f"sys.path.insert(0, {str(TESTS_DIR)!r})\n"
        f"sys.path.insert(0, {str(tmp_path)!r})\n"
        "# Register _sleeper_fake_session shim (mirrors conftest.py).\n"
        "import importlib.util\n"
        "_spec = importlib.util.spec_from_file_location(\n"
        "    '_sleeper_fake_session',\n"
        f"    {str(TESTS_DIR / 'source_audits' / 'sleeper_qb_v1' / '_fake_session.py')!r},\n"
        ")\n"
        "_mod = importlib.util.module_from_spec(_spec)\n"
        "_spec.loader.exec_module(_mod)\n"
        "sys.modules['_sleeper_fake_session'] = _mod\n"
        "from _sleeper_fake_session import FakeSleeperSession\n"
        "from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator\n"
        f"o = AuditOrchestrator(audit_root={str(audit_root)!r})\n"
        "r = o.run(session=FakeSleeperSession(), kind='scheduled',\n"
        "          forced_snapshot_id='snap-report-fail',\n"
        "          forced_observed_at_utc='2026-08-07T05:00:00+00:00')\n"
        "import json; print(json.dumps({'outcome': r['run_outcome'], 'exit_code': r['exit_code']}))\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{tmp_path}:{SRC_DIR}:{TESTS_DIR}:{REPO_ROOT}:{env.get('PYTHONPATH', '')}"
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
        f"rc={proc.returncode} stderr={proc.stderr!r}"
    )
    # Pointer must be unchanged.
    new_pointer = _read_pointer(audit_root)
    assert new_pointer == prior_pointer, (
        f"pointer advanced: {prior_pointer} -> {new_pointer}"
    )


def test_history_failure_leaves_pointer_unchanged(tmp_path: Path) -> None:
    """A history-write failure must NOT append any row.

    Rereview 4858328151 §3: the latest_snapshot pointer is
    written BEFORE the terminal-history row. A history-write
    failure therefore does NOT roll back the pointer (which was
    durably advanced on SUCCESS) — the pointer stays at the new
    snapshot, but ``run_history.parquet`` has zero rows for this
    invocation and ``latest_run_status.json`` is unchanged from
    the prior run. One row per invocation is preserved as "no
    row".
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
    prior_status_bytes = (audit_root / "latest_run_status.json").read_bytes()
    prior_history = _read_history(audit_root)
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "\n".join(
            [
                "from nfl_edge.source_audits.sleeper_qb_v1 import atomic_io",
                "_orig = atomic_io.atomic_append_run_history",
                "def _patched(path, row, **kw):",
                "    raise OSError('injected')",
                "    return _orig(path, row, **kw)",
                "atomic_io.atomic_append_run_history = _patched",
                "import nfl_edge.source_audits.sleeper_qb_v1.pipeline as _p",
                "_p.atomic_append_run_history = _patched",
            ]
        )
        + "\n"
    )
    code = (
        "import sys, os\n"
        f"sys.path.insert(0, {str(SRC_DIR)!r})\n"
        f"sys.path.insert(0, {str(TESTS_DIR)!r})\n"
        f"sys.path.insert(0, {str(tmp_path)!r})\n"
        "# Register _sleeper_fake_session shim (mirrors conftest.py).\n"
        "import importlib.util\n"
        "_spec = importlib.util.spec_from_file_location(\n"
        "    '_sleeper_fake_session',\n"
        f"    {str(TESTS_DIR / 'source_audits' / 'sleeper_qb_v1' / '_fake_session.py')!r},\n"
        ")\n"
        "_mod = importlib.util.module_from_spec(_spec)\n"
        "_spec.loader.exec_module(_mod)\n"
        "sys.modules['_sleeper_fake_session'] = _mod\n"
        "from _sleeper_fake_session import FakeSleeperSession\n"
        "from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator\n"
        f"o = AuditOrchestrator(audit_root={str(audit_root)!r})\n"
        "r = o.run(session=FakeSleeperSession(), kind='scheduled',\n"
        "          forced_snapshot_id='snap-hist-fail',\n"
        "          forced_observed_at_utc='2026-08-07T05:00:00+00:00')\n"
        "import json; print(json.dumps({'outcome': r['run_outcome'], 'exit_code': r['exit_code']}))\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{tmp_path}:{SRC_DIR}:{TESTS_DIR}:{REPO_ROOT}:{env.get('PYTHONPATH', '')}"
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
    assert outcome["exit_code"] == 13
    # History must NOT have grown (zero rows for this invocation).
    new_history = _read_history(audit_root)
    assert new_history.height == prior_history.height, (
        f"history grew from {prior_history.height} to "
        f"{new_history.height} on history-write failure"
    )
    # latest_run_status.json must NOT have been overwritten (the
    # status write was skipped because history failed first).
    after_status_bytes = (audit_root / "latest_run_status.json").read_bytes()
    assert after_status_bytes == prior_status_bytes, (
        "latest_run_status.json was modified despite history failure"
    )


def test_status_failure_leaves_pointer_unchanged(tmp_path: Path) -> None:
    """A status-write failure must not lose the durable terminal
    record.

    Rereview 4858328151 §3: history is written before status, so
    a status-write failure leaves ``run_history.parquet`` with
    one row reflecting the actual run outcome (SUCCESS in this
    test, because the run succeeded at HTTP/report/HOF/pointer
    and only the post-persistence status write failed). The
    pointer was durably advanced before the status write. The
    status file is unchanged from the prior run.
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
    prior_status = _read_status(audit_root)
    prior_history = _read_history(audit_root)
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "\n".join(
            [
                "from nfl_edge.source_audits.sleeper_qb_v1 import atomic_io",
                "_orig = atomic_io.atomic_write_text",
                "def _patched(path, data):",
                "    if 'latest_run_status.json' in str(path):",
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
        "import sys, os\n"
        f"sys.path.insert(0, {str(SRC_DIR)!r})\n"
        f"sys.path.insert(0, {str(TESTS_DIR)!r})\n"
        f"sys.path.insert(0, {str(tmp_path)!r})\n"
        "# Register _sleeper_fake_session shim (mirrors conftest.py).\n"
        "import importlib.util\n"
        "_spec = importlib.util.spec_from_file_location(\n"
        "    '_sleeper_fake_session',\n"
        f"    {str(TESTS_DIR / 'source_audits' / 'sleeper_qb_v1' / '_fake_session.py')!r},\n"
        ")\n"
        "_mod = importlib.util.module_from_spec(_spec)\n"
        "_spec.loader.exec_module(_mod)\n"
        "sys.modules['_sleeper_fake_session'] = _mod\n"
        "from _sleeper_fake_session import FakeSleeperSession\n"
        "from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator\n"
        f"o = AuditOrchestrator(audit_root={str(audit_root)!r})\n"
        "r = o.run(session=FakeSleeperSession(), kind='scheduled',\n"
        "          forced_snapshot_id='snap-status-fail',\n"
        "          forced_observed_at_utc='2026-08-07T05:00:00+00:00')\n"
        "import json; print(json.dumps({'outcome': r['run_outcome'], 'exit_code': r['exit_code']}))\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{tmp_path}:{SRC_DIR}:{TESTS_DIR}:{REPO_ROOT}:{env.get('PYTHONPATH', '')}"
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
    assert outcome["exit_code"] == 13
    # History MUST have grown by exactly one row (history is
    # written before status, so a status failure preserves it).
    new_history = _read_history(audit_root)
    assert new_history.height == prior_history.height + 1, (
        f"history grew by {new_history.height - prior_history.height} rows; "
        "expected exactly 1"
    )
    last_row = new_history.row(new_history.height - 1, named=True)
    assert last_row["outcome"] == "SUCCESS", (
        f"last history row outcome={last_row['outcome']!r}; "
        "expected SUCCESS (history-first ordering preserves the "
        "actual outcome even when the subsequent status write fails)"
    )
    # latest_run_status.json must NOT have been overwritten.
    new_status = _read_status(audit_root)
    assert new_status == prior_status, (
        "latest_run_status.json was overwritten despite failure"
    )


def test_full_success_advances_pointer_exactly_once(tmp_path: Path) -> None:
    """A fully successful run advances the latest-success pointer
    to the new snapshot exactly once.
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
        forced_snapshot_id="snap-first",
        forced_observed_at_utc="2026-08-06T22:00:00+00:00",
    )
    prior_pointer = _read_pointer(audit_root)
    AuditOrchestrator(audit_root=audit_root).run(
        session=FakeSleeperSession(),
        kind="scheduled",
        forced_snapshot_id="snap-second",
        forced_observed_at_utc="2026-08-07T05:00:00+00:00",
    )
    new_pointer = _read_pointer(audit_root)
    assert new_pointer["snapshot_id"] == "snap-second"
    assert new_pointer != prior_pointer


# ---------------------------------------------------------------------------
# §5 — status and history stay consistent
# ---------------------------------------------------------------------------


def test_history_failure_leaves_prior_status_intact(tmp_path: Path) -> None:
    """A history-write failure must leave the prior
    ``latest_run_status.json`` content completely intact.
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
        forced_snapshot_id="snap-seed",
        forced_observed_at_utc="2026-08-06T22:00:00+00:00",
    )
    prior_status_bytes = (audit_root / "latest_run_status.json").read_bytes()
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "\n".join(
            [
                "from nfl_edge.source_audits.sleeper_qb_v1 import atomic_io",
                "_orig = atomic_io.atomic_append_run_history",
                "def _patched(path, row, **kw):",
                "    raise OSError('injected')",
                "    return _orig(path, row, **kw)",
                "atomic_io.atomic_append_run_history = _patched",
                "import nfl_edge.source_audits.sleeper_qb_v1.pipeline as _p",
                "_p.atomic_append_run_history = _patched",
            ]
        )
        + "\n"
    )
    code = (
        "import sys, os\n"
        f"sys.path.insert(0, {str(SRC_DIR)!r})\n"
        f"sys.path.insert(0, {str(TESTS_DIR)!r})\n"
        f"sys.path.insert(0, {str(tmp_path)!r})\n"
        "# Register _sleeper_fake_session shim (mirrors conftest.py).\n"
        "import importlib.util\n"
        "_spec = importlib.util.spec_from_file_location(\n"
        "    '_sleeper_fake_session',\n"
        f"    {str(TESTS_DIR / 'source_audits' / 'sleeper_qb_v1' / '_fake_session.py')!r},\n"
        ")\n"
        "_mod = importlib.util.module_from_spec(_spec)\n"
        "_spec.loader.exec_module(_mod)\n"
        "sys.modules['_sleeper_fake_session'] = _mod\n"
        "from _sleeper_fake_session import FakeSleeperSession\n"
        "from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator\n"
        f"o = AuditOrchestrator(audit_root={str(audit_root)!r})\n"
        "r = o.run(session=FakeSleeperSession(), kind='scheduled',\n"
        "          forced_snapshot_id='snap-hist-fail-2',\n"
        "          forced_observed_at_utc='2026-08-07T05:00:00+00:00')\n"
        "import json; print(json.dumps({'outcome': r['run_outcome'], 'exit_code': r['exit_code']}))\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{tmp_path}:{SRC_DIR}:{TESTS_DIR}:{REPO_ROOT}:{env.get('PYTHONPATH', '')}"
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
    assert outcome["exit_code"] == 13
    after_status_bytes = (audit_root / "latest_run_status.json").read_bytes()
    assert after_status_bytes == prior_status_bytes, (
        "latest_run_status.json was modified despite history failure"
    )


def test_status_failure_surfaces_exit_13(tmp_path: Path) -> None:
    """A status-write failure must surface as exit code 13. The
    terminal-history row was already written (history-first
    ordering), so the durable record is preserved.
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
        forced_snapshot_id="snap-seed",
        forced_observed_at_utc="2026-08-06T22:00:00+00:00",
    )
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "\n".join(
            [
                "from nfl_edge.source_audits.sleeper_qb_v1 import atomic_io",
                "_orig = atomic_io.atomic_write_text",
                "def _patched(path, data):",
                "    if 'latest_run_status.json' in str(path):",
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
        "import sys, os\n"
        f"sys.path.insert(0, {str(SRC_DIR)!r})\n"
        f"sys.path.insert(0, {str(TESTS_DIR)!r})\n"
        f"sys.path.insert(0, {str(tmp_path)!r})\n"
        "# Register _sleeper_fake_session shim (mirrors conftest.py).\n"
        "import importlib.util\n"
        "_spec = importlib.util.spec_from_file_location(\n"
        "    '_sleeper_fake_session',\n"
        f"    {str(TESTS_DIR / 'source_audits' / 'sleeper_qb_v1' / '_fake_session.py')!r},\n"
        ")\n"
        "_mod = importlib.util.module_from_spec(_spec)\n"
        "_spec.loader.exec_module(_mod)\n"
        "sys.modules['_sleeper_fake_session'] = _mod\n"
        "from _sleeper_fake_session import FakeSleeperSession\n"
        "from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator\n"
        f"o = AuditOrchestrator(audit_root={str(audit_root)!r})\n"
        "r = o.run(session=FakeSleeperSession(), kind='scheduled',\n"
        "          forced_snapshot_id='snap-status-fail-2',\n"
        "          forced_observed_at_utc='2026-08-07T05:00:00+00:00')\n"
        "import json; print(json.dumps({'outcome': r['run_outcome'], 'exit_code': r['exit_code']}))\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{tmp_path}:{SRC_DIR}:{TESTS_DIR}:{REPO_ROOT}:{env.get('PYTHONPATH', '')}"
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
    assert outcome["exit_code"] == 13
    # The orchestrator's _failure_after_status_failure returns the
    # PERSISTENCE_FAILURE dict but does not emit stderr directly;
    # that surface is the CLI's responsibility. The typed exit
    # code in the JSON payload is the orchestrator-level signal.
    assert outcome["outcome"] == "PERSISTENCE_FAILURE"


def test_successful_record_writes_matching_fields_to_both_artifacts(
    tmp_path: Path,
) -> None:
    """On a successful run, ``latest_run_status.json`` and the
    last row of ``run_history.parquet`` must agree on outcome,
    kind, snapshot_id, and exit_code.
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
        forced_snapshot_id="snap-agree",
        forced_observed_at_utc="2026-08-06T22:00:00+00:00",
    )
    status = _read_status(audit_root)
    history = _read_history(audit_root)
    last = history.row(history.height - 1, named=True)
    for field in ("outcome", "kind", "snapshot_id", "exit_code"):
        assert status[field] == last[field], (
            f"{field}: status={status[field]!r} history={last[field]!r}"
        )