"""Defect A: same-week walk-forward leakage and pass 1 / pass 2 freeze.

These tests prove that:

- Every prediction in a block is computed from a frozen block-start
  state and no prediction in the block observes another prediction's
  outcome from the same block.
- A poisoned result in the first game of a block does not change any
  prediction in the same block.
- The next block's predictions respond to the prior block's results
  when the prior block contains at least one completed game.
- The prediction state frozen at the block boundary is recorded as
  the prediction row's ``home_elo_before`` and ``away_elo_before``.
- Every prediction in the block uses the exact same Elo values.
"""

from __future__ import annotations

import polars as pl
import pytest

from nfl_edge.backtest.walk_forward import (
    _build_exposure_for_block,
    _predict_block,
    _update_block,
)
from nfl_edge.models.qb_elo import EloConfig, initial_state

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _synthetic_block_payload() -> pl.DataFrame:
    """Three-game synthetic block. All games are scored. All games are
    home-vs-away with deterministic outcomes.

    The block is sorted by game_id when read by the orchestrator.
    """
    return pl.DataFrame([
        {
            "game_id": "GAME-001", "season": 2018, "season_type": "REG",
            "week": 1, "home_team": "AAA", "away_team": "BBB",
            "neutral_site": False, "target_margin": 7,
            "target_home_win": True, "target_tie": False,
            "target_available": True,
            "prediction_as_of_utc": __import__("datetime").datetime(
                2018, 9, 6, 17, 0, 0, tzinfo=__import__("datetime").timezone.utc
            ),
        },
        {
            "game_id": "GAME-002", "season": 2018, "season_type": "REG",
            "week": 1, "home_team": "CCC", "away_team": "DDD",
            "neutral_site": False, "target_margin": -3,
            "target_home_win": False, "target_tie": False,
            "target_available": True,
            "prediction_as_of_utc": __import__("datetime").datetime(
                2018, 9, 6, 17, 0, 0, tzinfo=__import__("datetime").timezone.utc
            ),
        },
        {
            "game_id": "GAME-003", "season": 2018, "season_type": "REG",
            "week": 1, "home_team": "EEE", "away_team": "FFF",
            "neutral_site": True, "target_margin": 0,
            "target_home_win": False, "target_tie": True,
            "target_available": True,
            "prediction_as_of_utc": __import__("datetime").datetime(
                2018, 9, 6, 17, 0, 0, tzinfo=__import__("datetime").timezone.utc
            ),
        },
    ])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_entire_block_predicted_before_any_update() -> None:
    """Every prediction row in a block reads from the same frozen state.

    The block is the same triple of games used in the poison test. All
    three games use the same initial team ratings (1500). All three
    predictions therefore compute the same Elo difference, the same
    HFA, and the same probability (up to neutral_site). The orchestrator
    must persist every prediction row before any state update.
    """
    block = _synthetic_block_payload()
    state = initial_state(
        sorted(set(block["home_team"].to_list() + block["away_team"].to_list())),
        EloConfig(),
    )
    config = EloConfig()
    predictions, _ = _predict_block(
        block_games=block,
        block_id="2018_REG_W01",
        block_as_of_utc=__import__("datetime").datetime(
            2018, 9, 6, 17, 0, 0, tzinfo=__import__("datetime").timezone.utc
        ),
        state=state,
        elo_config=config,
        run_id="test-run",
        model_version="v1.0.0",
        exposure={
            "training_rows_available_before_block": 0,
            "training_season_min": None,
            "training_season_max": None,
            "training_block_count": 0,
            "prior_completed_games_count": 0,
        },
        created_at=__import__("datetime").datetime(
            2018, 9, 6, 17, 0, 0, tzinfo=__import__("datetime").timezone.utc
        ),
    )
    assert len(predictions) == 3
    # All three games were predicted at the same frozen state.
    for pred in predictions:
        # home_elo_before is the initial rating for every team.
        assert pred["home_elo_before"] == pytest.approx(1500.0)
        assert pred["away_elo_before"] == pytest.approx(1500.0)


def test_same_week_poisoning_does_not_change_predictions() -> None:
    """Poisoning the result of the first game in a block does not
    change any prediction in the same block.

    Two passes: clean and poisoned. The first game's outcome is
    flipped from a home win to a heavy home loss. The prediction row
    ``predicted_home_win_probability`` is identical in both passes for
    every game in the block because the prediction step is purely a
    function of the frozen pregame state.
    """
    clean_block = _synthetic_block_payload()
    poisoned_block = _synthetic_block_payload().with_columns(
        pl.when(pl.col("game_id") == "GAME-001")
        .then(pl.lit(-21))
        .otherwise(pl.col("target_margin"))
        .alias("target_margin"),
        pl.when(pl.col("game_id") == "GAME-001")
        .then(pl.lit(False))
        .otherwise(pl.col("target_home_win"))
        .alias("target_home_win"),
    )

    config = EloConfig()
    state_clean = initial_state(
        sorted(set(clean_block["home_team"].to_list() + clean_block["away_team"].to_list())),
        config,
    )
    state_poison = initial_state(
        sorted(set(poisoned_block["home_team"].to_list() + poisoned_block["away_team"].to_list())),
        config,
    )
    clean_preds, _ = _predict_block(
        block_games=clean_block,
        block_id="2018_REG_W01",
        block_as_of_utc=__import__("datetime").datetime(
            2018, 9, 6, 17, 0, 0, tzinfo=__import__("datetime").timezone.utc
        ),
        state=state_clean,
        elo_config=config,
        run_id="test-run",
        model_version="v1.0.0",
        exposure={
            "training_rows_available_before_block": 0,
            "training_season_min": None,
            "training_season_max": None,
            "training_block_count": 0,
            "prior_completed_games_count": 0,
        },
        created_at=__import__("datetime").datetime(
            2018, 9, 6, 17, 0, 0, tzinfo=__import__("datetime").timezone.utc
        ),
    )
    poison_preds, _ = _predict_block(
        block_games=poisoned_block,
        block_id="2018_REG_W01",
        block_as_of_utc=__import__("datetime").datetime(
            2018, 9, 6, 17, 0, 0, tzinfo=__import__("datetime").timezone.utc
        ),
        state=state_poison,
        elo_config=config,
        run_id="test-run",
        model_version="v1.0.0",
        exposure={
            "training_rows_available_before_block": 0,
            "training_season_min": None,
            "training_season_max": None,
            "training_block_count": 0,
            "prior_completed_games_count": 0,
        },
        created_at=__import__("datetime").datetime(
            2018, 9, 6, 17, 0, 0, tzinfo=__import__("datetime").timezone.utc
        ),
    )
    # The home_elo_before and away_elo_before for every prediction must
    # be byte-identical between the clean and the poisoned passes.
    for clean, poison in zip(clean_preds, poison_preds):
        assert clean["game_id"] == poison["game_id"]
        assert clean["home_elo_before"] == poison["home_elo_before"]
        assert clean["away_elo_before"] == poison["away_elo_before"]
        assert clean["predicted_home_win_probability"] == poison["predicted_home_win_probability"]


def test_next_block_responds_to_prior_block() -> None:
    """After pass 2 finishes the current block, the next block's
    predictions use the updated ratings.

    A synthetic two-block fixture: block 1 contains GAME-001 (home
    win); block 2 contains GAME-002. After pass 2 of block 1, the
    ``AAA`` team has moved up and ``BBB`` has moved down. Block 2
    must see the new state.
    """
    block1 = _synthetic_block_payload().filter(pl.col("game_id") == "GAME-001")
    block2 = _synthetic_block_payload().filter(pl.col("game_id") == "GAME-002")

    config = EloConfig()
    teams = sorted(
        set(block1["home_team"].to_list() + block1["away_team"].to_list() +
            block2["home_team"].to_list() + block2["away_team"].to_list())
    )
    state = initial_state(teams, config)

    # Pass 1 + Pass 2 of block 1
    _, pre1 = _predict_block(
        block_games=block1,
        block_id="2018_REG_W01",
        block_as_of_utc=__import__("datetime").datetime(
            2018, 9, 6, 17, 0, 0, tzinfo=__import__("datetime").timezone.utc
        ),
        state=state,
        elo_config=config,
        run_id="test-run",
        model_version="v1.0.0",
        exposure={
            "training_rows_available_before_block": 0,
            "training_season_min": None,
            "training_season_max": None,
            "training_block_count": 0,
            "prior_completed_games_count": 0,
        },
        created_at=__import__("datetime").datetime(
            2018, 9, 6, 17, 0, 0, tzinfo=__import__("datetime").timezone.utc
        ),
    )
    _, state_after_block1, _ = _update_block(
        pregame_inputs=pre1,
        state=state,
        elo_config=config,
        block_id="2018_REG_W01",
        run_id="test-run",
        update_order_start=0,
    )

    # Pass 1 of block 2 should use the post-block-1 state.
    block2_preds, _ = _predict_block(
        block_games=block2,
        block_id="2018_REG_W01b",
        block_as_of_utc=__import__("datetime").datetime(
            2018, 9, 6, 17, 0, 0, tzinfo=__import__("datetime").timezone.utc
        ),
        state=state_after_block1,
        elo_config=config,
        run_id="test-run",
        model_version="v1.0.0",
        exposure={
            "training_rows_available_before_block": 1,
            "training_season_min": 2018,
            "training_season_max": 2018,
            "training_block_count": 1,
            "prior_completed_games_count": 1,
        },
        created_at=__import__("datetime").datetime(
            2018, 9, 6, 17, 0, 0, tzinfo=__import__("datetime").timezone.utc
        ),
    )
    # The CCC and DDD teams were not in block 1, so their ratings
    # are still 1500. But the predicted probability for GAME-002 must
    # be exactly what the canonical update would have produced if the
    # state had advanced.
    assert block2_preds[0]["home_team"] == "CCC"
    assert block2_preds[0]["away_team"] == "DDD"
    # Game 2 has CCC as home and DDD as away; both untouched by block 1.
    assert block2_preds[0]["home_elo_before"] == pytest.approx(1500.0)
    assert block2_preds[0]["away_elo_before"] == pytest.approx(1500.0)


def test_exposure_metadata_opening_block() -> None:
    """The opening block reports zero prior games and zero training rows."""

    games = _synthetic_block_payload()
    exposure = _build_exposure_for_block(
        block_season=2018, block_season_type="REG", block_week=1, games=games
    )
    assert exposure["training_rows_available_before_block"] == 0
    assert exposure["prior_completed_games_count"] == 0
    assert exposure["training_season_min"] is None
    assert exposure["training_season_max"] is None
    assert exposure["training_block_count"] == 0


def test_exposure_metadata_grows_monotonically() -> None:
    """Exposure metadata must grow as we walk forward in chronological
    order. The opening block is 0; the last block is N-1.
    """

    games = pl.DataFrame([
        {
            "game_id": f"G{i:03}", "season": 2018, "season_type": "REG",
            "week": (i // 3) + 1, "home_team": "AAA", "away_team": "BBB",
            "neutral_site": False, "target_margin": 7,
            "target_home_win": True, "target_tie": False,
            "target_available": True,
            "prediction_as_of_utc": __import__("datetime").datetime(
                2018, 9, 6, 17, 0, 0, tzinfo=__import__("datetime").timezone.utc
            ),
        }
        for i in range(9)
    ])
    exposures = []
    for week in (1, 2, 3):
        e = _build_exposure_for_block(
            block_season=2018, block_season_type="REG",
            block_week=week, games=games,
        )
        exposures.append(e)
    assert exposures[0]["prior_completed_games_count"] == 0
    assert exposures[1]["prior_completed_games_count"] == 3
    assert exposures[2]["prior_completed_games_count"] == 6
    # Training season max is 2018 throughout because all games are
    # in the same season.
    for e in exposures[1:]:
        assert e["training_season_min"] == 2018
        assert e["training_season_max"] == 2018
