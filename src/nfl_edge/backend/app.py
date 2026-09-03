"""Final FastAPI entrypoint with auth-response hardening over the backend V1 core."""
from __future__ import annotations

import secrets
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import Body, FastAPI, HTTPException, Request, Response

from . import _base_app as _base
from .settings import BackendSettings


def _drop_route(app: FastAPI, path: str, method: str) -> None:
    wanted = method.upper()
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and wanted in (getattr(route, "methods", None) or set())
        )
    ]


def create_app(settings: BackendSettings | None = None) -> FastAPI:
    """Build the backend and normalize all credential failures to one response."""
    app = _base.create_app(settings)
    active_settings: BackendSettings = app.state.settings
    db = app.state.db

    # The core route already uses Argon2id and server-side opaque sessions. Replace
    # only login parsing so invalid-looking credentials cannot reveal which side
    # of the credential pair failed validation.
    _drop_route(app, "/api/v1/auth/login", "POST")
    hasher = PasswordHasher()
    dummy_hash = hasher.hash("nfl-edge-login-dummy-credential-v1")
    limiter = _base._AuthLimiter(active_settings.auth_rate_limit_per_minute)

    @app.post("/api/v1/auth/login")
    def login(request: Request, response: Response, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        ip = request.client.host if request.client else "unknown"
        if not limiter.allow(f"login:{ip}"):
            raise HTTPException(429, "too many authentication attempts")
        if set(payload) != {"username", "password"}:
            raise HTTPException(422, "login requires username and password")

        username_raw = payload.get("username")
        password_raw = payload.get("password")
        normalized: str | None = None
        if isinstance(username_raw, str):
            display = username_raw.strip()
            if _base.USERNAME_RE.fullmatch(display):
                normalized = display.casefold()

        # Bound hostile payloads without exposing whether the username exists.
        if not isinstance(password_raw, str) or len(password_raw) > _base.PASSWORD_MAX_LENGTH:
            raise HTTPException(401, "invalid credentials")

        user = db.get_user_by_username_norm(normalized) if normalized is not None else None
        password_hash = str(user["password_hash"]) if user is not None else dummy_hash
        try:
            valid = hasher.verify(password_hash, password_raw)
        except (VerifyMismatchError, VerificationError):
            valid = False
        if user is None or not valid:
            raise HTTPException(401, "invalid credentials")

        token = secrets.token_urlsafe(32)
        db.create_session(
            user_id=str(user["user_id"]),
            token_hash=_base._token_hash(token),
            expires_at=_base._expires(active_settings.session_lifetime_seconds),
        )
        response.set_cookie(
            key=active_settings.cookie_name,
            value=token,
            max_age=active_settings.session_lifetime_seconds,
            httponly=True,
            secure=active_settings.cookie_secure,
            samesite=active_settings.cookie_samesite,
            path="/",
        )
        return {
            "user": _base._profile_public(
                db.get_profile(str(user["user_id"]))
                or (_ for _ in ()).throw(RuntimeError("authenticated profile missing"))
            )
        }

    return app


app = create_app()