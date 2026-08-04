"""Defect B / C / D: zero-sum Elo update, MOV formula, canonical path.

These tests cover:

- The home and away Elo changes must sum to zero for every game.
- Tie updates are zero-sum.
- The MOV formula matches the spec exactly for margins 0/1/6/12/24
  and a very large margin.
- The MOV cap is enforced.
- The update path is canonical: every persisted update record has
  the same ``update_multiplier`` on both sides and the same
  ``k_factor`` on both sides.
- The league-wide Elo total is preserved across an entire replay.
- Neutral-site HFA is exactly zero in the persisted update records.
"""

from __future__ import annotations

import pytest

from nfl_edge.models.qb_elo import (
    EloConfig,
    PregamePrediction,
    elo_expected,
    initial_state,
    mov_multiplier,
    update_state_with_margin,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_prediction(
    *,
    margin: int,
    home_win: bool | None,
    tie: bool,
    neutral_site: bool = False,
    season: int = 2018,
    season_type: str = "REG",
) -> PregamePrediction:
    return PregamePrediction(
        game_id="G",
        season=season,
        season_type=season_type,
        week=1,
        home_team="AAA",
        away_team="BBB",
        home_elo_before=1500.0,
        away_elo_before=1500.0,
        home_field_adjustment=0.0 if neutral_site else 48.0,
        home_qb_adjustment=0.0,
        away_qb_adjustment=0.0,
        qb_adjustment_net=0.0,
        qb_certainty_state="UNKNOWN",
        predicted_home_win_probability=elo_expected(
            1500.0 + (0.0 if neutral_site else 48.0), 1500.0
        ),
        actual_home_win=home_win,
        actual_tie=tie,
        target_available=True,
    )


# ---------------------------------------------------------------------------
# Defect B: zero-sum update
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("margin", [0, 1, 6, 12, 24, 60])
def test_home_away_update_sum_is_zero(margin: int) -> None:
    """The home change + away change must be exactly zero for any
    margin (within numerical tolerance)."""

    if margin == 0:
        home_win: bool | None = None
        tie = True
    else:
        home_win = margin > 0
        tie = False
    state = initial_state(["AAA", "BBB"], EloConfig())
    pred = _make_prediction(margin=margin, home_win=home_win, tie=tie)
    home, away, new_state = update_state_with_margin(
        prediction=pred, margin=margin, state=state, config=EloConfig()
    )
    assert home.elo_change + away.elo_change == pytest.approx(0.0, abs=1e-9)
    # Also verify the rating sum is preserved.
    before_sum = state.rating("AAA") + state.rating("BBB")
    after_sum = new_state.rating("AAA") + new_state.rating("BBB")
    assert after_sum == pytest.approx(before_sum, abs=1e-9)


def test_home_win_update() -> None:
    state = initial_state(["AAA", "BBB"], EloConfig())
    pred = _make_prediction(margin=7, home_win=True, tie=False)
    home, away, _ = update_state_with_margin(
        prediction=pred, margin=7, state=state, config=EloConfig()
    )
    assert home.elo_change > 0
    assert away.elo_change < 0


def test_away_win_update() -> None:
    state = initial_state(["AAA", "BBB"], EloConfig())
    pred = _make_prediction(margin=-7, home_win=False, tie=False)
    home, away, _ = update_state_with_margin(
        prediction=pred, margin=-7, state=state, config=EloConfig()
    )
    assert home.elo_change < 0
    assert away.elo_change > 0


def test_tie_update_is_zero_sum() -> None:
    state = initial_state(["AAA", "BBB"], EloConfig())
    pred = _make_prediction(margin=0, home_win=None, tie=True)
    home, away, new_state = update_state_with_margin(
        prediction=pred, margin=0, state=state, config=EloConfig()
    )
    assert home.elo_change + away.elo_change == pytest.approx(0.0, abs=1e-9)
    # The multiplier must be exactly 1.0 for a tie.
    assert home.update_multiplier == 1.0
    assert away.update_multiplier == 1.0
    # Mean is preserved.
    assert new_state.mean == pytest.approx(state.mean, abs=1e-9)


def test_postseason_uses_postseason_k() -> None:
    """Postseason (WC/DIV/CON/SB) uses ``k_factor_postseason``."""

    state = initial_state(["AAA", "BBB"], EloConfig())
    pred = _make_prediction(
        margin=7, home_win=True, tie=False, season_type="WC"
    )
    home, _, _ = update_state_with_margin(
        prediction=pred, margin=7, state=state, config=EloConfig()
    )
    assert home.k_factor == 4.0


def test_neutral_field_hfa_is_zero() -> None:
    """Neutral-site games have HFA = 0 on both update records."""

    state = initial_state(["AAA", "BBB"], EloConfig())
    pred = _make_prediction(
        margin=7, home_win=True, tie=False, neutral_site=True
    )
    home, away, _ = update_state_with_margin(
        prediction=pred, margin=7, state=state, config=EloConfig()
    )
    assert home.home_field_adjustment == 0.0
    assert away.home_field_adjustment == 0.0


def test_canonical_path_uses_one_delta() -> None:
    """The update path is canonical: the same multiplier is used on
    both home and away, the k_factor is the same on both, and the
    changes are exact opposites.
    """

    state = initial_state(["AAA", "BBB"], EloConfig())
    pred = _make_prediction(margin=10, home_win=True, tie=False)
    home, away, _ = update_state_with_margin(
        prediction=pred, margin=10, state=state, config=EloConfig()
    )
    assert home.update_multiplier == away.update_multiplier
    assert home.k_factor == away.k_factor
    assert home.elo_change == pytest.approx(-away.elo_change, abs=1e-12)


def test_large_margin_caps_at_mov_cap() -> None:
    """The MOV multiplier is capped at ``mov_cap`` even for huge
    margins."""

    cfg = EloConfig()
    m_24 = mov_multiplier(24, cfg)
    m_60 = mov_multiplier(60, cfg)
    m_300 = mov_multiplier(300, cfg)
    assert m_24 == pytest.approx(cfg.mov_cap)
    assert m_60 == pytest.approx(cfg.mov_cap)
    assert m_300 == pytest.approx(cfg.mov_cap)


# ---------------------------------------------------------------------------
# Defect C: MOV formula
# ---------------------------------------------------------------------------


def test_mov_formula_exact_values() -> None:
    """The MOV formula must match the spec for known margins."""

    cfg = EloConfig(mov_divisor=6.0, mov_cap=2.5)
    # margin 0 -> 1.0 (NOT 1.0 + 0.0^2; just 1.0)
    assert mov_multiplier(0, cfg) == 1.0
    # margin 1 -> 1 + (1/6)^2 = 1.02778
    assert mov_multiplier(1, cfg) == pytest.approx(1.0 + (1.0 / 6.0) ** 2)
    # margin 6 -> 1 + 1 = 2.0
    assert mov_multiplier(6, cfg) == pytest.approx(2.0)
    # margin 12 -> 1 + 4 = 5.0 -> capped at 2.5
    assert mov_multiplier(12, cfg) == pytest.approx(2.5)
    # margin 24 -> 1 + 16 = 17.0 -> capped at 2.5
    assert mov_multiplier(24, cfg) == pytest.approx(2.5)
    # Very large -> capped at 2.5
    assert mov_multiplier(1000, cfg) == pytest.approx(2.5)


def test_mov_uses_absolute_margin() -> None:
    """The MOV formula takes the absolute value of the margin."""

    cfg = EloConfig()
    assert mov_multiplier(-7, cfg) == mov_multiplier(7, cfg)
    assert mov_multiplier(-30, cfg) == mov_multiplier(30, cfg)


def test_mov_never_double_counts_leading_one() -> None:
    """The leading 1 is added exactly once. Margin 0 returns exactly
    1.0 (the leading 1 plus 0); margin 6 returns exactly 2.0 (the
    leading 1 plus 1.0, not 2 + 1.0 = 3.0).
    """

    cfg = EloConfig(mov_divisor=6.0, mov_cap=2.5)
    # If the leading 1 were added twice, margin 6 would be 3.0, not 2.0.
    assert mov_multiplier(6, cfg) < 3.0
    # Margin 0 must be exactly 1.0.
    assert mov_multiplier(0, cfg) == 1.0


# ---------------------------------------------------------------------------
# League-wide Elo total preserved across a replay
# ---------------------------------------------------------------------------


def test_league_wide_elo_total_preserved() -> None:
    """Summing the Elo changes over a sequence of updates must yield
    exactly zero, so the league total is preserved.
    """

    state = initial_state(["A", "B", "C", "D"], EloConfig())
    initial_total = sum(t.rating for t in state.teams.values())
    games = [
        ("A", "B", 7, True, False),
        ("C", "D", -3, False, False),
        ("A", "C", 14, True, False),
        ("B", "D", 0, None, True),
        ("A", "D", -7, False, False),
        ("B", "C", 1, True, False),
        ("A", "B", 6, True, False),
        ("C", "D", -12, False, False),
    ]
    for home, away, margin, home_win, tie in games:
        pred = PregamePrediction(
            game_id=f"{home}-{away}-{margin}",
            season=2018,
            season_type="REG",
            week=1,
            home_team=home,
            away_team=away,
            home_elo_before=state.rating(home),
            away_elo_before=state.rating(away),
            home_field_adjustment=48.0,
            home_qb_adjustment=0.0,
            away_qb_adjustment=0.0,
            qb_adjustment_net=0.0,
            qb_certainty_state="UNKNOWN",
            predicted_home_win_probability=elo_expected(
                state.rating(home) + 48.0, state.rating(away)
            ),
            actual_home_win=home_win,
            actual_tie=tie,
            target_available=True,
        )
        _, _, state = update_state_with_margin(
            prediction=pred, margin=margin, state=state, config=EloConfig()
        )
    final_total = sum(t.rating for t in state.teams.values())
    assert final_total == pytest.approx(initial_total, abs=1e-6)
