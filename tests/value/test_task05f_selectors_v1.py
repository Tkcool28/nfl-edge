import copy

import pytest

from nfl_edge.value.selectors import (
    select_balanced,
    select_high_hit_rate,
    select_primary_cards,
    select_value,
)


def _row(
    cid: str,
    *,
    probability: float = 0.60,
    ev: float = 0.05,
    edge: float = 0.03,
    reliability: str = "MEDIUM",
    status: str = "VALUE",
    supported: bool = True,
    uncertainty: float | None = 0.02,
    season: int = 2024,
    game_id: str | None = None,
    market: str = "spread",
    selection: str = "home",
    book: str = "draftkings",
    line: float | None = -2.5,
    price: int = -110,
):
    return {
        "candidate_id": cid,
        "game_id": game_id or cid,
        "season": season,
        "week": 1,
        "market_type": market,
        "selection": selection,
        "actionable_book": book,
        "actionable_line": line,
        "actionable_price_american": price,
        "actionable_probability": probability,
        "expected_value": ev,
        "evaluated_edge_probability": edge,
        "reliability": reliability,
        "price_status": status,
        "supported": supported,
        "strict_positive_value": status == "VALUE" and ev > 0.0,
        "uncertainty": uncertainty,
        # Present specifically to prove selectors ignore risk-sizing probability.
        "staking_probability": 0.01,
    }


def test_identical_candidate_table_produces_identical_selections_independent_of_input_order():
    rows = [
        _row("a", probability=0.61, ev=0.03),
        _row("b", probability=0.58, ev=0.08),
        _row("c", probability=0.64, ev=-0.004, status="PLAYABLE"),
    ]
    first = select_primary_cards(rows)
    second = select_primary_cards(list(reversed(copy.deepcopy(rows))))
    assert first == second


def test_unsupported_and_low_reliability_never_primary_selected():
    rows = [
        _row("unsupported", probability=0.90, ev=0.40, supported=False),
        _row("low", probability=0.89, ev=0.39, reliability="LOW"),
        _row("medium", probability=0.60, ev=0.04, reliability="MEDIUM"),
    ]
    picks = select_primary_cards(rows)
    assert {pick["candidate_id"] for pick in picks.values() if pick} == {"medium"}


def test_high_hit_rate_can_select_playable_over_lower_probability_value():
    rows = [
        _row("value", probability=0.66, ev=0.03, status="VALUE"),
        _row("playable", probability=0.72, ev=-0.006, status="PLAYABLE"),
    ]
    assert select_high_hit_rate(rows)["candidate_id"] == "playable"


def test_high_hit_rate_requires_value_or_playable():
    rows = [
        _row("lean", probability=0.90, ev=-0.03, status="LEAN"),
        _row("pass", probability=0.91, ev=-0.05, status="PASS"),
        _row("value", probability=0.58, ev=0.02, status="VALUE"),
    ]
    assert select_high_hit_rate(rows)["candidate_id"] == "value"


def test_balanced_requires_strict_positive_value_and_minimax_picks_middle_compromise():
    rows = [
        _row("hit", probability=0.70, ev=0.01),
        _row("middle", probability=0.60, ev=0.05),
        _row("value", probability=0.55, ev=0.10),
        _row("playable", probability=0.80, ev=-0.002, status="PLAYABLE"),
    ]
    pick = select_balanced(rows)
    assert pick["candidate_id"] == "middle"
    assert pick["balanced_hit_rank"] == 2
    assert pick["balanced_value_rank"] == 2
    assert pick["balanced_worst_rank"] == 2
    assert pick["balanced_rank_sum"] == 4


def test_balanced_competition_rank_gives_equal_values_same_rank():
    rows = [
        _row("a", probability=0.70, ev=0.02),
        _row("b", probability=0.60, ev=0.08),
        _row("c", probability=0.60, ev=0.05),
    ]
    pick = select_balanced(rows)
    assert pick["candidate_id"] == "b"
    assert pick["balanced_hit_rank"] == 2
    assert pick["balanced_value_rank"] == 1


def test_value_requires_strict_positive_value_and_chooses_largest_ev():
    rows = [
        _row("playable", ev=-0.001, edge=0.10, status="PLAYABLE"),
        _row("small", ev=0.03, edge=0.04),
        _row("large", ev=0.09, edge=0.02),
    ]
    assert select_value(rows)["candidate_id"] == "large"


def test_high_hit_ties_follow_preregistered_reliability_then_status_then_ev():
    rows = [
        _row("medium", probability=0.65, ev=0.08, reliability="MEDIUM", status="VALUE"),
        _row("high_play", probability=0.65, ev=-0.001, reliability="HIGH", status="PLAYABLE"),
        _row("high_value", probability=0.65, ev=0.02, reliability="HIGH", status="VALUE"),
    ]
    assert select_high_hit_rate(rows)["candidate_id"] == "high_value"


def test_value_ties_follow_reliability_then_edge():
    rows = [
        _row("medium", ev=0.08, edge=0.20, reliability="MEDIUM"),
        _row("high_low_edge", ev=0.08, edge=0.04, reliability="HIGH"),
        _row("high_high_edge", ev=0.08, edge=0.07, reliability="HIGH"),
    ]
    assert select_value(rows)["candidate_id"] == "high_high_edge"


def test_deterministic_identity_breaks_exact_numeric_ties():
    rows = [
        _row("z", game_id="GAME-Z", probability=0.60, ev=0.05, edge=0.03),
        _row("a", game_id="GAME-A", probability=0.60, ev=0.05, edge=0.03),
    ]
    picks = select_primary_cards(rows)
    assert all(pick["game_id"] == "GAME-A" for pick in picks.values() if pick)


def test_duplicate_wager_across_cards_is_allowed():
    only = _row("only", probability=0.65, ev=0.07, edge=0.05, reliability="HIGH")
    picks = select_primary_cards([only])
    assert [picks[name]["candidate_id"] for name in ("HIGH_HIT_RATE", "BALANCED", "VALUE")] == [
        "only",
        "only",
        "only",
    ]


def test_no_play_is_valid():
    rows = [
        _row("low", reliability="LOW"),
        _row("lean", reliability="MEDIUM", status="LEAN", ev=-0.03),
    ]
    picks = select_primary_cards(rows)
    assert picks == {"HIGH_HIT_RATE": None, "BALANCED": None, "VALUE": None}


def test_missing_required_field_fails_closed():
    good = _row("good", probability=0.60, ev=0.03, edge=0.02)
    bad = _row("bad", probability=0.99, ev=0.50, edge=0.50)
    bad["actionable_probability"] = None
    picks = select_primary_cards([bad, good])
    assert all(pick["candidate_id"] == "good" for pick in picks.values() if pick)


def test_staking_probability_is_not_used_in_ranking():
    a = _row("a", probability=0.62, ev=0.04)
    b = _row("b", probability=0.61, ev=0.03)
    a["staking_probability"] = 0.01
    b["staking_probability"] = 0.99
    assert select_high_hit_rate([a, b])["candidate_id"] == "a"


def test_selector_rejects_outcome_fields():
    row = _row("a")
    row["realized_profit"] = 1.0
    with pytest.raises(RuntimeError, match="forbidden outcome fields"):
        select_primary_cards([row])


def test_sealed_2025_firewall():
    with pytest.raises(RuntimeError, match="sealed season"):
        select_primary_cards([_row("sealed", season=2025)])
