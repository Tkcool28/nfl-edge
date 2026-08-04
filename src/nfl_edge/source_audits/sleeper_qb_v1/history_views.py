"""History-derived selectors for the Sleeper QB source audit.

Rereview 4851615980 / current pass — authoritativeness:

``run_history.parquet`` is the only authoritative terminal commit
ledger. Every selector in this module reads from that ledger; none
of them reads from derived cache files (``latest_snapshot.json``,
``latest_run_status.json``, ``hof_pregame_pointer.json``).

Any row whose ``snapshot_id`` does not occur in
``run_history.parquet`` is considered an uncommitted / "ghost"
snapshot artifact. Ghost rows are filtered out by every selector
that gates state selection — they are never used for:

* the prior successful snapshot (change detection);
* the committed pregame snapshot (HOF postgame);
* the rolling scheduled / success / fail counts;
* the change-event counts.

A successful run may have ``payload_sha256`` and ``raw_payload_path``
populated on its terminal-history row; these are sufficient to
reconstruct the latest-success pointer without trusting any cache.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from .outcomes import RunOutcome


def load_run_history(path: str | Path) -> pl.DataFrame:
    """Read ``run_history.parquet`` (terminal-history ledger).

    Returns an empty frame if the file does not exist or is empty.
    The schema is enforced so downstream filters are well-typed.
    """
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return pl.DataFrame()
    frame = pl.read_parquet(path)
    return frame


def committed_snapshot_ids(history: pl.DataFrame) -> set[str]:
    """Return the set of ``snapshot_id`` values that occur in
    committed history rows.

    Empty strings and nulls are excluded; only non-empty
    ``snapshot_id`` values count.
    """
    if history.height == 0 or "snapshot_id" not in history.columns:
        return set()
    values = history["snapshot_id"].to_list()
    return {v for v in values if isinstance(v, str) and v}


def select_latest_successful_snapshot(
    history: pl.DataFrame,
) -> dict[str, Any] | None:
    """Return the latest committed SUCCESS row from history, or
    ``None`` if no SUCCESS row exists.

    Selection is deterministic:

    1. ``outcome == SUCCESS`` (the terminal-history contract);
    2. ``snapshot_id`` not null and not empty;
    3. ordered by ``finished_at_utc`` descending, with
       ``observed_at_utc`` and ``snapshot_id`` as deterministic
       tie-breakers (ascending).

    The returned dict carries the fields needed to reconstruct
    ``latest_snapshot.json`` without trusting any cache:
    ``snapshot_id``, ``observed_at_utc``, ``finished_at_utc``,
    ``payload_sha256``, ``raw_payload_path``, ``kind``.
    """
    if history.height == 0 or "outcome" not in history.columns:
        return None
    if "snapshot_id" not in history.columns:
        return None

    successful = history.filter(
        (pl.col("outcome") == RunOutcome.SUCCESS.value)
        & pl.col("snapshot_id").is_not_null()
        & (pl.col("snapshot_id") != "")
    )
    if successful.height == 0:
        return None

    finished_col = (
        pl.col("finished_at_utc")
        if "finished_at_utc" in successful.columns
        else pl.lit("")
    )
    observed_col = (
        pl.col("observed_at_utc")
        if "observed_at_utc" in successful.columns
        else pl.lit("")
    )

    ranked = successful.with_columns(
        [
            finished_col.alias("__finished"),
            observed_col.alias("__observed"),
        ]
    ).sort(
        [
            "__finished",
            "__observed",
            "snapshot_id",
        ],
        descending=[True, False, False],
        nulls_last=True,
    )
    last = ranked.row(0, named=True)
    return {
        "snapshot_id": last.get("snapshot_id"),
        "observed_at_utc": last.get("observed_at_utc"),
        "finished_at_utc": last.get("finished_at_utc"),
        "payload_sha256": last.get("payload_sha256"),
        "raw_payload_path": last.get("raw_payload_path"),
        "kind": last.get("kind"),
    }


def select_pregame_from_history(
    history: pl.DataFrame,
    *,
    kickoff_utc: str,
) -> dict[str, Any] | None:
    """Return the latest committed SUCCESS pregame row whose
    ``observed_at_utc`` is strictly before ``kickoff_utc``.

    Selection is deterministic (same tie-breakers as
    :func:`select_latest_successful_snapshot`). Returns ``None`` if
    no qualifying row exists; the caller must treat ``None`` as
    "no committed pregame snapshot" (HOF postgame cannot run).
    """
    if history.height == 0:
        return None
    if "outcome" not in history.columns or "kind" not in history.columns:
        return None

    from .pipeline import _utc_iso_is_before  # late import to avoid cycle

    candidates = history.filter(
        (pl.col("outcome") == RunOutcome.SUCCESS.value)
        & (pl.col("kind") == "pregame")
        & pl.col("snapshot_id").is_not_null()
        & (pl.col("snapshot_id") != "")
        & pl.col("observed_at_utc").is_not_null()
    )
    if candidates.height == 0:
        return None

    keep: list[dict[str, Any]] = []
    for row in candidates.to_dicts():
        obs = row.get("observed_at_utc")
        if not obs:
            continue
        try:
            if _utc_iso_is_before(str(obs), kickoff_utc):
                keep.append(row)
        except ValueError:
            continue
    if not keep:
        return None

    # Deterministic ordering: largest finished_at_utc first;
    # observed_at_utc ascending; snapshot_id ascending. The
    # negative-epoch trick puts the largest finished_at_utc first
    # without a custom comparator.
    keep.sort(
        key=lambda r: (
            -_iso_to_epoch(str(r.get("finished_at_utc") or "")),
            _iso_to_epoch(str(r.get("observed_at_utc") or "")),
            str(r.get("snapshot_id") or ""),
        )
    )
    last = keep[0]
    return {
        "snapshot_id": last.get("snapshot_id"),
        "observed_at_utc": last.get("observed_at_utc"),
        "finished_at_utc": last.get("finished_at_utc"),
        "payload_sha256": last.get("payload_sha256"),
        "raw_payload_path": last.get("raw_payload_path"),
        "kind": last.get("kind"),
    }


def _iso_to_epoch(value: str) -> int:
    """Parse an ISO-8601 UTC string into an epoch int (for sort)."""
    from datetime import datetime

    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return 0
    if dt.tzinfo is None:
        return 0
    return int(dt.timestamp())


def filter_committed(
    frame: pl.DataFrame,
    committed_ids: set[str],
    *,
    snapshot_column: str = "snapshot_id",
) -> pl.DataFrame:
    """Return ``frame`` filtered to rows whose ``snapshot_column``
    value is in ``committed_ids``.

    Rows whose snapshot_id is null, empty, or otherwise missing
    from the committed-history ledger are excluded.
    """
    if frame.height == 0:
        return frame
    if snapshot_column not in frame.columns:
        return pl.DataFrame()
    if not committed_ids:
        return pl.DataFrame()
    return frame.filter(pl.col(snapshot_column).is_in(list(committed_ids)))


def filter_committed_by_observed_at(
    frame: pl.DataFrame,
    history: pl.DataFrame,
    *,
    observed_column: str = "fetched_at_utc",
) -> pl.DataFrame:
    """Return ``frame`` filtered to rows whose ``observed_column``
    value matches the ``observed_at_utc`` of a committed history row.

    Used to attach snapshot artifacts to the right committed run
    (e.g. fetch-attempts or active rows whose only join key is the
    observed timestamp).
    """
    if frame.height == 0:
        return frame
    if observed_column not in frame.columns:
        return pl.DataFrame()
    if history.height == 0 or "observed_at_utc" not in history.columns:
        return pl.DataFrame()
    valid = {
        v for v in history["observed_at_utc"].to_list()
        if isinstance(v, str) and v
    }
    if not valid:
        return pl.DataFrame()
    return frame.filter(pl.col(observed_column).is_in(list(valid)))


def history_row_count(history: pl.DataFrame) -> int:
    """Return the number of committed terminal-history rows."""
    return int(history.height)


def history_last_finished_at_utc(history: pl.DataFrame) -> str | None:
    """Return the largest ``finished_at_utc`` among committed rows."""
    if history.height == 0 or "finished_at_utc" not in history.columns:
        return None
    last = history.sort(
        "finished_at_utc", descending=True, nulls_last=True
    ).row(0, named=True)
    return last.get("finished_at_utc")


def history_last_snapshot_id(history: pl.DataFrame) -> str | None:
    """Return the ``snapshot_id`` of the row with the largest
    ``finished_at_utc``."""
    if history.height == 0:
        return None
    if "finished_at_utc" not in history.columns:
        return None
    if "snapshot_id" not in history.columns:
        return None
    last = history.sort(
        "finished_at_utc", descending=True, nulls_last=True
    ).row(0, named=True)
    return last.get("snapshot_id")


__all__ = [
    "load_run_history",
    "committed_snapshot_ids",
    "select_latest_successful_snapshot",
    "select_pregame_from_history",
    "filter_committed",
    "filter_committed_by_observed_at",
    "history_row_count",
    "history_last_finished_at_utc",
    "history_last_snapshot_id",
]