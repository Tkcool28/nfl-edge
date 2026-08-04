"""Cross-ledger ``actual_margin`` validation tests.

The state ledger and the prediction ledger must agree on the
``actual_margin`` for every completed game. The verifier compares:

  prediction.actual_margin
  ==
  state.home.actual_margin
  ==
  state.away.actual_margin

and identifies the game, side, prediction value, and state value on
mismatch. There is no fallback for the retired ``margin`` field.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.backtest.walk_forward import run_development_walk_forward
from nfl_edge.common.errors import StateLedgerCorruptionError
from nfl_edge.models.qb_elo import detect_state_ledger_corruption
from nfl_edge.models.qb_elo_config import (
    canonical_config_to_eloconfig,
    load_qb_elo_canonical_config,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---- 1. Clean ledger passes ---------------------------------------


def test_clean_ledger_passes(tmp_path: Path) -> None:
    pred, state = _run_clean(tmp_path)
    problems = detect_state_ledger_corruption(
        state_ledger=state, predictions=pred, config=_cfg()
    )
    assert problems == []


# ---- 2. Corrupt home state actual_margin only ---------------------


def test_corrupt_home_state_actual_margin_only(tmp_path: Path) -> None:
    pred, state = _run_clean(tmp_path)
    state = copy.deepcopy(state)
    home = next(r for r in state if r["side"] == "home")
    home["actual_margin"] = 999
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state, predictions=pred, config=_cfg()
        )
    msg = str(exc.value)
    assert "actual_margin" in msg
    assert "home" in msg


# ---- 3. Corrupt away state actual_margin only ---------------------


def test_corrupt_away_state_actual_margin_only(tmp_path: Path) -> None:
    pred, state = _run_clean(tmp_path)
    state = copy.deepcopy(state)
    away = next(r for r in state if r["side"] == "away")
    away["actual_margin"] = 999
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state, predictions=pred, config=_cfg()
        )
    msg = str(exc.value)
    assert "actual_margin" in msg
    assert "away" in msg


# ---- 4. Corrupt both state margins to the same wrong positive value --


def test_corrupt_both_state_margins_same_wrong_positive(tmp_path: Path) -> None:
    pred, state = _run_clean(tmp_path)
    state = copy.deepcopy(state)
    for r in state:
        r["actual_margin"] = 999
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state, predictions=pred, config=_cfg()
        )
    msg = str(exc.value)
    assert "actual_margin" in msg
    assert "prediction" in msg
    assert "state" in msg


# ---- 5. Corrupt both state margins to the same wrong negative value --


def test_corrupt_both_state_margins_same_wrong_negative(tmp_path: Path) -> None:
    pred, state = _run_clean(tmp_path)
    state = copy.deepcopy(state)
    for r in state:
        r["actual_margin"] = -999
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state, predictions=pred, config=_cfg()
        )
    msg = str(exc.value)
    assert "actual_margin" in msg
    assert "prediction" in msg
    assert "state" in msg


# ---- 6. Prediction margin 7 vs state margins 999 fails ------------


def test_prediction_margin_7_vs_state_999_fails(tmp_path: Path) -> None:
    pred, state = _run_clean(tmp_path)
    state = copy.deepcopy(state)
    for r in state:
        r["actual_margin"] = 999
    with pytest.raises(StateLedgerCorruptionError):
        detect_state_ledger_corruption(
            state_ledger=state, predictions=pred, config=_cfg()
        )


# ---- 7. Prediction margin -3 vs state margins 3 fails -------------


def test_prediction_margin_neg3_vs_state_3_fails(tmp_path: Path) -> None:
    pred, state = _run_clean(tmp_path)
    state = copy.deepcopy(state)
    for r in state:
        r["actual_margin"] = 3
    with pytest.raises(StateLedgerCorruptionError):
        detect_state_ledger_corruption(
            state_ledger=state, predictions=pred, config=_cfg()
        )


# ---- 8. Tie prediction margin 0 vs nonzero state margins fails ----


def test_tie_prediction_zero_vs_nonzero_state_fails(tmp_path: Path) -> None:
    pred, state = _run_clean(tmp_path)
    state = copy.deepcopy(state)
    for r in state:
        r["actual_margin"] = 1
    with pytest.raises(StateLedgerCorruptionError):
        detect_state_ledger_corruption(
            state_ledger=state, predictions=pred, config=_cfg()
        )


# ---- 9. Missing state actual_margin fails explicitly --------------


def test_missing_state_actual_margin_fails(tmp_path: Path) -> None:
    pred, state = _run_clean(tmp_path)
    state = copy.deepcopy(state)
    for r in state:
        del r["actual_margin"]
    with pytest.raises(KeyError):
        detect_state_ledger_corruption(
            state_ledger=state, predictions=pred, config=_cfg()
        )


# ---- 10. Missing prediction actual_margin for target_available=True fails --


def test_missing_prediction_actual_margin_fails(tmp_path: Path) -> None:
    pred, state = _run_clean(tmp_path)
    pred = copy.deepcopy(pred)
    pred[0].pop("actual_margin", None)
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state, predictions=pred, config=_cfg()
        )
    msg = str(exc.value)
    assert "missing prediction actual_margin" in msg


# ---- 11. Home/away state margins differing from each other fail ---


def test_state_margins_differing_from_each_other_fail(tmp_path: Path) -> None:
    pred, state = _run_clean(tmp_path)
    state = copy.deepcopy(state)
    by_gid: dict[str, dict[str, dict]] = {}
    for r in state:
        by_gid.setdefault(r["game_id"], {})[r["side"]] = r
    for gid, sides in by_gid.items():
        if "home" in sides and "away" in sides:
            sides["home"]["actual_margin"] = 7
            sides["away"]["actual_margin"] = -7
            break
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state, predictions=pred, config=_cfg()
        )
    msg = str(exc.value)
    assert "actual_margin" in msg
    assert "side-vs-side" in msg or "inconsistency" in msg or "cross-ledger" in msg


# ---- 12. Error message contains game, side, field, prediction, state --


def test_error_message_includes_required_fields(tmp_path: Path) -> None:
    pred, state = _run_clean(tmp_path)
    state = copy.deepcopy(state)
    for r in state:
        r["actual_margin"] = 999
    with pytest.raises(StateLedgerCorruptionError) as exc:
        detect_state_ledger_corruption(
            state_ledger=state, predictions=pred, config=_cfg()
        )
    msg = str(exc.value)
    assert "game" in msg.lower()
    assert "side" in msg.lower()
    assert "actual_margin" in msg
    assert "prediction" in msg
    assert "state" in msg


# ---- 13. Retired margin field is not silently defaulted -----------


def test_no_margin_field_fallback(tmp_path: Path) -> None:
    """The verifier must not use ``row.get("actual_margin", row.get("margin", 0))``.
    A state row carrying only the retired ``margin`` field must fail
    explicitly with a KeyError, not silently default to 0."""
    pred, state = _run_clean(tmp_path)
    state = copy.deepcopy(state)
    for r in state:
        r["margin"] = r.pop("actual_margin")
    with pytest.raises(KeyError):
        detect_state_ledger_corruption(
            state_ledger=state, predictions=pred, config=_cfg()
        )


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


def _cfg():
    return canonical_config_to_eloconfig(
        load_qb_elo_canonical_config(REPO_ROOT / "config/qb_elo_v1.yaml")
    )


def _run_clean(tmp_path: Path) -> tuple[list[dict], list[dict]]:
    """Run a one-block pipeline into tmp_path and return the
    prediction and state ledgers as dict lists."""
    if not (REPO_ROOT / "data/derived/features_v1").exists():
        pytest.skip("data not available")
    out = tmp_path / "cl"
    out.mkdir()
    run_development_walk_forward(
        games_path=Path("data/derived/features_v1/game_features_2018_2025.parquet"),
        team_features_path=Path("data/derived/features_v1/team_pregame_features_2018_2025.parquet"),
        output_dir=out,
        created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
        project_root=REPO_ROOT,
    )
    pred = pl.read_parquet(out / "qb_elo_predictions_2018_2024.parquet").to_dicts()
    state = pl.read_parquet(out / "qb_elo_state_transitions_2018_2024.parquet").to_dicts()
    return pred, state
