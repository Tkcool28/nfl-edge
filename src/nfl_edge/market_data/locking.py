"""Exclusive acquisition worker lock (fail-fast, auto-release).

Implements a single bounded exclusive lock around LIVE ``--execute``
acquisition using POSIX ``fcntl.flock``. ``flock`` is released automatically
when the owning process exits (even a crash), so there is no stale-owner
recovery problem.

Policy:

* **Dry-run never acquires the lock** — only the live execution path does.
* The lock is **fail-fast** by default (``lock_timeout_seconds=0.0``): a second
  concurrent acquisition worker raises :class:`LockFailure` immediately,
  *before* any HTTP call, instead of queueing.
* The lock releases on normal exit and on exception (context manager).
"""

from __future__ import annotations

import errno
import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

LOCK_FILENAME = "acquisition.lock"
POLL_INTERVAL_SECONDS = 0.05


class LockFailure(RuntimeError):
    """Raised when the acquisition lock cannot be acquired."""


@contextmanager
def acquisition_lock(
    lock_dir: str | Path,
    *,
    kind: str = "acquisition",
    lock_timeout_seconds: float = 0.0,
) -> Iterator[None]:
    """Hold the exclusive acquisition lock for the duration of the block.

    ``lock_timeout_seconds=0.0`` (default) fails fast if another worker holds
    the lock, so a concurrent acquisition cannot proceed.
    """
    lock_dir = Path(lock_dir)
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / LOCK_FILENAME
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    deadline = time.monotonic() + max(0.0, float(lock_timeout_seconds))
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                    raise LockFailure(f"flock failed on {lock_path}: {exc}") from exc
                if time.monotonic() >= deadline:
                    raise LockFailure(
                        f"acquisition lock held at {lock_path}; a concurrent "
                        f"worker is active (kind={kind}). Failing fast with no "
                        "API call."
                    )
                time.sleep(POLL_INTERVAL_SECONDS)
        try:
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)
    except BaseException:
        os.close(fd)
        raise
