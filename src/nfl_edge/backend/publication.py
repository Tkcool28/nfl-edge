"""Atomic last-good product storage and publication metadata for backend V1."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from nfl_edge.contracts.live_product_v1 import validate_product_snapshot
from nfl_edge.publication.live_product_v1 import promote_validated_snapshot

STATUS_FILE = "publication-status-v1.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}-", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _fsync_dir(path.parent)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


class ProductStore:
    """Readers always see one fully validated immutable product version."""

    def __init__(self, publication_dir: str | Path) -> None:
        self.root = Path(publication_dir)
        self.latest_path = self.root / "latest.json"
        self.status_path = self.root / STATUS_FILE
        self._lock = threading.RLock()
        self._snapshot: dict[str, Any] | None = None

    def _read_status(self) -> dict[str, Any]:
        if not self.status_path.exists():
            return {
                "last_publication_attempt": None,
                "last_successful_publication": None,
                "last_failure": None,
            }
        try:
            raw = json.loads(self.status_path.read_text(encoding="utf-8"))
            return dict(raw) if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            return {
                "last_publication_attempt": None,
                "last_successful_publication": None,
                "last_failure": {"at": _now(), "type": "STATUS_METADATA_UNREADABLE"},
            }

    def load_latest(self, *, required: bool = False) -> dict[str, Any] | None:
        if not self.latest_path.exists():
            if required:
                raise FileNotFoundError(self.latest_path)
            return None
        payload = json.loads(self.latest_path.read_text(encoding="utf-8"))
        validated = validate_product_snapshot(payload)
        with self._lock:
            self._snapshot = validated
            return deepcopy(validated)

    def snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            return deepcopy(self._snapshot) if self._snapshot is not None else None

    def publish(self, candidate: Mapping[str, Any]) -> Path:
        attempt = _now()
        before = self._read_status()
        status = {
            **before,
            "last_publication_attempt": attempt,
        }
        try:
            immutable = promote_validated_snapshot(candidate, self.root)
            validated = validate_product_snapshot(candidate)
        except Exception as exc:
            status["last_failure"] = {
                "at": attempt,
                "type": type(exc).__name__,
                "message": str(exc)[:500],
            }
            _atomic_json(self.status_path, status)
            raise

        success = _now()
        status.update(
            last_successful_publication=success,
            product_version=str(validated["product_version"]),
            generated_at_utc=str(validated["generated_at_utc"]),
            prediction_as_of_utc=str(validated["prediction_as_of_utc"]),
            football_data_version=str(validated["football_data_version"]),
            qb_snapshot_version=str(validated["qb_snapshot_version"]),
            market_snapshot_version=str(validated["market_snapshot_version"]),
            freshness=deepcopy(validated["freshness"]),
            stale=bool(validated["stale"]),
            immutable_snapshot=str(immutable.name),
            last_failure=None,
        )
        _atomic_json(self.status_path, status)
        with self._lock:
            self._snapshot = deepcopy(validated)
        return immutable

    def metadata(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        status = self._read_status()
        if snapshot is None:
            return {**status, "product_available": False}
        generated = datetime.fromisoformat(str(snapshot["generated_at_utc"])[:-1] + "+00:00")
        age = max(0.0, (datetime.now(timezone.utc) - generated).total_seconds())
        threshold = float(snapshot["freshness"]["threshold_seconds"])
        if age <= threshold:
            runtime_state = "FRESH"
        elif age <= threshold * 2.0:
            runtime_state = "AGING"
        else:
            runtime_state = "STALE"
        return {
            **status,
            "product_available": True,
            "product_version": snapshot["product_version"],
            "generated_at_utc": snapshot["generated_at_utc"],
            "prediction_as_of_utc": snapshot["prediction_as_of_utc"],
            "football_data_version": snapshot["football_data_version"],
            "qb_snapshot_version": snapshot["qb_snapshot_version"],
            "market_snapshot_version": snapshot["market_snapshot_version"],
            "runtime_age_seconds": age,
            "runtime_freshness_state": runtime_state,
            "stale": runtime_state == "STALE" or bool(snapshot["stale"]),
        }