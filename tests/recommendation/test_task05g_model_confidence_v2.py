from __future__ import annotations

import importlib.util
from pathlib import Path


def _core():
    path = Path(__file__).resolve().parents[2] / "scripts" / "task05g_model_confidence_v2_runner.py"
    spec = importlib.util.spec_from_file_location("task05g_model_confidence_v2_runner_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_spread_model_probability_home_and_away_are_oriented_correctly():
    m = _core()
    residuals = [-7.0, -3.0, 0.0, 3.0, 7.0] * 60
    # expected margin +3, home -2: actual margin must exceed +2 to cover.
    _, _, _, q_home = m._spread_probability(
        residuals,
        expected_home_margin=3.0,
        side="home",
        line=-2.0,
    )
    # Away +2 is the exact complement apart from pushes.
    _, _, _, q_away = m._spread_probability(
        residuals,
        expected_home_margin=3.0,
        side="away",
        line=2.0,
    )
    assert q_home is not None and q_away is not None
    assert abs((q_home + q_away) - 1.0) < 1e-12


def test_hhr_eligibility_does_not_require_value_or_positive_model_price_gap():
    m = _core()
    row = {
        "supported": True,
        "model_confidence_supported": True,
        "model_confidence_support_n": 512,
        "market_type": "moneyline",
        "sportsbook": "draftkings",
        "break_even_probability": 0.60,
        "model_confidence_probability": 0.58,
        "model_price_gap": -0.02,
        "american_odds": -150,
        "price_status": "PLAYABLE",
    }
    assert m._hhr_eligible(row)


def test_balanced_grid_is_exactly_preregistered_three_tolerances():
    m = _core()
    assert m.BALANCED_TOLERANCES == {"B0": 0.00, "B1": -0.01, "B2": -0.02}


def test_balanced_is_model_probability_first_not_value_or_ev_first():
    m = _core()
    base = {
        "supported": True,
        "model_confidence_supported": True,
        "model_confidence_support_n": 512,
        "market_type": "moneyline",
        "sportsbook": "draftkings",
        "break_even_probability": 0.55,
        "american_odds": -122,
        "reliability": "MEDIUM",
        "price_status": "PLAYABLE",
        "expected_value": -0.01,
        "realized_profit": 0.0,
        "settlement": "PUSH",
        "block": "2022-01",
    }
    high_q = dict(base, game_id="a", model_confidence_probability=0.60, model_price_gap=0.05, candidate_id="a")
    lower_q = dict(base, game_id="b", model_confidence_probability=0.57, model_price_gap=0.02, candidate_id="b", price_status="VALUE", expected_value=0.20)
    choice = m._select_balanced([high_q, lower_q], 0.00)
    assert choice is not None
    assert choice["game_id"] == "a"


def test_value_requires_both_model_price_support_and_task05f_strict_value():
    m = _core()
    row = {
        "supported": True,
        "model_confidence_supported": True,
        "model_confidence_support_n": 512,
        "market_type": "moneyline",
        "sportsbook": "draftkings",
        "break_even_probability": 0.45,
        "model_confidence_probability": 0.50,
        "model_price_gap": 0.05,
        "american_odds": 120,
        "price_status": "VALUE",
        "expected_value": 0.01,
    }
    assert m._value_eligible(row)
    assert not m._value_eligible(dict(row, model_price_gap=-0.001))
    assert not m._value_eligible(dict(row, price_status="PLAYABLE"))


def test_balanced_winner_rule_enforces_coverage_hit_rate_and_roi_before_ranking():
    m = _core()
    def report(plays, hit, roi, seasons):
        return {
            "play_blocks": plays,
            "hit_rate_nonpush": hit,
            "roi": roi,
            "by_season": {str(s): {"roi": seasons[i]} for i, s in enumerate(sorted(m.DEVELOPMENT_SEASONS))},
        }
    reports = {
        "B0": report(20, 0.70, 0.20, [0.1, 0.1, 0.1]),  # fails coverage
        "B1": report(45, 0.56, 0.03, [0.1, -0.1, 0.1]),
        "B2": report(50, 0.54, 0.10, [0.1, 0.1, 0.1]),  # fails hit rate
    }
    decision = m._pick_balanced_winner(reports, original_v1_dev_plays=50)
    assert decision["winner"] == "B1"


def test_totals_are_never_common_v2_headline_candidates():
    m = _core()
    row = {
        "supported": True,
        "model_confidence_supported": True,
        "model_confidence_support_n": 512,
        "market_type": "total",
        "sportsbook": "fanduel",
        "break_even_probability": 0.52,
    }
    assert not m._common_v2(row)
