"""OS-advisory file lock with timeout + dead-owner recovery.

The audit uses a POSIX-advisory lock with two layers:

1. An **atomic ownership sentinel** written via ``O_CREAT|O_EXCL`` so
   that two processes cannot both believe they own the lock. The
   sentinel file contains ``{"pid": <int>, "kind": <str>,
   "started_at_utc": <iso>}``. The sentinel is created in the same
   directory as the lock file and is renamed to ``<lock>.owner``
   when held, ``<lock>`` always being a small ``flock``-protected
   file.
2. A **``fcntl.flock`` advisory lock** on a separate small file in
   the same directory. ``flock(LOCK_EX|LOCK_NB)`` returns
   immediately when contended; the caller polls with a small sleep
   until the timeout is exhausted.

The two layers compose:

* if a prior process died leaving a stale sentinel, the new owner
  first reads the sentinel's PID; if that PID is no longer alive
  (POSIX ``kill(pid, 0)`` raises ``ProcessLookupError``) the stale
  sentinel is removed and the new owner proceeds;
* if a prior process is alive but holding the flock, the new owner
  waits up to the timeout, polling;
* on clean exit the owner removes both files.

Parameters
----------

``lock_dir``
    Directory containing the lock file pair. Created if missing.
``lock_timeout_seconds``
    Maximum wall-clock seconds the caller will wait to acquire the
    lock. ``0.0`` means "fail fast if held".
``kind``
    Free-form string recorded in the sentinel; the orchestrator
    passes ``"scheduled"``, ``"pregame"``, or ``"postgame"`` so an
    operator can tell which kind of run is currently holding the
    lock.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

LOCK_FILENAME = "audit.lock"
OWNER_FILENAME = "audit.lock.owner"
POLL_INTERVAL_SECONDS = 0.05


class LockFailure(RuntimeError):
    """Raised when the lock cannot be acquired within the timeout
    or when an unrecoverable OS error occurs."""


@dataclass(frozen=True)
class LockHolder:
    pid: int
    kind: str
    started_at_utc: str


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by another user; treat as alive
        # so we do not silently steal a foreign lock.
        return True
    return True


def _read_owner(path: Path) -> LockHolder | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    pid_raw = payload.get("pid")
    if not isinstance(pid_raw, int):
        return None
    return LockHolder(
        pid=pid_raw,
        kind=str(payload.get("kind", "")),
        started_at_utc=str(payload.get("started_at_utc", "")),
    )


def _acquire_sentinel(lock_dir: Path, kind: str) -> tuple[int, Path]:
    """Atomically create the ownership sentinel via O_CREAT|O_EXCL."""
    owner_path = lock_dir / OWNER_FILENAME
    fd = os.open(
        str(owner_path),
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    try:
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "kind": kind,
                "started_at_utc": _utc_now_iso(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return os.getpid(), owner_path


def _clear_owner(owner_path: Path) -> None:
    try:
        owner_path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        # Owner file is best-effort cleanup; if removal fails the
        # next holder's stale-PID recovery will sweep it.
        if exc.errno != errno.ENOENT:
            raise


@contextmanager
def advisory_lock(
    lock_dir: str | Path,
    *,
    kind: str,
    lock_timeout_seconds: float = 0.0,
) -> Iterator[None]:
    """Hold the audit lock for the duration of the ``with`` block.

    Raises ``LockFailure`` if the lock cannot be acquired within
    ``lock_timeout_seconds`` (or immediately when the timeout is
    ``0.0`` and the lock is held).
    """
    lock_dir = Path(lock_dir)
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / LOCK_FILENAME
    owner_path = lock_dir / OWNER_FILENAME

    deadline = time.monotonic() + max(0.0, float(lock_timeout_seconds))
    attempts = 0

    while True:
        attempts += 1
        # Layer 1: try to atomically claim the owner sentinel. If it
        # exists and the recorded PID is no longer alive, sweep it
        # and retry.
        if owner_path.exists():
            holder = _read_owner(owner_path)
            if holder is not None and not _pid_alive(holder.pid):
                # Stale owner; recover.
                _clear_owner(owner_path)
                continue
            if holder is not None and holder.pid == os.getpid():
                # We already own it from a prior loop; fall through.
                pass
            else:
                if time.monotonic() >= deadline:
                    raise LockFailure(
                        f"audit lock held by pid={holder.pid if holder else '?'} "
                        f"kind={holder.kind if holder else '?'}; "
                        f"timed out after {lock_timeout_seconds}s"
                    )
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

        try:
            _acquire_sentinel(lock_dir, kind)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise LockFailure(
                    f"audit lock owner sentinel already exists at {owner_path}"
                )
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        except OSError as exc:
            raise LockFailure(f"failed to create lock owner: {exc}") from exc

        # Layer 2: flock the lock file. The owner sentinel is ours;
        # the flock keeps a second observer from racing with us in
        # the same process. flock itself is advisory but combined
        # with the O_EXCL sentinel it is robust.
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                    _clear_owner(owner_path)
                    if time.monotonic() >= deadline:
                        raise LockFailure(
                            f"audit lock file held; timed out after {lock_timeout_seconds}s"
                        )
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue
                raise LockFailure(f"flock failed: {exc}") from exc
        except Exception:
            os.close(lock_fd)
            raise
        break

    try:
        yield
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(lock_fd)
        except OSError:
            pass
        _clear_owner(owner_path)
