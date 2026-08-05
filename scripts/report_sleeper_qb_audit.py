"""Bounded CLI to print the latest Sleeper QB source-audit report.

This is the entry point a human reviewer (or a test) calls to read the
audit's most recent outputs without having to know the audit tree
layout.

State matrix (Rereview 4859731679):

* **Missing ledger** (``run_history.parquet`` does not exist) —
  valid empty authority. Empty provenance is accepted as matching
  empty cached provenance.
* **Zero-byte ledger** — valid empty authority. Same behavior.
* **Valid empty parquet** (height == 0, schema valid) — valid empty
  authority. Same behavior.
* **Readable authoritative ledger whose cached provenance disagrees**
  — ``STALE_DERIVED_REPORT`` (exit 2).
* **Unreadable / corrupt / schema-invalid authoritative ledger** —
  ``AUTHORITATIVE_LEDGER_READ_FAILURE`` (exit 3). The CLI does NOT
  print the cached report payload in this case.

Both ``STALE_DERIVED_REPORT`` and
``AUTHORITATIVE_LEDGER_READ_FAILURE`` are report-consumer validation
errors — not a ``RunOutcome``.

The CLI does not modify any audit artifact.
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
AUTHORITY_READ_FAILURE_EXIT_CODE = 3

REQUIRED_HISTORY_COLUMNS: tuple[str, ...] = (
    "finished_at_utc",
    "snapshot_id",
)

PREFERRED_HISTORY_COLUMNS: tuple[str, ...] = (
    "outcome",
    "observed_at_utc",
    "kind",
)


class AuthorityReadError(RuntimeError):
    """Raised when the authoritative ``run_history.parquet`` ledger
    cannot be read or validated. The CLI converts this into
    ``AUTHORITATIVE_LEDGER_READ_FAILURE`` (exit 3) — never a stale-
    cache exit, never an empty-history provenance.
    """


def _load_config(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"audit config not found: {path}")
    return yaml.safe_load(path.read_text())


def _validate_history_schema(frame: Any) -> None:
    """Require the authoritative ledger to expose at least
    ``finished_at_utc`` and ``snapshot_id`` so a deterministic sort
    by ``finished_at_utc`` is possible.

    Missing required columns → ``AuthorityReadError``. Missing
    preferred columns → logged as warnings (does not raise).
    """

    if not hasattr(frame, "columns"):
        raise AuthorityReadError(
            "ledger frame is not a tabular object (no .columns attribute)"
        )
    cols = list(frame.columns)
    missing_required = [c for c in REQUIRED_HISTORY_COLUMNS if c not in cols]
    if missing_required:
        raise AuthorityReadError(
            "authoritative ledger is missing required columns: "
            f"{', '.join(sorted(missing_required))}"
        )
    # Deterministic-sort check: try sorting by finished_at_utc and
    # observe an exception. A valid ledger accepts a sort without
    # raising regardless of value types.
    try:
        frame.sort("finished_at_utc", descending=True, nulls_last=True)
    except Exception as exc:  # noqa: BLE001 — fail closed on any sort failure
        raise AuthorityReadError(
            "authoritative ledger cannot be deterministically sorted by "
            f"finished_at_utc: {type(exc).__name__}: {exc}"
        ) from exc


def _valid_empty_history_frame() -> Any:
    """Return an empty polars frame with the required history
    schema. Used for the legitimate missing / zero-byte state."""
    import polars as pl

    return pl.DataFrame(schema={c: pl.Utf8 for c in REQUIRED_HISTORY_COLUMNS})


def _read_authoritative_history_or_missing(
    history_path: Path,
) -> Any:
    """Read ``run_history.parquet`` and validate it, distinguishing
    legitimate missing from inaccessible authority.

    * ``FileNotFoundError`` from ``stat`` → legitimate missing
      ledger; return an empty frame with the required schema.
    * Any other ``OSError`` from ``stat`` → inaccessible
      authority; raise :class:`AuthorityReadError`.
    * Zero-byte file → legitimate empty authority.
    * Polars read / validation errors → inaccessible authority;
      raise :class:`AuthorityReadError`.
    """
    import polars as pl

    try:
        stat_result = history_path.stat()
    except FileNotFoundError:
        return _valid_empty_history_frame()
    except OSError as exc:
        raise AuthorityReadError(
            f"cannot stat ledger at {history_path}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if stat_result.st_size == 0:
        return _valid_empty_history_frame()

    try:
        frame = pl.read_parquet(history_path)
    except Exception as exc:  # noqa: BLE001 — any read failure is authority failure
        raise AuthorityReadError(
            f"cannot read ledger at {history_path}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    _validate_history_schema(frame)
    return frame


def _provenance_from_history_frame(frame: Any) -> dict[str, Any]:
    """Build the provenance dict from a validated ledger frame.

    Assumes the frame has already passed
    :func:`_validate_history_schema`.
    """

    height = int(frame.height)
    if height == 0:
        return {
            "source_history_row_count": 0,
            "source_history_last_finished_at_utc": None,
            "source_history_last_snapshot_id": None,
        }
    sorted_frame = frame.sort(
        "finished_at_utc", descending=True, nulls_last=True
    )
    row = sorted_frame.row(0, named=True)
    last_finished_val = row.get("finished_at_utc")
    last_sid_val = row.get("snapshot_id")
    return {
        "source_history_row_count": height,
        "source_history_last_finished_at_utc": (
            str(last_finished_val) if last_finished_val is not None else None
        ),
        "source_history_last_snapshot_id": (
            str(last_sid_val) if last_sid_val is not None else None
        ),
    }


def _current_provenance(history_path: Path) -> dict[str, Any]:
    """Return the current ledger provenance from
    ``run_history.parquet``.

    Behavior (Rereview 4859731679):

    * Missing / zero-byte / valid-empty → valid empty authority.
    * Any read / validation failure → raises
      :class:`AuthorityReadError`.

    Empty provenance is NEVER used to represent read failure.
    """
    frame = _read_authoritative_history_or_missing(history_path)
    return _provenance_from_history_frame(frame)


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


def _print_authority_read_failure(
    history_path: Path,
    exc: BaseException,
) -> None:
    """Emit the AUTHORITATIVE_LEDGER_READ_FAILURE token and the
    diagnostic details on stderr. Does NOT print the cached report."""
    print("AUTHORITATIVE_LEDGER_READ_FAILURE", file=sys.stdout)
    print(
        f"Authoritative ledger at {history_path} cannot be read "
        f"or validated.",
        file=sys.stderr,
    )
    print(
        f"  ledger path:    {history_path}",
        file=sys.stderr,
    )
    print(
        f"  exception class: {type(exc).__name__}",
        file=sys.stderr,
    )
    print(
        f"  exception message: {exc}",
        file=sys.stderr,
    )


def _print_live(audit_root: Path) -> int:
    """Print the live audit report, validating provenance freshness.

    Returns the process exit code:

    * 0 — provenance matches;
    * 2 — STALE_DERIVED_REPORT (readable authority, stale cache);
    * 3 — AUTHORITATIVE_LEDGER_READ_FAILURE (unreadable / invalid
      authority).
    """
    report_path = audit_root / "reports" / "sleeper_qb_live_audit.json"
    history_path = audit_root / "run_history.parquet"
    if not report_path.exists():
        print(f"ERROR: report not found at {report_path}", file=sys.stderr)
        return 1
    payload: dict[str, Any] = json.loads(report_path.read_text())

    try:
        expected = _current_provenance(history_path)
    except AuthorityReadError as exc:
        _print_authority_read_failure(history_path, exc)
        return AUTHORITY_READ_FAILURE_EXIT_CODE

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
            "STALE_DERIVED_REPORT (exit 2). Unreadable / invalid "
            "authoritative ledgers are rejected with "
            "AUTHORITATIVE_LEDGER_READ_FAILURE (exit 3)."
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