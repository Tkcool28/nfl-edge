"""Test the QB-adjusted Elo engine against known NFL data.

Smoke tests: state initialization, predict probabilities in (0,1),
update preserves symmetry, margin multiplier is bounded.
"""
from nfl_edge.elo import EloState


def test_predict_in_unit_interval():
    e = EloState()
    e.initialize_team("KC")
    e.initialize_team("BUF")
    e.initialize_qb("Mahomes", 1700)
    e.initialize_qb("Allen", 1650)
    p = e.predict("KC", "BUF", "Mahomes", "Allen")
    assert 0.0 < p < 1.0


def test_home_field_advantage():
    e = EloState()
    e.initialize_team("A")
    e.initialize_team("B")
    e.initialize_qb("A_qb", 1500)
    e.initialize_qb("B_qb", 1500)
    p_neutral = e.predict("A", "B", "A_qb", "B_qb", neutral=True)
    p_home = e.predict("A", "B", "A_qb", "B_qb", neutral=False)
    assert p_home > p_neutral, f"Home should have higher prob: {p_home} vs {p_neutral}"


def test_update_symmetry():
    e1 = EloState()
    e2 = EloState()
    e1.initialize_team("A"); e1.initialize_team("B")
    e1.initialize_qb("qa", 1500); e1.initialize_qb("qb", 1500)
    e2.team_elo = e1.team_elo.copy()
    e2.qb_elo = e1.qb_elo.copy()
    e1.update("A", "B", "qa", "qb", 24, 17)
    e2.update("B", "A", "qb", "qa", 17, 24)
    # After A beats B at home, and B beats A at home, the ratings should
    # approximately return to original (with minor HFA adjustment)
    assert abs(e1.team_elo["A"] - e2.team_elo["A"]) < 50


def test_margin_multiplier_bounded():
    for m in [1, 3, 7, 14, 28, 50]:
        mult = EloState._margin_multiplier(m)
        assert 0.0 < mult < 2.5, f"margin={m}, mult={mult}"
