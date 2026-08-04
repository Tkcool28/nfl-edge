"""Tests for the QB-Elo model math: probability, neutral site, tie, QB adjustment,
home-field advantage, mean reversion, carryover, and clamping.

These tests are matched to the actual public API exposed by
``nfl_edge.models.qb_elo``. The QB adjustment public function is
``qb_adjustment_for(...)`` and returns a ``(adjustment_elo, certainty_state)``
tuple.
"""

from __future__ import annotations

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
    ensure_team,
    initial_state,
    qb_adjustment_for,
)

# ---------------------------------------------------------------------------
# config_from_dict
# ---------------------------------------------------------------------------


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


def test_config_from_dict_round_trip():
    original = EloConfig()
    cfg = config_from_dict({
        "initial_rating": original.initial_rating,
        "k_factor_regular": original.k_factor_regular,
        "k_factor_postseason": original.k_factor_postseason,
        "home_field_elo": original.home_field_elo,
        "season_mean_reversion_fraction": original.season_mean_reversion_fraction,
        "mov_divisor": original.mov_divisor,
        "mov_cap": original.mov_cap,
        "prob_min": original.prob_min,
        "prob_max": original.prob_max,
    })
    assert cfg == original


# ---------------------------------------------------------------------------
# elo_expected (pure math)
# ---------------------------------------------------------------------------


def test_elo_expected_symmetric():
    # Equal ratings -> 0.5
    assert abs(elo_expected(1500.0, 1500.0) - 0.5) < 1e-9
    # 400 Elo higher -> clearly favored
    assert elo_expected(1900.0, 1500.0) > 0.9
    # Symmetric: home-favored should equal (1 - away_favored)
    p_home = elo_expected(1700.0, 1500.0)
    p_away = elo_expected(1500.0, 1700.0)
    assert abs(p_home - (1.0 - p_away)) < 1e-9


# ---------------------------------------------------------------------------
# elo_probability_home
# ---------------------------------------------------------------------------


def test_probability_at_equal_elos_with_hfa_favors_home():
    p = elo_probability_home(
        home_elo=1500.0,
        away_elo=1500.0,
        home_field_adjustment=48.0,
        home_qb_adjustment=0.0,
        away_qb_adjustment=0.0,
    )
    assert p > 0.55
    assert p < 0.65


def test_probability_monotonic_in_home_elo():
    p_low = elo_probability_home(
        home_elo=1400.0, away_elo=1500.0,
        home_field_adjustment=0.0,
        home_qb_adjustment=0.0, away_qb_adjustment=0.0,
    )
    p_mid = elo_probability_home(
        home_elo=1500.0, away_elo=1500.0,
        home_field_adjustment=0.0,
        home_qb_adjustment=0.0, away_qb_adjustment=0.0,
    )
    p_high = elo_probability_home(
        home_elo=1600.0, away_elo=1500.0,
        home_field_adjustment=0.0,
        home_qb_adjustment=0.0, away_qb_adjustment=0.0,
    )
    assert p_low < p_mid < p_high


def test_probability_with_qb_adjustment_tilts_correctly():
    p_neutral = elo_probability_home(
        home_elo=1500.0, away_elo=1500.0,
        home_field_adjustment=0.0,
        home_qb_adjustment=0.0, away_qb_adjustment=0.0,
    )
    p_home_up = elo_probability_home(
        home_elo=1500.0, away_elo=1500.0,
        home_field_adjustment=0.0,
        home_qb_adjustment=30.0, away_qb_adjustment=0.0,
    )
    p_away_up = elo_probability_home(
        home_elo=1500.0, away_elo=1500.0,
        home_field_adjustment=0.0,
        home_qb_adjustment=0.0, away_qb_adjustment=30.0,
    )
    assert p_home_up > p_neutral
    assert p_away_up < p_neutral


# ---------------------------------------------------------------------------
# qb_adjustment_for
# ---------------------------------------------------------------------------


def test_qb_adjustment_zero_when_unknown():
    """An unknown pregame starter must produce zero adjustment."""
    qb_cfg = QBAdjustmentConfig()
    adj, state = qb_adjustment_for(
        candidate_player_id=None,
        confidence_state="UNKNOWN",
        shrunk_passing_epa=None,
        config=qb_cfg,
    )
    assert adj == 0.0
    assert state == "UNKNOWN"


def test_qb_adjustment_zero_when_postgame_only_evidence():
    """Postgame evidence never produces a confirmed adjustment."""
    qb_cfg = QBAdjustmentConfig()
    adj, state = qb_adjustment_for(
        candidate_player_id="player-123",
        confidence_state="POSTGAME_ONLY_EVIDENCE",
        shrunk_passing_epa=0.5,
        config=qb_cfg,
    )
    assert adj == 0.0
    assert state == "UNKNOWN"


def test_qb_adjustment_zero_when_confirmed_without_shrunk_epa():
    """Confirmed with no EPA data returns zero and is labeled correctly."""
    qb_cfg = QBAdjustmentConfig()
    adj, state = qb_adjustment_for(
        candidate_player_id="player-123",
        confidence_state="CONFIRMED_PRE_CUTOFF",
        shrunk_passing_epa=None,
        config=qb_cfg,
    )
    assert adj == 0.0
    assert state == "CONFIRMED_BUT_NO_DATA"


def test_qb_adjustment_bounded_by_max_abs_elo():
    """Confirmed starter with extreme EPA must be clamped to max_abs_elo."""
    qb_cfg = QBAdjustmentConfig(max_abs_elo=50.0)
    adj, state = qb_adjustment_for(
        candidate_player_id="player-123",
        confidence_state="CONFIRMED_PRE_CUTOFF",
        shrunk_passing_epa=1000.0,  # absurdly high
        config=qb_cfg,
    )
    assert abs(adj) <= 50.0
    assert state == "CONFIRMED"


def test_qb_adjustment_uses_supported_but_uncertain_state():
    """Depth-chart support without confirmation uses the supported branch."""
    qb_cfg = QBAdjustmentConfig()
    adj, state = qb_adjustment_for(
        candidate_player_id="player-123",
        confidence_state="DEPTH_CHART_SUPPORTED",
        shrunk_passing_epa=0.5,
        config=qb_cfg,
    )
    # Supported branch returns zero adjustment (replacement scenario)
    assert adj == 0.0
    assert state == "SUPPORTED_BUT_UNCERTAIN"


def test_qb_adjustment_no_name_only_lookup():
    """A player id with no confidence context must not produce an adjustment."""
    qb_cfg = QBAdjustmentConfig()
    adj, state = qb_adjustment_for(
        candidate_player_id="player-123",
        confidence_state=None,
        shrunk_passing_epa=0.5,
        config=qb_cfg,
    )
    assert adj == 0.0
    assert state == "UNKNOWN"


def test_qb_adjustment_no_current_game_qb_information():
    """Confidence state 'UNKNOWN' short-circuits regardless of any other data."""
    qb_cfg = QBAdjustmentConfig()
    adj, state = qb_adjustment_for(
        candidate_player_id="player-123",
        confidence_state="UNKNOWN",
        shrunk_passing_epa=0.5,  # would otherwise suggest a real adjustment
        config=qb_cfg,
    )
    assert adj == 0.0
    assert state == "UNKNOWN"


# ---------------------------------------------------------------------------
# clamp_probability
# ---------------------------------------------------------------------------


def test_clamp_probability_within_bounds():
    cfg = EloConfig(prob_min=0.01, prob_max=0.99)
    assert clamp_probability(0.0, cfg) == 0.01
    assert clamp_probability(1.0, cfg) == 0.99
    assert clamp_probability(0.5, cfg) == 0.5


def test_clamp_probability_does_not_affect_valid_input():
    cfg = EloConfig(prob_min=0.01, prob_max=0.99)
    assert clamp_probability(0.72, cfg) == 0.72


# ---------------------------------------------------------------------------
# state helpers
# ---------------------------------------------------------------------------


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


def test_ensure_team_is_noop_for_existing_team():
    state = initial_state(["A"], EloConfig())
    new_state = ensure_team(state, "A", EloConfig())
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
        home_elo=3000.0, away_elo=-1000.0, home_field_adjustment=0.0,
        home_qb_adjustment=0.0, away_qb_adjustment=0.0,
    )
    p = clamp_probability(p, cfg)
    assert 0.01 <= p <= 0.99
