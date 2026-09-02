from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.models.xgboost_live_v2 import (
    XGBoostLiveContractError,
    predict_xgboost_live_block_v2,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "data" / "modeling" / "development_v1" / "xgboost_feature_contract_v1.json"


def _features() -> list[str]:
    return list(json.loads(CONTRACT.read_text())["deterministic_ordering"]["feature_order"])


def _feature_values(feature_cols: list[str], roof: str) -> dict[str, object]:
    values: dict[str, object] = {name: 0.0 for name in feature_cols}
    values["roof_category"] = roof
    return values


def _settled_row(
    feature_cols: list[str],
    *,
    season: int,
    season_type: str,
    week: int,
    game: int,
    start: datetime,
) -> dict[str, object]:
    row = _feature_values(feature_cols, "outdoors" if game % 2 == 0 else "dome")
    target = 1 if game % 2 == 0 else 0
    row.update(
        {
            "game_id": f"{season}_{season_type}_{week:02d}_{game:02d}",
            "season": season,
            "season_type": season_type,
            "week": week,
            "scheduled_start_utc": start,
            "prediction_as_of_utc": start - timedelta(days=2),
            "home_team": f"H{game:02d}",
            "away_team": f"A{game:02d}",
            "neutral_site": False,
            "target_available": True,
            "target_home_win": target,
            "target_tie": False,
            "target_margin": 3 if target else -3,
        }
    )
    return row


def _season_end(feature_cols: list[str], season: int) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    start = datetime(season, 9, 1, 17, tzinfo=timezone.utc)
    for week in range(1, 9):
        for game in range(16):
            rows.append(
                _settled_row(
                    feature_cols,
                    season=season,
                    season_type="REG",
                    week=week,
                    game=game,
                    start=start + timedelta(days=7 * (week - 1), minutes=game),
                )
            )
    for idx, (season_type, week, games) in enumerate(
        [("WC", 19, 6), ("DIV", 20, 4), ("CON", 21, 2), ("SB", 22, 1)]
    ):
        for game in range(games):
            rows.append(
                _settled_row(
                    feature_cols,
                    season=season,
                    season_type=season_type,
                    week=week,
                    game=game,
                    start=start + timedelta(days=7 * (18 + idx), minutes=game),
                )
            )
    return pl.DataFrame(rows)


def _current(feature_cols: list[str], season: int) -> pl.DataFrame:
    row = _feature_values(feature_cols, "outdoors")
    row.update(
        {
            "game_id": f"{season}_REG_01_LIVE",
            "season": season,
            "season_type": "REG",
            "week": 1,
            "scheduled_start_utc": datetime(season, 9, 4, 0, tzinfo=timezone.utc),
            "prediction_as_of_utc": datetime(season, 9, 1, 18, tzinfo=timezone.utc),
            "home_team": "LIVE_HOME",
            "away_team": "LIVE_AWAY",
            "neutral_site": False,
            "target_available": False,
            "target_home_win": None,
            "target_tie": False,
            "target_margin": None,
        }
    )
    return pl.DataFrame([row])


def test_live_v2_predicts_2026_week1_from_strictly_prior_2025_history():
    feature_cols = _features()
    development_reference = _season_end(feature_cols, 2024)
    prior_history = _season_end(feature_cols, 2025)
    current = _current(feature_cols, 2026)

    result = predict_xgboost_live_block_v2(
        development_reference=development_reference,
        prior_history=prior_history,
        current_games=current,
        season=2026,
        season_type="REG",
        week=1,
        feature_cols=feature_cols,
    )

    assert result["season"] == 2026
    assert result["week"] == 1
    assert result["split_policy_version"] == "ADAPTIVE_STRICT_PRIOR_VALIDATION_TAIL_V2"
    assert result["warmup"] is False
    assert result["fit_rows"] >= 32
    assert result["validation_rows"] >= 21
    assert result["validation_blocks"] > 2
    assert result["game_ids"] == ["2026_REG_01_LIVE"]
    assert len(result["probabilities"]) == 1
    assert 0.0 < result["probabilities"][0] < 1.0
    assert result["outcomes_revealed"] is False


def test_live_v2_rejects_current_or_future_history():
    feature_cols = _features()
    development_reference = _season_end(feature_cols, 2024)
    prior_history = pl.concat(
        [_season_end(feature_cols, 2025), _season_end(feature_cols, 2026)],
        how="vertical_relaxed",
    )
    current = _current(feature_cols, 2026)

    with pytest.raises(XGBoostLiveContractError, match="current/future"):
        predict_xgboost_live_block_v2(
            development_reference=development_reference,
            prior_history=prior_history,
            current_games=current,
            season=2026,
            season_type="REG",
            week=1,
            feature_cols=feature_cols,
        )


def test_live_v2_rejects_revealed_current_outcome():
    feature_cols = _features()
    development_reference = _season_end(feature_cols, 2024)
    prior_history = _season_end(feature_cols, 2025)
    current = _current(feature_cols, 2026).with_columns(pl.lit(1).alias("target_home_win"))

    with pytest.raises(XGBoostLiveContractError, match="target_home_win must be null"):
        predict_xgboost_live_block_v2(
            development_reference=development_reference,
            prior_history=prior_history,
            current_games=current,
            season=2026,
            season_type="REG",
            week=1,
            feature_cols=feature_cols,
        )
