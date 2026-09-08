from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from nfl_edge.backend.db import BackendDatabase, BankrollError, utc_now


def _user(db: BackendDatabase, *, username: str = "bankroll_user", bankroll_cents: int = 50_000) -> str:
    created = db.create_user(username=username, username_norm=username.casefold(), password_hash="test-hash")
    user_id = str(created["user_id"])
    db.update_profile(user_id=user_id, bankroll_cents=bankroll_cents, risk_profile="Normal")
    return user_id


def _row(
    user_id: str,
    *,
    wager_id: str = "wager-1",
    stake_cents: int | None = 500,
    price: int = -200,
    status: str = "OPEN",
    idempotency_key: str = "bankroll-idem-1",
) -> dict:
    now = utc_now()
    return {
        "wager_id": wager_id,
        "user_id": user_id,
        "created_at": now,
        "updated_at": now,
        "source_type": "EXACT_OFFER",
        "product_version": "bankroll-test-v1",
        "generated_at_utc": now,
        "season": 2026,
        "week": 1,
        "game_id": "bankroll-game",
        "kickoff_at_utc": now,
        "lane": None,
        "market_type": "MONEYLINE",
        "selection": "AAA",
        "book": "MANUAL",
        "line": None,
        "price": price,
        "recommendation_state": "BET",
        "recommended_units": 0.5,
        "recommended_dollars_cents": 500,
        "actual_units": 0.5 if stake_cents is not None else None,
        "actual_dollars_cents": stake_cents,
        "play_through_json": None,
        "value_at_json": None,
        "status": status,
        "note": None,
        "provenance_json": "{}",
        "idempotency_key": idempotency_key,
        "idempotency_hash": "same-request-hash",
    }


def _bankroll_cents(db: BackendDatabase, user_id: str) -> int:
    profile = db.get_profile(user_id)
    assert profile is not None
    return int(profile["bankroll_cents"])


def _patch(
    db: BackendDatabase,
    *,
    user_id: str,
    wager_id: str,
    status: str | None = None,
    actual_dollars_cents: int | None = None,
    supplied: set[str],
):
    return db.patch_wager(
        user_id=user_id,
        wager_id=wager_id,
        actual_units=None,
        actual_dollars_cents=actual_dollars_cents,
        status=status,
        note=None,
        supplied=supplied,
    )


def test_open_reserves_stake_win_returns_full_payout_and_transitions_are_reversible(tmp_path: Path) -> None:
    db = BackendDatabase(tmp_path / "bankroll.sqlite3")
    db.initialize()
    user_id = _user(db)
    row = _row(user_id)

    created, replayed = db.create_wager(row)
    assert replayed is False
    assert created["bankroll_tracked"] is True
    assert created["bankroll_effect"] == "-5.00"
    assert _bankroll_cents(db, user_id) == 49_500
    assert db.bankroll_summary(user_id=user_id) == {
        "schema_version": "NFL_EDGE_BANKROLL_SUMMARY_V1",
        "current_bankroll": "495.00",
        "realized_pl": "0.00",
        "open_stakes": "5.00",
        "tracked_open_wagers": 1,
        "tracked_settled_wagers": 0,
        "legacy_untracked_wagers": 0,
    }

    # Idempotent wager replay cannot reserve the stake twice.
    replay, replayed = db.create_wager(row)
    assert replayed is True
    assert replay["wager_id"] == row["wager_id"]
    assert _bankroll_cents(db, user_id) == 49_500

    # $5 at -200 wins $2.50 profit. Because the $5 stake was already reserved,
    # OPEN -> WON must add the full $7.50 payout and finish at $502.50.
    won = _patch(db, user_id=user_id, wager_id=row["wager_id"], status="WON", supplied={"status"})
    assert won is not None
    assert won["bankroll_effect"] == "2.50"
    assert _bankroll_cents(db, user_id) == 50_250
    won_summary = db.bankroll_summary(user_id=user_id)
    assert won_summary["current_bankroll"] == "502.50"
    assert won_summary["realized_pl"] == "2.50"
    assert won_summary["open_stakes"] == "0.00"

    # Repeating the same settled status is idempotent.
    _patch(db, user_id=user_id, wager_id=row["wager_id"], status="WON", supplied={"status"})
    assert _bankroll_cents(db, user_id) == 50_250

    # Corrections reverse the old effect before applying the new one.
    _patch(db, user_id=user_id, wager_id=row["wager_id"], status="LOST", supplied={"status"})
    assert _bankroll_cents(db, user_id) == 49_500
    assert db.bankroll_summary(user_id=user_id)["realized_pl"] == "-5.00"

    _patch(db, user_id=user_id, wager_id=row["wager_id"], status="PUSH", supplied={"status"})
    assert _bankroll_cents(db, user_id) == 50_000
    assert db.bankroll_summary(user_id=user_id)["realized_pl"] == "0.00"

    _patch(db, user_id=user_id, wager_id=row["wager_id"], status="OPEN", supplied={"status"})
    assert _bankroll_cents(db, user_id) == 49_500

    _patch(db, user_id=user_id, wager_id=row["wager_id"], status="CANCELLED", supplied={"status"})
    assert _bankroll_cents(db, user_id) == 50_000


def test_open_stake_edit_reconciles_reserved_cash(tmp_path: Path) -> None:
    db = BackendDatabase(tmp_path / "bankroll.sqlite3")
    db.initialize()
    user_id = _user(db)
    row = _row(user_id)
    db.create_wager(row)
    assert _bankroll_cents(db, user_id) == 49_500

    updated = _patch(
        db,
        user_id=user_id,
        wager_id=row["wager_id"],
        actual_dollars_cents=700,
        supplied={"actual_dollars"},
    )
    assert updated is not None
    assert updated["actual_dollars"] == "7.00"
    assert updated["bankroll_effect"] == "-7.00"
    assert _bankroll_cents(db, user_id) == 49_300
    assert db.bankroll_summary(user_id=user_id)["open_stakes"] == "7.00"


def test_insufficient_available_bankroll_rolls_back_wager_creation(tmp_path: Path) -> None:
    db = BackendDatabase(tmp_path / "bankroll.sqlite3")
    db.initialize()
    user_id = _user(db, bankroll_cents=300)
    row = _row(user_id, stake_cents=500)

    with pytest.raises(BankrollError, match="too small"):
        db.create_wager(row)

    assert _bankroll_cents(db, user_id) == 300
    assert db.get_wager(user_id=user_id, wager_id=row["wager_id"]) is None
    assert db.bankroll_summary(user_id=user_id)["tracked_open_wagers"] == 0


def test_pre_feature_wager_is_not_retroactively_reserved_but_is_adopted_on_result_change(tmp_path: Path) -> None:
    db = BackendDatabase(tmp_path / "bankroll.sqlite3")
    db.initialize()
    user_id = _user(db)
    row = _row(user_id, wager_id="legacy-wager", idempotency_key="legacy-idem")

    # Simulate a wager already present before the bankroll-ledger feature exists.
    columns = (
        "wager_id", "user_id", "created_at", "updated_at", "source_type", "product_version",
        "generated_at_utc", "season", "week", "game_id", "kickoff_at_utc", "lane", "market_type",
        "selection", "book", "line", "price", "recommendation_state", "recommended_units",
        "recommended_dollars_cents", "actual_units", "actual_dollars_cents", "play_through_json",
        "value_at_json", "status", "note", "provenance_json", "idempotency_key", "idempotency_hash",
    )
    conn = sqlite3.connect(db.path)
    try:
        conn.execute(
            f"INSERT INTO wagers({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
            tuple(row.get(column) for column in columns),
        )
        conn.commit()
    finally:
        conn.close()

    assert _bankroll_cents(db, user_id) == 50_000
    assert db.bankroll_summary(user_id=user_id)["legacy_untracked_wagers"] == 1

    # Editing metadata or re-saving OPEN must not suddenly deduct a historical stake.
    db.patch_wager(
        user_id=user_id,
        wager_id=row["wager_id"],
        actual_units=None,
        actual_dollars_cents=None,
        status=None,
        note="old wager note",
        supplied={"note"},
    )
    _patch(db, user_id=user_id, wager_id=row["wager_id"], status="OPEN", supplied={"status"})
    assert _bankroll_cents(db, user_id) == 50_000
    assert db.bankroll_summary(user_id=user_id)["legacy_untracked_wagers"] == 1

    # On the first real result transition, adopt the historical wager at its net
    # settled effect. A $5 -200 win increases the current balance by $2.50, not
    # $7.50, because this feature never reserved the historical $5 stake.
    won = _patch(db, user_id=user_id, wager_id=row["wager_id"], status="WON", supplied={"status"})
    assert won is not None
    assert won["bankroll_tracked"] is True
    assert won["bankroll_effect"] == "2.50"
    assert _bankroll_cents(db, user_id) == 50_250
    summary = db.bankroll_summary(user_id=user_id)
    assert summary["realized_pl"] == "2.50"
    assert summary["legacy_untracked_wagers"] == 0
