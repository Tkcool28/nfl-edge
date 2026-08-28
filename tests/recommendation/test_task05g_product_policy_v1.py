from __future__ import annotations

from types import SimpleNamespace

import pytest

import nfl_edge.recommendation.product_policy_v1 as product
from nfl_edge.value.contracts import NormalizedOffer


def _profit_multiple(odds: int) -> float:
    return float(odds) / 100.0 if odds > 0 else 100.0 / abs(float(odds))


def _fake_result(offer: NormalizedOffer, *, q: float, reliability: str = "HIGH", uncertainty: float = 0.0):
    b = _profit_multiple(int(offer.price_american))
    ev = q * b - (1.0 - q)
    be = 1.0 / (1.0 + b)
    return SimpleNamespace(
        supported=True,
        reliability=reliability,
        expected_value=ev,
        conditional_nonpush_probability=q,
        break_even_probability=be,
        actionable_probability=q,
        uncertainty=uncertainty,
        strict_positive_value=ev > 0.0,
        fair_price_american=-105,
    )


def test_current_bad_price_uses_clear_no_then_bet_at(monkeypatch):
    # q chosen so the confidence-adjusted same-line PLAYABLE boundary is
    # materially better than the current -125 price.
    q = 0.509
    monkeypatch.setattr(product, "evaluate_offer", lambda _g, offer, _s, _a, _r: _fake_result(offer, q=q))

    decision = product.evaluate_default_market_offer(
        game_state=object(),
        offer=NormalizedOffer("moneyline", "home", "draftkings", -125, source="stored"),
        evaluator_state=object(),
        market_anchor=object(),
        reliability_state=object(),
        bankroll=250.0,
        profile="Normal",
    )

    assert decision.policy == "BALANCED"
    assert decision.primary_action == "NO"
    assert decision.current_units == 0.0
    assert decision.current_stake == 0.0
    assert decision.secondary_action == "BET_AT"
    assert decision.secondary_price_american is not None
    assert decision.secondary_price_american > -125
    assert decision.secondary_units in {0.5, 0.75}
    assert decision.secondary_stake > 0.0


def test_actionable_default_uses_bet_then_playable_through(monkeypatch):
    q = 0.58
    monkeypatch.setattr(product, "evaluate_offer", lambda _g, offer, _s, _a, _r: _fake_result(offer, q=q))

    decision = product.evaluate_default_market_offer(
        game_state=object(),
        offer=NormalizedOffer("moneyline", "away", "fanduel", -110, source="stored"),
        evaluator_state=object(),
        market_anchor=object(),
        reliability_state=object(),
        bankroll=250.0,
        profile="Normal",
    )

    assert decision.primary_action == "BET"
    assert decision.current_units > 0.0
    assert decision.current_stake > 0.0
    assert decision.secondary_action == "PLAYABLE_THROUGH"
    assert decision.secondary_price_american is not None
    assert decision.secondary_price_american < -110
    assert decision.secondary_units in {0.5, 0.75}
    assert decision.secondary_stake > 0.0


def test_manual_and_stored_exact_offer_are_methodology_identical(monkeypatch):
    q = 0.58
    seen = []

    def fake(_g, offer, _s, _a, _r):
        seen.append((offer.source, offer.market_type, offer.side, offer.line, offer.price_american))
        return _fake_result(offer, q=q)

    monkeypatch.setattr(product, "evaluate_offer", fake)
    common = dict(market_type="spread", side="home", book="user_entry", line=3.0, price_american=-110)
    stored = NormalizedOffer(**common, source="stored")
    manual = NormalizedOffer(**common, source="manual")

    a = product.evaluate_default_market_offer(
        game_state=object(), offer=stored, evaluator_state=object(), market_anchor=object(), reliability_state=object(), bankroll=250.0, profile="Normal"
    )
    b = product.evaluate_default_market_offer(
        game_state=object(), offer=manual, evaluator_state=object(), market_anchor=object(), reliability_state=object(), bankroll=250.0, profile="Normal"
    )

    fields = (
        "policy",
        "current_price_american",
        "current_line",
        "current_status",
        "primary_action",
        "current_units",
        "current_stake",
        "secondary_action",
        "secondary_price_american",
        "secondary_line",
        "secondary_units",
        "secondary_stake",
        "reliability",
        "strict_value",
        "expected_value",
        "actionable_probability",
        "fair_price_american",
    )
    for field in fields:
        assert getattr(a, field) == pytest.approx(getattr(b, field)) if isinstance(getattr(a, field), float) else getattr(a, field) == getattr(b, field)
    assert a.source == "stored"
    assert b.source == "manual"
    # Both the current offer and its same-line boundary are re-evaluated; only
    # provenance differs. No DK/FD-only gate is applied to manual input.
    assert {entry[0] for entry in seen} == {"stored", "manual"}


def test_different_spread_line_requires_exact_new_offer(monkeypatch):
    q = 0.56
    observed_lines = []

    def fake(_g, offer, _s, _a, _r):
        observed_lines.append(offer.line)
        return _fake_result(offer, q=q)

    monkeypatch.setattr(product, "evaluate_offer", fake)
    product.evaluate_default_market_offer(
        game_state=object(),
        offer=NormalizedOffer("spread", "home", "manual", -110, line=2.5, source="manual"),
        evaluator_state=object(),
        market_anchor=object(),
        reliability_state=object(),
        bankroll=250.0,
        profile="Normal",
    )
    assert set(observed_lines) == {2.5}
