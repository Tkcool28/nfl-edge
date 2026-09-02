"""Atomic publication utility for NFL_EDGE_PRODUCT_API_V1 snapshots.

Publication is fail-closed: validate first, persist an immutable snapshot, fsync,
then atomically replace the latest pointer.  A failed candidate never replaces
an existing valid latest snapshot.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from nfl_edge.contracts.live_product_v1 import validate_product_snapshot

_SAFE_STAMP = re.compile(r"[^0-9A-Za-z_.-]+")


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def promote_validated_snapshot(candidate: Any, output_dir: str | Path) -> Path:
    """Validate, write immutable JSON, and atomically promote ``latest.json``.

    Returns the immutable snapshot path.  If validation or persistence fails,
    the pre-existing ``latest.json`` is left untouched.
    """
    validated = validate_product_snapshot(candidate)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)

    stamp = _SAFE_STAMP.sub("-", str(validated["generated_at_utc"]).replace(":", ""))
    version = _SAFE_STAMP.sub("-", str(validated["product_version"]))
    immutable = root / f"product-{stamp}-{version}.json"
    latest = root / "latest.json"
    if immutable.exists():
        raise FileExistsError(f"immutable snapshot already exists: {immutable}")

    payload = (json.dumps(validated, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(immutable, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        immutable.unlink(missing_ok=True)
        raise
    _fsync_directory(root)

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=root, prefix=".latest-", delete=False) as temp:
            temp_path = Path(temp.name)
            temp.write(payload)
            temp.flush()
            os.fsync(temp.fileno())
        os.chmod(temp_path, 0o640)
        os.replace(temp_path, latest)
        _fsync_directory(root)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
    return immutable


__all__ = ["promote_validated_snapshot"]
