import copy

import pytest

from nfl_edge.value.evaluated_wager_board import (
    EXPECTED_MARGIN_RMSE,
    TOTALS_R4_RMSE,
    assert_candidate_fields_preserved,
    build_evaluated_wager_board,
    evaluate_wager_row,
    football_confidence_z,
)


def _row(
    cid,
    *,
    market,
    raw,
    line,
    selection,
    status="VALUE",
    reliability="MEDIUM",
    supported=True,
    season=2024,
    ev=0.03,
):
    return {
        "candidate_id": cid,
        "game_id": cid,
        "season": season,
        "week": 1,
        "block": "2024-W01",
        "market_type": market,
        "selection": selection,
        "raw_football_output": raw,
        "actionable_book": "draftkings",
        "actionable_line": line,
        "actionable_price_american": -110,
        "actionable_decimal_price": 1.91,
        "expected_value": ev,
        "evaluated_edge_probability": max(ev / 2, 0.001),
        "strict_positive_value": status == "VALUE" and ev > 0,
        "price_status": status,
        "supported": supported,
        "reliability": reliability,
        "uncertainty": 0.03,
        "play_through_confidence_multiplier": 0.35 if reliability == "LOW" else 0.70,
        "play_through_break_even_concession": 0.006,
        "break_even_probability": 0.505,
        "actionable_probability": 0.50,
        "play_through_break_even_probability": 0.51,
        "staking_probability": 0.54,
    }


def test_all_candidate_fields_preserved():
    rows = [
        _row("ml", market="moneyline", raw=0.70, line=None, selection="home"),
        _row("sp", market="spread", raw=6.0, line=-3.0, selection="home"),
        _row("tot", market="total", raw=50.0, line=47.0, selection="over"),
    ]
    board = build_evaluated_wager_board(rows)
    assert_candidate_fields_preserved(rows, board)


def test_all_three_markets_get_common_confidence():
    rows = [
        _row("ml", market="moneyline", raw=0.70, line=None, selection="home"),
        _row("sp", market="spread", raw=6.0, line=-3.0, selection="home"),
        _row("tot", market="total", raw=50.0, line=47.0, selection="over"),
    ]
    board = build_evaluated_wager_board(rows)
    assert all(row["football_confidence_z"] is not None for row in board)
    assert all(0 < row["football_cash_confidence_proxy"] < 1 for row in board)


def test_confidence_uses_model_and_line_not_price_or_ev():
    base = _row("a", market="spread", raw=7.0, line=-3.0, selection="home", ev=0.02)
    changed = copy.deepcopy(base)
    changed["candidate_id"] = "b"
    changed["game_id"] = "b"
    changed["actionable_price_american"] = -160
    changed["expected_value"] = -0.20
    assert football_confidence_z(base) == pytest.approx(football_confidence_z(changed))


def test_selected_side_direction_is_correct_for_point_markets():
    home = _row("h", market="spread", raw=7.0, line=-3.0, selection="home")
    away = _row("a", market="spread", raw=7.0, line=3.0, selection="away")
    over = _row("o", market="total", raw=51.0, line=47.0, selection="over")
    under = _row("u", market="total", raw=51.0, line=47.0, selection="under")
    assert football_confidence_z(home) == pytest.approx(4.0 / EXPECTED_MARGIN_RMSE)
    assert football_confidence_z(away) == pytest.approx(-4.0 / EXPECTED_MARGIN_RMSE)
    assert football_confidence_z(over) == pytest.approx(4.0 / TOTALS_R4_RMSE)
    assert football_confidence_z(under) == pytest.approx(-4.0 / TOTALS_R4_RMSE)


def test_low_reliability_can_be_actionable_when_play_through_allows():
    row = _row(
        "low",
        market="moneyline",
        raw=0.72,
        line=None,
        selection="home",
        status="PLAYABLE",
        reliability="LOW",
        ev=-0.005,
    )
    evaluated = evaluate_wager_row(row)
    assert evaluated["evaluator_recommended_units"] > 0
    assert evaluated["evaluator_actionable"] is True


def test_unsupported_is_not_actionable():
    row = _row("u", market="moneyline", raw=0.72, line=None, selection="home", supported=False)
    evaluated = evaluate_wager_row(row)
    assert evaluated["evaluator_recommended_units"] == 0
    assert evaluated["evaluator_actionable"] is False


def test_outcome_firewall():
    row = _row("x", market="moneyline", raw=0.70, line=None, selection="home")
    row["settlement"] = "WIN"
    with pytest.raises(RuntimeError, match="forbidden outcome fields"):
        evaluate_wager_row(row)


def test_sealed_2025_firewall():
    row = _row("x", market="moneyline", raw=0.70, line=None, selection="home", season=2025)
    with pytest.raises(RuntimeError, match="sealed season"):
        evaluate_wager_row(row)
