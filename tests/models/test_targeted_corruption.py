"""Targeted corruption tests — full matrix.

Each error must identify the game ID, the side where applicable, the
field, and the expected vs actual value.

Coverage matrix:
- home elo_before; away elo_before
- home expected_result; away expected_result
- home actual_result; away actual_result
- home update_multiplier; away update_multiplier
- home k_factor; away k_factor
- home elo_change; away elo_change
- home elo_after; away elo_after
- home actual_margin; away actual_margin
- both actual_margin rows identically wrong (cross-ledger)
- missing home row; missing away row
- duplicate home row; duplicate away row
- orphan home row; orphan away row
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
from nfl_edge.models.qb_elo_config import (
    canonical_config_to_elo_config_input,
    load_qb_elo_canonical_config,
)


def _cfg() -> EloConfig:
    return EloConfig(
        **canonical_config_to_elo_config_input(
            load_qb_elo_canonical_config(
                Path("config/qb_elo_v1.yaml")
            )
        )
    )


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


def _corrupt_field(
    rows: list[dict], gid: str, side: str, field: str, value: Any
) -> list[dict]:
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


def _assert_problem_contains(
    problems: list[str], must_contain: tuple[str, ...]
) -> None:
    msg = " | ".join(problems)
    for needle in must_contain:
        assert needle in msg, f"expected {needle!r} in problems, got: {msg}"


# ---- baseline -----------------------------------------------------


def test_clean_ledger_baseline(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    problems = detect_state_ledger_corruption(
        state_ledger=state, predictions=pred, config=_cfg()
    )
    assert problems == []


# ---- elo_before ---------------------------------------------------


def test_corrupt_home_elo_before_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _corrupt_field(
        state, gid, "home", "elo_before", state[0]["elo_before"] + 1.0
    )
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "home", "elo_before")
    )


def test_corrupt_away_elo_before_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    away_row = next(r for r in state if r["game_id"] == gid and r["side"] == "away")
    state_corrupted = _corrupt_field(
        state, gid, "away", "elo_before", away_row["elo_before"] + 1.0
    )
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "away", "elo_before")
    )


# ---- expected_result ----------------------------------------------


def test_corrupt_home_expected_result_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _corrupt_field(
        state, gid, "home", "expected_result", 0.99
    )
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "home", "expected_result")
    )


def test_corrupt_away_expected_result_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _corrupt_field(
        state, gid, "away", "expected_result", 0.01
    )
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "away", "expected_result")
    )


# ---- actual_result ------------------------------------------------


def test_corrupt_home_actual_result_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    home = next(r for r in state if r["game_id"] == gid and r["side"] == "home")
    state_corrupted = _corrupt_field(
        state, gid, "home", "actual_result", 1.0 - home["actual_result"]
    )
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "home", "actual_result")
    )


def test_corrupt_away_actual_result_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    away = next(r for r in state if r["game_id"] == gid and r["side"] == "away")
    state_corrupted = _corrupt_field(
        state, gid, "away", "actual_result", 1.0 - away["actual_result"]
    )
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "away", "actual_result")
    )


# ---- update_multiplier --------------------------------------------


def test_corrupt_home_update_multiplier_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _corrupt_field(
        state, gid, "home", "update_multiplier", 1.99
    )
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "home", "update_multiplier")
    )


def test_corrupt_away_update_multiplier_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _corrupt_field(
        state, gid, "away", "update_multiplier", 1.99
    )
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "away", "update_multiplier")
    )


# ---- k_factor -----------------------------------------------------


def test_corrupt_home_k_factor_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _corrupt_field(
        state, gid, "home", "k_factor", 99.0
    )
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "home", "k_factor")
    )


def test_corrupt_away_k_factor_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _corrupt_field(
        state, gid, "away", "k_factor", 99.0
    )
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "away", "k_factor")
    )


# ---- elo_change ---------------------------------------------------


def test_corrupt_home_elo_change_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _corrupt_field(
        state, gid, "home", "elo_change", state[0]["elo_change"] + 0.5
    )
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "home", "elo_change")
    )


def test_corrupt_away_elo_change_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    away = next(r for r in state if r["game_id"] == gid and r["side"] == "away")
    state_corrupted = _corrupt_field(
        state, gid, "away", "elo_change", away["elo_change"] + 0.5
    )
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "away", "elo_change")
    )


# ---- elo_after ----------------------------------------------------


def test_corrupt_home_elo_after_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _corrupt_field(
        state, gid, "home", "elo_after", state[0]["elo_after"] + 1.0
    )
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "home", "elo_after")
    )


def test_corrupt_away_elo_after_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    away = next(r for r in state if r["game_id"] == gid and r["side"] == "away")
    state_corrupted = _corrupt_field(
        state, gid, "away", "elo_after", away["elo_after"] + 1.0
    )
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "away", "elo_after")
    )


# ---- actual_margin (per-side) -------------------------------------


def test_corrupt_home_actual_margin_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    # Move home only, leaving away at the prediction's value.
    state_corrupted = _corrupt_field(
        state, gid, "home", "actual_margin", 999
    )
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "home", "actual_margin")
    )


def test_corrupt_away_actual_margin_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _corrupt_field(
        state, gid, "away", "actual_margin", 999
    )
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "away", "actual_margin")
    )


def test_both_actual_margins_identically_wrong_detected(tmp_path: Path) -> None:
    """Both state rows carry the same wrong actual_margin. The
    side-vs-side check would pass, but the cross-ledger check
    must catch it."""
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _corrupt_field(
        state, gid, "home", "actual_margin", 999
    )
    state_corrupted = _corrupt_field(
        state_corrupted, gid, "away", "actual_margin", 999
    )
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "actual_margin", "cross-ledger")
    )


# ---- missing / duplicate / orphan ---------------------------------


def test_missing_home_row_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _missing_side(state, gid, "home")
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(exc.value.problems, (gid, "home"))


def test_missing_away_row_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _missing_side(state, gid, "away")
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(exc.value.problems, (gid, "away"))


def test_duplicate_home_row_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _duplicate_side(state, gid, "home")
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "home", "duplicate")
    )


def test_duplicate_away_row_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    gid = state[0]["game_id"]
    state_corrupted = _duplicate_side(state, gid, "away")
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state_corrupted, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, (gid, "away", "duplicate")
    )


def test_orphan_home_row_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    state.append({**state[0], "game_id": "GHOST_HOME", "side": "home"})
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, ("GHOST_HOME", "orphan")
    )


def test_orphan_away_row_detected(tmp_path: Path) -> None:
    pred, state = _run_clean_into(tmp_path)
    state.append({**state[0], "game_id": "GHOST_AWAY", "side": "away"})
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state, predictions=pred, config=_cfg()
        )
    _assert_problem_contains(
        exc.value.problems, ("GHOST_AWAY", "orphan")
    )
