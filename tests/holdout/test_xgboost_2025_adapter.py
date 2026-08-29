from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.holdout.football_2025 import (
    HoldoutFootballContractError,
    build_holdout_blocks,
)
from nfl_edge.holdout.xgboost_2025 import predict_xgboost_block

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "data" / "modeling" / "development_v1" / "xgboost_feature_contract_v1.json"


def _features() -> list[str]:
    return list(json.loads(CONTRACT.read_text())["deterministic_ordering"]["feature_order"])


def _base_feature_values(feature_cols: list[str], *, roof: str = "outdoors") -> dict[str, object]:
    values: dict[str, object] = {name: 0.0 for name in feature_cols}
    values["roof_category"] = roof
    return values


def _history(feature_cols: list[str]) -> pl.DataFrame:
    rows = []
    start = datetime(2024, 9, 1, 17, tzinfo=timezone.utc)
    for week in range(1, 7):
        for game in range(12):
            row = _base_feature_values(feature_cols, roof="outdoors" if game % 2 == 0 else "dome")
            row.update(
                {
                    "game_id": f"2024_{week:02d}_{game:02d}",
                    "season": 2024,
                    "season_type": "REG",
                    "week": week,
                    "scheduled_start_utc": start + timedelta(days=7 * (week - 1), minutes=game),
                    "prediction_as_of_utc": start + timedelta(days=7 * (week - 1) - 2),
                    "home_team": f"H{game:02d}",
                    "away_team": f"A{game:02d}",
                    "neutral_site": False,
                    "target_available": True,
                    "target_home_win": 1 if game % 2 == 0 else 0,
                    "target_tie": False,
                    "target_margin": 3 if game % 2 == 0 else -3,
                }
            )
            rows.append(row)
    return pl.DataFrame(rows)


def _current(feature_cols: list[str], *, roof: str = "outdoors", revealed: bool = False) -> pl.DataFrame:
    row = _base_feature_values(feature_cols, roof=roof)
    row.update(
        {
            "game_id": "2025_01_AAA_BBB",
            "season": 2025,
            "season_type": "REG",
            "week": 1,
            "scheduled_start_utc": datetime(2025, 9, 4, 0, tzinfo=timezone.utc),
            "prediction_as_of_utc": datetime(2025, 9, 1, 18, tzinfo=timezone.utc),
            "home_team": "AAA",
            "away_team": "BBB",
            "neutral_site": False,
            "target_available": revealed,
            "target_home_win": 1 if revealed else None,
            "target_tie": False,
            "target_margin": 7 if revealed else None,
        }
    )
    return pl.DataFrame([row])


def test_xgboost_holdout_uses_frozen_132_feature_contract_and_predicts_label_free():
    feature_cols = _features()
    history = _history(feature_cols)
    current = _current(feature_cols)
    block = build_holdout_blocks(current)[0]
    result = predict_xgboost_block(
        development_reference=history,
        prior_history=history,
        current_games=current,
        block=block,
        feature_cols=feature_cols,
    )
    assert result["candidate_id"] == "conservative"
    assert result["warmup"] is False
    assert result["fit_rows"] == 48
    assert result["validation_rows"] == 24
    assert result["game_ids"] == ["2025_01_AAA_BBB"]
    assert len(result["probabilities"]) == 1
    assert 0.0 < result["probabilities"][0] < 1.0
    assert result["categorical_vocabulary"]["roof_category"] == ["dome", "outdoors"]
    assert result["outcomes_revealed"] is False


def test_xgboost_holdout_rejects_unseen_2025_category_instead_of_learning_it():
    feature_cols = _features()
    history = _history(feature_cols)
    current = _current(feature_cols, roof="future_roof_category")
    block = build_holdout_blocks(current)[0]
    with pytest.raises(HoldoutFootballContractError, match="unseen XGBoost category"):
        predict_xgboost_block(
            development_reference=history,
            prior_history=history,
            current_games=current,
            block=block,
            feature_cols=feature_cols,
        )


def test_xgboost_holdout_rejects_current_outcome_before_fit():
    feature_cols = _features()
    history = _history(feature_cols)
    current = _current(feature_cols, revealed=True)
    block = build_holdout_blocks(_current(feature_cols))[0]
    with pytest.raises(HoldoutFootballContractError, match="outcome already marked available"):
        predict_xgboost_block(
            development_reference=history,
            prior_history=history,
            current_games=current,
            block=block,
            feature_cols=feature_cols,
        )


def test_xgboost_holdout_rejects_feature_order_drift():
    feature_cols = _features()
    changed = list(feature_cols)
    changed[0], changed[1] = changed[1], changed[0]
    history = _history(feature_cols)
    current = _current(feature_cols)
    block = build_holdout_blocks(current)[0]
    with pytest.raises(HoldoutFootballContractError, match="feature order drift"):
        predict_xgboost_block(
            development_reference=history,
            prior_history=history,
            current_games=current,
            block=block,
            feature_cols=changed,
        )
