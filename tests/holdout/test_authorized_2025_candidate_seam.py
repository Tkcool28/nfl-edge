from __future__ import annotations

import pytest

from nfl_edge.value.candidate_table import build_candidate_table


def _row(season: int) -> dict[str, object]:
    return {
        "game_id": f"synthetic_{season}",
        "season": season,
        "week": "1",
        "block": f"{season}-01",
        "market_type": "moneyline",
        "selected_side": "home",
        "american_odds": -110,
        "sportsbook": "draftkings",
        "market_snapshot_timestamp": "2025-09-01T00:00:00Z",
        "supported": True,
        "reliability": "HIGH",
        "price_status": "PLAYABLE",
    }


def test_candidate_table_rejects_2025_by_default():
    with pytest.raises(RuntimeError, match="sealed season 2025"):
        build_candidate_table([_row(2025)], {})


def test_candidate_table_accepts_true_2025_only_when_explicitly_authorized():
    rows = build_candidate_table(
        [_row(2025)],
        {},
        allow_authorized_holdout_2025=True,
    )
    assert len(rows) == 1
    assert rows[0]["season"] == 2025
    assert rows[0]["game_id"] == "synthetic_2025"


def test_candidate_table_development_behavior_is_unchanged():
    rows = build_candidate_table([_row(2024)], {})
    assert len(rows) == 1
    assert rows[0]["season"] == 2024
