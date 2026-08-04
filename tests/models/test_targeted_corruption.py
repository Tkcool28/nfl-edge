"""Targeted corruption tests.

Each error must identify the game ID, the side where applicable, the
field, and the expected vs actual value.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from nfl_edge.backtest.walk_forward import run_development_walk_forward
from nfl_edge.common.errors import StateLedgerCorruptionError
from nfl_edge.models.qb_elo import EloConfig, detect_state_ledger_corruption


def _run_clean_into(tmp_path: Path) -> tuple[list[dict], list[dict]]:
    out = tmp_path / "clean"
    out.mkdir()
    run_development_walk_forward(
        games_path=Path("data/derived/features_v1/game_features_2018_2025.parquet"),
        team_features_path=Path("data/derived/features_v1/team_pregame_features_2018_2025.parquet"),
        output_dir=out,
        created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
        project_root=Path("."),
    )
    pred = pl.read_parquet(out / "qb_elo_predictions_2018_2024.parquet")
    state = pl.read_parquet(out / "qb_elo_state_transitions_2018_2024.parquet")
    return pred.to_dicts(), state.to_dicts()


def _corrupt_field(rows: list[dict], gid: str, side: str, field: str, value: Any) -> list[dict]:
    out = []
    for r in rows:
        if r["game_id"] == gid and r["side"] == side:
            r = {**r, field: value}
        out.append(r)
    return out


def _missing_side(rows: list[dict], gid: str, side: str) -> list[dict]:
    return [r for r in rows if not (r["game_id"] == gid and r["side"] == side)]


def _duplicate_side(rows: list[dict], gid: str, side: str) -> list[dict]:
    extra = [r for r in rows if r["game_id"] == gid and r["side"] == side][0]
    out = list(rows)
    out.append({**extra})
    return out


def _assert_problem_contains(problems: list[str], must_contain: tuple[str, ...]) -> None:
    msg = " | ".join(problems)
    for needle in must_contain:
        assert needle in msg, f"expected {needle!r} in problems, got: {msg}"


def test_clean_ledger_baseline(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    problems = detect_state_ledger_corruption(
        state_ledger=state, predictions=pred, config=EloConfig()
    )
    assert problems == []


def test_corrupt_home_elo_before_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _corrupt_field(state, gid, "home", "elo_before", state[0]["elo_before"] + 1.0)
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=EloConfig()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "home", "elo_before")
    )


def test_corrupt_away_elo_change_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    # Find the away row
    away_row = next(r for r in state if r["game_id"] == gid and r["side"] == "away")
    state_corrupted = _corrupt_field(state, gid, "away", "elo_change", away_row["elo_change"] + 0.5)
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=EloConfig()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "away", "elo_change")
    )


def test_corrupt_k_factor_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _corrupt_field(state, gid, "home", "k_factor", 99.0)
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=EloConfig()
        )
    _assert_problem_contains(exc.value.problems, (gid, "home", "k_factor"))


def test_corrupt_update_multiplier_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _corrupt_field(state, gid, "home", "update_multiplier", 1.99)
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=EloConfig()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "home", "update_multiplier")
    )


def test_corrupt_actual_margin_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    # Corrupt the away row's actual_margin so it differs from home.
    state_corrupted = _corrupt_field(state, gid, "away", "actual_margin", 999)
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=EloConfig()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "actual_margin")
    )


def test_missing_home_row_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _missing_side(state, gid, "home")
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=EloConfig()
        )
    _assert_problem_contains(exc.value.problems, (gid, "home"))


def test_duplicate_home_row_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _duplicate_side(state, gid, "home")
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=EloConfig()
        )
    _assert_problem_contains(exc.value.problems, (gid, "home", "duplicate"))


def test_orphan_state_row_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    # Inject a row whose game_id is not in the prediction set
    state.append({**state[0], "game_id": "GHOST_GAME_ID", "side": "home"})
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state, predictions=pred, config=EloConfig()
        )
    _assert_problem_contains(exc.value.problems, ("GHOST_GAME_ID", "orphan"))


def test_corrupt_elo_after_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _corrupt_field(state, gid, "home", "elo_after", state[0]["elo_after"] + 1.0)
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=EloConfig()
        )
    _assert_problem_contains(exc.value.problems, (gid, "home", "elo_after"))
