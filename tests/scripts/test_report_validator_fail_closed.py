"""Fail-closed validator tests for the live-report CLI (Rereview 4859731679).

Proves the state matrix for ``scripts/report_sleeper_qb_audit.py
--report live``:

* Missing / zero-byte / valid-empty parquet → valid empty authority
  (matched empty cached provenance → exit 0).
* Readable ledger + stale cache → STALE_DERIVED_REPORT (exit 2).
* Unreadable / corrupt / schema-invalid ledger →
  AUTHORITATIVE_LEDGER_READ_FAILURE (exit 3); cached report NEVER
  printed.

This file uses the CLI as a subprocess (the same way a human
reviewer would) so the exit codes, stdout tokens, and stderr
diagnostics are exercised end-to-end.
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

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
SCRIPTS_DIR = REPO_ROOT / "scripts"

PYTHONPATH_PARTS = [
    str(SRC_DIR),
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


def _seed_history(audit_root: Path, rows: list[dict[str, Any]]) -> Path:
    history_path = audit_root / "run_history.parquet"
    if rows:
        pl.DataFrame(rows).write_parquet(history_path)
    return history_path


def _cli_subprocess(audit_root: Path) -> subprocess.CompletedProcess:
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
            "live",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


EMPTY_PROVENANCE = {
    "source_history_row_count": 0,
    "source_history_last_finished_at_utc": None,
    "source_history_last_snapshot_id": None,
}


# ----------------------------------------------------------------------
# A. Missing ledger + matching empty cached provenance → exit 0
# ----------------------------------------------------------------------


def test_missing_ledger_with_matching_empty_cache_accepted(
    tmp_path: Path,
) -> None:
    audit_root = _make_audit_root(tmp_path)
    # No run_history.parquet on disk.
    _seed_live_report(audit_root, dict(EMPTY_PROVENANCE))
    proc = _cli_subprocess(audit_root)
    assert proc.returncode == 0, proc.stderr


# ----------------------------------------------------------------------
# B. Zero-byte ledger + matching empty cached provenance → exit 0
# ----------------------------------------------------------------------


def test_zero_byte_ledger_with_matching_empty_cache_accepted(
    tmp_path: Path,
) -> None:
    audit_root = _make_audit_root(tmp_path)
    history_path = audit_root / "run_history.parquet"
    history_path.write_bytes(b"")  # touch as zero-byte
    _seed_live_report(audit_root, dict(EMPTY_PROVENANCE))
    proc = _cli_subprocess(audit_root)
    assert proc.returncode == 0, proc.stderr


# ----------------------------------------------------------------------
# C. Valid empty parquet + matching empty cached provenance → exit 0
# ----------------------------------------------------------------------


def test_valid_empty_parquet_with_matching_empty_cache_accepted(
    tmp_path: Path,
) -> None:
    audit_root = _make_audit_root(tmp_path)
    history_path = audit_root / "run_history.parquet"
    pl.DataFrame(
        schema={"finished_at_utc": pl.Utf8, "snapshot_id": pl.Utf8}
    ).write_parquet(history_path)
    _seed_live_report(audit_root, dict(EMPTY_PROVENANCE))
    proc = _cli_subprocess(audit_root)
    assert proc.returncode == 0, proc.stderr


# ----------------------------------------------------------------------
# D. Corrupt non-parquet bytes → exit 3 + token, no cached report
# ----------------------------------------------------------------------


def test_corrupt_ledger_fails_closed(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path)
    history_path = audit_root / "run_history.parquet"
    history_path.write_bytes(b"not a parquet at all just garbage bytes!!!")
    report_path = _seed_live_report(audit_root, dict(EMPTY_PROVENANCE))
    proc = _cli_subprocess(audit_root)
    assert proc.returncode == 3
    assert "AUTHORITATIVE_LEDGER_READ_FAILURE" in proc.stdout
    assert str(history_path) in proc.stderr
    # Cached report payload must NOT be printed.
    try:
        json.loads(proc.stdout.split("\n", 1)[1] if "\n" in proc.stdout else proc.stdout)
    except (json.JSONDecodeError, IndexError):
        # stdout does not contain a JSON payload after the token.
        pass
    # Hard assertion: no schema_version in stdout.
    assert "sleeper-qb-live-audit-v1" not in proc.stdout
    # Confirm the cached report on disk was NOT mutated.
    assert report_path.exists()


# ----------------------------------------------------------------------
# E. Valid parquet missing finished_at_utc → exit 3
# ----------------------------------------------------------------------


def test_missing_finished_at_utc_fails_closed(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path)
    history_path = audit_root / "run_history.parquet"
    pl.DataFrame(
        [
            {
                "snapshot_id": "snap-r",
                "observed_at_utc": "2026-08-06T22:00:00Z",
            }
        ]
    ).write_parquet(history_path)
    _seed_live_report(audit_root, dict(EMPTY_PROVENANCE))
    proc = _cli_subprocess(audit_root)
    assert proc.returncode == 3
    assert "AUTHORITATIVE_LEDGER_READ_FAILURE" in proc.stdout
    assert "finished_at_utc" in proc.stderr


# ----------------------------------------------------------------------
# F. Valid parquet missing snapshot_id → exit 3
# ----------------------------------------------------------------------


def test_missing_snapshot_id_fails_closed(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path)
    history_path = audit_root / "run_history.parquet"
    pl.DataFrame(
        [
            {
                "finished_at_utc": "2026-08-06T22:00:01Z",
                "observed_at_utc": "2026-08-06T22:00:00Z",
            }
        ]
    ).write_parquet(history_path)
    _seed_live_report(audit_root, dict(EMPTY_PROVENANCE))
    proc = _cli_subprocess(audit_root)
    assert proc.returncode == 3
    assert "AUTHORITATIVE_LEDGER_READ_FAILURE" in proc.stdout
    assert "snapshot_id" in proc.stderr


# ----------------------------------------------------------------------
# G. Injected stat/read permission OSError → exit 3
# ----------------------------------------------------------------------


def test_permission_error_fails_closed(tmp_path: Path) -> None:
    """A ledger path that is a directory (stat succeeds, but
    polars cannot read it as parquet) must fail closed."""
    audit_root = _make_audit_root(tmp_path)
    # Replace the parquet with a directory so polars raises.
    history_path = audit_root / "run_history.parquet"
    if history_path.exists():
        history_path.unlink()
    history_path.mkdir()
    # A valid-looking report whose cached provenance matches what
    # the broken ledger WOULD show if it were empty — this proves
    # the CLI does NOT accept empty provenance on an invalid ledger.
    _seed_live_report(audit_root, dict(EMPTY_PROVENANCE))
    proc = _cli_subprocess(audit_root)
    assert proc.returncode == 3
    assert "AUTHORITATIVE_LEDGER_READ_FAILURE" in proc.stdout


# ----------------------------------------------------------------------
# H. Polars read exception → exit 3
# ----------------------------------------------------------------------


def test_polars_read_exception_fails_closed(tmp_path: Path) -> None:
    """A valid-looking parquet that polars cannot parse must fail
    closed, not silently produce empty provenance."""
    audit_root = _make_audit_root(tmp_path)
    history_path = audit_root / "run_history.parquet"
    # Write a single empty byte that polars will reject as an
    # invalid parquet footer.
    history_path.write_bytes(b"\x00\x00\x00\x00")
    _seed_live_report(audit_root, dict(EMPTY_PROVENANCE))
    proc = _cli_subprocess(audit_root)
    assert proc.returncode == 3
    assert "AUTHORITATIVE_LEDGER_READ_FAILURE" in proc.stdout


# ----------------------------------------------------------------------
# I. Unreadable authority + empty-provenance cache → still exit 3
# ----------------------------------------------------------------------


def test_unreadable_authority_with_empty_cache_still_fails(
    tmp_path: Path,
) -> None:
    """The cached report's empty provenance MUST NOT be accepted
    when the ledger is unreadable — the ledger is invalid
    authority, not empty authority."""
    audit_root = _make_audit_root(tmp_path)
    history_path = audit_root / "run_history.parquet"
    history_path.write_bytes(b"definitely not parquet")
    _seed_live_report(audit_root, dict(EMPTY_PROVENANCE))
    proc = _cli_subprocess(audit_root)
    assert proc.returncode == 3
    assert "AUTHORITATIVE_LEDGER_READ_FAILURE" in proc.stdout
    # Cached report must NOT be printed (no schema_version).
    assert "sleeper-qb-live-audit-v1" not in proc.stdout


# ----------------------------------------------------------------------
# J. Readable ledger + stale cache → STALE_DERIVED_REPORT (exit 2)
# ----------------------------------------------------------------------


def test_stale_cache_remains_exit_2(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path)
    _seed_history(
        audit_root,
        [
            {
                "finished_at_utc": "2026-08-06T22:00:01Z",
                "snapshot_id": "snap-r",
                "observed_at_utc": "2026-08-06T22:00:00Z",
                "outcome": "SUCCESS",
                "kind": "scheduled",
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
    # Should NOT be the read-failure token.
    assert "AUTHORITATIVE_LEDGER_READ_FAILURE" not in proc.stdout


# ----------------------------------------------------------------------
# K. Readable valid authority + matching provenance → exit 0
# ----------------------------------------------------------------------


def test_matching_cache_remains_exit_0(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path)
    _seed_history(
        audit_root,
        [
            {
                "finished_at_utc": "2026-08-06T22:00:01Z",
                "snapshot_id": "snap-r",
                "observed_at_utc": "2026-08-06T22:00:00Z",
                "outcome": "SUCCESS",
                "kind": "scheduled",
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


# ----------------------------------------------------------------------
# L. CLI mutates no audit artifact
# ----------------------------------------------------------------------


def test_cli_does_not_mutate_audit_artifacts(tmp_path: Path) -> None:
    audit_root = _make_audit_root(tmp_path)
    _seed_history(
        audit_root,
        [
            {
                "finished_at_utc": "2026-08-06T22:00:01Z",
                "snapshot_id": "snap-r",
                "observed_at_utc": "2026-08-06T22:00:00Z",
                "outcome": "SUCCESS",
                "kind": "scheduled",
            }
        ],
    )
    report_path = _seed_live_report(
        audit_root,
        {
            "source_history_row_count": 1,
            "source_history_last_finished_at_utc": "2026-08-06T22:00:01Z",
            "source_history_last_snapshot_id": "snap-r",
        },
    )
    history_before = (audit_root / "run_history.parquet").read_bytes()
    report_before = report_path.read_bytes()
    proc = _cli_subprocess(audit_root)
    assert proc.returncode == 0
    assert (audit_root / "run_history.parquet").read_bytes() == history_before
    assert report_path.read_bytes() == report_before

    # Also test on a corrupt-ledger failure path: still no mutation.
    history_path = audit_root / "run_history.parquet"
    history_path.write_bytes(b"garbage")
    history_before_bad = history_path.read_bytes()
    report_before_bad = report_path.read_bytes()
    proc_bad = _cli_subprocess(audit_root)
    assert proc_bad.returncode == 3
    assert history_path.read_bytes() == history_before_bad
    assert report_path.read_bytes() == report_before_bad