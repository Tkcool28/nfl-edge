"""Environment-backed settings for the NFL EDGE backend V1."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class BackendSettings:
    host: str = "127.0.0.1"
    port: int = 8769
    db_path: Path = Path("data/runtime/backend/nfl_edge_users_v1.sqlite3")
    product_dir: Path = Path("data/runtime/product_v1")
    decision_state_path: Path = Path("data/live/2026/entering_product_state_v1.json")
    session_lifetime_seconds: int = 30 * 24 * 60 * 60
    cookie_name: str = "nfl_edge_session"
    cookie_secure: bool = True
    cookie_samesite: str = "lax"
    allowed_origin: str | None = None
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "testserver")
    auth_rate_limit_per_minute: int = 10

    @classmethod
    def from_env(cls) -> "BackendSettings":
        hosts = tuple(
            item.strip()
            for item in os.getenv("NFL_EDGE_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
            if item.strip()
        )
        origin = os.getenv("NFL_EDGE_ALLOWED_ORIGIN")
        return cls(
            host=os.getenv("NFL_EDGE_BACKEND_HOST", "127.0.0.1"),
            port=int(os.getenv("NFL_EDGE_BACKEND_PORT", "8769")),
            db_path=Path(os.getenv("NFL_EDGE_DB_PATH", "data/runtime/backend/nfl_edge_users_v1.sqlite3")),
            product_dir=Path(os.getenv("NFL_EDGE_PRODUCT_DIR", "data/runtime/product_v1")),
            decision_state_path=Path(
                os.getenv("NFL_EDGE_DECISION_STATE_PATH", "data/live/2026/entering_product_state_v1.json")
            ),
            session_lifetime_seconds=int(os.getenv("NFL_EDGE_SESSION_LIFETIME_SECONDS", str(30 * 24 * 60 * 60))),
            cookie_name=os.getenv("NFL_EDGE_SESSION_COOKIE", "nfl_edge_session"),
            cookie_secure=_bool("NFL_EDGE_COOKIE_SECURE", True),
            cookie_samesite=os.getenv("NFL_EDGE_COOKIE_SAMESITE", "lax").lower(),
            allowed_origin=origin.strip() if origin and origin.strip() else None,
            allowed_hosts=hosts or ("localhost", "127.0.0.1", "testserver"),
            auth_rate_limit_per_minute=int(os.getenv("NFL_EDGE_AUTH_RATE_LIMIT_PER_MINUTE", "10")),
        )