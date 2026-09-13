"""Read-only loader for the independently published NFL EDGE Daily News brief."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

NEWS_SCHEMA_VERSION = "NFL_EDGE_DAILY_NEWS_V1"
MAX_NEWS_BYTES = 1_000_000
_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "NFL_EDGE_DAILY_NEWS_V1.schema.json"


def load_latest_news(path: Path) -> dict[str, Any]:
    """Load and minimally validate the latest editorial brief.

    News is intentionally downstream of the betting product. A missing or invalid
    news artifact must fail on the news endpoint only; it must never affect the
    canonical product or recommendation routes.
    """
    raw = path.read_bytes()
    if len(raw) > MAX_NEWS_BYTES:
        raise ValueError("news artifact exceeds size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("news artifact is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("news artifact must be an object")
    if payload.get("schema_version") != NEWS_SCHEMA_VERSION:
        raise ValueError("unsupported news schema")
    for field in ("published_at_utc", "title", "sections"):
        if field not in payload:
            raise ValueError(f"news artifact missing {field}")
    if not isinstance(payload["published_at_utc"], str) or not payload["published_at_utc"].strip():
        raise ValueError("published_at_utc must be a non-empty string")
    if not isinstance(payload["title"], str) or not payload["title"].strip():
        raise ValueError("title must be a non-empty string")
    if not isinstance(payload["sections"], list):
        raise ValueError("sections must be a list")
    try:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(payload)
    except (OSError, ValueError, SchemaError, ValidationError) as exc:
        raise ValueError(f"news artifact schema validation failed: {exc}") from exc
    return payload
