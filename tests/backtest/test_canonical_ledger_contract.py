"""Canonical ledger contract tests.

These tests pin the on-disk schema, the per-row invariants enforced by
the canonical builders, and the engine's obligation to use the
canonical ``build_prediction_ledger`` / ``build_state_ledger`` /
``write_ledger`` functions as the only writer path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from nfl_edge.backtest.ledger import (
    PREDICTION_LEDGER_COLUMNS,
    STATE_LEDGER_COLUMNS,
    build_prediction_ledger,
    build_state_ledger,
    write_ledger,
)
from nfl_edge.common.errors import (
    SealedHoldoutAccessError,
    WalkForwardError,
)

# ---- Helper: minimal canonical prediction row ------------------------------


def _pred_row(**overrides: Any) -> dict[str, Any]:
    base = {
        "prediction_id": "R:G1",
        "run_id": "R",
        "game_id": "G1",
        "season": 2024,
        "season_type": "REG",
        "week": 1,
        "as_of_utc": "2024-09-01T00:00:00Z",
        "model_name": "qb_elo",
        "model_version": "v1.0.0",
        "prediction_block_id": "B1",
        "home_team": "AAA",
        "away_team": "BBB",
        "home_elo_before": 1500.0,
        "away_elo_before": 1500.0,
        "home_field_adjustment": 48.0,
        "home_qb_adjustment": 0.0,
        "away_qb_adjustment": 0.0,
        "qb_adjustment_net": 0.0,
        "qb_certainty_state": "UNKNOWN",
        "predicted_home_win_probability": 0.6,
        "actual_margin": 7,
        "actual_home_win": True,
        "actual_tie": False,
        "target_available": True,
        "is_binary_scored": True,
        "training_rows_available_before_block": 0,
        "training_season_min": None,
        "training_season_max": None,
        "training_block_count": 0,
        "prior_completed_games_count": 0,
        "exposure_kind": "prior_state_exposure",
        "created_at_utc": "2026-08-03T12:00:00Z",
    }
    base.update(overrides)
    return base


def _state_row(**overrides: Any) -> dict[str, Any]:
    base = {
        "run_id": "R",
        "game_id": "G1",
        "season": 2024,
        "season_type": "REG",
        "week": 1,
        "team": "AAA",
        "opponent": "BBB",
        "side": "home",
        "elo_before": 1500.0,
        "expected_result": 0.6,
        "actual_result": 1.0,
        "actual_margin": 7,
        "update_multiplier": 1.1234,
        "k_factor": 20.0,
        "home_field_adjustment": 48.0,
        "probability_before_update": 0.6,
        "elo_change": 12.3,
        "elo_after": 1512.3,
        "state_update_order": 0,
        "prediction_block_id": "B1",
    }
    base.update(overrides)
    return base


# ---- 1. Schema equality on disk --------------------------------------------


def test_declared_prediction_schema_equals_parquet_columns(tmp_path: Path) -> None:
    rows = [_pred_row()]
    df = build_prediction_ledger(rows)
    out = tmp_path / "p.parquet"
    write_ledger(df, str(out))
    reread = pl.read_parquet(str(out))
    assert tuple(reread.columns) == PREDICTION_LEDGER_COLUMNS


def test_declared_state_schema_equals_parquet_columns(tmp_path: Path) -> None:
    rows = [
        _state_row(side="home", team="AAA"),
        _state_row(side="away", team="BBB"),
    ]
    df = build_state_ledger(rows)
    out = tmp_path / "s.parquet"
    write_ledger(df, str(out))
    reread = pl.read_parquet(str(out))
    assert tuple(reread.columns) == STATE_LEDGER_COLUMNS


def test_prediction_required_fields_present() -> None:
    df = build_prediction_ledger([_pred_row()])
    for col in (
        "actual_margin", "is_binary_scored", "predicted_home_win_probability",
        "target_available", "actual_tie", "actual_home_win",
        "training_rows_available_before_block", "training_block_count",
    ):
        assert col in df.columns


def test_obsolete_training_rows_absent() -> None:
    df = build_prediction_ledger([_pred_row()])
    assert "training_rows" not in df.columns


def test_is_scored_absent() -> None:
    df = build_prediction_ledger([_pred_row()])
    assert "is_scored" not in df.columns


# ---- 2. Per-row validation --------------------------------------------------


def test_first_row_extra_field_rejected() -> None:
    row = _pred_row(unauthorized="x")
    with pytest.raises(WalkForwardError):
        build_prediction_ledger([row])


def test_later_row_extra_field_rejected() -> None:
    rows = [_pred_row(prediction_id="R:G1"), _pred_row(prediction_id="R:G2", extra="x")]
    with pytest.raises(WalkForwardError):
        build_prediction_ledger(rows)


def test_first_row_missing_field_rejected() -> None:
    row = _pred_row()
    del row["actual_margin"]
    with pytest.raises(WalkForwardError):
        build_prediction_ledger([row])


def test_later_row_missing_field_rejected() -> None:
    rows = [_pred_row(prediction_id="R:G1")]
    row2 = _pred_row(prediction_id="R:G2")
    del row2["predicted_home_win_probability"]
    with pytest.raises(WalkForwardError):
        build_prediction_ledger([row1 for row1 in rows] + [row2])


def test_duplicate_prediction_id_rejected() -> None:
    rows = [_pred_row(prediction_id="R:G1"), _pred_row(prediction_id="R:G1")]
    with pytest.raises(WalkForwardError):
        build_prediction_ledger(rows)


def test_probability_below_zero_rejected() -> None:
    with pytest.raises(WalkForwardError):
        build_prediction_ledger([_pred_row(predicted_home_win_probability=-0.1)])


def test_probability_above_one_rejected() -> None:
    with pytest.raises(WalkForwardError):
        build_prediction_ledger([_pred_row(predicted_home_win_probability=1.1)])


def test_2025_row_rejected() -> None:
    with pytest.raises((SealedHoldoutAccessError, WalkForwardError)):
        build_prediction_ledger([_pred_row(season=2025)])


def test_market_field_rejected() -> None:
    with pytest.raises(WalkForwardError):
        build_prediction_ledger([_pred_row(market_consensus_spread=-3.5)])


def test_null_actual_margin_with_target_available_rejected() -> None:
    with pytest.raises(WalkForwardError):
        build_prediction_ledger(
            [_pred_row(actual_margin=None, target_available=True, actual_home_win=True, is_binary_scored=True)]
        )


def test_non_null_actual_margin_with_target_unavailable_rejected() -> None:
    with pytest.raises(WalkForwardError):
        build_prediction_ledger(
            [
                _pred_row(
                    actual_margin=0,
                    target_available=False,
                    actual_home_win=None,
                    actual_tie=False,
                    is_binary_scored=False,
                )
            ]
        )


def test_positive_margin_with_home_loss_rejected() -> None:
    with pytest.raises(WalkForwardError):
        build_prediction_ledger(
            [_pred_row(actual_margin=7, actual_home_win=False, actual_tie=False, is_binary_scored=True)]
        )


def test_negative_margin_with_home_win_rejected() -> None:
    with pytest.raises(WalkForwardError):
        build_prediction_ledger(
            [_pred_row(actual_margin=-3, actual_home_win=True, actual_tie=False, is_binary_scored=True)]
        )


def test_zero_margin_without_tie_rejected() -> None:
    with pytest.raises(WalkForwardError):
        build_prediction_ledger(
            [_pred_row(actual_margin=0, actual_tie=False, actual_home_win=True, is_binary_scored=True)]
        )


def test_tie_with_is_binary_scored_true_rejected() -> None:
    with pytest.raises(WalkForwardError):
        build_prediction_ledger(
            [_pred_row(actual_margin=0, actual_tie=True, actual_home_win=None, is_binary_scored=True)]
        )


def test_non_tie_with_is_binary_scored_false_rejected() -> None:
    with pytest.raises(WalkForwardError):
        build_prediction_ledger(
            [_pred_row(actual_margin=7, actual_tie=False, actual_home_win=True, is_binary_scored=False)]
        )


def test_deterministic_round_trip_preserves_schema_and_values(tmp_path: Path) -> None:
    rows = [
        _pred_row(prediction_id="R:G1"),
        _pred_row(
            prediction_id="R:G2", game_id="G2",
            actual_margin=-3, actual_home_win=False,
        ),
    ]
    df = build_prediction_ledger(rows)
    out = tmp_path / "p.parquet"
    write_ledger(df, str(out))
    reread = pl.read_parquet(str(out))
    assert tuple(reread.columns) == PREDICTION_LEDGER_COLUMNS
    assert reread.height == 2
    assert set(reread["prediction_id"].to_list()) == {"R:G1", "R:G2"}


# ---- 3. State ledger validations -------------------------------------------


def _make_state_pair(home_elo_after: float = 1512.3, away_elo_after: float = 1487.7) -> list[dict[str, Any]]:
    return [
        _state_row(side="home", team="AAA", elo_change=12.3, elo_after=home_elo_after),
        _state_row(side="away", team="BBB", elo_change=-12.3, elo_after=away_elo_after),
    ]


def test_state_duplicate_side_rejected() -> None:
    rows = [
        _state_row(side="home", team="AAA"),
        _state_row(side="home", team="AAA"),
    ]
    with pytest.raises(WalkForwardError):
        build_state_ledger(rows)


def test_state_missing_side_rejected() -> None:
    rows = [_state_row(side="home", team="AAA")]
    with pytest.raises(WalkForwardError):
        build_state_ledger(rows)


def test_state_zero_sum_violation_rejected_by_validator() -> None:
    """The zero-sum invariant is enforced by the engine's hard
    correctness gate, not by the canonical builder. Verify the gate
    still fires."""
    from nfl_edge.backtest.walk_forward import _validate_state_ledger_correctness
    rows = [
        _state_row(side="home", team="AAA", elo_change=12.3),
        _state_row(side="away", team="BBB", elo_change=-12.3 + 1e-3),
    ]
    df = build_state_ledger(rows)
    from nfl_edge.common.errors import StateLedgerCorruptionError
    with pytest.raises(StateLedgerCorruptionError):
        _validate_state_ledger_correctness(df)


def test_state_market_field_rejected() -> None:
    rows = _make_state_pair()
    rows[0]["market_consensus_spread"] = -3.5
    with pytest.raises(WalkForwardError):
        build_state_ledger(rows)


def test_state_2025_rejected() -> None:
    rows = _make_state_pair()
    rows[0]["season"] = 2025
    with pytest.raises((SealedHoldoutAccessError, WalkForwardError)):
        build_state_ledger(rows)


# ---- 4. Engine uses canonical builders only ---------------------------------


def test_walk_forward_uses_canonical_builders(monkeypatch, tmp_path) -> None:
    """The walk-forward engine must call the canonical builders, not
    bypass them. We intercept them and assert each is called.

    The post-2026-08-04 contract requires the engine to read the
    on-disk Parquet bytes for ``file_sha256``. Stubbing
    ``write_ledger`` with a no-op therefore breaks the file-hash
    step (it tries to read a file that was never written). The
    test records the call AND still lets the real writer run."""
    from nfl_edge.backtest import walk_forward as wf
    calls: list[str] = []

    real_bpl = build_prediction_ledger
    real_bsl = build_state_ledger
    real_wl = write_ledger

    def _stub_bpl(*args: Any, **kwargs: Any) -> pl.DataFrame:
        calls.append("build_prediction_ledger")
        return real_bpl(*args, **kwargs)

    def _stub_bsl(*args: Any, **kwargs: Any) -> pl.DataFrame:
        calls.append("build_state_ledger")
        return real_bsl(*args, **kwargs)

    def _stub_wl(*args: Any, **kwargs: Any) -> None:
        calls.append("write_ledger")
        return real_wl(*args, **kwargs)

    monkeypatch.setattr(wf, "build_prediction_ledger", _stub_bpl)
    monkeypatch.setattr(wf, "build_state_ledger", _stub_bsl)
    monkeypatch.setattr(wf, "write_ledger", _stub_wl)
    out = tmp_path / "p4_canon_test"
    if out.exists():
        import shutil
        shutil.rmtree(out)
    # Now call the engine through run_development_walk_forward
    wf.run_development_walk_forward(
        games_path=Path("data/derived/features_v1/game_features_2018_2025.parquet"),
        team_features_path=Path("data/derived/features_v1/team_pregame_features_2018_2025.parquet"),
        output_dir=out,
        created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
        project_root=Path("."),
    )
    assert "build_prediction_ledger" in calls
    assert "build_state_ledger" in calls
    assert "write_ledger" in calls
