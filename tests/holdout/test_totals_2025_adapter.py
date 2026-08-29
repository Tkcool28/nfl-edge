from __future__ import annotations

from datetime import datetime, timezone

import polars as pl
import pytest

from nfl_edge.features.totals_v1.feature_table import EXACT_90_COLUMNS
from nfl_edge.holdout.football_2025 import (
    HoldoutFootballContractError,
    build_holdout_blocks,
)
from nfl_edge.holdout.totals_2025 import predict_ridge_totals_block


def _feature_values(seed: int = 0) -> dict[str, object]:
    values: dict[str, object] = {name: 0.0 for name in EXACT_90_COLUMNS}
    values["roof_category"] = "outdoors" if seed % 2 == 0 else "dome"
    values["surface_category"] = "grass" if seed % 2 == 0 else "fieldturf"
    values["away_rest_days"] = float(6 + seed % 4)
    values["home_rest_days"] = float(6 + (seed + 1) % 4)
    values["away_matchup_epa_per_play"] = float(seed) / 100.0
    return values


def _development_history() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    ordinal = 0
    for season in range(2018, 2025):
        for game in range(10):
            week = game + 1
            row = _feature_values(ordinal)
            row.update(
                {
                    "game_id": f"{season}_{game:02d}_AAA_BBB",
                    "season": season,
                    "season_type": "REG",
                    "week": week,
                    "home_team": "AAA",
                    "away_team": "BBB",
                    "block_id": f"{season}_REG_W{week:02d}",
                    "target_available": True,
                    "target_total_points": float(38 + ordinal % 15),
                }
            )
            rows.append(row)
            ordinal += 1
    return pl.DataFrame(rows)


def _current(*, total: float | None = None, home_score: int | None = None) -> pl.DataFrame:
    row = _feature_values(999)
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
            "block_id": "2025_REG_W01",
            "target_available": home_score is not None,
            "target_total_points": total,
            "target_margin": None,
            "target_home_win": None,
            "home_score": home_score,
            "away_score": None,
        }
    )
    return pl.DataFrame([row])


def test_r4_totals_holdout_predicts_current_block_without_current_target():
    history = _development_history()
    current = _current()
    block = build_holdout_blocks(current)[0]

    result = predict_ridge_totals_block(
        prior_history=history,
        current_games=current,
        block=block,
    )

    assert result["candidate_id"] == "R4"
    assert result["alpha"] == 100
    assert result["fit_rows"] == 70
    assert result["game_ids"] == ["2025_01_AAA_BBB"]
    assert len(result["predicted_totals"]) == 1
    assert isinstance(result["predicted_totals"][0], float)
    assert result["outcomes_revealed"] is False


def test_r4_totals_holdout_rejects_revealed_current_outcome():
    history = _development_history()
    sealed = _current()
    block = build_holdout_blocks(sealed)[0]

    with pytest.raises(HoldoutFootballContractError, match="outcome already marked available"):
        predict_ridge_totals_block(
            prior_history=history,
            current_games=_current(home_score=24),
            block=block,
        )


def test_r4_totals_holdout_rejects_current_total_target_even_without_score():
    history = _development_history()
    current = _current(total=47.0)
    block = build_holdout_blocks(_current())[0]

    with pytest.raises(HoldoutFootballContractError, match="target_total_points must be null"):
        predict_ridge_totals_block(
            prior_history=history,
            current_games=current,
            block=block,
        )


def test_r4_totals_holdout_requires_complete_frozen_development_seasons():
    history = _development_history().filter(pl.col("season") != 2018)
    current = _current()
    block = build_holdout_blocks(current)[0]

    with pytest.raises(HoldoutFootballContractError, match="exactly seasons 2018-2024"):
        predict_ridge_totals_block(
            prior_history=history,
            current_games=current,
            block=block,
        )


def test_r4_totals_holdout_rejects_unrevealed_prior_2025_rows():
    history = _development_history()
    prior = _current().with_columns(
        pl.lit(0).alias("week"),
        pl.lit("2025_REG_W00").alias("block_id"),
        pl.lit(45.0).alias("target_total_points"),
        pl.lit(False).alias("target_available"),
    )
    history = pl.concat([history, prior.select(history.columns)], how="vertical")
    current = _current()
    block = build_holdout_blocks(current)[0]

    with pytest.raises(HoldoutFootballContractError, match="unrevealed target"):
        predict_ridge_totals_block(
            prior_history=history,
            current_games=current,
            block=block,
        )
