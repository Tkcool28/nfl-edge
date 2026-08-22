from nfl_edge.value.candidate_table import (
    BookOfferContext,
    CandidateOfferContext,
    build_candidate_row,
    make_candidate_id,
)


def _upstream(price=-150, book="draftkings", snapshot="t1"):
    return {
        "game_id": "g",
        "season": 2026,
        "week": "1",
        "block": "2026-01",
        "market_type": "moneyline",
        "selected_side": "home",
        "sportsbook": book,
        "line": None,
        "american_odds": price,
        "market_snapshot_timestamp": snapshot,
        "raw_model_output": 0.65,
        "football_model_name": "QB_ELO_XGB_EXACT_AVG",
        "supported": True,
        "strict_positive_value": False,
    }


def test_candidate_id_is_stable_across_price_and_book_refreshes():
    assert make_candidate_id("g", "moneyline", "home") == make_candidate_id("g", "moneyline", "home")
    a = build_candidate_row(_upstream(-150, "draftkings", "t1"), CandidateOfferContext())
    b = build_candidate_row(_upstream(-145, "fanduel", "t2"), CandidateOfferContext())
    assert a["candidate_id"] == b["candidate_id"]
    assert a["offer_id"] != b["offer_id"]


def test_candidate_preserves_dk_fd_pinnacle_display_context():
    context = CandidateOfferContext(
        draftkings=BookOfferContext(None, -150),
        fanduel=BookOfferContext(None, -145),
        pinnacle=BookOfferContext(None, -148),
    )
    row = build_candidate_row(_upstream(), context)
    assert row["draftkings_price_american"] == -150
    assert row["fanduel_price_american"] == -145
    assert row["pinnacle_price_american"] == -148
    assert row["actionable_book"] == "draftkings"
