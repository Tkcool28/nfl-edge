"""Deterministic SHA-256 hashing for Task 03A artifacts.

Fingerprints are computed from logical content only. Filesystem mtime, mode
flags, and the current wall clock are never consulted. The same inputs
therefore produce the same fingerprint in any clean checkout regardless of
when the run is executed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

# The values pl/numpy may inject (NaN, Inf, datetime, etc.) are normalized
# through ``default=str`` so the canonical serialization is portable.


def canonical_json_sha256(value: object) -> str:
    """Stable SHA-256 of a JSON-serializable Python object.

    Keys are sorted, separators are fixed, and ``default=str`` is used so
    datetime/Path/Decimal values become their canonical textual form. The
    output is the lowercase hex digest."""

    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str | Path, chunk_bytes: int = 1024 * 1024) -> str:
    """Hex SHA-256 of the bytes of ``path``. The function never reads mtime
    or metadata, only the file content. Used for ledger/artifact pinning."""

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_bytes), b""):
            digest.update(chunk)
    return digest.hexdigest()


def code_fingerprint(paths: list[str | Path], root: str | Path) -> str:
    """Deterministic SHA-256 over a sorted set of repository-relative files.

    The list of paths is sorted by their repository-relative posix form so
    the output is stable across runners. Each path contributes its relative
    name, a newline, and the raw file bytes. The function reads bytes only
    (no metadata) and never touches the current time."""

    root_path = Path(root)
    sorted_paths = sorted(
        (Path(path) for path in paths),
        key=lambda candidate: candidate.resolve().relative_to(root_path).as_posix(),
    )
    digest = hashlib.sha256()
    for path in sorted_paths:
        resolved = path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"code_fingerprint input not found: {resolved}")
        relative = resolved.relative_to(root_path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\n")
        digest.update(resolved.read_bytes())
        digest.update(b"\n")
    return digest.hexdigest()
