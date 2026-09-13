"""Authenticated staging boundary for ChatGPT-authored NFL EDGE Daily News submissions."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

SUBMISSION_SCHEMA_VERSION = "NFL_EDGE_DAILY_NEWS_EDITORIAL_SUBMISSION_V1"
MAX_SUBMISSION_BYTES = 1_500_000
_ROOT = Path(__file__).resolve().parents[3]
_SUBMISSION_SCHEMA = _ROOT / "schemas" / "NFL_EDGE_DAILY_NEWS_EDITORIAL_SUBMISSION_V1.schema.json"
_ARTICLE_SCHEMA = _ROOT / "schemas" / "NFL_EDGE_DAILY_NEWS_V1.schema.json"


def _schema(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(payload)
    return payload


def validate_editorial_submission(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(payload)
    try:
        Draft202012Validator(_schema(_SUBMISSION_SCHEMA)).validate(value)
        Draft202012Validator(_schema(_ARTICLE_SCHEMA)).validate(value["article"])
    except (OSError, ValueError, SchemaError, ValidationError) as exc:
        raise ValueError(f"editorial submission schema validation failed: {exc}") from exc
    evidence_by_id = {
        str(item.get("evidence_id")): item
        for item in value.get("evidence", [])
        if isinstance(item, dict) and item.get("evidence_id")
    }
    for evidence_id, evidence in evidence_by_id.items():
        sources = evidence.get("sources")
        if not isinstance(sources, list):
            raise ValueError(f"evidence {evidence_id} sources must be a list")
        if evidence.get("verification") != "INTERNAL_CANONICAL" and not sources:
            raise ValueError(f"external evidence {evidence_id} must include at least one source")
    for section in value["article"].get("sections", []):
        if not isinstance(section, dict):
            continue
        for item in section.get("items", []):
            if not isinstance(item, dict):
                continue
            evidence_ids = [str(x) for x in item.get("evidence_ids", [])]
            external_ids = [
                evidence_id
                for evidence_id in evidence_ids
                if evidence_id in evidence_by_id
                and evidence_by_id[evidence_id].get("verification") != "INTERNAL_CANONICAL"
            ]
            if external_ids and not item.get("sources"):
                raise ValueError(
                    "article items citing external evidence must include at least one cited source"
                )

    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_SUBMISSION_BYTES:
        raise ValueError("editorial submission exceeds size limit")
    return value


def require_bearer(authorization: str | None, expected_token: str) -> None:
    if not expected_token:
        raise RuntimeError("editorial ingest is not configured")
    prefix = "Bearer "
    supplied = authorization[len(prefix):] if authorization and authorization.startswith(prefix) else ""
    if not supplied or not secrets.compare_digest(supplied, expected_token):
        raise PermissionError("invalid editorial token")


def parse_strict_json(raw: bytes) -> dict[str, Any]:
    """Decode one bounded JSON object without duplicate keys or non-finite values."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid JSON constant: {value}")),
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid editorial JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("editorial submission must be a JSON object")
    return value


def _atomic_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}-", delete=False) as handle:
            temp = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def stage_editorial_submission(path: Path, payload: Mapping[str, Any]) -> dict[str, str]:
    value = validate_editorial_submission(payload)
    raw = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    _atomic_bytes(path, raw)
    return {"submission_sha256": digest}
