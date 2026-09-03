"""Durable SQLite persistence for NFL EDGE backend V1."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

WAGER_STATUSES = frozenset({"OPEN", "WON", "LOST", "PUSH", "VOID", "CANCELLED"})
SETTLED_WAGER_STATUSES = frozenset({"WON", "LOST", "PUSH", "VOID", "CANCELLED"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def cents_to_usd(cents: int | None) -> str | None:
    if cents is None:
        return None
    sign = "-" if cents < 0 else ""
    absolute = abs(int(cents))
    return f"{sign}{absolute // 100}.{absolute % 100:02d}"


class BackendDatabase:
    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 30_000) -> None:
        self.path = Path(path)
        self.busy_timeout_ms = int(busy_timeout_ms)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        return conn

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    username_norm TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);

                CREATE TABLE IF NOT EXISTS profiles (
                    user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                    bankroll_cents INTEGER NOT NULL DEFAULT 0 CHECK(bankroll_cents >= 0),
                    risk_profile TEXT NOT NULL DEFAULT 'Normal',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS wagers (
                    wager_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    product_version TEXT NOT NULL,
                    generated_at_utc TEXT,
                    season INTEGER,
                    week INTEGER,
                    game_id TEXT NOT NULL,
                    kickoff_at_utc TEXT,
                    lane TEXT,
                    market_type TEXT NOT NULL,
                    selection TEXT NOT NULL,
                    book TEXT NOT NULL,
                    line REAL,
                    price INTEGER NOT NULL,
                    recommendation_state TEXT NOT NULL,
                    recommended_units REAL NOT NULL,
                    recommended_dollars_cents INTEGER,
                    actual_units REAL,
                    actual_dollars_cents INTEGER,
                    play_through_json TEXT,
                    value_at_json TEXT,
                    status TEXT NOT NULL,
                    note TEXT,
                    provenance_json TEXT NOT NULL,
                    idempotency_key TEXT,
                    idempotency_hash TEXT,
                    UNIQUE(user_id, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_wagers_user_created ON wagers(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_wagers_user_status ON wagers(user_id, status);
                CREATE INDEX IF NOT EXISTS idx_wagers_user_product ON wagers(user_id, product_version);
                CREATE INDEX IF NOT EXISTS idx_wagers_user_game ON wagers(user_id, game_id);
                """
            )
            conn.commit()
        finally:
            conn.close()

    def health(self) -> bool:
        try:
            conn = self._connect()
            try:
                return conn.execute("SELECT 1").fetchone()[0] == 1
            finally:
                conn.close()
        except sqlite3.Error:
            return False

    def create_user(self, *, username: str, username_norm: str, password_hash: str) -> dict[str, Any]:
        now = utc_now()
        user_id = str(uuid.uuid4())
        with self._write() as conn:
            conn.execute(
                "INSERT INTO users(user_id, username, username_norm, password_hash, created_at, updated_at, active) "
                "VALUES(?,?,?,?,?,?,1)",
                (user_id, username, username_norm, password_hash, now, now),
            )
            conn.execute(
                "INSERT INTO profiles(user_id, bankroll_cents, risk_profile, created_at, updated_at) VALUES(?,?,?,?,?)",
                (user_id, 0, "Normal", now, now),
            )
        return self.get_user(user_id) or {}

    def get_user_by_username_norm(self, username_norm: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE username_norm=? AND active=1",
                (username_norm,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM users WHERE user_id=? AND active=1", (user_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def create_session(self, *, user_id: str, token_hash: str, expires_at: str) -> str:
        session_id = str(uuid.uuid4())
        now = utc_now()
        with self._write() as conn:
            conn.execute(
                "INSERT INTO sessions(session_id, token_hash, user_id, created_at, expires_at, last_seen_at, revoked_at) "
                "VALUES(?,?,?,?,?,?,NULL)",
                (session_id, token_hash, user_id, now, expires_at, now),
            )
        return session_id

    def resolve_session(self, *, token_hash: str, now: str) -> dict[str, Any] | None:
        with self._write() as conn:
            row = conn.execute(
                "SELECT s.session_id, s.user_id, s.expires_at, u.username, u.username_norm, u.created_at AS user_created_at "
                "FROM sessions s JOIN users u ON u.user_id=s.user_id "
                "WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.active=1",
                (token_hash, now),
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE sessions SET last_seen_at=? WHERE session_id=?", (now, row["session_id"]))
            return dict(row)

    def revoke_session(self, *, token_hash: str) -> None:
        now = utc_now()
        with self._write() as conn:
            conn.execute(
                "UPDATE sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                (now, token_hash),
            )

    def get_profile(self, user_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT p.*, u.username FROM profiles p JOIN users u ON u.user_id=p.user_id "
                "WHERE p.user_id=? AND u.active=1",
                (user_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_profile(self, *, user_id: str, bankroll_cents: int, risk_profile: str) -> dict[str, Any]:
        now = utc_now()
        with self._write() as conn:
            changed = conn.execute(
                "UPDATE profiles SET bankroll_cents=?, risk_profile=?, updated_at=? WHERE user_id=?",
                (int(bankroll_cents), risk_profile, now, user_id),
            ).rowcount
            if changed != 1:
                raise KeyError("profile not found")
        profile = self.get_profile(user_id)
        if profile is None:
            raise KeyError("profile not found")
        return profile

    def create_wager(self, row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        key = row.get("idempotency_key")
        with self._write() as conn:
            if key:
                existing = conn.execute(
                    "SELECT * FROM wagers WHERE user_id=? AND idempotency_key=?",
                    (row["user_id"], key),
                ).fetchone()
                if existing is not None:
                    if existing["idempotency_hash"] != row.get("idempotency_hash"):
                        raise ValueError("idempotency key already used with different request")
                    return self._wager_dict(existing), True
            columns = (
                "wager_id", "user_id", "created_at", "updated_at", "source_type", "product_version",
                "generated_at_utc", "season", "week", "game_id", "kickoff_at_utc", "lane", "market_type",
                "selection", "book", "line", "price", "recommendation_state", "recommended_units",
                "recommended_dollars_cents", "actual_units", "actual_dollars_cents", "play_through_json",
                "value_at_json", "status", "note", "provenance_json", "idempotency_key", "idempotency_hash"
            )
            conn.execute(
                f"INSERT INTO wagers({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                tuple(row.get(column) for column in columns),
            )
            created = conn.execute("SELECT * FROM wagers WHERE wager_id=?", (row["wager_id"],)).fetchone()
            if created is None:
                raise RuntimeError("wager insert disappeared")
            return self._wager_dict(created), False

    def get_wager(self, *, user_id: str, wager_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM wagers WHERE user_id=? AND wager_id=?",
                (user_id, wager_id),
            ).fetchone()
            return self._wager_dict(row) if row else None
        finally:
            conn.close()

    def list_wagers(
        self,
        *,
        user_id: str,
        state: str | None = None,
        game_id: str | None = None,
        week: int | None = None,
        product_version: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["user_id=?"]
        params: list[Any] = [user_id]
        if state == "open":
            clauses.append("status='OPEN'")
        elif state == "settled":
            clauses.append("status IN ('WON','LOST','PUSH','VOID','CANCELLED')")
        if game_id:
            clauses.append("game_id=?")
            params.append(game_id)
        if week is not None:
            clauses.append("week=?")
            params.append(int(week))
        if product_version:
            clauses.append("product_version=?")
            params.append(product_version)
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM wagers WHERE {' AND '.join(clauses)} ORDER BY created_at DESC, wager_id DESC",
                tuple(params),
            ).fetchall()
            return [self._wager_dict(row) for row in rows]
        finally:
            conn.close()

    def patch_wager(
        self,
        *,
        user_id: str,
        wager_id: str,
        actual_units: float | None,
        actual_dollars_cents: int | None,
        status: str | None,
        note: str | None,
        supplied: set[str],
    ) -> dict[str, Any] | None:
        updates: list[str] = []
        params: list[Any] = []
        if "actual_units" in supplied:
            updates.append("actual_units=?")
            params.append(actual_units)
        if "actual_dollars" in supplied:
            updates.append("actual_dollars_cents=?")
            params.append(actual_dollars_cents)
        if "status" in supplied:
            updates.append("status=?")
            params.append(status)
        if "note" in supplied:
            updates.append("note=?")
            params.append(note)
        if not updates:
            return self.get_wager(user_id=user_id, wager_id=wager_id)
        updates.append("updated_at=?")
        params.append(utc_now())
        params.extend([user_id, wager_id])
        with self._write() as conn:
            changed = conn.execute(
                f"UPDATE wagers SET {', '.join(updates)} WHERE user_id=? AND wager_id=?",
                tuple(params),
            ).rowcount
            if changed != 1:
                return None
            row = conn.execute(
                "SELECT * FROM wagers WHERE user_id=? AND wager_id=?", (user_id, wager_id)
            ).fetchone()
            return self._wager_dict(row) if row else None

    @staticmethod
    def _wager_dict(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        for raw, public in (
            ("recommended_dollars_cents", "recommended_dollars"),
            ("actual_dollars_cents", "actual_dollars"),
        ):
            out[public] = cents_to_usd(out.pop(raw))
        for raw, public in (
            ("play_through_json", "play_through"),
            ("value_at_json", "value_at"),
            ("provenance_json", "provenance"),
        ):
            value = out.pop(raw)
            out[public] = json.loads(value) if value else None
        out.pop("idempotency_hash", None)
        out.pop("user_id", None)
        return out