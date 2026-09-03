"""FastAPI application for persistent NFL EDGE users, wagers, and product serving V1."""
from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import Body, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from nfl_edge.contracts.common_v1 import USER_STATE_SCHEMA_VERSION
from nfl_edge.contracts.user_state_v1 import RISK_PROFILES, UserProfileState, user_specific_stake
from nfl_edge.staking_policy_v1 import cap_slate_stakes

from .db import BackendDatabase, WAGER_STATUSES, cents_to_usd, utc_now
from .exact_offer import ExactOfferEngine, ExactOfferError
from .publication import ProductStore
from .settings import BackendSettings

USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$")
PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 256
MAX_MONEY = Decimal("1000000000.00")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _money_to_cents(value: Any, field: str, *, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool):
        raise HTTPException(422, f"{field} must be a USD decimal")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise HTTPException(422, f"{field} must be a USD decimal") from None
    if not amount.is_finite():
        raise HTTPException(422, f"{field} must be finite")
    if amount < 0 or amount > MAX_MONEY:
        raise HTTPException(422, f"{field} must be between 0.00 and {MAX_MONEY}")
    if amount.as_tuple().exponent < -2:
        raise HTTPException(422, f"{field} must have at most two decimal places")
    return int(amount * 100)


def _actual_units(value: Any, *, nullable: bool = True) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool):
        raise HTTPException(422, "actual_units must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(422, "actual_units must be finite and non-negative") from None
    if not math.isfinite(number) or number < 0:
        raise HTTPException(422, "actual_units must be finite and non-negative")
    return number


def _username(value: Any) -> tuple[str, str]:
    if not isinstance(value, str):
        raise HTTPException(422, "username must be a string")
    display = value.strip()
    if not USERNAME_RE.fullmatch(display):
        raise HTTPException(
            422,
            "username must be 3-32 ASCII characters, start alphanumeric, and use only letters, digits, '.', '_' or '-'",
        )
    return display, display.casefold()


def _password(value: Any) -> str:
    if not isinstance(value, str):
        raise HTTPException(422, "password must be a string")
    if len(value) < PASSWORD_MIN_LENGTH or len(value) > PASSWORD_MAX_LENGTH:
        raise HTTPException(422, f"password length must be {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} characters")
    return value


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _expires(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=int(seconds))).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _profile_public(profile: Mapping[str, Any]) -> dict[str, Any]:
    validated = UserProfileState(
        user_id=str(profile["user_id"]),
        bankroll=float(int(profile["bankroll_cents"]) / 100.0),
        risk_profile=str(profile["risk_profile"]),
        created_at=str(profile["created_at"]),
        updated_at=str(profile["updated_at"]),
    ).validate()
    payload = {
        "schema_version": USER_STATE_SCHEMA_VERSION,
        "user_id": validated.user_id,
        "username": str(profile["username"]),
        "bankroll": cents_to_usd(int(profile["bankroll_cents"])),
        "risk_profile": validated.risk_profile,
        "created_at": validated.created_at,
        "updated_at": validated.updated_at,
    }
    if set(payload) != {"schema_version", "user_id", "username", "bankroll", "risk_profile", "created_at", "updated_at"}:
        raise RuntimeError("NFL_EDGE_USER_STATE_V1 response contract drift")
    return payload


def _stake_profile(profile: Mapping[str, Any]) -> UserProfileState:
    return UserProfileState(
        user_id=str(profile["user_id"]),
        bankroll=float(int(profile["bankroll_cents"]) / 100.0),
        risk_profile=str(profile["risk_profile"]),
        created_at=str(profile["created_at"]),
        updated_at=str(profile["updated_at"]),
    ).validate()


class _AuthLimiter:
    def __init__(self, per_minute: int) -> None:
        self.limit = max(1, int(per_minute))
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._events[key]
            while bucket and now - bucket[0] >= 60.0:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True


def create_app(settings: BackendSettings | None = None) -> FastAPI:
    settings = settings or BackendSettings.from_env()
    if settings.cookie_samesite not in {"lax", "strict", "none"}:
        raise ValueError("cookie_samesite must be lax, strict, or none")
    db = BackendDatabase(settings.db_path)
    db.initialize()
    store = ProductStore(settings.product_dir)
    store.root.mkdir(parents=True, exist_ok=True)
    store.load_latest(required=False)
    exact = ExactOfferEngine(settings.decision_state_path)
    hasher = PasswordHasher()
    limiter = _AuthLimiter(settings.auth_rate_limit_per_minute)

    app = FastAPI(title="NFL EDGE Backend V1", version="1.0")
    app.state.settings = settings
    app.state.db = db
    app.state.product_store = store
    app.state.exact_offer_engine = exact

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
    if settings.allowed_origin:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[settings.allowed_origin],
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
            allow_headers=["Content-Type", "Idempotency-Key"],
        )

    @app.middleware("http")
    async def csrf_origin_guard(request: Request, call_next):
        if request.method not in SAFE_METHODS and request.cookies.get(settings.cookie_name):
            origin = request.headers.get("origin")
            if origin:
                expected = settings.allowed_origin or f"{request.url.scheme}://{request.headers.get('host', '')}"
                if origin.rstrip("/") != expected.rstrip("/"):
                    return JSONResponse({"detail": "origin rejected"}, status_code=403)
        return await call_next(request)

    def optional_user(request: Request) -> dict[str, Any] | None:
        token = request.cookies.get(settings.cookie_name)
        if not token:
            return None
        return db.resolve_session(token_hash=_token_hash(token), now=utc_now())

    def require_user(request: Request) -> dict[str, Any]:
        user = optional_user(request)
        if user is None:
            raise HTTPException(401, "authentication required")
        return user

    def issue_session(response: Response, user_id: str) -> None:
        token = secrets.token_urlsafe(32)
        db.create_session(user_id=user_id, token_hash=_token_hash(token), expires_at=_expires(settings.session_lifetime_seconds))
        response.set_cookie(
            key=settings.cookie_name,
            value=token,
            max_age=settings.session_lifetime_seconds,
            httponly=True,
            secure=settings.cookie_secure,
            samesite=settings.cookie_samesite,
            path="/",
        )

    def current_product() -> dict[str, Any]:
        product = store.snapshot()
        if product is None:
            raise HTTPException(503, "no validated product is currently available")
        return product

    def profile_for_user(user_id: str) -> dict[str, Any]:
        profile = db.get_profile(user_id)
        if profile is None:
            raise HTTPException(500, "authenticated profile missing")
        return profile

    def headline_overlays(product: Mapping[str, Any], user: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
        overlays = {
            key: {
                "recommended_dollars": None,
                "wager_logged": False,
                "logged_wager_id": None,
                "actual_units": None,
                "actual_dollars": None,
                "wager_status": None,
            }
            for key in ("hit_rate", "balanced", "value")
        }
        if user is None:
            return overlays, None
        profile = profile_for_user(str(user["user_id"]))
        stake_profile = _stake_profile(profile)
        proposed: list[tuple[str, float]] = []
        for key in ("hit_rate", "balanced", "value"):
            headline = product["headlines"][key]
            if str(headline["state"]) == "BET":
                proposed.append((key, user_specific_stake(stake_profile, float(headline["recommended_units"]))))
        capped = cap_slate_stakes(stake_profile.bankroll, proposed)
        for key, amount in capped.items():
            overlays[key]["recommended_dollars"] = f"{amount:.2f}"

        wagers = db.list_wagers(user_id=str(user["user_id"]), product_version=str(product["product_version"]))
        for key in ("hit_rate", "balanced", "value"):
            headline = product["headlines"][key]
            for wager in wagers:
                if (
                    wager["source_type"] == "HEADLINE"
                    and wager.get("lane") == headline.get("lane")
                    and wager["game_id"] == headline.get("game_id")
                    and wager["market_type"] == headline.get("market")
                    and wager["selection"] == headline.get("selection")
                    and wager["book"] == headline.get("book")
                    and wager["price"] == headline.get("american_odds")
                    and wager.get("line") == headline.get("line")
                ):
                    overlays[key].update(
                        wager_logged=True,
                        logged_wager_id=wager["wager_id"],
                        actual_units=wager["actual_units"],
                        actual_dollars=wager["actual_dollars"],
                        wager_status=wager["status"],
                    )
                    break
        return overlays, _profile_public(profile)

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        publication = store.metadata()
        db_ok = db.health()
        return {
            "schema_version": "NFL_EDGE_BACKEND_HEALTH_V1",
            "api_healthy": True,
            "database_healthy": db_ok,
            "product_available": bool(publication.get("product_available")),
            "product_freshness": publication.get("runtime_freshness_state"),
            "product_stale": publication.get("stale"),
            "last_publication_attempt": publication.get("last_publication_attempt"),
            "last_successful_publication": publication.get("last_successful_publication"),
            "last_refresh_failed": publication.get("last_failure") is not None,
            "last_failure": publication.get("last_failure"),
            "product_version": publication.get("product_version"),
            "generated_at_utc": publication.get("generated_at_utc"),
            "prediction_as_of_utc": publication.get("prediction_as_of_utc"),
            "football_data_version": publication.get("football_data_version"),
            "qb_snapshot_version": publication.get("qb_snapshot_version"),
            "market_snapshot_version": publication.get("market_snapshot_version"),
        }

    @app.post("/api/v1/auth/register", status_code=201)
    def register(request: Request, response: Response, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        ip = request.client.host if request.client else "unknown"
        if not limiter.allow(f"register:{ip}"):
            raise HTTPException(429, "too many authentication attempts")
        if set(payload) - {"username", "password", "display_name"}:
            raise HTTPException(422, "unknown registration field")
        username, normalized = _username(payload.get("username"))
        password = _password(payload.get("password"))
        try:
            user = db.create_user(username=username, username_norm=normalized, password_hash=hasher.hash(password))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "username unavailable") from None
        issue_session(response, str(user["user_id"]))
        return {"user": _profile_public(profile_for_user(str(user["user_id"])))}

    @app.post("/api/v1/auth/login")
    def login(request: Request, response: Response, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        ip = request.client.host if request.client else "unknown"
        if not limiter.allow(f"login:{ip}"):
            raise HTTPException(429, "too many authentication attempts")
        if set(payload) != {"username", "password"}:
            raise HTTPException(422, "login requires username and password")
        _, normalized = _username(payload.get("username"))
        password = _password(payload.get("password"))
        user = db.get_user_by_username_norm(normalized)
        if user is None:
            raise HTTPException(401, "invalid credentials")
        try:
            valid = hasher.verify(str(user["password_hash"]), password)
        except (VerifyMismatchError, VerificationError):
            valid = False
        if not valid:
            raise HTTPException(401, "invalid credentials")
        issue_session(response, str(user["user_id"]))
        return {"user": _profile_public(profile_for_user(str(user["user_id"])))}

    @app.post("/api/v1/auth/logout", status_code=204)
    def logout(request: Request, response: Response) -> Response:
        token = request.cookies.get(settings.cookie_name)
        if token:
            db.revoke_session(token_hash=_token_hash(token))
        response.delete_cookie(settings.cookie_name, path="/", secure=settings.cookie_secure, httponly=True, samesite=settings.cookie_samesite)
        response.status_code = 204
        return response

    @app.get("/api/v1/auth/me")
    def me(request: Request) -> dict[str, Any]:
        user = require_user(request)
        return {"user": _profile_public(profile_for_user(str(user["user_id"])))}

    @app.get("/api/v1/profile")
    def get_profile(request: Request) -> dict[str, Any]:
        user = require_user(request)
        return _profile_public(profile_for_user(str(user["user_id"])))

    @app.put("/api/v1/profile")
    def put_profile(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        user = require_user(request)
        if set(payload) - {"bankroll", "risk_profile"} or not set(payload):
            raise HTTPException(422, "profile update accepts bankroll and/or risk_profile only")
        current = profile_for_user(str(user["user_id"]))
        bankroll_cents = int(current["bankroll_cents"])
        risk = str(current["risk_profile"])
        if "bankroll" in payload:
            parsed = _money_to_cents(payload["bankroll"], "bankroll")
            assert parsed is not None
            bankroll_cents = parsed
        if "risk_profile" in payload:
            risk = str(payload["risk_profile"])
            if risk not in RISK_PROFILES:
                raise HTTPException(422, f"risk_profile must be one of {RISK_PROFILES}")
        updated = db.update_profile(user_id=str(user["user_id"]), bankroll_cents=bankroll_cents, risk_profile=risk)
        return _profile_public(updated)

    @app.get("/api/v1/product/latest")
    def product_latest(request: Request) -> dict[str, Any]:
        product = current_product()
        overlays, public_user = headline_overlays(product, optional_user(request))
        return {
            "schema_version": "NFL_EDGE_PRODUCT_VIEW_V1",
            "product": product,
            "user": public_user,
            "headline_overlays": overlays,
        }

    @app.get("/api/v1/games")
    def games() -> dict[str, Any]:
        product = current_product()
        return {"product_version": product["product_version"], "games": product["games"]}

    @app.get("/api/v1/games/{game_id}")
    def game(game_id: str) -> dict[str, Any]:
        product = current_product()
        for row in product["games"]:
            if str(row["game_id"]) == game_id:
                return {"product_version": product["product_version"], "game": row}
        raise HTTPException(404, "game not found")

    @app.post("/api/v1/evaluate-offer")
    def evaluate_offer_endpoint(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        product = current_product()
        try:
            evaluation, context = exact.evaluate(product, payload)
        except (ExactOfferError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from None
        user = optional_user(request)
        recommended_dollars = None
        public_user = None
        if user is not None:
            profile = profile_for_user(str(user["user_id"]))
            public_user = _profile_public(profile)
            if evaluation["verdict"] == "BET" and float(evaluation["recommended_units"]) > 0:
                amount = user_specific_stake(_stake_profile(profile), float(evaluation["recommended_units"]))
                recommended_dollars = f"{amount:.2f}"
        return {
            "schema_version": "NFL_EDGE_EXACT_OFFER_VIEW_V1",
            "product_version": product["product_version"],
            "evaluation": evaluation,
            "recommended_dollars": recommended_dollars,
            "user": public_user,
            "provenance": {"state_version": context.get("state_version"), "evaluator_version": context.get("evaluator_version")},
        }

    @app.get("/api/v1/wagers")
    def wagers(
        request: Request,
        state: str | None = Query(default=None),
        game_id: str | None = Query(default=None),
        week: int | None = Query(default=None),
    ) -> dict[str, Any]:
        user = require_user(request)
        if state is not None and state not in {"open", "settled"}:
            raise HTTPException(422, "state must be open or settled")
        return {"wagers": db.list_wagers(user_id=str(user["user_id"]), state=state, game_id=game_id, week=week)}

    @app.get("/api/v1/wagers/{wager_id}")
    def wager(request: Request, wager_id: str) -> dict[str, Any]:
        user = require_user(request)
        found = db.get_wager(user_id=str(user["user_id"]), wager_id=wager_id)
        if found is None:
            raise HTTPException(404, "wager not found")
        return found

    @app.post("/api/v1/wagers", status_code=201)
    def create_wager(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        user = require_user(request)
        allowed = {
            "source_type", "product_version", "lane", "exact_offer", "actual_units", "actual_dollars",
            "status", "note", "idempotency_key"
        }
        if set(payload) - allowed:
            raise HTTPException(422, "unknown wager field")
        product = current_product()
        if str(payload.get("product_version") or "") != str(product["product_version"]):
            raise HTTPException(409, "product version is obsolete; refresh before logging wager")
        source_type = str(payload.get("source_type") or "HEADLINE").upper()
        if source_type not in {"HEADLINE", "EXACT_OFFER"}:
            raise HTTPException(422, "source_type must be HEADLINE or EXACT_OFFER")
        status = str(payload.get("status") or "OPEN").upper()
        if status not in WAGER_STATUSES:
            raise HTTPException(422, f"status must be one of {sorted(WAGER_STATUSES)}")
        actual_units = _actual_units(payload.get("actual_units"), nullable=True)
        actual_dollars_cents = _money_to_cents(payload.get("actual_dollars"), "actual_dollars", nullable=True)
        note = payload.get("note")
        if note is not None:
            if not isinstance(note, str) or len(note) > 2000:
                raise HTTPException(422, "note must be a string up to 2000 characters")
        idempotency_key = payload.get("idempotency_key") or request.headers.get("Idempotency-Key")
        if idempotency_key is not None:
            if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
                raise HTTPException(422, "idempotency key must be 1-128 characters")

        games_by_id = {str(game["game_id"]): game for game in product["games"]}
        profile = profile_for_user(str(user["user_id"]))
        generated = str(product["generated_at_utc"])
        lane = None
        play_through = None
        value_at = None
        provenance: dict[str, Any]

        if source_type == "HEADLINE":
            requested_lane = str(payload.get("lane") or "").upper()
            headline = next((row for row in product["headlines"].values() if row["lane"] == requested_lane), None)
            if headline is None:
                raise HTTPException(422, "lane must identify a current headline")
            if headline["state"] != "BET":
                raise HTTPException(409, "current headline is not a BET; refresh/evaluate the exact offer instead")
            lane = requested_lane
            game_row = games_by_id[str(headline["game_id"])]
            overlays, _ = headline_overlays(product, user)
            overlay_key = {"HIT_RATE": "hit_rate", "BALANCED": "balanced", "VALUE": "value"}[requested_lane]
            dollars_text = overlays[overlay_key]["recommended_dollars"] or "0.00"
            recommended_dollars_cents = _money_to_cents(dollars_text, "recommended_dollars")
            context = {
                "game_id": headline["game_id"],
                "kickoff_at_utc": game_row["kickoff_at_utc"],
                "market_type": headline["market"],
                "selection": headline["selection"],
                "book": headline["book"],
                "line": headline["line"],
                "price": headline["american_odds"],
                "recommendation_state": headline["state"],
                "recommended_units": headline["recommended_units"],
            }
            play_through = headline["play_through"]
            value_at = headline["value_at"]
            provenance = {
                "source": "current_headline",
                "headline": headline,
                "prediction_as_of_utc": product["prediction_as_of_utc"],
                "football_data_version": product["football_data_version"],
                "qb_snapshot_version": product["qb_snapshot_version"],
                "market_snapshot_version": product["market_snapshot_version"],
            }
        else:
            exact_offer = payload.get("exact_offer")
            if not isinstance(exact_offer, Mapping):
                raise HTTPException(422, "exact_offer object is required for EXACT_OFFER source_type")
            try:
                evaluation, exact_context = exact.evaluate(product, exact_offer)
            except (ExactOfferError, ValueError) as exc:
                raise HTTPException(422, str(exc)) from None
            game_row = games_by_id[str(exact_offer["game_id"])]
            dollars = 0.0
            if evaluation["verdict"] == "BET" and float(evaluation["recommended_units"]) > 0:
                dollars = user_specific_stake(_stake_profile(profile), float(evaluation["recommended_units"]))
            recommended_dollars_cents = int(Decimal(str(dollars)) * 100)
            context = {
                "game_id": exact_offer["game_id"],
                "kickoff_at_utc": game_row["kickoff_at_utc"],
                "market_type": exact_offer["market_type"],
                "selection": exact_offer["selection"],
                "book": exact_offer["book"],
                "line": exact_offer["line"],
                "price": exact_offer["price"],
                "recommendation_state": evaluation["verdict"],
                "recommended_units": evaluation["recommended_units"],
            }
            play_through = evaluation["play_through"]
            value_at = evaluation["value_at"]
            provenance = {
                "source": "exact_offer_evaluation",
                "evaluation": evaluation,
                "evaluation_context": exact_context,
                "prediction_as_of_utc": product["prediction_as_of_utc"],
                "football_data_version": product["football_data_version"],
                "qb_snapshot_version": product["qb_snapshot_version"],
                "market_snapshot_version": product["market_snapshot_version"],
            }

        request_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        now = utc_now()
        row = {
            "wager_id": str(uuid.uuid4()),
            "user_id": str(user["user_id"]),
            "created_at": now,
            "updated_at": now,
            "source_type": source_type,
            "product_version": str(product["product_version"]),
            "generated_at_utc": generated,
            "season": int(product["season"]),
            "week": int(product["week"]),
            "game_id": str(context["game_id"]),
            "kickoff_at_utc": str(context["kickoff_at_utc"]),
            "lane": lane,
            "market_type": str(context["market_type"]),
            "selection": str(context["selection"]),
            "book": str(context["book"]),
            "line": context["line"],
            "price": int(context["price"]),
            "recommendation_state": str(context["recommendation_state"]),
            "recommended_units": float(context["recommended_units"]),
            "recommended_dollars_cents": int(recommended_dollars_cents or 0),
            "actual_units": actual_units,
            "actual_dollars_cents": actual_dollars_cents,
            "play_through_json": json.dumps(play_through, sort_keys=True) if play_through is not None else None,
            "value_at_json": json.dumps(value_at, sort_keys=True) if value_at is not None else None,
            "status": status,
            "note": note,
            "provenance_json": json.dumps(provenance, sort_keys=True, allow_nan=False),
            "idempotency_key": idempotency_key,
            "idempotency_hash": request_hash if idempotency_key else None,
        }
        try:
            created, replayed = db.create_wager(row)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return {"wager": created, "idempotent_replay": replayed}

    @app.patch("/api/v1/wagers/{wager_id}")
    def patch_wager(request: Request, wager_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        user = require_user(request)
        allowed = {"actual_units", "actual_dollars", "status", "note"}
        if set(payload) - allowed:
            raise HTTPException(422, "only actual_units, actual_dollars, status, and note are editable")
        status = None
        if "status" in payload:
            status = str(payload["status"]).upper()
            if status not in WAGER_STATUSES:
                raise HTTPException(422, f"status must be one of {sorted(WAGER_STATUSES)}")
        note = payload.get("note")
        if "note" in payload and note is not None and (not isinstance(note, str) or len(note) > 2000):
            raise HTTPException(422, "note must be a string up to 2000 characters")
        updated = db.patch_wager(
            user_id=str(user["user_id"]),
            wager_id=wager_id,
            actual_units=_actual_units(payload.get("actual_units"), nullable=True) if "actual_units" in payload else None,
            actual_dollars_cents=(
                _money_to_cents(payload.get("actual_dollars"), "actual_dollars", nullable=True)
                if "actual_dollars" in payload else None
            ),
            status=status,
            note=note,
            supplied=set(payload),
        )
        if updated is None:
            raise HTTPException(404, "wager not found")
        return updated

    return app


app = create_app()