from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from nfl_edge.prospective.card_tracking_v1 import (
    AppendOnlyViolation,
    ProspectiveCardError,
    build_pending_results,
    build_publication_snapshot,
    build_summary,
    canonical_json_bytes,
    derive_episodes,
    performance_summary,
    realized_profit_units,
    resolve_official,
    write_publication_snapshot,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/contracts/nfl_edge_product_api_v1_week1_mock.json"
LANES = ("hit_rate", "balanced", "value")


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _no_play(lane_key: str) -> dict:
    lane = {"hit_rate": "HIT_RATE", "balanced": "BALANCED", "value": "VALUE"}[lane_key]
    return {
        "lane_key": lane_key,
        "lane": lane,
        "state": "NO_PLAY",
        "game_id": None,
        "away_team": None,
        "home_team": None,
        "kickoff_at_utc": None,
        "market": None,
        "selection": None,
        "normalized_selection": None,
        "normalized_side": None,
        "book": None,
        "line": None,
        "american_odds": None,
        "recommended_units": 0.0,
        "play_through": None,
        "value_at": None,
        "model_probability": None,
        "trust_probability": None,
        "market_probability": None,
        "ev": None,
        "support": "SUPPORTED",
        "reliability": None,
        "warnings": [],
        "selector_version": "test",
        "roof_state": None,
        "canonical_headline": {},
        "portfolio_duplicate_of_lane": None,
        "portfolio_stake_suppressed_reason": None,
        "logical_recommendation_id": None,
        "wager_identity_id": None,
        "exact_offer_identity_id": None,
    }


def _bet(
    lane_key: str,
    *,
    game_id: str = "game-a",
    kickoff: str = "2026-09-13T17:00:00Z",
    market: str = "MONEYLINE",
    selection: str = "AAA",
    side: str = "home",
    book: str = "DRAFTKINGS",
    line: float | None = None,
    price: int = -120,
    units: float = 0.75,
    logical: str | None = None,
) -> dict:
    row = _no_play(lane_key)
    row.update(
        state="BET",
        game_id=game_id,
        away_team="BBB",
        home_team="AAA",
        kickoff_at_utc=kickoff,
        market=market,
        selection=selection,
        normalized_selection=selection,
        normalized_side=side,
        book=book,
        line=line,
        american_odds=price,
        recommended_units=units,
        model_probability=0.55,
        trust_probability=0.54,
        market_probability=0.52,
        ev=0.01,
        logical_recommendation_id=logical or f"logical-{lane_key}-{game_id}-{market}-{selection}",
        wager_identity_id=f"wager-{lane_key}-{game_id}-{market}-{selection}-{line}",
        exact_offer_identity_id=f"offer-{game_id}-{market}-{selection}-{book}-{line}-{price}",
    )
    return row


def _publication(ts: str, **lane_rows: dict) -> dict:
    lanes = {lane: _no_play(lane) for lane in LANES}
    lanes.update(lane_rows)
    digest = hashlib.sha256((ts + json.dumps(lane_rows, sort_keys=True)).encode()).hexdigest()
    return {
        "schema_version": "NFL_EDGE_PROSPECTIVE_CARD_PUBLICATION_V1",
        "publication_id": "publication-" + digest[:24],
        "season": 2026,
        "week": 1,
        "published_at_utc": ts,
        "source_product_sha256": digest,
        "lanes": lanes,
    }


def test_publication_is_deterministic_links_hash_and_preserves_nulls() -> None:
    product = _fixture()
    first = build_publication_snapshot(
        product,
        published_at_utc="2026-09-02T14:00:05Z",
        source_commit_sha="a" * 40,
        capture_mode="REPO_SIMULATION",
    )
    second = build_publication_snapshot(
        product,
        published_at_utc="2026-09-02T14:00:05Z",
        source_commit_sha="a" * 40,
        capture_mode="REPO_SIMULATION",
    )
    assert first == second
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert first["source_product_sha256"] == hashlib.sha256(canonical_json_bytes(product)).hexdigest()
    assert first["creation_provenance"]["provider_calls"] == 0
    assert first["creation_provenance"]["user_specific_data_included"] is False
    assert first["lanes"]["hit_rate"]["state"] == "NO_PLAY"
    assert first["lanes"]["hit_rate"]["game_id"] is None
    assert first["lanes"]["balanced"]["american_odds"] == -115
    assert first["lanes"]["balanced"]["play_through"]["price_american"] == -120
    assert first["lanes"]["value"]["value_at"]["price_american"] == 105
    assert first["field_availability"]["evaluator_probability"] == "NOT_EXPOSED_BY_CANONICAL_PRODUCT_V1"


def test_exact_duplicate_lanes_preserve_history_and_mark_portfolio_suppression() -> None:
    product = _fixture()
    duplicate = deepcopy(product["headlines"]["balanced"])
    duplicate["lane"] = "HIT_RATE"
    product["headlines"]["hit_rate"] = duplicate
    snapshot = build_publication_snapshot(product, published_at_utc="2026-09-02T14:00:05Z")
    hit = snapshot["lanes"]["hit_rate"]
    balanced = snapshot["lanes"]["balanced"]
    assert hit["exact_offer_identity_id"] == balanced["exact_offer_identity_id"]
    assert hit["portfolio_duplicate_of_lane"] is None
    assert balanced["portfolio_duplicate_of_lane"] == "hit_rate"
    assert balanced["portfolio_stake_suppressed_reason"] == "DUPLICATE_EXACT_OFFER"


def test_idempotent_write_and_append_only_conflict(tmp_path: Path) -> None:
    product = _fixture()
    first = build_publication_snapshot(product, published_at_utc="2026-09-02T14:00:05Z")
    path, created = write_publication_snapshot(first, tmp_path)
    assert created is True

    retry = build_publication_snapshot(product, published_at_utc="2026-09-02T14:05:00Z")
    retry_path, retry_created = write_publication_snapshot(retry, tmp_path)
    assert retry_path == path
    assert retry_created is False
    assert json.loads(path.read_text())["published_at_utc"] == "2026-09-02T14:00:05Z"

    conflicting = deepcopy(first)
    conflicting["publication_id"] = "publication-" + "f" * 24
    with pytest.raises(AppendOnlyViolation):
        write_publication_snapshot(conflicting, tmp_path)


def test_price_and_spread_line_movement_remain_one_episode() -> None:
    logical = "logical-balanced-game-a-spread-AAA"
    pubs = [
        _publication(
            "2026-09-10T10:00:00Z",
            balanced=_bet("balanced", market="SPREAD", line=2.5, price=-115, logical=logical),
        ),
        _publication(
            "2026-09-11T10:00:00Z",
            balanced=_bet("balanced", market="SPREAD", line=3.0, price=-120, logical=logical),
        ),
        _publication(
            "2026-09-12T10:00:00Z",
            balanced=_bet("balanced", market="SPREAD", line=2.0, price=-110, logical=logical),
        ),
    ]
    episode = next(
        row for row in derive_episodes(pubs)["episodes"] if row["lane_key"] == "balanced"
    )
    assert episode["publication_count"] == 3
    assert episode["first_price"] == -115
    assert episode["last_price"] == -110
    assert episode["best_price"] == -110
    assert episode["worst_price"] == -120
    assert episode["first_line"] == 2.5
    assert episode["last_line"] == 2.0
    assert episode["best_line"] == 3.0
    assert episode["worst_line"] == 2.0


def test_total_line_quality_matches_existing_production_semantics() -> None:
    over = "logical-value-over"
    under = "logical-hit-under"
    pubs = [
        _publication(
            "2026-09-10T10:00:00Z",
            value=_bet("value", market="TOTAL", selection="OVER", side="over", line=47.5, logical=over),
            hit_rate=_bet("hit_rate", market="TOTAL", selection="UNDER", side="under", line=47.5, logical=under),
        ),
        _publication(
            "2026-09-11T10:00:00Z",
            value=_bet("value", market="TOTAL", selection="OVER", side="over", line=46.5, logical=over),
            hit_rate=_bet("hit_rate", market="TOTAL", selection="UNDER", side="under", line=48.5, logical=under),
        ),
    ]
    by_lane = {row["lane_key"]: row for row in derive_episodes(pubs)["episodes"]}
    assert by_lane["value"]["best_line"] == 46.5
    assert by_lane["value"]["worst_line"] == 47.5
    assert by_lane["hit_rate"]["best_line"] == 48.5
    assert by_lane["hit_rate"]["worst_line"] == 47.5


def test_disappear_then_return_creates_separate_episode() -> None:
    logical = "logical-value-return"
    pubs = [
        _publication("2026-09-10T10:00:00Z", value=_bet("value", logical=logical)),
        _publication("2026-09-11T10:00:00Z"),
        _publication("2026-09-12T10:00:00Z", value=_bet("value", price=-105, logical=logical)),
    ]
    episodes = [
        row for row in derive_episodes(pubs)["episodes"] if row["lane_key"] == "value"
    ]
    assert len(episodes) == 2
    assert episodes[0]["terminal_reason"] == "DISAPPEARED"
    assert episodes[0]["returned_after_gap"] is False
    assert episodes[1]["returned_after_gap"] is True
    assert episodes[0]["episode_id"] != episodes[1]["episode_id"]


def test_lane_wager_change_replaces_episode() -> None:
    pubs = [
        _publication("2026-09-10T10:00:00Z", balanced=_bet("balanced", logical="logical-a")),
        _publication(
            "2026-09-11T10:00:00Z",
            balanced=_bet("balanced", market="SPREAD", line=2.5, logical="logical-b"),
        ),
    ]
    episodes = [
        row for row in derive_episodes(pubs)["episodes"] if row["lane_key"] == "balanced"
    ]
    assert len(episodes) == 2
    assert episodes[0]["terminal_reason"] == "REPLACED"


def test_official_scenario_1_uses_final_sunday_prekick_bet() -> None:
    kickoff = "2026-09-13T17:00:00Z"
    pubs = [
        _publication("2026-09-07T12:00:00Z", balanced=_bet("balanced", kickoff=kickoff, price=-120)),
        _publication("2026-09-08T12:00:00Z", balanced=_bet("balanced", kickoff=kickoff, price=-125)),
        _publication("2026-09-13T16:59:00Z", balanced=_bet("balanced", kickoff=kickoff, price=-130)),
    ]
    resolution = next(
        row for row in resolve_official(pubs)["resolutions"] if row["lane_key"] == "balanced"
    )
    assert resolution["resolution_state"] == "OFFICIAL_BET"
    assert resolution["official_wager"]["american_odds"] == -130
    assert resolution["source_publication_id"] == pubs[-1]["publication_id"]
    assert resolution["first_appearance"]["american_odds"] == -120


def test_official_scenario_2_final_no_play_cancels_stale_bet() -> None:
    kickoff = "2026-09-13T17:00:00Z"
    pubs = [
        _publication("2026-09-07T12:00:00Z", balanced=_bet("balanced", kickoff=kickoff, price=-120)),
        _publication("2026-09-12T12:00:00Z", balanced=_bet("balanced", kickoff=kickoff, price=-125)),
        _publication("2026-09-13T16:59:00Z"),
    ]
    official = resolve_official(pubs)
    resolution = next(
        row for row in official["resolutions"] if row["lane_key"] == "balanced"
    )
    assert resolution["resolution_state"] == "OFFICIAL_NO_PLAY_OR_REPLACED"
    assert resolution["official_wager"] is None
    assert official["portfolio_entries"] == []


def test_official_scenario_3_thursday_freezes_while_sunday_keeps_updating() -> None:
    thursday = "2026-09-11T00:00:00Z"
    sunday = "2026-09-13T20:00:00Z"
    pubs = [
        _publication(
            "2026-09-10T23:50:00Z",
            hit_rate=_bet("hit_rate", game_id="tnf", kickoff=thursday, price=-140),
        ),
        _publication(
            "2026-09-11T01:00:00Z",
            hit_rate=_bet("hit_rate", game_id="sun", kickoff=sunday, price=-115),
        ),
        _publication(
            "2026-09-13T19:59:00Z",
            hit_rate=_bet("hit_rate", game_id="sun", kickoff=sunday, price=-125),
        ),
        _publication(
            "2026-09-13T20:00:00Z",
            hit_rate=_bet("hit_rate", game_id="sun", kickoff=sunday, price=-200),
        ),
    ]
    official = resolve_official(pubs)
    tnf = next(row for row in official["resolutions"] if row["game_id"] == "tnf")
    sun = next(row for row in official["resolutions"] if row["game_id"] == "sun")
    assert tnf["official_wager"]["american_odds"] == -140
    assert sun["official_wager"]["american_odds"] == -125
    assert sun["source_publication_id"] == pubs[2]["publication_id"]


def test_postkick_publication_cannot_replace_official_and_timestamps_are_utc() -> None:
    kickoff = "2026-09-13T17:00:00Z"
    pubs = [
        _publication("2026-09-13T16:59:59Z", value=_bet("value", kickoff=kickoff, price=110)),
        _publication("2026-09-13T17:00:00Z", value=_bet("value", kickoff=kickoff, price=150)),
        _publication("2026-09-13T17:01:00Z", value=_bet("value", kickoff=kickoff, price=200)),
    ]
    resolution = next(
        row for row in resolve_official(pubs)["resolutions"] if row["lane_key"] == "value"
    )
    assert resolution["official_wager"]["american_odds"] == 110

    bad = deepcopy(pubs[0])
    bad["published_at_utc"] = "2026-09-13T10:59:59-06:00"
    with pytest.raises(ProspectiveCardError):
        resolve_official([bad])


def test_official_duplicate_counts_each_lane_but_only_one_portfolio_exposure() -> None:
    kickoff = "2026-09-13T17:00:00Z"
    hit = _bet("hit_rate", kickoff=kickoff, price=-198, units=0.75)
    balanced = _bet("balanced", kickoff=kickoff, price=-198, units=0.75)
    pub = _publication(
        "2026-09-13T16:00:00Z",
        hit_rate=hit,
        balanced=balanced,
    )
    official = resolve_official([pub])
    assert len(official["official_wagers"]) == 2
    assert len(official["portfolio_entries"]) == 1
    assert official["portfolio_entries"][0]["lane_keys"] == ["hit_rate", "balanced"]
    assert official["overlap_count"] == 1


def test_pending_results_and_exact_odds_unit_economics() -> None:
    kickoff = "2026-09-13T17:00:00Z"
    pub = _publication(
        "2026-09-13T16:00:00Z",
        balanced=_bet("balanced", kickoff=kickoff, price=-198, units=1.0),
    )
    official = resolve_official([pub])
    results = build_pending_results(official)
    assert results["settlement_status"] == "PENDING"
    assert results["lane_results"][0]["price_used_for_scoring"] == -198
    assert results["lane_results"][0]["realized_units"] is None
    assert realized_profit_units(grade="WIN", american_odds=-198, units_risked=1.0) == pytest.approx(100 / 198)
    assert realized_profit_units(grade="WIN", american_odds=150, units_risked=1.0) == pytest.approx(1.5)
    assert realized_profit_units(grade="LOSS", american_odds=-198, units_risked=1.0) == -1.0
    assert realized_profit_units(grade="PUSH", american_odds=-198, units_risked=1.0) == 0.0
    assert realized_profit_units(grade="VOID", american_odds=-198, units_risked=1.0) == 0.0


def test_summary_separates_lane_records_from_deduplicated_portfolio() -> None:
    kickoff = "2026-09-13T17:00:00Z"
    pub = _publication(
        "2026-09-13T16:00:00Z",
        hit_rate=_bet("hit_rate", kickoff=kickoff, price=-120),
        balanced=_bet("balanced", kickoff=kickoff, price=-120),
    )
    official = resolve_official([pub])
    results = build_pending_results(official)
    episodes = derive_episodes([pub])
    summary = build_summary(official=official, results=results, episodes=episodes)
    assert len(results["lane_results"]) == 2
    assert len(results["portfolio_results"]) == 1
    assert summary["overlap_count"] == 1
    assert summary["portfolio"]["settled_wagers"] == 0
    assert summary["interpretation"] == "DESCRIPTIVE_PROSPECTIVE_EVIDENCE_ONLY_NO_RETUNING"


def test_performance_summary_uses_units_not_hit_rate_alone() -> None:
    rows = [
        {"grade": "WIN", "units_risked": 1.0, "realized_units": 0.5},
        {"grade": "LOSS", "units_risked": 1.5, "realized_units": -1.5},
        {"grade": "PUSH", "units_risked": 0.5, "realized_units": 0.0},
        {"grade": "PENDING", "units_risked": 2.0, "realized_units": None},
    ]
    summary = performance_summary(rows)
    assert summary["wins"] == 1
    assert summary["losses"] == 1
    assert summary["pushes"] == 1
    assert summary["hit_rate"] == 0.5
    assert summary["units_risked"] == 3.0
    assert summary["net_units"] == -1.0
    assert summary["roi"] == pytest.approx(-1 / 3)


def test_repo_side_week_simulation_preserves_change_disappearance_and_return() -> None:
    kickoff = "2026-09-14T00:20:00Z"
    ml = "logical-balanced-lar-ml"
    spread = "logical-balanced-lar-spread"
    pubs = [
        _publication("2026-09-07T15:00:00Z", balanced=_bet("balanced", kickoff=kickoff, price=-125, logical=ml)),
        _publication("2026-09-08T15:00:00Z", balanced=_bet("balanced", kickoff=kickoff, price=-135, logical=ml)),
        _publication(
            "2026-09-09T15:00:00Z",
            balanced=_bet("balanced", kickoff=kickoff, market="SPREAD", line=-2.5, price=-110, logical=spread),
        ),
        _publication("2026-09-10T15:00:00Z"),
        _publication("2026-09-13T20:00:00Z", balanced=_bet("balanced", kickoff=kickoff, price=-118, logical=ml)),
    ]
    episodes = [
        row for row in derive_episodes(pubs)["episodes"] if row["lane_key"] == "balanced"
    ]
    assert len(episodes) == 3
    assert [row["terminal_reason"] for row in episodes] == [
        "REPLACED",
        "DISAPPEARED",
        "WEEK_HISTORY_END",
    ]
    assert episodes[-1]["returned_after_gap"] is True
    official = resolve_official(pubs)
    resolution = next(
        row for row in official["resolutions"] if row["lane_key"] == "balanced"
    )
    assert resolution["official_wager"]["market"] == "MONEYLINE"
    assert resolution["official_wager"]["american_odds"] == -118
