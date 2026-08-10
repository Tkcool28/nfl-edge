"""Task 04C-3 focused tests: minimal paired QB-Elo evaluation harness.

Proves the two modes (BASELINE vs ORACLE) differ only in the prediction
path and share byte-identical team-Elo transitions, plus the oracle
fail-closed contract and the canonical block chronology invariants.

These are evaluation-only fixture tests. They do NOT run the full
1942-game universe and do NOT compute model-quality metrics.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.backtest.task04c_paired_evaluation import (
    OracleAdjustmentError,
    OracleQBAdjustments,
    assert_transition_ledgers_equal,
    build_transition_audit_ledger,
    make_resolver,
)
from nfl_edge.backtest.walk_forward import (
    _predict_block,
    _update_block,
    run_development_walk_forward,
)
from nfl_edge.common.errors import SealedHoldoutAccessError
from nfl_edge.models.qb_elo import EloConfig, initial_state

REPO_ROOT = Path(__file__).resolve().parents[2]
ORACLE_PATH = (
    REPO_ROOT
    / "data/derived/oracle_qb_entering_state_v2"
    / "oracle_qb_pregame_adjustments_by_game_2018_2024_v2.parquet"
)
AS_OF = datetime(2018, 9, 6, 17, 0, 0, tzinfo=timezone.utc)
GAMES_PATH = REPO_ROOT / "data/derived/features_v1/game_features_2018_2025.parquet"
TEAM_PATH = REPO_ROOT / "data/derived/features_v1/team_pregame_features_2018_2025.parquet"

# A real oracle game with nonzero home AND away adjustments and no same-block
# repeated-team issue when used alone.
ORACLE_GAME = "2018_02_ARI_LA"  # home=LAR away=ARI
ORACLE_HOME = 12.635426
ORACLE_AWAY = -22.784371


def _exposure(**kw) -> dict:
    base = {
        "training_rows_available_before_block": 0,
        "training_season_min": None,
        "training_season_max": None,
        "training_block_count": 0,
        "prior_completed_games_count": 0,
    }
    base.update(kw)
    return base


def _block_row(
    game_id: str,
    home: str,
    away: str,
    *,
    margin: int = 7,
    home_win: bool = True,
    tie: bool = False,
    season: int = 2018,
    st: str = "REG",
    week: int = 1,
    neutral: bool = False,
) -> dict:
    return {
        "game_id": game_id,
        "season": season,
        "season_type": st,
        "week": week,
        "home_team": home,
        "away_team": away,
        "neutral_site": neutral,
        "target_margin": None if (margin is None or tie) else margin,
        "target_home_win": None if tie else home_win,
        "target_tie": tie,
        "target_available": margin is not None,
        "prediction_as_of_utc": AS_OF,
    }


def _run_block(frames, resolver, config=None):
    cfg = config or EloConfig()
    teams = sorted(
        set(frames["home_team"].to_list() + frames["away_team"].to_list())
    )
    state = initial_state(teams, cfg)
    preds, pre = _predict_block(
        block_games=frames,
        block_id="2018_REG_W01",
        block_as_of_utc=AS_OF,
        state=state,
        elo_config=cfg,
        run_id="task04c-run",
        model_version="v1.0.0",
        exposure=_exposure(),
        created_at=AS_OF,
        qb_adjustment_resolver=resolver,
    )
    updates, new_state, _ = _update_block(
        pregame_inputs=pre,
        state=state,
        elo_config=cfg,
        block_id="2018_REG_W01",
        run_id="task04c-run",
        update_order_start=0,
    )
    return preds, updates, new_state


# ---------------------------------------------------------------------------
# A. Baseline adjustment test
# ---------------------------------------------------------------------------


def test_A_baseline_supplies_zero_adjustments():
    frames = pl.DataFrame([_block_row(ORACLE_GAME, "LAR", "ARI")])
    preds, _, _ = _run_block(frames, make_resolver("BASELINE"))
    for p in preds:
        assert p["home_qb_adjustment"] == 0.0
        assert p["away_qb_adjustment"] == 0.0
        assert p["qb_adjustment_net"] == 0.0
        assert p["qb_certainty_state"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# B. Oracle adjustment test
# ---------------------------------------------------------------------------


def test_B_oracle_consumes_frozen_values():
    frames = pl.DataFrame([_block_row(ORACLE_GAME, "LAR", "ARI")])
    oracle = OracleQBAdjustments(ORACLE_PATH)
    preds, _, _ = _run_block(frames, oracle)
    p = preds[0]
    assert p["game_id"] == ORACLE_GAME
    assert p["home_qb_adjustment"] == pytest.approx(ORACLE_HOME)
    assert p["away_qb_adjustment"] == pytest.approx(ORACLE_AWAY)
    assert p["qb_certainty_state"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# C. Probability-isolation test
# ---------------------------------------------------------------------------


def test_C_oracle_changes_probability_when_net_nonzero():
    frames = pl.DataFrame([_block_row(ORACLE_GAME, "LAR", "ARI")])
    base_preds, _, _ = _run_block(frames, make_resolver("BASELINE"))
    oracle = OracleQBAdjustments(ORACLE_PATH)
    oracle_preds, _, _ = _run_block(frames, oracle)
    assert base_preds[0]["game_id"] == oracle_preds[0]["game_id"]
    # Net adjustment = 12.635 - (-22.784) = 35.42 != 0 -> probability must differ
    assert oracle_preds[0]["qb_adjustment_net"] != 0.0
    assert base_preds[0]["predicted_home_win_probability"] != pytest.approx(
        oracle_preds[0]["predicted_home_win_probability"]
    )
    # Same pregame state inputs, only probability (and qb adj) differ.
    assert base_preds[0]["home_elo_before"] == oracle_preds[0]["home_elo_before"]
    assert base_preds[0]["away_elo_before"] == oracle_preds[0]["away_elo_before"]
    assert base_preds[0]["home_field_adjustment"] == oracle_preds[0]["home_field_adjustment"]


# ---------------------------------------------------------------------------
# D. Team-state isolation test (CRITICAL GATE)
# ---------------------------------------------------------------------------


def test_D_baseline_oracle_identical_team_transitions():
    # Two real oracle games in the same block (week 2, 2018 REG).
    frames = pl.DataFrame([
        _block_row("2018_02_ARI_LA", "LAR", "ARI", week=2),
        _block_row("2018_02_CLE_NO", "NO", "CLE", week=2, margin=-6, home_win=False),
    ])
    base_preds, base_updates, _ = _run_block(frames, make_resolver("BASELINE"))
    oracle = OracleQBAdjustments(ORACLE_PATH)
    ora_preds, ora_updates, _ = _run_block(frames, oracle)

    base_t = build_transition_audit_ledger(base_updates)
    ora_t = build_transition_audit_ledger(ora_updates)
    assert base_t.height == ora_t.height == 2
    assert_transition_ledgers_equal(base_t, ora_t)

    # The critical gate: per-game update expectation/delta/postgame elo identical.
    for col in [
        "pregame_home_elo",
        "pregame_away_elo",
        "expected_result_home",
        "delta",
        "postgame_home_elo",
        "postgame_away_elo",
    ]:
        assert base_t[col].to_list() == ora_t[col].to_list(), f"diverged on {col}"

    # Predictions differ (oracle adjustment nonzero) but transitions do not.
    base_p = {p["game_id"]: p for p in base_preds}
    ora_p = {p["game_id"]: p for p in ora_preds}
    assert base_p[ORACLE_GAME]["predicted_home_win_probability"] != pytest.approx(
        ora_p[ORACLE_GAME]["predicted_home_win_probability"]
    )


# ---------------------------------------------------------------------------
# E. Missing oracle game fails closed
# ---------------------------------------------------------------------------


def test_E_missing_oracle_game_fails_closed():
    oracle = OracleQBAdjustments(ORACLE_PATH)
    with pytest.raises(OracleAdjustmentError) as exc:
        oracle("NOT-A-REAL-GAME-ID")
    assert "no oracle row" in str(exc.value)


# ---------------------------------------------------------------------------
# F. Duplicate oracle game fails closed
# ---------------------------------------------------------------------------


def test_F_duplicate_oracle_game_fails_closed(tmp_path):
    dup = pl.DataFrame(
        [
            {"game_id": "G1", "home_qb_adjustment_elo": 1.0, "away_qb_adjustment_elo": 2.0},
            {"game_id": "G1", "home_qb_adjustment_elo": 3.0, "away_qb_adjustment_elo": 4.0},
        ]
    )
    path = tmp_path / "dup.parquet"
    dup.write_parquet(path)
    with pytest.raises(OracleAdjustmentError) as exc:
        OracleQBAdjustments(path)
    assert "duplicate" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# G. Null adjustment test
# ---------------------------------------------------------------------------


def test_G_null_adjustment_fails_closed(tmp_path):
    null_row = pl.DataFrame(
        [
            {
                "game_id": "G1",
                "home_qb_adjustment_elo": None,
                "away_qb_adjustment_elo": 2.0,
            }
        ]
    )
    path = tmp_path / "null.parquet"
    null_row.write_parquet(path)
    with pytest.raises(OracleAdjustmentError) as exc:
        OracleQBAdjustments(path)
    assert "null" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# H. Same-block freezing test
# ---------------------------------------------------------------------------


def test_H_block_start_state_shared_all_predictions():
    frames = pl.DataFrame(
        [
            _block_row("G1", "AAA", "BBB", margin=7, home_win=True),
            _block_row("G2", "CCC", "DDD", margin=-3, home_win=False),
            _block_row("G3", "EEE", "FFF", margin=0, tie=True),
        ]
    )
    preds, _, _ = _run_block(frames, make_resolver("BASELINE"))
    # All three predictions at initial rating 1500 -> same frozen block-start state
    for p in preds:
        assert p["home_elo_before"] == pytest.approx(1500.0)
        assert p["away_elo_before"] == pytest.approx(1500.0)
    # Prediction for G2 uses block-start state, NOT the post-G1 state.
    assert preds[1]["game_id"] == "G2"
    assert preds[1]["home_elo_before"] == pytest.approx(1500.0)


# ---------------------------------------------------------------------------
# I. Post-block transition test
# ---------------------------------------------------------------------------


def test_I_transitions_apply_only_after_all_predictions_frozen():
    frames = pl.DataFrame(
        [
            _block_row("G1", "AAA", "BBB", margin=7, home_win=True),
            _block_row("G2", "CCC", "DDD", margin=-3, home_win=False),
        ]
    )
    cfg = EloConfig()
    teams = sorted(set(frames["home_team"].to_list() + frames["away_team"].to_list()))
    state = initial_state(teams, cfg)
    # Pass 1 (predict) with no mutation: assert state unchanged after prediction
    state_after_predict = state
    preds, pre = _predict_block(
        block_games=frames,
        block_id="2018_REG_W01",
        block_as_of_utc=AS_OF,
        state=state_after_predict,
        elo_config=cfg,
        run_id="task04c-run",
        model_version="v1.0.0",
        exposure=_exposure(),
        created_at=AS_OF,
        qb_adjustment_resolver=make_resolver("BASELINE"),
    )
    # A prediction pass never mutates the state: both AAA/BBB still 1500
    assert state_after_predict.rating("AAA") == pytest.approx(1500.0)
    # Only pass 2 (update) advanced ratings.
    _, new_state, _ = _update_block(
        pregame_inputs=pre,
        state=state_after_predict,
        elo_config=cfg,
        block_id="2018_REG_W01",
        run_id="task04c-run",
        update_order_start=0,
    )
    assert new_state.rating("AAA") != pytest.approx(1500.0)
    # G2 predicted while AAA was still 1500 (frozen), evidenced by preds row
    assert preds[0]["home_elo_before"] == pytest.approx(1500.0)


# ---------------------------------------------------------------------------
# J. Canonical ordering determinism
# ---------------------------------------------------------------------------


def test_J_deterministic_repeat(tmp_path):
    frames = pl.DataFrame(
        [
            _block_row("G2", "CCC", "DDD", margin=-3, home_win=False),
            _block_row("G1", "AAA", "BBB", margin=7, home_win=True),
        ]
    )
    r1_preds, r1_updates, _ = _run_block(frames, make_resolver("BASELINE"))
    r2_preds, r2_updates, _ = _run_block(frames, make_resolver("BASELINE"))
    # Deterministic game_id ordering (not input order): G1 before G2
    assert [p["game_id"] for p in r1_preds] == ["G1", "G2"]
    assert [p["game_id"] for p in r2_preds] == ["G1", "G2"]
    assert [p["predicted_home_win_probability"] for p in r1_preds] == [
        p["predicted_home_win_probability"] for p in r2_preds
    ]
    t1 = build_transition_audit_ledger(r1_updates)
    t2 = build_transition_audit_ledger(r2_updates)
    assert_transition_ledgers_equal(t1, t2)


# ---------------------------------------------------------------------------
# K. 2025 exclusion
# ---------------------------------------------------------------------------


def test_K_2025_rows_excluded_and_rejected(tmp_path):
    from nfl_edge.backtest.blocks import (
        DEVELOPMENT_SEASON_MAX,
        assert_development_seasons_only,
        build_development_blocks,
    )

    # A 2025-only frame is rejected by the boundary tripwire and yields no
    # development blocks (2025 can never enter the Task04C dev schedule).
    bad = pl.DataFrame([_block_row("FUTURE-2025", "AAA", "BBB", season=2025)])
    with pytest.raises(SealedHoldoutAccessError):
        assert_development_seasons_only(bad)
    assert build_development_blocks(bad) == []

    # A mixed 2018+2025 fixture: blocks must contain only development rows.
    mixed = pl.DataFrame(
        [
            _block_row("G-2018-A", "AAA", "BBB", season=2018, week=1),
            _block_row("G-2018-B", "CCC", "DDD", season=2018, week=1),
            _block_row("G-FUTURE", "EEE", "FFF", season=2025, week=1),
        ]
    )
    blocks = build_development_blocks(mixed)
    assert all(b.season <= DEVELOPMENT_SEASON_MAX for b in blocks)
    assert blocks  # dev blocks present
    # No 2025 block id present.
    assert not any("2025" in b.block_id for b in blocks)
    # The engine's two-pass walk over the minimal dev fixture exposes only
    # development rows in its prediction ledger.
    dev_only = mixed.filter(pl.col("season") <= 2024)
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        run_development_walk_forward(
            games_path=_write_games_fixture(dev_only, tmp_path),
            team_features_path=TEAM_PATH,
            output_dir=out,
            project_root=REPO_ROOT,
        )
        preds = pl.read_parquet(out / "qb_elo_predictions_2018_2024.parquet")
        assert int(preds["season"].max()) <= 2024
        assert "G-FUTURE" not in preds["game_id"].to_list()


def _write_games_fixture(frames: pl.DataFrame, tmp_path: Path) -> Path:
    """Write a minimal synthetic games parquet with the canonical feature
    frame schema (superset tolerated by _load_games)."""
    path = tmp_path / "task04c_fixture_games.parquet"
    frames.write_parquet(path)
    return path


# ---------------------------------------------------------------------------
# L. Parameter-isolation regression
# ---------------------------------------------------------------------------


def test_L_parameter_isolation_defaults_unchanged():
    cfg = EloConfig()
    assert cfg.initial_rating == 1500.0
    assert cfg.home_field_elo == 48.0
    assert cfg.k_factor_regular == 20.0
    assert cfg.k_factor_postseason == 4.0
    assert cfg.mov_divisor == 6.0
    assert cfg.mov_cap == 2.5
    assert cfg.qb_adjustment.max_abs_elo == 50.0
    assert cfg.qb_adjustment.scale_elo_per_shrunk_epa == 500.0
    # Resolver seam does not mutate any config values.
    resolver = make_resolver("ORACLE", OracleQBAdjustments(ORACLE_PATH))
    assert resolver is not None
    assert cfg.initial_rating == 1500.0


# ---------------------------------------------------------------------------
# Additional: baseline default path (resolver=None) unchanged
# ---------------------------------------------------------------------------


def test_baseline_default_resolver_None_unchanged():
    frames = pl.DataFrame([_block_row(ORACLE_GAME, "LAR", "ARI")])
    preds_default, _, _ = _run_block(frames, None)
    preds_explicit, _, _ = _run_block(frames, make_resolver("BASELINE"))
    assert preds_default[0]["home_qb_adjustment"] == preds_explicit[0]["home_qb_adjustment"]
    assert preds_default[0]["away_qb_adjustment"] == preds_explicit[0]["away_qb_adjustment"]
    assert preds_default[0]["qb_certainty_state"] == "UNKNOWN"
    assert preds_default[0]["predicted_home_win_probability"] == pytest.approx(
        preds_explicit[0]["predicted_home_win_probability"]
    )
