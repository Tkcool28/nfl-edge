from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts/task05g_ml_headline_trust_v1_runner.py"
spec = importlib.util.spec_from_file_location("task05g_ml_headline_trust_v1_runner", RUNNER)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_primary_ml_trust_penalizes_half_disagreement_without_rewriting_q():
    row = {
        "market_type": "moneyline",
        "model_confidence_probability": 0.72,
        "raw_qbelo_probability_selected": 0.84,
        "raw_xgb_probability_selected": 0.60,
    }
    q_before = row["model_confidence_probability"]
    assert mod._disagreement(row) == pytest.approx(0.24)
    assert mod._trust_score(row, 0.50) == pytest.approx(0.60)
    assert row["model_confidence_probability"] == q_before


def test_primary_ml_trust_rewards_agreement_at_equal_q():
    disagree = {
        "market_type": "moneyline",
        "model_confidence_probability": 0.72,
        "raw_qbelo_probability_selected": 0.84,
        "raw_xgb_probability_selected": 0.60,
    }
    agree = {
        "market_type": "moneyline",
        "model_confidence_probability": 0.72,
        "raw_qbelo_probability_selected": 0.73,
        "raw_xgb_probability_selected": 0.71,
    }
    assert mod._trust_score(agree, 0.50) > mod._trust_score(disagree, 0.50)


def test_spread_trust_score_is_existing_confidence():
    row = {"market_type": "spread", "model_confidence_probability": 0.57}
    assert mod._trust_score(row, 0.50) == pytest.approx(0.57)
    assert mod._disagreement(row) is None


def test_ml_missing_constituent_probabilities_fails_closed_for_trust_score():
    row = {
        "market_type": "moneyline",
        "model_confidence_probability": 0.70,
        "raw_qbelo_probability_selected": None,
        "raw_xgb_probability_selected": 0.65,
    }
    with pytest.raises(RuntimeError, match="missing constituent-model probabilities"):
        mod._trust_score(row, 0.50)


def test_fixed_penalties_match_preregistration():
    assert mod.PRIMARY_LAMBDA == pytest.approx(0.50)
    assert mod.SENSITIVITY == {"T025": 0.25, "T100": 1.00}
    assert mod.SEALED == 2025
