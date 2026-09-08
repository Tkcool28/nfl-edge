"""Durable SQLite persistence for NFL EDGE backend V1."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterator

WAGER_STATUSES = frozenset({"OPEN", "WON", "LOST", "PUSH", "VOID", "CANCELLED"})
SETTLED_WAGER_STATUSES = frozenset({"WON", "LOST", "PUSH", "VOID", "CANCELLED"})


class BankrollError(ValueError):
    """Raised when a wager transition would make the tracked bankroll invalid."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def cents_to_usd(cents: int | None) -> str | None:
    if cents is None:
        return None
    sign = "-" if cents < 0 else ""
    absolute = abs(int(cents))
    return f"{sign}{absolute // 100}.{absolute % 100:02d}"


def _profit_cents(stake_cents: int, price: int) -> int:
    """Return net winnings in cents using American odds and half-up cent rounding."""
    stake = Decimal(int(stake_cents))
    american = int(price)
    if american > 0:
        profit = stake * Decimal(american) / Decimal(100)
    elif american < 0:
        profit = stake * Decimal(100) / Decimal(abs(american))
    else:
        raise BankrollError("American odds cannot be zero for bankroll settlement")
    return int(profit.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _target_wager_effect_cents(*, status: str, stake_cents: int | None, price: int) -> int:
    """Cumulative bankroll effect for a wager in its current state.

    OPEN reserves the full stake. WON's cumulative effect is net profit, so an
    OPEN -> WON transition returns the full payout (stake + winnings). LOST
    keeps the stake deducted. PUSH/VOID/CANCELLED return the stake.
    """
    if stake_cents is None:
        return 0
    stake = int(stake_cents)
    state = str(status).upper()
    if state in {"OPEN", "LOST"}:
        return -stake
    if state == "WON":
        return _profit_cents(stake, int(price))
    if state in {"PUSH", "VOID", "CANCELLED"}:
        return 0
    raise BankrollError(f"unsupported wager status for bankroll accounting: {state}")


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

                CREATE TABLE IF NOT EXISTS bankroll_ledger (
                    ledger_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    wager_id TEXT REFERENCES wagers(wager_id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    entry_type TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL,
                    balance_after_cents INTEGER NOT NULL CHECK(balance_after_cents >= 0),
                    prior_status TEXT,
                    new_status TEXT,
                    note TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_bankroll_ledger_user_created
                    ON bankroll_ledger(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_bankroll_ledger_wager
                    ON bankroll_ledger(wager_id, created_at);
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
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT s.session_id, s.user_id, s.expires_at, u.username, u.username_norm, u.created_at AS user_created_at "
                "FROM sessions s JOIN users u ON u.user_id=s.user_id "
                "WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.active=1",
                (token_hash, now),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

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
            current = conn.execute(
                "SELECT bankroll_cents FROM profiles WHERE user_id=?",
                (user_id,),
            ).fetchone()
            if current is None:
                raise KeyError("profile not found")
            old_bankroll = int(current["bankroll_cents"])
            changed = conn.execute(
                "UPDATE profiles SET bankroll_cents=?, risk_profile=?, updated_at=? WHERE user_id=?",
                (int(bankroll_cents), risk_profile, now, user_id),
            ).rowcount
            if changed != 1:
                raise KeyError("profile not found")
            if old_bankroll != int(bankroll_cents):
                conn.execute(
                    "INSERT INTO bankroll_ledger(ledger_id,user_id,wager_id,created_at,entry_type,amount_cents," 
                    "balance_after_cents,prior_status,new_status,note) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(uuid.uuid4()), user_id, None, now, "MANUAL_BANKROLL_SET",
                        int(bankroll_cents) - old_bankroll, int(bankroll_cents), None, None,
                        "User-set current bankroll",
                    ),
                )
        profile = self.get_profile(user_id)
        if profile is None:
            raise KeyError("profile not found")
        return profile

    @staticmethod
    def _ledger_effect(conn: sqlite3.Connection, *, user_id: str, wager_id: str) -> tuple[int, bool]:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount_cents),0) AS effect, COUNT(*) AS entries "
            "FROM bankroll_ledger WHERE user_id=? AND wager_id=?",
            (user_id, wager_id),
        ).fetchone()
        assert row is not None
        return int(row["effect"]), int(row["entries"]) > 0

    @staticmethod
    def _apply_bankroll_delta(
        conn: sqlite3.Connection,
        *,
        user_id: str,
        wager_id: str,
        delta_cents: int,
        entry_type: str,
        prior_status: str | None,
        new_status: str | None,
        record_zero: bool = False,
    ) -> None:
        profile = conn.execute(
            "SELECT bankroll_cents FROM profiles WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if profile is None:
            raise KeyError("profile not found")
        old_balance = int(profile["bankroll_cents"])
        new_balance = old_balance + int(delta_cents)
        if new_balance < 0:
            raise BankrollError("Current bankroll is too small for this wager amount or correction")
        now = utc_now()
        if delta_cents:
            conn.execute(
                "UPDATE profiles SET bankroll_cents=?, updated_at=? WHERE user_id=?",
                (new_balance, now, user_id),
            )
        if delta_cents or record_zero:
            conn.execute(
                "INSERT INTO bankroll_ledger(ledger_id,user_id,wager_id,created_at,entry_type,amount_cents," 
                "balance_after_cents,prior_status,new_status,note) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()), user_id, wager_id, now, entry_type, int(delta_cents),
                    new_balance, prior_status, new_status, None,
                ),
            )

    def _reconcile_wager_effect(
        self,
        conn: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        prior_status: str | None,
        entry_type: str,
        record_zero: bool = False,
    ) -> None:
        user_id = str(row["user_id"])
        wager_id = str(row["wager_id"])
        current_effect, _ = self._ledger_effect(conn, user_id=user_id, wager_id=wager_id)
        target = _target_wager_effect_cents(
            status=str(row["status"]),
            stake_cents=row["actual_dollars_cents"],
            price=int(row["price"]),
        )
        self._apply_bankroll_delta(
            conn,
            user_id=user_id,
            wager_id=wager_id,
            delta_cents=target - current_effect,
            entry_type=entry_type,
            prior_status=prior_status,
            new_status=str(row["status"]),
            record_zero=record_zero,
        )

    @staticmethod
    def _select_wager_conn(conn: sqlite3.Connection, *, user_id: str, wager_id: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT w.*, "
            "COALESCE((SELECT SUM(l.amount_cents) FROM bankroll_ledger l WHERE l.user_id=w.user_id AND l.wager_id=w.wager_id),0) AS bankroll_effect_cents, "
            "CASE WHEN EXISTS(SELECT 1 FROM bankroll_ledger l WHERE l.user_id=w.user_id AND l.wager_id=w.wager_id) THEN 1 ELSE 0 END AS bankroll_tracked "
            "FROM wagers w WHERE w.user_id=? AND w.wager_id=?",
            (user_id, wager_id),
        ).fetchone()

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
                    selected = self._select_wager_conn(
                        conn, user_id=str(row["user_id"]), wager_id=str(existing["wager_id"])
                    )
                    if selected is None:
                        raise RuntimeError("idempotent wager disappeared")
                    return self._wager_dict(selected), True
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
            if created["actual_dollars_cents"] is not None:
                self._reconcile_wager_effect(
                    conn,
                    row=created,
                    prior_status=None,
                    entry_type="WAGER_CREATED",
                    record_zero=True,
                )
            selected = self._select_wager_conn(
                conn, user_id=str(row["user_id"]), wager_id=str(row["wager_id"])
            )
            if selected is None:
                raise RuntimeError("wager insert disappeared")
            return self._wager_dict(selected), False

    def get_wager(self, *, user_id: str, wager_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = self._select_wager_conn(conn, user_id=user_id, wager_id=wager_id)
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
        clauses = ["w.user_id=?"]
        params: list[Any] = [user_id]
        if state == "open":
            clauses.append("w.status='OPEN'")
        elif state == "settled":
            clauses.append("w.status IN ('WON','LOST','PUSH','VOID','CANCELLED')")
        if game_id:
            clauses.append("w.game_id=?")
            params.append(game_id)
        if week is not None:
            clauses.append("w.week=?")
            params.append(int(week))
        if product_version:
            clauses.append("w.product_version=?")
            params.append(product_version)
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT w.*, "
                "COALESCE((SELECT SUM(l.amount_cents) FROM bankroll_ledger l WHERE l.user_id=w.user_id AND l.wager_id=w.wager_id),0) AS bankroll_effect_cents, "
                "CASE WHEN EXISTS(SELECT 1 FROM bankroll_ledger l WHERE l.user_id=w.user_id AND l.wager_id=w.wager_id) THEN 1 ELSE 0 END AS bankroll_tracked "
                f"FROM wagers w WHERE {' AND '.join(clauses)} ORDER BY w.created_at DESC, w.wager_id DESC",
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
            before = conn.execute(
                "SELECT * FROM wagers WHERE user_id=? AND wager_id=?", (user_id, wager_id)
            ).fetchone()
            if before is None:
                return None
            changed = conn.execute(
                f"UPDATE wagers SET {', '.join(updates)} WHERE user_id=? AND wager_id=?",
                tuple(params),
            ).rowcount
            if changed != 1:
                return None
            after = conn.execute(
                "SELECT * FROM wagers WHERE user_id=? AND wager_id=?", (user_id, wager_id)
            ).fetchone()
            if after is None:
                return None

            _, tracked = self._ledger_effect(conn, user_id=user_id, wager_id=wager_id)
            bankroll_fields_changed = bool({"actual_dollars", "status"} & supplied)
            if bankroll_fields_changed:
                if tracked:
                    self._reconcile_wager_effect(
                        conn,
                        row=after,
                        prior_status=str(before["status"]),
                        entry_type="WAGER_RECONCILED",
                    )
                else:
                    status_changed = str(before["status"]) != str(after["status"])
                    stake_was_added = before["actual_dollars_cents"] is None and after["actual_dollars_cents"] is not None
                    if status_changed or stake_was_added:
                        self._reconcile_wager_effect(
                            conn,
                            row=after,
                            prior_status=str(before["status"]),
                            entry_type="LEGACY_WAGER_ADOPTED",
                            record_zero=True,
                        )

            selected = self._select_wager_conn(conn, user_id=user_id, wager_id=wager_id)
            return self._wager_dict(selected) if selected else None

    def bankroll_summary(self, *, user_id: str) -> dict[str, Any]:
        conn = self._connect()
        try:
            profile = conn.execute(
                "SELECT bankroll_cents FROM profiles WHERE user_id=?", (user_id,)
            ).fetchone()
            if profile is None:
                raise KeyError("profile not found")
            realized = conn.execute(
                "SELECT COALESCE(SUM(effect),0) AS total FROM ("
                "SELECT w.wager_id, COALESCE(SUM(l.amount_cents),0) AS effect "
                "FROM wagers w JOIN bankroll_ledger l ON l.wager_id=w.wager_id AND l.user_id=w.user_id "
                "WHERE w.user_id=? AND w.status IN ('WON','LOST','PUSH','VOID','CANCELLED') "
                "GROUP BY w.wager_id)",
                (user_id,),
            ).fetchone()
            open_row = conn.execute(
                "SELECT COALESCE(SUM(w.actual_dollars_cents),0) AS stakes, COUNT(*) AS count "
                "FROM wagers w WHERE w.user_id=? AND w.status='OPEN' AND w.actual_dollars_cents IS NOT NULL "
                "AND EXISTS(SELECT 1 FROM bankroll_ledger l WHERE l.user_id=w.user_id AND l.wager_id=w.wager_id)",
                (user_id,),
            ).fetchone()
            settled_row = conn.execute(
                "SELECT COUNT(DISTINCT w.wager_id) AS count FROM wagers w "
                "WHERE w.user_id=? AND w.status IN ('WON','LOST','PUSH','VOID','CANCELLED') "
                "AND EXISTS(SELECT 1 FROM bankroll_ledger l WHERE l.user_id=w.user_id AND l.wager_id=w.wager_id)",
                (user_id,),
            ).fetchone()
            legacy_row = conn.execute(
                "SELECT COUNT(*) AS count FROM wagers w WHERE w.user_id=? "
                "AND NOT EXISTS(SELECT 1 FROM bankroll_ledger l WHERE l.user_id=w.user_id AND l.wager_id=w.wager_id)",
                (user_id,),
            ).fetchone()
            return {
                "schema_version": "NFL_EDGE_BANKROLL_SUMMARY_V1",
                "current_bankroll": cents_to_usd(int(profile["bankroll_cents"])),
                "realized_pl": cents_to_usd(int(realized["total"] if realized else 0)),
                "open_stakes": cents_to_usd(int(open_row["stakes"] if open_row else 0)),
                "tracked_open_wagers": int(open_row["count"] if open_row else 0),
                "tracked_settled_wagers": int(settled_row["count"] if settled_row else 0),
                "legacy_untracked_wagers": int(legacy_row["count"] if legacy_row else 0),
            }
        finally:
            conn.close()

    @staticmethod
    def _wager_dict(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        for raw, public in (
            ("recommended_dollars_cents", "recommended_dollars"),
            ("actual_dollars_cents", "actual_dollars"),
        ):
            out[public] = cents_to_usd(out.pop(raw))
        tracked = bool(out.pop("bankroll_tracked", 0))
        effect_cents = int(out.pop("bankroll_effect_cents", 0))
        out["bankroll_tracked"] = tracked
        out["bankroll_effect"] = cents_to_usd(effect_cents) if tracked else None
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
