"""Reference-fixture verification and atomic-write helpers.

The audit consults two reference artifacts:

* ``reference/nflverse_player_identity_pre2025.parquet``
* ``reference/hof_game_2026_fixture.parquet``

Both are committed to the repository as small audited deterministic
fixtures (see ``docs/sleeper_qb_source_contract_v1.md`` §11). The
audit refuses to proceed without them and refuses to proceed if
their on-disk SHA-256 does not match the manifest embedded in this
module.

The module also exposes ``atomic_write_bytes`` and
``atomic_write_parquet``, which together provide the temp-file +
fsync + ``os.replace`` idiom used by every mutable artifact the
audit owns.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import polars as pl

# Reference-fixture manifest. The SHA-256 values are filled in at
# commit time. The audit refuses to proceed if the on-disk fixtures
# do not match; this prevents the harness from silently running
# against a reference that has been edited or corrupted.
#
# The fixtures are committed directly under
# ``data/source_audits/sleeper_qb_v1/reference/`` (Option A from the
# remediation spec). They are intentionally tiny — a few KB each —
# so the cost of committing them is negligible compared to the
# value of a clean-clone-able audit.
REFERENCE_MANIFEST_PATH = (
    Path(__file__).resolve().parents[4]
    / "data"
    / "source_audits"
    / "sleeper_qb_v1"
    / "reference"
    / "manifest.json"
)


@dataclass(frozen=True)
class ReferenceArtifact:
    """One row of the reference-artifact manifest."""

    path: str
    sha256: str
    row_count: int


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def sha256_of_file(path: str | Path) -> str:
    """Compute the SHA-256 of the bytes at ``path``."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically.

    Rereview durability sequence (Rereview 4851615980):

    1. write the data to a temp file in the same directory as
       ``path``;
    2. flush the temp file's userspace buffer;
    3. ``fsync`` the temp file so its contents reach the disk
       BEFORE the rename;
    4. ``os.replace`` the temp file into the target path;
    5. ``fsync`` the parent directory so the rename itself is
       durable across power loss.

    The temp file lives in the same directory as the target so
    ``os.replace`` is atomic on POSIX. The parent directory fsync
    happens *after* the replace; doing it before would not
    guarantee the rename was durable.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        # Parent-directory fsync after the rename so the directory
        # entry change is durable. This is the only ordering that
        # protects against a power loss between os.replace and
        # the kernel flushing the directory inode.
        dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def atomic_write_text(path: str | Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_parquet(path: str | Path, frame: pl.DataFrame) -> None:
    """Atomically persist a polars frame as parquet.

    Rereview durability sequence (Rereview 4851615980):

    1. write the parquet to a temp path;
    2. open the temp file read-only (the writer has already
       closed it);
    3. ``fsync`` the temp file so the parquet bytes reach the
       disk before the rename;
    4. ``os.replace`` the temp file into the target path;
    5. ``fsync`` the parent directory so the rename is durable.

    Doing the parent-directory fsync *after* ``os.replace`` is the
    only ordering that guarantees the rename is durable across a
    power loss.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        frame.write_parquet(tmp)
        with open(tmp, "rb") as handle:
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def atomic_append_parquet(
    path: str | Path,
    new_rows: pl.DataFrame,
    *,
    schema_dtypes: Mapping[str, pl.DataType] | None = None,
) -> None:
    """Append ``new_rows`` to an existing parquet file atomically.

    The previous valid file remains readable and byte-identical
    until the new combined frame is fully written and renamed into
    place. If ``schema_dtypes`` is provided, the combined frame is
    cast to those dtypes so downstream readers see a stable schema.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pl.read_parquet(path)
        combined = pl.concat([existing, new_rows], how="diagonal_relaxed")
    else:
        combined = new_rows
    if schema_dtypes:
        combined = combined.select(
            [
                pl.col(field).cast(dt, strict=False).alias(field)
                for field, dt in schema_dtypes.items()
            ]
        )
    atomic_write_parquet(path, combined)


def verify_reference_manifest(
    reference_dir: str | Path,
    manifest: list[ReferenceArtifact],
) -> tuple[bool, list[str]]:
    """Verify that every manifest entry matches the on-disk file.

    Returns ``(ok, errors)``. ``ok`` is True iff every file exists
    and has the expected SHA-256. ``errors`` contains one message
    per failed file (missing or checksum mismatch). The caller is
    expected to surface the failure as a ``reference_failure``
    outcome.
    """
    reference_dir = Path(reference_dir)
    errors: list[str] = []
    for artifact in manifest:
        full = reference_dir / artifact.path
        if not full.exists():
            errors.append(f"missing reference fixture: {full}")
            continue
        actual = sha256_of_file(full)
        if actual != artifact.sha256:
            errors.append(
                f"reference checksum mismatch for {full}: "
                f"expected={artifact.sha256} actual={actual}"
            )
    return (not errors), errors
