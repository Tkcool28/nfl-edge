"""Focused unit tests for the Task 03B runner wiring.

These tests exercise ``_extract_development_games`` — the runner step
that joins the canonical point-in-time development features to the
frozen completed-game final scores. The tests prove the runner-level
guards:

  1. duplicate ``game_id`` keys on either source are rejected;
  2. feature rows without a matching frozen completed-game score are
     rejected (never silently dropped);
  3. the returned extraction contains exactly seasons 2018-2024;
  4. 2025 sealed-holdout rows are excluded before any model boundary;
  5. forward-use seasons (2026 and later) are rejected at the
     boundary;
  6. joined home and away scores attach to the correct game.

Note on current-block leakage (the runner test does NOT duplicate it):
the isolation of the current block's outcome from its own prediction
is enforced by the walk-forward and already covered by
``tests/models/test_expected_margin_v1_model.py``
(``test_current_block_outcome_poisoning_does_not_mutate_block``,
``test_future_outcome_poisoning_does_not_leak``,
``test_current_block_excluded_from_mapping``).

These tests write only under pytest's ``tmp_path``; they generate no
permanent artifacts.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import polars as pl
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNNER_FILE = REPO_ROOT / "scripts" / "expected_margin_v1_runner.py"

_spec = importlib.util.spec_from_file_location(
    "expected_margin_v1_runner", _RUNNER_FILE
)
assert _spec is not None and _spec.loader is not None
_runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_runner)
_extract = _runner._extract_development_games


def _feature_frame(seasons: list[int]) -> pl.DataFrame:
    rows = [
        {
            "game_id": f"g{s}",
            "season": s,
            "home_team": f"H{s}",
            "away_team": f"A{s}",
            "point_in_time_feature": float(s) * 1.5,
        }
        for s in seasons
    ]
    return pl.DataFrame(rows)


def _games_frame(season_to_scores: dict[int, tuple[int, int]]) -> pl.DataFrame:
    rows = [
        {
            "game_id": f"g{s}",
            "home_score": h,
            "away_score": a,
        }
        for s, (h, a) in season_to_scores.items()
    ]
    return pl.DataFrame(rows)


def _write(tmp_path: Path, df: pl.DataFrame) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / f"{df.columns[0]}.parquet"
    df.write_parquet(p)
    return p


def test_output_seasons_exactly_2018_to_2024(tmp_path: Path) -> None:
    seasons = list(range(2018, 2025))
    feats = _write(tmp_path / "f", _feature_frame(seasons))
    games = _write(tmp_path / "g", _games_frame({s: (24, 17) for s in seasons}))
    out = _extract(feats, games, None)
    assert sorted(int(s) for s in out["season"].unique().to_list()) == seasons
    assert out.height == 7
    # Point-in-time features are preserved alongside the joined scores.
    assert "point_in_time_feature" in out.columns
    assert "home_score" in out.columns and "away_score" in out.columns


def test_2025_excluded_before_model_boundary(tmp_path: Path) -> None:
    seasons = list(range(2018, 2026))  # includes the 2025 sealed holdout
    feats = _write(tmp_path / "f", _feature_frame(seasons))
    games = _write(tmp_path / "g", _games_frame({s: (20, 10) for s in seasons}))
    out = _extract(feats, games, None)
    # 2025 must NOT be in the development frame.
    assert sorted(int(s) for s in out["season"].unique().to_list()) == list(
        range(2018, 2025)
    )
    assert 2025 not in out["season"].to_list()


def test_2026_rejected_at_boundary(tmp_path: Path) -> None:
    seasons = list(range(2018, 2027))  # contains 2026 forward-use season
    feats = _write(tmp_path / "f", _feature_frame(seasons))
    games = _write(tmp_path / "g", _games_frame({s: (20, 10) for s in seasons}))
    with pytest.raises(ValueError, match="forward-use seasons"):
        _extract(feats, games, None)


def test_duplicate_frozen_game_key_rejected(tmp_path: Path) -> None:
    feats = _write(tmp_path / "f", _feature_frame([2018, 2019]))
    dup_games = pl.DataFrame(
        [
            {"game_id": "g2018", "home_score": 24, "away_score": 17},
            {"game_id": "g2018", "home_score": 27, "away_score": 14},
            {"game_id": "g2019", "home_score": 20, "away_score": 7},
        ]
    )
    games = _write(tmp_path / "g", dup_games)
    with pytest.raises(ValueError, match="Duplicate game_id"):
        _extract(feats, games, None)


def test_missing_score_match_rejected(tmp_path: Path) -> None:
    # Features has a game_id (g2024) with no frozen score row.
    feats = pl.DataFrame(
        [
            {"game_id": "g2018", "season": 2018, "home_team": "H", "away_team": "A"},
            {"game_id": "g2024", "season": 2024, "home_team": "H", "away_team": "A"},
        ]
    )
    games = pl.DataFrame(
        [{"game_id": "g2018", "home_score": 20, "away_score": 13}]
    )
    f = _write(tmp_path / "f", feats)
    g = _write(tmp_path / "g", games)
    with pytest.raises(ValueError, match="no matching frozen completed-game score"):
        _extract(f, g, None)


def test_joined_scores_match_correct_game_id(tmp_path: Path) -> None:
    seasons = list(range(2018, 2025))
    feats_df = _feature_frame(seasons)
    feats = _write(tmp_path / "f", feats_df)
    scores = {s: (20, 10) for s in seasons}
    scores[2018] = (31, 3)
    scores[2019] = (14, 28)
    games = _write(tmp_path / "g", _games_frame(scores))
    out = _extract(feats, games, None)
    row_2018 = out.filter(pl.col("season") == 2018)
    row_2019 = out.filter(pl.col("season") == 2019)
    # g2018 home/away scores (31, 3) attach only to g2018.
    assert int(row_2018["home_score"][0]) == 31
    assert int(row_2018["away_score"][0]) == 3
    assert int(row_2019["home_score"][0]) == 14
    assert int(row_2019["away_score"][0]) == 28
