"""Bounded CLI to print the latest Sleeper QB source-audit report.

This is the entry point a human reviewer (or a test) calls to read the
audit's most recent outputs without having to know the audit tree
layout.

Stale-cache detection (Rereview 4859475614 defect 4):

For ``--report live``, the cached ``source_history`` provenance block
is compared against the current ``run_history.parquet`` ledger
provenance. If any field differs, is missing, or the cached report has
no ``source_history`` block, the CLI prints ``STALE_DERIVED_REPORT``
to stdout, includes expected and cached provenance on stderr, and
returns exit code 2. This is a report-consumer validation error — not
a ``RunOutcome``.

For ``--report hof``, current behavior is preserved (the HOF report
does not yet carry provenance fields; stale-detection for HOF is
documented as out-of-scope for this pass).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

STALE_EXIT_CODE = 2


def _load_config(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"audit config not found: {path}")
    return yaml.safe_load(path.read_text())


def _current_provenance(history_path: Path) -> dict[str, Any]:
    """Return the current ledger provenance from
    ``run_history.parquet``."""
    if not history_path.exists():
        return {
            "source_history_row_count": 0,
            "source_history_last_finished_at_utc": None,
            "source_history_last_snapshot_id": None,
        }
    try:
        import polars as pl

        if history_path.stat().st_size == 0:
            return {
                "source_history_row_count": 0,
                "source_history_last_finished_at_utc": None,
                "source_history_last_snapshot_id": None,
            }
        frame = pl.read_parquet(history_path)
        height = int(frame.height)
        last_finished: str | None = None
        last_sid: str | None = None
        if height > 0 and "finished_at_utc" in frame.columns:
            sorted_frame = frame.sort(
                "finished_at_utc", descending=True, nulls_last=True
            )
            row = sorted_frame.row(0, named=True)
            val = row.get("finished_at_utc")
            last_finished = str(val) if val is not None else None
        if height > 0 and "snapshot_id" in frame.columns:
            sorted_frame = frame.sort(
                "finished_at_utc", descending=True, nulls_last=True
            )
            row = sorted_frame.row(0, named=True)
            val = row.get("snapshot_id")
            last_sid = str(val) if val is not None else None
        return {
            "source_history_row_count": height,
            "source_history_last_finished_at_utc": last_finished,
            "source_history_last_snapshot_id": last_sid,
        }
    except Exception:  # noqa: BLE001 — malformed parquet → empty provenance
        return {
            "source_history_row_count": 0,
            "source_history_last_finished_at_utc": None,
            "source_history_last_snapshot_id": None,
        }


def _cached_provenance(report: Mapping[str, Any]) -> dict[str, Any] | None:
    """Extract the cached ``source_history`` provenance block from
    the report payload, or return ``None`` if absent."""
    block = report.get("source_history")
    if not isinstance(block, Mapping):
        return None
    return dict(block)


def _provenance_matches(
    expected: Mapping[str, Any],
    cached: Mapping[str, Any] | None,
) -> tuple[bool, str | None]:
    """Compare the current ledger provenance against the cached
    report's provenance. Returns ``(matches, first_mismatch_field)``.

    If ``cached`` is ``None``, the report has no provenance block and
    cannot be considered fresh.
    """
    if cached is None:
        return False, "source_history"
    for key in (
        "source_history_row_count",
        "source_history_last_finished_at_utc",
        "source_history_last_snapshot_id",
    ):
        expected_val = expected.get(key)
        cached_val = cached.get(key)
        if expected_val != cached_val:
            return False, key
    return True, None


def _print_live(
    audit_root: Path,
) -> int:
    """Print the live audit report, validating provenance freshness.

    Returns the process exit code.
    """
    report_path = audit_root / "reports" / "sleeper_qb_live_audit.json"
    history_path = audit_root / "run_history.parquet"
    if not report_path.exists():
        print(f"ERROR: report not found at {report_path}", file=sys.stderr)
        return 1
    payload: dict[str, Any] = json.loads(report_path.read_text())
    expected = _current_provenance(history_path)
    cached = _cached_provenance(payload)
    matches, mismatch_field = _provenance_matches(expected, cached)
    if not matches:
        print("STALE_DERIVED_REPORT", file=sys.stdout)
        print(
            f"Stale derived live report at {report_path}",
            file=sys.stderr,
        )
        if mismatch_field is not None:
            print(
                f"  first mismatched field: {mismatch_field}",
                file=sys.stderr,
            )
        print(
            f"  expected provenance: {json.dumps(expected, default=str)}",
            file=sys.stderr,
        )
        print(
            f"  cached provenance:   {json.dumps(cached or {}, default=str)}",
            file=sys.stderr,
        )
        return STALE_EXIT_CODE
    print(json.dumps(payload, indent=2, default=str))
    return 0


def _print_hof(audit_root: Path) -> int:
    """Print the HOF report. Stale-detection for HOF is not yet
    implemented (the HOF report schema does not carry provenance);
    preserved as-is from the prior pass."""
    report_path = audit_root / "reports" / "sleeper_hof_game_observation.json"
    if not report_path.exists():
        print(f"ERROR: report not found at {report_path}", file=sys.stderr)
        return 1
    payload = json.loads(report_path.read_text())
    print(json.dumps(payload, indent=2, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Print the latest Sleeper QB source-audit report. "
            "Stale derived live reports are rejected with "
            "STALE_DERIVED_REPORT (exit 2)."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "config" / "sleeper_qb_audit_v1.yaml",
        help="Path to the audit YAML config (default: config/sleeper_qb_audit_v1.yaml).",
    )
    parser.add_argument(
        "--report",
        default="live",
        choices=["live", "hof"],
        help="Which report to print: 'live' or 'hof'.",
    )
    args = parser.parse_args()
    config = _load_config(args.config)
    audit_root = Path(config.get("audit_root", "data/source_audits/sleeper_qb_v1"))
    if args.report == "live":
        return _print_live(audit_root)
    return _print_hof(audit_root)


if __name__ == "__main__":
    raise SystemExit(main())