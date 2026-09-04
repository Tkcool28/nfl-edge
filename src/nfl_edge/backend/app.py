"""Final FastAPI entrypoint with auth and duplicate-staking hardening."""
from __future__ import annotations

import secrets
from typing import Any, Callable, Mapping

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import Body, FastAPI, HTTPException, Request, Response

from . import _base_app as _base
from .settings import BackendSettings

LANE_ORDER = ("hit_rate", "balanced", "value")


def _take_route(app: FastAPI, path: str, method: str) -> Callable[..., Any]:
    wanted = method.upper()
    found: Callable[..., Any] | None = None
    kept = []
    for route in app.router.routes:
        matches = getattr(route, "path", None) == path and wanted in (getattr(route, "methods", None) or set())
        if matches:
            if found is not None:
                raise RuntimeError(f"duplicate route {method} {path}")
            found = route.endpoint
        else:
            kept.append(route)
    if found is None:
        raise RuntimeError(f"route not found {method} {path}")
    app.router.routes[:] = kept
    return found


def _headline_identity(headline: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        headline.get("game_id"),
        headline.get("market"),
        headline.get("selection"),
        headline.get("book"),
        headline.get("line"),
        headline.get("american_odds"),
    )


def _headline_duplicate_map(product: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Return primary lane by exact offer and duplicate lane -> primary lane.

    The frozen staking helper deduplicates by wager identity. Headline lane names
    are presentation roles, not wager identities, so identical BET offers that
    happen to win multiple lanes must consume only one stake slot.
    """
    primary_for_identity: dict[tuple[Any, ...], str] = {}
    duplicate_to_primary: dict[str, str] = {}
    identity_key_by_lane: dict[str, str] = {}
    for lane_key in LANE_ORDER:
        headline = product["headlines"][lane_key]
        if str(headline.get("state")) != "BET":
            continue
        identity = _headline_identity(headline)
        identity_key_by_lane[lane_key] = repr(identity)
        primary = primary_for_identity.setdefault(identity, lane_key)
        if primary != lane_key:
            duplicate_to_primary[lane_key] = primary
    return duplicate_to_primary, identity_key_by_lane


def create_app(settings: BackendSettings | None = None) -> FastAPI:
    """Build the backend and apply final transport/presentation safety guards."""
    # _base_app constructs the process-global application at import. Reuse that
    # instance for production; explicit settings always create an isolated app,
    # which is what tests and future embedding callers need.
    app = _base.app if settings is None else _base.create_app(settings)
    active_settings: BackendSettings = app.state.settings
    db = app.state.db

    core_login = _take_route(app, "/api/v1/auth/login", "POST")
    del core_login  # intentionally replaced below
    core_product_latest = _take_route(app, "/api/v1/product/latest", "GET")
    core_create_wager = _take_route(app, "/api/v1/wagers", "POST")

    # Normalize invalid-looking and ordinary wrong credentials to the same
    # generic failure. A dummy Argon2id verify also avoids a cheap username
    # existence timing oracle.
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

        # Bound hostile payloads without revealing whether the username exists.
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
        profile = db.get_profile(str(user["user_id"]))
        if profile is None:
            raise HTTPException(500, "authenticated profile missing")
        return {"user": _base._profile_public(profile)}

    @app.get("/api/v1/product/latest")
    def product_latest(request: Request) -> dict[str, Any]:
        view = core_product_latest(request)
        user = view.get("user")
        if user is None:
            return view

        product = view["product"]
        overlays = view["headline_overlays"]
        profile = db.get_profile(str(user["user_id"]))
        if profile is None:
            raise HTTPException(500, "authenticated profile missing")
        stake_profile = _base._stake_profile(profile)
        duplicate_to_primary, identity_key_by_lane = _headline_duplicate_map(product)

        # Re-apply the frozen slate-cap helper using exact wager identity rather
        # than lane identity. This preserves duplicate/conflict semantics while
        # leaving canonical units and every model/product field untouched.
        proposed: list[tuple[str, float]] = []
        seen_identity_keys: set[str] = set()
        for lane_key in LANE_ORDER:
            headline = product["headlines"][lane_key]
            overlays[lane_key]["duplicate_of_lane"] = None
            overlays[lane_key]["stake_suppressed_reason"] = None
            if str(headline.get("state")) != "BET":
                continue
            identity_key = identity_key_by_lane[lane_key]
            if identity_key in seen_identity_keys:
                continue
            seen_identity_keys.add(identity_key)
            proposed.append(
                (
                    identity_key,
                    _base.user_specific_stake(stake_profile, float(headline["recommended_units"])),
                )
            )
        capped = _base.cap_slate_stakes(stake_profile.bankroll, proposed)

        for lane_key in LANE_ORDER:
            headline = product["headlines"][lane_key]
            if str(headline.get("state")) != "BET":
                continue
            primary = duplicate_to_primary.get(lane_key)
            if primary is None:
                overlays[lane_key]["recommended_dollars"] = f"{capped[identity_key_by_lane[lane_key]]:.2f}"
                continue
            overlays[lane_key]["recommended_dollars"] = "0.00"
            overlays[lane_key]["duplicate_of_lane"] = str(product["headlines"][primary]["lane"])
            overlays[lane_key]["stake_suppressed_reason"] = "DUPLICATE_EXACT_OFFER"
            # One logged exact wager satisfies every lane that points at that
            # identical offer; do not make the UI imply a second wager is needed.
            for field in ("wager_logged", "logged_wager_id", "actual_units", "actual_dollars", "wager_status"):
                overlays[lane_key][field] = overlays[primary][field]
        return view

    @app.post("/api/v1/wagers", status_code=201)
    def create_wager(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        source_type = str(payload.get("source_type") or "HEADLINE").upper()
        if source_type == "HEADLINE":
            product = app.state.product_store.snapshot()
            if product is not None:
                requested_lane = str(payload.get("lane") or "").upper()
                lane_key = next(
                    (key for key in LANE_ORDER if str(product["headlines"][key].get("lane")) == requested_lane),
                    None,
                )
                if lane_key is not None:
                    duplicate_to_primary, _ = _headline_duplicate_map(product)
                    primary = duplicate_to_primary.get(lane_key)
                    if primary is not None:
                        primary_lane = str(product["headlines"][primary]["lane"])
                        raise HTTPException(
                            409,
                            f"duplicate headline recommendation; log the {primary_lane} card for this exact offer",
                        )
        return core_create_wager(request, payload)

    return app


app = create_app()