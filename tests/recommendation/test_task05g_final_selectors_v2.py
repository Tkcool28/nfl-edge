from __future__ import annotations

from nfl_edge.recommendation.final_selectors_v1 import select_hit_rate as select_hit_rate_v1
from nfl_edge.recommendation.final_selectors_v1 import select_value as select_value_v1
from nfl_edge.recommendation.final_selectors_v2 import (
    BALANCED_ML_MIN_PINNACLE,
    BALANCED_ML_ODDS,
    BALANCED_SPREAD_MIN_Q,
    ValueSelectorState,
    select_balanced,
    select_headlines,
    select_hit_rate,
    select_value,
)
from nfl_edge.recommendation.policy import NO_BALANCED_PLAY


def row(
    cid: str,
    *,
    market: str = "moneyline",
    side: str = "home",
    odds: int = -115,
    q: float = 0.56,
    pinnacle: float | None = 0.55,
    line: float | None = None,
    break_even: float = 0.535,
    regions: str = "",
    cover_margin: float = 0.0,
    ev: float = -0.10,
    status: str = "LEAN",
):
    return {
        "candidate_id": cid,
        "game_id": cid.split("|")[0],
        "season": 2024,
        "week": 10,
        "block": "2024-10",
        "market_type": market,
        "selected_side": side,
        "sportsbook": "draftkings",
        "line": line,
        "american_odds": odds,
        "supported": True,
        "reliability": "HIGH",
        "model_confidence_supported": True,
        "model_confidence_support_n": 800,
        "model_confidence_probability": q,
        "pinnacle_anchor_probability": pinnacle,
        "break_even_probability": break_even,
        "expected_value": ev,
        "evaluated_edge_probability": -0.01,
        "price_status": status,
        "model_candidate_regions": regions,
        "model_price_gap": q - break_even,
        "model_cover_margin_v3": cover_margin,
    }


def spread(
    cid: str,
    *,
    q: float = 0.510,
    odds: int = -110,
    break_even: float = 0.52381,
    cover_margin: float = 2.0,
    regions: str = "SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4",
):
    return row(
        cid,
        market="spread",
        side="away",
        odds=odds,
        q=q,
        pinnacle=None,
        line=3.0,
        break_even=break_even,
        regions=regions,
        cover_margin=cover_margin,
    )


def test_balanced_ml_is_short_true_favorite_only_and_caps_juice_at_minus_130():
    assert BALANCED_ML_ODDS == (-130, -100)
    assert BALANCED_ML_MIN_PINNACLE == 0.50
    good = row("good|ml|home", odds=-130, q=0.58, pinnacle=0.54, break_even=0.56522)
    too_juiced = row("juiced|ml|home", odds=-131, q=0.80, pinnacle=0.75, break_even=0.56710)
    plus_money = row("dog|ml|away", odds=105, q=0.60, pinnacle=0.52, break_even=0.48780)
    false_favorite = row("fake|ml|away", odds=-105, q=0.58, pinnacle=0.49, break_even=0.51220)
    selected = select_balanced([good, too_juiced, plus_money, false_favorite])
    assert selected["candidate_id"] == good["candidate_id"]
    assert select_balanced([too_juiced, plus_money, false_favorite]) == NO_BALANCED_PLAY


def test_balanced_ml_does_not_require_positive_ev_or_value_status():
    candidate = row(
        "lean|ml|home",
        odds=-120,
        q=0.55,
        pinnacle=0.53,
        break_even=0.54545,
        ev=-0.25,
        status="PASS",
    )
    selected = select_balanced([candidate])
    assert selected["candidate_id"] == candidate["candidate_id"]


def test_balanced_spread_uses_validated_0_4_region_without_old_52pct_guillotine():
    assert BALANCED_SPREAD_MIN_Q == 0.50
    candidate = spread("spread|spread|away", q=0.510)
    selected = select_balanced([candidate])
    assert selected["candidate_id"] == candidate["candidate_id"]
    assert selected["balanced_protocol_version"] == "BALANCED_PRICE_BOUNDED_V2"


def test_balanced_spread_fails_closed_without_region_positive_margin_or_neutral_probability():
    wrong_region = spread("r|spread|away", regions="NOT_THE_0_4_REGION")
    wrong_direction = spread("m|spread|away", cover_margin=0.0)
    below_neutral = spread("q|spread|away", q=0.499)
    assert select_balanced([wrong_region, wrong_direction, below_neutral]) == NO_BALANCED_PLAY


def test_balanced_cross_market_ranking_penalizes_juice_without_becoming_an_ev_gate():
    # ML: q=.54, market-half trust=.535, -130 BE=.56522 => utility=.46978.
    ml = row(
        "ml|ml|home",
        odds=-130,
        q=0.54,
        pinnacle=0.53,
        break_even=0.56522,
        ev=-0.20,
        status="PASS",
    )
    # Spread: q=.510, -110 BE=.52381 => utility=.48619.
    # It wins because the price burden is lighter, even though raw cash q is lower.
    sp = spread("sp|spread|away", q=0.510)
    selected = select_balanced([ml, sp])
    assert selected["candidate_id"] == sp["candidate_id"]
    assert selected["balanced_utility"] < 0.51  # juice is actually penalized


def test_balanced_still_prefers_a_strong_short_favorite_when_quality_justifies_price():
    # q=.58, trust=.57, -125 BE=.55556 => utility=.51444.
    ml = row(
        "ml|ml|home",
        odds=-125,
        q=0.58,
        pinnacle=0.56,
        break_even=0.55556,
    )
    sp = spread("sp|spread|away", q=0.510)
    assert select_balanced([ml, sp])["candidate_id"] == ml["candidate_id"]


def test_hhr_and_value_are_exact_v1_delegates():
    material = [
        row("ml|ml|home", odds=-125, q=0.60, pinnacle=0.58, break_even=0.55556),
        spread("sp|spread|away", q=0.51),
    ]
    state = ValueSelectorState()
    assert select_hit_rate(material) == select_hit_rate_v1(material)
    assert select_value(material, state) == select_value_v1(material, state)


def test_successor_headline_surface_uses_balanced_v2():
    ml = row("ml|ml|home", odds=-200, q=0.70, pinnacle=0.68, break_even=0.66667)
    sp = spread("sp|spread|away", q=0.510)
    cards = select_headlines([ml, sp], ValueSelectorState())
    assert cards["balanced"]["candidate_id"] == sp["candidate_id"]
    # HHR is intentionally free to keep the more expensive high-probability ML.
    assert cards["hit_rate"]["candidate_id"] == ml["candidate_id"]
