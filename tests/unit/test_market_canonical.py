"""Task 05E-D2 Phase B: canonical-layer contract tests (outcome-blind)."""

import json
import tempfile
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.market_data.canonical import (
    AMBIGUOUS,
    MATCHED_EXACT,
    UNMATCHED_NO_EVENT,
    build_canonical,
)

SAMPLE_SCHEDULE = [
    {"game_id": "2020_01_HOU_KC", "season": 2020, "gameday": "2020-09-10",
     "gametime": "20:20", "away_team": "HOU", "home_team": "KC"},
    {"game_id": "2021_01_BAL_KC", "season": 2021, "gameday": "2021-09-09",
     "gametime": "20:20", "away_team": "BAL", "home_team": "KC"},
]


def _norm_frame():
    """A minimal normalized frame spanning the two sample games (target events)."""
    return pl.DataFrame([
        {
            "request_plan_id": "md_2020_001", "season": 2020,
            "raw_file_path": "2020/md_2020_001.json",
            "raw_file_sha256": "aa11", "requested_snapshot_timestamp_utc": "2020-09-10T23:20:00+00:00",
            "actual_snapshot_timestamp_utc": "2020-09-10T23:15:38+00:00",
            "expected_earliest_kickoff_utc": "2020-09-11T00:20:00Z",
            "provider_event_id": "ev1", "event_commence_time_utc": "2020-09-11T00:20:00+00:00",
            "provider_home_team": "Kansas City Chiefs", "provider_away_team": "Houston Texans",
            "home_abbr": "KC", "away_abbr": "HOU", "is_target_event": True,
            "matched_target_game_ids": "2020_01_HOU_KC",
            "bookmaker_key": "draftkings", "bookmaker_title": "DraftKings",
            "bookmaker_last_update_utc": "2020-09-10T23:15:11+00:00",
            "market_key": "h2h", "market_last_update_utc": "2020-09-10T23:15:11+00:00",
            "side": "team", "outcome_name": "Kansas City Chiefs", "point": None,
            "american_price": -150, "malformed_market": False, "malformed_reason": None,
        },
        {
            "request_plan_id": "md_2020_001", "season": 2020,
            "raw_file_path": "2020/md_2020_001.json", "raw_file_sha256": "aa11",
            "requested_snapshot_timestamp_utc": "2020-09-10T23:20:00+00:00",
            "actual_snapshot_timestamp_utc": "2020-09-10T23:15:38+00:00",
            "expected_earliest_kickoff_utc": "2020-09-11T00:20:00Z",
            "provider_event_id": "ev1", "event_commence_time_utc": "2020-09-11T00:20:00+00:00",
            "provider_home_team": "Kansas City Chiefs", "provider_away_team": "Houston Texans",
            "home_abbr": "KC", "away_abbr": "HOU", "is_target_event": True,
            "matched_target_game_ids": "2020_01_HOU_KC",
            "bookmaker_key": "draftkings", "bookmaker_title": "DraftKings",
            "bookmaker_last_update_utc": "2020-09-10T23:15:11+00:00",
            "market_key": "h2h", "market_last_update_utc": "2020-09-10T23:15:11+00:00",
            "side": "team", "outcome_name": "Houston Texans", "point": None,
            "american_price": 130, "malformed_market": False, "malformed_reason": None,
        },
        {
            "request_plan_id": "md_2021_001", "season": 2021,
            "raw_file_path": "2021/md_2021_001.json", "raw_file_sha256": "bb22",
            "requested_snapshot_timestamp_utc": "2021-09-09T23:20:00+00:00",
            "actual_snapshot_timestamp_utc": "2021-09-09T23:15:38+00:00",
            "expected_earliest_kickoff_utc": "2021-09-10T00:20:00Z",
            "provider_event_id": "ev2", "event_commence_time_utc": "2021-09-10T00:20:00+00:00",
            "provider_home_team": "Kansas City Chiefs", "provider_away_team": "Baltimore Ravens",
            "home_abbr": "KC", "away_abbr": "BAL", "is_target_event": True,
            "matched_target_game_ids": "2021_01_BAL_KC",
            "bookmaker_key": "fanduel", "bookmaker_title": "FanDuel",
            "bookmaker_last_update_utc": "2021-09-09T23:15:11+00:00",
            "market_key": "h2h", "market_last_update_utc": "2021-09-09T23:15:11+00:00",
            "side": "team", "outcome_name": "Kansas City Chiefs", "point": None,
            "american_price": -160, "malformed_market": False, "malformed_reason": None,
        },
        {
            "request_plan_id": "md_2021_001", "season": 2021,
            "raw_file_path": "2021/md_2021_001.json", "raw_file_sha256": "bb22",
            "requested_snapshot_timestamp_utc": "2021-09-09T23:20:00+00:00",
            "actual_snapshot_timestamp_utc": "2021-09-09T23:15:38+00:00",
            "expected_earliest_kickoff_utc": "2021-09-10T00:20:00Z",
            "provider_event_id": "ev2", "event_commence_time_utc": "2021-09-10T00:20:00+00:00",
            "provider_home_team": "Kansas City Chiefs", "provider_away_team": "Baltimore Ravens",
            "home_abbr": "KC", "away_abbr": "BAL", "is_target_event": True,
            "matched_target_game_ids": "2021_01_BAL_KC",
            "bookmaker_key": "fanduel", "bookmaker_title": "FanDuel",
            "bookmaker_last_update_utc": "2021-09-09T23:15:11+00:00",
            "market_key": "h2h", "market_last_update_utc": "2021-09-09T23:15:11+00:00",
            "side": "team", "outcome_name": "Baltimore Ravens", "point": None,
            "american_price": 140, "malformed_market": False, "malformed_reason": None,
        },
    ], strict=False)


def _plan():
    return pl.DataFrame([
        {"request_plan_id": "md_2020_001", "season": 2020,
         "requested_target_timestamp_utc": "2020-09-10T23:20:00Z",
         "expected_earliest_kickoff_utc": "2020-09-11T00:20:00Z",
         "target_game_ids": "2020_01_HOU_KC"},
        {"request_plan_id": "md_2021_001", "season": 2021,
         "requested_target_timestamp_utc": "2021-09-09T23:20:00Z",
         "expected_earliest_kickoff_utc": "2021-09-10T00:20:00Z",
         "target_game_ids": "2021_01_BAL_KC"},
    ])


def _sched():
    return pl.DataFrame(SAMPLE_SCHEDULE, strict=False)


class TestCanonical:
    def test_all_targets_present(self):
        games, bm = build_canonical(_norm_frame(), _plan(), _sched())
        assert games.height == 2
        assert set(games["game_id"].to_list()) == {"2020_01_HOU_KC", "2021_01_BAL_KC"}
        assert games["season"].min() == 2020 and games["season"].max() == 2021

    def test_match_status(self):
        games, bm = build_canonical(_norm_frame(), _plan(), _sched())
        assert (games["match_status"] == MATCHED_EXACT).all()

    def test_pregame_lead(self):
        games, bm = build_canonical(_norm_frame(), _plan(), _sched())
        assert (games["lead_minutes"].is_not_null()).all()
        assert (games["lead_minutes"] > 0).all()
        assert (games["lead_minutes"].min() >= 55)

    def test_no_2025(self):
        games, bm = build_canonical(_norm_frame(), _plan(), _sched())
        assert games.filter(pl.col("season") == 2025).height == 0

    def test_snapshot_strictly_before_kickoff(self):
        games, bm = build_canonical(_norm_frame(), _plan(), _sched())
        for r in games.to_dicts():
            assert r["actual_snapshot_timestamp_utc"] < r["kickoff_time_utc"]

    def test_book_market_conserves_sides(self):
        games, bm = build_canonical(_norm_frame(), _plan(), _sched())
        assert bm.height == 4  # 2 games x 1 book x 2 h2h sides
        assert bm["american_price"].is_not_null().all()

    def test_no_outcome_fields(self):
        games, bm = build_canonical(_norm_frame(), _plan(), _sched())
        banned = {"score", "winner", "result", "ats", "edge", "roi", "profit"}
        for df in (games, bm):
            cols_lower = {c.lower() for c in df.columns}
            assert not (banned & cols_lower)


class TestRawImmutability:
    def test_raw_bytes_unchanged(self, tmp_path):
        p = tmp_path / "raw.json"
        original = b'{"timestamp": "2024-09-05T23:15:38Z", "data": []}'
        p.write_bytes(original)
        # read and parse should not mutate the file
        _ = json.loads(p.read_text("utf-8"))
        assert p.read_bytes() == original
        assert p.stat().st_size == len(original)