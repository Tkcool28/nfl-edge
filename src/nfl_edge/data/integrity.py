"""Integrity primitives shared by source retrieval and contract tests."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TEAM_ALIASES = {
    "JAC": "JAX",
    "LA": "LAR",
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LAR",
    "WAS": "WAS",
}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_schema_fingerprint(columns: list[str] | tuple[str, ...]) -> str:
    payload = json.dumps(list(columns), separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()


def normalize_team(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip().upper()
    return TEAM_ALIASES.get(token, token)


def normalize_player_id(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip()
    if not token or token.lower() in {"nan", "none", "null"}:
        return None
    token = re.sub(r"^ID", "", token, flags=re.IGNORECASE)
    return token


def utc_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def verify_manifest_file(manifest: dict[str, Any], root: str | Path = ".") -> None:
    path = Path(root) / manifest["file_name"]
    if not path.is_file():
        raise FileNotFoundError(path)
    actual_size = path.stat().st_size
    actual_sha = sha256_file(path)
    if actual_size != manifest["byte_size"]:
        raise ValueError(f"byte size mismatch for {path}: {actual_size} != {manifest['byte_size']}")
    if actual_sha != manifest["sha256"]:
        raise ValueError(f"sha256 mismatch for {path}")
