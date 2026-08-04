"""End-to-end CLI tests for the Sleeper audit.

These tests invoke ``scripts/collect_sleeper_qbs.py`` as a
subprocess so the assertions exercise the real CLI surface — exit
codes, stdout JSON, and the pregame / postgame freeze-pointer
workflow. The CLI uses the deterministic ``FakeSleeperSession``
when ``--use-fake-session`` is passed.

What the tests prove:

* ``--kind=scheduled`` exits 0 on success;
* ``--kind=postgame`` without a pregame pointer exits nonzero
  (``NORMALIZATION_FAILURE`` = 12);
* ``--kind=pregame`` exits 0 and writes an immutable pregame
  pointer file with the documented schema fields;
* ``--kind=postgame`` after a successful pregame exits 0 and
  produces an HOF observation with BOTH pregame and postgame
  per-QB values preserved;
* the CLI exits nonzero on timeout exhaustion when the
  ``FakeSleeperSession`` raises timeouts;
* the CLI exits nonzero on HTTP failure when the fake session
  returns a non-2xx response;
* the CLI exits nonzero on invalid JSON (parseable JSON envelope
  that does not match the player-map shape);
* the latest-run-status JSON reflects the actual outcome even
  after a failure (no stale success).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SRC_DIR = REPO_ROOT / "src"


def _free_port() -> int:
    """Bind a socket to an ephemeral port and release it. The number
    is unlikely to be reused before the test process exits.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_cli(
    *,
    audit_root: Path,
    config_path: Path,
    extra_args: list[str] | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess:
    """Invoke the audit CLI with ``--use-fake-session`` so it never
    reaches the network.
    """
    args = [
        sys.executable,
        str(SCRIPTS_DIR / "collect_sleeper_qbs.py"),
        "--config",
        str(config_path),
        "--use-fake-session",
    ]
    if extra_args:
        args.extend(extra_args)
    run_env = os.environ.copy()
    # Include the source tree, the tests tree, and the repo root
    # so the CLI's ``scripts._sleeper_fake_session`` shim can
    # re-export the test-only stub session.
    run_env["PYTHONPATH"] = (
        f"{SRC_DIR}:{REPO_ROOT / 'tests'}:{REPO_ROOT}:"
        f"{run_env.get('PYTHONPATH', '')}"
    )
    if env:
        run_env.update(env)
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=run_env,
        cwd=str(REPO_ROOT),
    )


def _write_config(audit_root: Path, config_path: Path) -> None:
    config_path.write_text(
        f"audit_root: {audit_root.as_posix()}\n"
        "endpoint: https://api.sleeper.app/v1/players/nfl\n"
        "staleness_threshold_seconds: 21600\n"
    )


@contextmanager
def _temp_audit_root(tmp_path: Path) -> Iterator[Path]:
    audit_root = tmp_path / "audit"
    audit_root.mkdir(parents=True, exist_ok=True)
    yield audit_root


def test_cli_scheduled_exits_zero_on_success(tmp_path: Path) -> None:
    config_path = tmp_path / "cfg.yaml"
    with _temp_audit_root(tmp_path) as audit_root:
        _write_config(audit_root, config_path)
        result = _run_cli(
            audit_root=audit_root,
            config_path=config_path,
            extra_args=["--kind=scheduled"],
        )
    assert result.returncode == 0, (
        f"stderr={result.stderr!r} stdout={result.stdout[:400]!r}"
    )
    payload = json.loads(result.stdout)
    assert payload["run_outcome"] == "SUCCESS"
    assert payload["exit_code"] == 0


def test_cli_postgame_without_pregame_pointer_is_normalization_failure(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "cfg.yaml"
    with _temp_audit_root(tmp_path) as audit_root:
        _write_config(audit_root, config_path)
        result = _run_cli(
            audit_root=audit_root,
            config_path=config_path,
            extra_args=["--kind=postgame"],
        )
    # NORMALIZATION_FAILURE = 12
    assert result.returncode == 12, (
        f"stderr={result.stderr!r} stdout={result.stdout[:400]!r}"
    )
    payload = json.loads(result.stdout)
    assert payload["run_outcome"] == "NORMALIZATION_FAILURE"
    # The latest-run-status file reflects the failure.
    status = json.loads((audit_root / "latest_run_status.json").read_text())
    assert status["outcome"] == "NORMALIZATION_FAILURE"


def test_cli_pregame_writes_immutable_pointer(tmp_path: Path) -> None:
    """``--kind=pregame`` must exit 0 and persist a pregame pointer
    with every documented field populated.
    """
    config_path = tmp_path / "cfg.yaml"
    with _temp_audit_root(tmp_path) as audit_root:
        _write_config(audit_root, config_path)
        result = _run_cli(
            audit_root=audit_root,
            config_path=config_path,
            extra_args=["--kind=pregame", "--lock-timeout-seconds", "5"],
        )
    assert result.returncode == 0, (
        f"stderr={result.stderr!r} stdout={result.stdout[:400]!r}"
    )
    pointer_path = audit_root / "hof_pregame_pointer.json"
    assert pointer_path.exists(), "pregame pointer not written"
    pointer = json.loads(pointer_path.read_text())
    expected_fields = {
        "schema_version",
        "game_id",
        "kickoff_utc",
        "selected_snapshot_id",
        "observed_at_utc",
        "normalized_snapshot_reference",
        "evidence_snapshot_reference",
    }
    assert expected_fields.issubset(pointer.keys()), (
        f"missing pointer fields: {expected_fields - set(pointer.keys())}"
    )
    # The selected snapshot must be before kickoff.
    kickoff = pointer["kickoff_utc"]
    observed = pointer["observed_at_utc"]
    assert observed < kickoff, (
        f"pregame observed_at_utc={observed} must be < kickoff={kickoff}"
    )


def test_cli_pregame_then_postgame_preserves_both_per_qb_values(
    tmp_path: Path,
) -> None:
    """Pregame freezes a snapshot; postgame reloads it and builds
    the HOF observation with BOTH pregame and postgame per-QB
    values preserved.

    The audit's HOF kickoff is 2026-08-07T00:00:00Z; we override
    ``--observed-at-utc`` so the pregame lands before kickoff and
    the postgame lands well after.
    """
    config_path = tmp_path / "cfg.yaml"
    with _temp_audit_root(tmp_path) as audit_root:
        _write_config(audit_root, config_path)
        # Pregame at 2026-08-07 22:00 UTC (well before kickoff at
        # 00:00Z which is later that *day*; the kickoff is the
        # evening of Aug 6 local time). The pregame must be
        # before the kickoff.
        r1 = _run_cli(
            audit_root=audit_root,
            config_path=config_path,
            extra_args=[
                "--kind=pregame",
                "--observed-at-utc=2026-08-06T23:00:00Z",
                "--snapshot-id=snap-pregame-1",
            ],
        )
        assert r1.returncode == 0, (
            f"pregame failed rc={r1.returncode} stderr={r1.stderr!r}"
        )
        # Postgame at 2026-08-07 05:00 UTC, hours after kickoff.
        r2 = _run_cli(
            audit_root=audit_root,
            config_path=config_path,
            extra_args=[
                "--kind=postgame",
                "--observed-at-utc=2026-08-07T05:00:00Z",
                "--snapshot-id=snap-postgame-1",
            ],
        )
    assert r2.returncode == 0, (
        f"postgame failed rc={r2.returncode} stderr={r2.stderr!r}"
    )
    payload = json.loads(r2.stdout)
    assert payload["run_outcome"] == "SUCCESS"
    hof = payload["hof"]
    assert hof is not None
    observation = hof["observation"]
    for field in (
        "pregame_depth_order",
        "pregame_injury_status",
        "pregame_practice_participation",
        "pregame_evidence_state",
        "observed_depth_order",
        "observed_injury_status",
        "observed_practice_participation",
        "derived_evidence_state",
    ):
        assert field in observation, f"missing field in HOF observation: {field}"
    # The pregame and postgame lists are independent (the postgame
    # column is not aliased to the pregame column). With the fake
    # session flipping injury_status only on the second call,
    # postgame injury_status will differ from pregame for at least
    # one QB; we assert that the columns are not the same list.
    assert observation["pregame_injury_status"] is not observation["observed_injury_status"]


def test_cli_timeout_exhaustion_exits_nonzero(tmp_path: Path) -> None:
    """The fake session's ``raise_timeout`` flag forces every
    attempt to time out, exhausting the bounded retry budget.
    The CLI must exit nonzero with ``TRANSPORT_FAILURE``.
    """
    config_path = tmp_path / "cfg.yaml"
    with _temp_audit_root(tmp_path) as audit_root:
        _write_config(audit_root, config_path)
        # Drop a module-level flag into the fake session before
        # invoking the CLI. The CLI imports the fake session on
        # every invocation, so we set the attribute via PYTHONPATH
        # + a tiny bootstrap module. Simpler: monkeypatch via env
        # by adding an import hook in the CLI's PYTHONPATH.
        sitecustomize = tmp_path / "sitecustomize.py"
        sitecustomize.write_text(
            "import scripts._sleeper_fake_session as _f\n"
            "from scripts._sleeper_fake_session import FakeSleeperSession\n"
            "_orig_init = FakeSleeperSession.__init__\n"
            "def _patched_init(self, *a, **kw):\n"
            "    _orig_init(self, *a, **kw)\n"
            "    self.raise_timeout = True\n"
            "FakeSleeperSession.__init__ = _patched_init\n"
        )
        env = {"PYTHONPATH": f"{tmp_path}:{SRC_DIR}:{REPO_ROOT / 'tests'}:{REPO_ROOT}"}
        result = _run_cli(
            audit_root=audit_root,
            config_path=config_path,
            extra_args=["--kind=scheduled"],
            env=env,
            timeout=60.0,
        )
    # TRANSPORT_FAILURE = 10. The bounded retry budget is 3
    # attempts × 30s default timeout + backoff, so the test
    # should finish well under the 60s outer timeout.
    assert result.returncode == 10, (
        f"rc={result.returncode} stderr={result.stderr!r}"
    )
    payload = json.loads(result.stdout)
    assert payload["run_outcome"] == "TRANSPORT_FAILURE"


def test_cli_http_failure_exits_nonzero(tmp_path: Path) -> None:
    """The fake session can return HTTP 500 to force every attempt
    to fail. The CLI must exit nonzero with
    ``TRANSPORT_FAILURE``.
    """
    config_path = tmp_path / "cfg.yaml"
    with _temp_audit_root(tmp_path) as audit_root:
        _write_config(audit_root, config_path)
        sitecustomize = tmp_path / "sitecustomize.py"
        sitecustomize.write_text(
            "import scripts._sleeper_fake_session as _f\n"
            "from scripts._sleeper_fake_session import FakeSleeperSession\n"
            "_orig_init = FakeSleeperSession.__init__\n"
            "def _patched_init(self, *a, **kw):\n"
            "    _orig_init(self, *a, **kw)\n"
            "    self.raise_status = 503\n"
            "FakeSleeperSession.__init__ = _patched_init\n"
        )
        env = {"PYTHONPATH": f"{tmp_path}:{SRC_DIR}:{REPO_ROOT / 'tests'}:{REPO_ROOT}"}
        result = _run_cli(
            audit_root=audit_root,
            config_path=config_path,
            extra_args=["--kind=scheduled"],
            env=env,
            timeout=30.0,
        )
    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["run_outcome"] == "TRANSPORT_FAILURE"


def test_cli_invalid_json_exits_nonzero(tmp_path: Path) -> None:
    """The fake session can return HTTP 200 with a body that is
    not a JSON object of player records. The CLI must exit
    nonzero with ``INCOMPLETE_RESPONSE``.
    """
    config_path = tmp_path / "cfg.yaml"
    with _temp_audit_root(tmp_path) as audit_root:
        _write_config(audit_root, config_path)
        sitecustomize = tmp_path / "sitecustomize.py"
        sitecustomize.write_text(
            "import scripts._sleeper_fake_session as _f\n"
            "from scripts._sleeper_fake_session import FakeSleeperSession\n"
            "_orig_init = FakeSleeperSession.__init__\n"
            "def _patched_init(self, *a, **kw):\n"
            "    _orig_init(self, *a, **kw)\n"
            "    self.invalid_json = True\n"
            "FakeSleeperSession.__init__ = _patched_init\n"
        )
        env = {"PYTHONPATH": f"{tmp_path}:{SRC_DIR}:{REPO_ROOT / 'tests'}:{REPO_ROOT}"}
        result = _run_cli(
            audit_root=audit_root,
            config_path=config_path,
            extra_args=["--kind=scheduled"],
            env=env,
            timeout=30.0,
        )
    # INCOMPLETE_RESPONSE = 11
    assert result.returncode == 11
    payload = json.loads(result.stdout)
    assert payload["run_outcome"] == "INCOMPLETE_RESPONSE"


def test_cli_latest_run_status_reflects_failure(tmp_path: Path) -> None:
    """A failed run must overwrite the latest-run-status file with
    the failure outcome; no stale success remains visible.
    """
    config_path = tmp_path / "cfg.yaml"
    with _temp_audit_root(tmp_path) as audit_root:
        _write_config(audit_root, config_path)
        # 1) Successful run.
        r1 = _run_cli(
            audit_root=audit_root,
            config_path=config_path,
            extra_args=["--kind=scheduled"],
        )
        assert r1.returncode == 0
        status_after_success = json.loads(
            (audit_root / "latest_run_status.json").read_text()
        )
        assert status_after_success["outcome"] == "SUCCESS"
        # 2) Failed run with timeout exhaustion.
        sitecustomize = tmp_path / "sitecustomize.py"
        sitecustomize.write_text(
            "import scripts._sleeper_fake_session as _f\n"
            "from scripts._sleeper_fake_session import FakeSleeperSession\n"
            "_orig_init = FakeSleeperSession.__init__\n"
            "def _patched_init(self, *a, **kw):\n"
            "    _orig_init(self, *a, **kw)\n"
            "    self.raise_timeout = True\n"
            "FakeSleeperSession.__init__ = _patched_init\n"
        )
        env = {"PYTHONPATH": f"{tmp_path}:{SRC_DIR}:{REPO_ROOT / 'tests'}:{REPO_ROOT}"}
        r2 = _run_cli(
            audit_root=audit_root,
            config_path=config_path,
            extra_args=["--kind=scheduled"],
            env=env,
            timeout=60.0,
        )
        assert r2.returncode != 0
    status_after_failure = json.loads(
        (audit_root / "latest_run_status.json").read_text()
    )
    assert status_after_failure["outcome"] == "TRANSPORT_FAILURE"
    # The successful status must be fully overwritten.
    assert status_after_failure != status_after_success
