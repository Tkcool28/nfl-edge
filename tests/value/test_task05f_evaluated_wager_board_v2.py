import math

import pytest

from nfl_edge.value.evaluated_wager_board_v2 import (
    EXPECTED_MARGIN_RMSE,
    TOTALS_R4_RMSE,
    build_evaluated_wager_board,
    enrich_evaluated_wager,
)


def _row(
    cid: str,
    *,
    market: str = "moneyline",
    side: str = "home",
    raw: float = 0.70,
    line: float | None = None,
    reliability: str = "MEDIUM",
    supported: bool = True,
    status: str = "VALUE",
    ev: float = 0.04,
    season: int = 2024,
):
    return {
        "candidate_id": cid,
        "game_id": cid,
        "season": season,
        "week": 1,
        "market_type": market,
        "selection": side,
        "raw_football_output": raw,
        "actionable_book": "draftkings",
        "actionable_line": line,
        "actionable_price_american": -110,
        "actionable_decimal_price": 1.909090909,
        "supported": supported,
        "reliability": reliability if supported else "UNSUPPORTED",
        "price_status": status,
        "strict_positive_value": status == "VALUE" and ev > 0,
        "expected_value": ev,
        "evaluated_edge_probability": max(ev, 0.01),
        "play_through_confidence_multiplier": 0.6,
        "play_through_break_even_concession": 0.006,
        "break_even_probability": 0.5238095238,
        "actionable_probability": 0.53,
        "play_through_break_even_probability": 0.536,
        "staking_probability": 0.54,
    }


def test_moneyline_confidence_proxy_preserves_native_probability():
    out = enrich_evaluated_wager(_row("ml", raw=0.75))
    assert out["football_confidence_z"] > 0
    assert out["football_cash_confidence_proxy"] == pytest.approx(0.75)


def test_spread_confidence_uses_selected_side_cover_edge_and_frozen_scale():
    out = enrich_evaluated_wager(
        _row("sp", market="spread", side="home", raw=7.0, line=-3.0)
    )
    assert out["football_selected_side_edge_points"] == pytest.approx(4.0)
    assert out["football_confidence_z"] == pytest.approx(4.0 / EXPECTED_MARGIN_RMSE)


def test_away_spread_orientation_is_selected_side_correct():
    out = enrich_evaluated_wager(
        _row("sp-away", market="spread", side="away", raw=3.0, line=7.0)
    )
    assert out["football_selected_side_edge_points"] == pytest.approx(4.0)


def test_total_confidence_uses_projected_edge_and_frozen_scale():
    over = enrich_evaluated_wager(
        _row("tot-o", market="total", side="over", raw=51.0, line=47.0)
    )
    under = enrich_evaluated_wager(
        _row("tot-u", market="total", side="under", raw=43.0, line=47.0)
    )
    assert over["football_confidence_z"] == pytest.approx(4.0 / TOTALS_R4_RMSE)
    assert under["football_confidence_z"] == pytest.approx(4.0 / TOTALS_R4_RMSE)


def test_supported_low_reliability_value_is_not_hard_zeroed():
    out = enrich_evaluated_wager(_row("low", reliability="LOW"))
    assert out["evaluator_units"] >= 1.0
    assert out["primary_actionable"] is True
    assert out["strict_value_actionable"] is True


def test_unsupported_and_lean_fail_closed_for_primary_actionability():
    unsupported = enrich_evaluated_wager(_row("u", supported=False))
    lean = enrich_evaluated_wager(_row("l", status="LEAN", ev=-0.01))
    assert unsupported["evaluator_units"] == 0.0
    assert unsupported["primary_actionable"] is False
    assert lean["evaluator_units"] == 0.0
    assert lean["primary_actionable"] is False


def test_build_board_is_deterministic_and_preserves_candidate_payload():
    rows = [_row("b", raw=0.65), _row("a", raw=0.75)]
    out = build_evaluated_wager_board(rows)
    assert [row["candidate_id"] for row in out] == ["a", "b"]
    assert out[0]["raw_football_output"] == rows[1]["raw_football_output"]


def test_outcome_and_2025_firewalls():
    leaked = _row("x")
    leaked["settlement"] = "WIN"
    with pytest.raises(RuntimeError, match="forbidden outcome fields"):
        enrich_evaluated_wager(leaked)
    with pytest.raises(RuntimeError, match="sealed season"):
        enrich_evaluated_wager(_row("sealed", season=2025))
