"""Tests for the QB-Elo model math: probability, neutral site, tie, QB adjustment,
home-field advantage, mean reversion, carryover, and clamping."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nfl_edge.models.qb_elo import (
    EloConfig,
    EloState,
    QBAdjustmentConfig,
    TeamState,
    apply_season_carryover,
    clamp_probability,
    config_from_dict,
    elo_expected,
    elo_probability_home,
    initial_state,
    qb_adjustment_from_data,
)


def test_config_from_dict_basic():
    cfg = config_from_dict({
        "initial_rating": 1500.0,
        "k_factor_regular": 20.0,
        "k_factor_postseason": 4.0,
        "home_field_elo": 48.0,
    })
    assert cfg.initial_rating == 1500.0
    assert cfg.k_factor_regular == 20.0
    assert cfg.k_factor_postseason == 4.0
    assert cfg.home_field_elo == 48.0


def test_elo_expected_symmetric():
    # Equal ratings -> 0.5
    assert abs(elo_expected(1500.0, 1500.0) - 0.5) < 1e-9
    # 200 Elo higher -> clearly favored
    assert elo_expected(1700.0, 1500.0) > 0.9
    # Symmetric: home-favored should equal (1 - away_favored)
    p_home = elo_expected(1700.0, 1500.0)
    p_away = elo_expected(1500.0, 1700.0)
    assert abs(p_home - (1.0 - p_away)) < 1e-9


def test_probability_at_equal_elos_with_hfa_favors_home():
    p = elo_probability_home(
        home_elo=1500.0,
        away_elo=1500.0,
        home_field_adjustment=48.0,
    )
    assert p > 0.55
    assert p < 0.65


def test_probability_monotonic_in_home_elo():
    p_low = elo_probability_home(home_elo=1400.0, away_elo=1500.0, home_field_adjustment=0.0)
    p_mid = elo_probability_home(home_elo=1500.0, away_elo=1500.0, home_field_adjustment=0.0)
    p_high = elo_probability_home(home_elo=1600.0, away_elo=1500.0, home_field_adjustment=0.0)
    assert p_low < p_mid < p_high


def test_qb_adjustment_zero_when_unknown():
    qb_cfg = QBAdjustmentConfig()
    adj = qb_adjustment_from_data(
        starter_certainty="UNKNOWN",
        qb_data=None,
        config=qb_cfg,
        elo_config=EloConfig(),
    )
    assert adj == 0.0


def test_qb_adjustment_zero_when_postgame_only_evidence():
    qb_cfg = QBAdjustmentConfig()
    adj = qb_adjustment_from_data(
        starter_certainty="POSTGAME_ONLY_EVIDENCE",
        qb_data=None,
        config=qb_cfg,
        elo_config=EloConfig(),
    )
    assert adj == 0.0


def test_qb_adjustment_zero_when_confirmed_but_no_data():
    qb_cfg = QBAdjustmentConfig()
    adj = qb_adjustment_from_data(
        starter_certainty="CONFIRMED",
        qb_data=None,
        config=qb_cfg,
        elo_config=EloConfig(),
    )
    assert adj == 0.0


def test_qb_adjustment_bounded():
    qb_cfg = QBAdjustmentConfig(max_abs_adjustment=50.0)
    # confirmed starter with extreme prior and proven EPA
    adj = qb_adjustment_from_data(
        starter_certainty="CONFIRMED",
        qb_data={"prior_epa": 0.0, "expected_epa": 100.0, "n_games": 1000},
        config=qb_cfg,
        elo_config=EloConfig(),
    )
    assert abs(adj) <= 50.0


def test_qb_adjustment_shrinkage_low_sample():
    qb_cfg = QBAdjustmentConfig()
    # Confirmed but very few games -> heavy shrinkage
    adj = qb_adjustment_from_data(
        starter_certainty="CONFIRMED",
        qb_data={"prior_epa": 0.0, "expected_epa": 0.5, "n_games": 1},
        config=qb_cfg,
        elo_config=EloConfig(),
    )
    # Should be much smaller than the unscaled value
    assert abs(adj) < 5.0


def test_clamp_probability_within_bounds():
    cfg = EloConfig(prob_min=0.01, prob_max=0.99)
    assert clamp_probability(0.0, cfg) == 0.01
    assert clamp_probability(1.0, cfg) == 0.99
    assert clamp_probability(0.5, cfg) == 0.5


def test_initial_state_uses_configured_rating():
    cfg = EloConfig(initial_rating=1520.0)
    state = initial_state(["A", "B"], cfg)
    assert state.rating("A") == 1520.0
    assert state.rating("B") == 1520.0


def test_ensure_team_adds_new_team():
    state = initial_state(["A"], EloConfig())
    new_state = ensure_team(state, "B", EloConfig())
    assert new_state.rating("B") == 1500.0
    assert new_state.rating("A") == 1500.0


def test_season_carryover_mean_reversion():
    state = EloState(
        teams={"A": TeamState(team="A", rating=1700.0, last_season=2018)},
        mean=1500.0,
        current_season=2018,
    )
    cfg = EloConfig(season_mean_reversion_fraction=1.0 / 3.0)
    new_state = apply_season_carryover(state, new_season=2019, config=cfg)
    # 1700 mean-reverts 1/3 toward 1500 -> 1500 + 0.667*(1700-1500) = 1633.33
    assert abs(new_state.rating("A") - 1633.333) < 0.01


def test_season_carryover_full_reversion_resets_to_mean():
    state = EloState(
        teams={"A": TeamState(team="A", rating=1700.0, last_season=2018)},
        mean=1500.0,
        current_season=2018,
    )
    cfg = EloConfig(season_mean_reversion_fraction=1.0)
    new_state = apply_season_carryover(state, new_season=2019, config=cfg)
    assert new_state.rating("A") == 1500.0


def test_probability_bounds_never_exceed_clamp():
    cfg = EloConfig(prob_min=0.01, prob_max=0.99)
    # Extreme Elo difference
    p = elo_probability_home(
        home_elo=3000.0, away_elo=-1000.0, home_field_adjustment=0.0
    )
    p = clamp_probability(p, cfg)
    assert 0.01 <= p <= 0.99
