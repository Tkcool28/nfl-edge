from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from nfl_edge.holdout.football_2025 import build_holdout_blocks
from nfl_edge.holdout.xgboost_2025 import predict_xgboost_block
from nfl_edge.holdout.xgboost_2025_v2 import predict_xgboost_block_v2

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "data" / "modeling" / "development_v1" / "xgboost_feature_contract_v1.json"


def _features() -> list[str]:
    return list(json.loads(CONTRACT.read_text())["deterministic_ordering"]["feature_order"])


def _base_feature_values(feature_cols: list[str], *, roof: str = "outdoors") -> dict[str, object]:
    values: dict[str, object] = {name: 0.0 for name in feature_cols}
    values["roof_category"] = roof
    return values


def _row(
    feature_cols: list[str],
    *,
    game_id: str,
    season_type: str,
    week: int,
    start: datetime,
    target: int,
    roof: str,
) -> dict[str, object]:
    row = _base_feature_values(feature_cols, roof=roof)
    row.update(
        {
            "game_id": game_id,
            "season": 2024,
            "season_type": season_type,
            "week": week,
            "scheduled_start_utc": start,
            "prediction_as_of_utc": start - timedelta(days=2),
            "home_team": f"H_{game_id}",
            "away_team": f"A_{game_id}",
            "neutral_site": False,
            "target_available": True,
            "target_home_win": target,
            "target_tie": False,
            "target_margin": 3 if target else -3,
        }
    )
    return row


def _season_end_history(feature_cols: list[str]) -> pl.DataFrame:
    """Enough total history, but the final two postseason blocks have only 3 rows."""
    rows: list[dict[str, object]] = []
    start = datetime(2024, 9, 1, 17, tzinfo=timezone.utc)

    # Eight healthy regular-season blocks. The final REG block alone is large
    # enough to bring the adaptive validation tail above 21 rows.
    for week in range(1, 9):
        for game in range(16):
            rows.append(
                _row(
                    feature_cols,
                    game_id=f"2024_REG_{week:02d}_{game:02d}",
                    season_type="REG",
                    week=week,
                    start=start + timedelta(days=7 * (week - 1), minutes=game),
                    target=1 if game % 2 == 0 else 0,
                    roof="outdoors" if game % 2 == 0 else "dome",
                )
            )

    postseason = [("WC", 19, 6), ("DIV", 20, 4), ("CON", 21, 2), ("SB", 22, 1)]
    postseason_start = start + timedelta(days=7 * 18)
    for idx, (season_type, week, games) in enumerate(postseason):
        for game in range(games):
            rows.append(
                _row(
                    feature_cols,
                    game_id=f"2024_{season_type}_{game:02d}",
                    season_type=season_type,
                    week=week,
                    start=postseason_start + timedelta(days=7 * idx, minutes=game),
                    target=1 if game % 2 == 0 else 0,
                    roof="outdoors" if game % 2 == 0 else "dome",
                )
            )
    return pl.DataFrame(rows)


def _current(feature_cols: list[str]) -> pl.DataFrame:
    row = _base_feature_values(feature_cols, roof="outdoors")
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
            "target_available": False,
            "target_home_win": None,
            "target_tie": False,
            "target_margin": None,
        }
    )
    return pl.DataFrame([row])


def test_v2_eliminates_artificial_week1_warmup_with_abundant_prior_history():
    feature_cols = _features()
    history = _season_end_history(feature_cols)
    current = _current(feature_cols)
    block = build_holdout_blocks(current)[0]

    frozen_v1 = predict_xgboost_block(
        development_reference=history,
        prior_history=history,
        current_games=current,
        block=block,
        feature_cols=feature_cols,
    )
    assert frozen_v1["warmup"] is True
    assert frozen_v1["warmup_reason"] == "insufficient_validation_rows"
    assert frozen_v1["validation_rows"] == 3

    successor = predict_xgboost_block_v2(
        development_reference=history,
        prior_history=history,
        current_games=current,
        block=block,
        feature_cols=feature_cols,
    )
    assert successor["split_policy_version"] == "ADAPTIVE_STRICT_PRIOR_VALIDATION_TAIL_V2"
    assert successor["warmup"] is False
    assert successor["fit_rows"] >= 32
    assert successor["fit_blocks"] >= 2
    assert successor["validation_rows"] >= 21
    assert successor["validation_blocks"] > 2
    assert successor["game_ids"] == ["2025_01_AAA_BBB"]
    assert len(successor["probabilities"]) == 1
    assert 0.0 < successor["probabilities"][0] < 1.0
    assert successor["outcomes_revealed"] is False


def test_v2_validation_tail_remains_strictly_prior():
    feature_cols = _features()
    history = _season_end_history(feature_cols)
    current = _current(feature_cols)
    block = build_holdout_blocks(current)[0]

    result = predict_xgboost_block_v2(
        development_reference=history,
        prior_history=history,
        current_games=current,
        block=block,
        feature_cols=feature_cols,
    )
    # The sealed current row is prediction-only. If it leaked into validation,
    # the adapter's null-target/current-block guards would fail before fitting.
    assert result["warmup"] is False
    assert result["outcomes_revealed"] is False
