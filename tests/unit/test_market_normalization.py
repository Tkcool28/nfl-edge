"""Task 05E-D2 Phase B test suite: matching, normalization, canonicalization.

Outcome-blind by construction: these tests never touch final scores, winners,
betting results, or edges.
"""

import hashlib
import json
import tempfile
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.market_data import matching
from nfl_edge.market_data.matching import (
    MatchError,
    canonicalize_name,
    event_abbr_pair,
    game_id_abbr_pair,
    resolve_event_identity,
)
from nfl_edge.market_data.normalize import (
    NormalizationError,
    _norm_ts,
    build_normalized,
    parse_market,
)


class TestTeamAliases:
    def test_canonicalize_known(self):
        assert canonicalize_name("Los Angeles Rams") == "LA"
        assert canonicalize_name("Washington Football Team") == "WAS"
        assert canonicalize_name("Washington Commanders") == "WAS"
        assert canonicalize_name("Kansas City Chiefs") == "KC"

    def test_canonicalize_unknown(self):
        assert canonicalize_name("Unknown FC") is None

    def test_resolve_event(self):
        ident = resolve_event_identity("Kansas City Chiefs", "Baltimore Ravens")
        assert ident.home_abbr == "KC"
        assert ident.away_abbr == "BAL"
        assert ident.matched_exact

    def test_resolve_unmatched(self):
        ident = resolve_event_identity("Kansas City Chiefs", "Unknown")
        assert not ident.matched_exact

    def test_game_id_abbr_pair(self):
        assert game_id_abbr_pair("2024_01_BAL_KC") == frozenset({"KC", "BAL"})

    def test_game_id_unparseable(self):
        with pytest.raises(MatchError):
            game_id_abbr_pair("bad")

    def test_event_abbr_pair(self):
        ev = {"home_team": "Green Bay Packers", "away_team": "Philadelphia Eagles"}
        assert event_abbr_pair(ev) == frozenset({"GB", "PHI"})

    def test_rams_alias_schedule_abbr(self):
        assert matching.TEAM_ALIASES["LA"] == ("Los Angeles Rams",)


class TestTimestampNormalization:
    def test_utc_z(self):
        assert _norm_ts("2024-09-05T23:15:38Z") == "2024-09-05T23:15:38+00:00"

    def test_utc_offset(self):
        v = _norm_ts("2024-09-05T18:15:38-05:00")
        assert v is not None
        # must be timezone-aware and parseable
        from datetime import datetime
        dt = datetime.fromisoformat(v)
        assert dt.tzinfo is not None

    def test_invalid(self):
        assert _norm_ts("not-a-date") is None
        assert _norm_ts(None) is None
        assert _norm_ts("2024-09-05") is None

    def test_naive_fails_closed(self):
        assert _norm_ts("2024-09-05T23:15:38") is None


class TestMarketParsing:
    def _mk(self, key, outcomes):
        return {"key": key, "outcomes": outcomes}

    def test_h2h_two_way(self):
        r = parse_market(self._mk("h2h", [
            {"name": "Ravens", "price": 124}, {"name": "Chiefs", "price": -148}]))
        assert not r.malformed and len(r.outcome_rows) == 2

    def test_h2h_malformed(self):
        r = parse_market(self._mk("h2h", [{"name": "A", "price": 100}]))
        assert r.malformed and r.malformed_reason

    def test_spreads_symmetric(self):
        r = parse_market(self._mk("spreads", [
            {"name": "A", "point": 3.0, "price": -115},
            {"name": "B", "point": -3.0, "price": -105}]))
        assert not r.malformed

    def test_spreads_asymmetric_flag(self):
        r = parse_market(self._mk("spreads", [
            {"name": "A", "point": 3.0, "price": -115},
            {"name": "B", "point": -5.0, "price": -105}]))
        assert r.malformed

    def test_totals_agreement(self):
        r = parse_market(self._mk("totals", [
            {"name": "Over", "point": 47.0, "price": -110},
            {"name": "Under", "point": 47.0, "price": -110}]))
        assert not r.malformed

    def test_totals_disagree_flag(self):
        r = parse_market(self._mk("totals", [
            {"name": "Over", "point": 47.0, "price": -110},
            {"name": "Under", "point": 46.5, "price": -110}]))
        assert r.malformed

    def test_unexpected_market(self):
        r = parse_market(self._mk("player_points", [{"name": "x", "price": 100}]))
        assert r.malformed

    def test_parse_never_alters_price(self):
        r = parse_market(self._mk("h2h", [
            {"name": "A", "price": 124}, {"name": "B", "price": -148}]))
        prices = [o["price"] for o in r.outcome_rows]
        assert prices == [124, -148]


class TestBuildNormalized:
    def _write_tree(self, tmp):
        """Write a minimal raw tree + ledger + plan for two seasons."""
        raw = tmp / "raw"
        (raw / "2020").mkdir(parents=True)
        (raw / "2021").mkdir(parents=True)
        ledger = tmp / "historical_acquisition_ledger_v1.parquet"
        plan = tmp / "historical_market_request_plan_v1.parquet"
        # one request per season
        plan_rows = []
        for rid, season, gid, teams in [
            ("md_2020_001", 2020, "2020_01_HOU_KC", ("Kansas City Chiefs", "Houston Texans")),
            ("md_2021_001", 2021, "2021_01_BAL_KC", ("Kansas City Chiefs", "Baltimore Ravens")),
        ]:
            plan_rows.append({
                "request_plan_id": rid, "cluster_id": f"{season}_001", "season": season,
                "gameday": "2020-09-10" if season == 2020 else "2021-09-09",
                "earliest_kickoff_utc": "2020-09-11T00:20:00Z" if season == 2020 else "2021-09-10T00:20:00Z",
                "expected_earliest_kickoff_utc": "2020-09-11T00:20:00Z" if season == 2020 else "2021-09-10T00:20:00Z",
                "requested_target_timestamp_utc": "2020-09-10T23:20:00Z" if season == 2020 else "2021-09-09T23:20:00Z",
                "cluster_width_minutes": 0.0, "expected_lead_min": 60.0, "expected_lead_max": 60.0,
                "game_count": 1, "target_game_ids": gid,
                "requested_bookmaker_keys": "draftkings,fanduel",
                "requested_markets": "h2h,spreads,totals", "expected_credits": 30,
            })
        pl.DataFrame(plan_rows).write_parquet(plan)

        def payload(home, away, ts):
            return {
                "timestamp": ts, "data": [{
                    "id": f"ev_{home}", "sport_key": "americanfootball_nfl",
                    "commence_time": "2020-09-11T00:20:00Z" if "2020" in ts else "2021-09-10T00:20:00Z",
                    "home_team": home, "away_team": away,
                    "bookmakers": [{
                        "key": "draftkings", "title": "DraftKings", "last_update": ts,
                        "markets": [
                            {"key": "h2h", "last_update": ts, "outcomes": [{"name": home, "price": -150}, {"name": away, "price": 130}]},
                            {"key": "spreads", "last_update": ts, "outcomes": [{"name": home, "point": -3.0, "price": -110}, {"name": away, "point": 3.0, "price": -110}]},
                            {"key": "totals", "last_update": ts, "outcomes": [{"name": "Over", "point": 47.0, "price": -110}, {"name": "Under", "point": 47.0, "price": -110}]},
                        ],
                    }],
                }],
            }

        raw_2020 = raw / "2020" / "md_2020_001.json"
        raw_2020.write_text(json.dumps(payload("Kansas City Chiefs", "Houston Texans", "2020-09-10T23:15:38Z")))
        raw_2021 = raw / "2021" / "md_2021_001.json"
        raw_2021.write_text(json.dumps(payload("Kansas City Chiefs", "Baltimore Ravens", "2021-09-09T23:15:38Z")))

        sha0 = hashlib.sha256(raw_2020.read_bytes()).hexdigest()
        sha1 = hashlib.sha256(raw_2021.read_bytes()).hexdigest()
        led_rows = [
            {"request_plan_id": "md_2020_001", "season": 2020, "actual_snapshot_timestamp_utc": "2020-09-10T23:15:38+00:00",
             "expected_earliest_kickoff_utc": "2020-09-11T00:20:00Z", "response_content_sha256": sha0,
             "success": True, "attempt_category": "VERIFIED_SUCCESS",
             "raw_payload_path": "2020/md_2020_001.json", "http_status": 200, "x_requests_last": 30},
            {"request_plan_id": "md_2021_001", "season": 2021, "actual_snapshot_timestamp_utc": "2021-09-09T23:15:38+00:00",
             "expected_earliest_kickoff_utc": "2021-09-10T00:20:00Z", "response_content_sha256": sha1,
             "success": True, "attempt_category": "VERIFIED_SUCCESS",
             "raw_payload_path": "2021/md_2021_001.json", "http_status": 200, "x_requests_last": 30},
        ]
        pl.DataFrame(led_rows).write_parquet(ledger)
        return raw, ledger, plan

    def test_build_normalized_ok(self, tmp_path):
        raw, ledger, plan = self._write_tree(tmp_path)
        df = build_normalized(raw, ledger, plan)
        assert df.height > 0
        assert "is_target_event" in df.columns
        assert "raw_file_sha256" in df.columns
        # both target and non-target: non-target = summing away? here only targets present
        assert df.filter(pl.col("is_target_event") == True).height > 0  # noqa: E712
        assert df["season"].dtype is not None

    def test_build_normalized_hash_mismatch_stops(self, tmp_path):
        raw, ledger, plan = self._write_tree(tmp_path)
        # corrupt a raw file -> hash mismatch should raise NormalizationError
        p = raw / "2020" / "md_2020_001.json"
        p.write_text(p.read_text() + "\n")
        with pytest.raises(NormalizationError):
            build_normalized(raw, ledger, plan)

    def test_build_normalized_no_2025(self, tmp_path):
        raw, ledger, plan = self._write_tree(tmp_path)
        df = build_normalized(raw, ledger, plan)
        assert df.filter(pl.col("season") == 2025).height == 0

    def test_traceable_raw_normalized(self, tmp_path):
        raw, ledger, plan = self._write_tree(tmp_path)
        df = build_normalized(raw, ledger, plan)
        # every row carries raw path + sha
        assert df["raw_file_path"].is_not_null().all()
        assert df["raw_file_sha256"].is_not_null().all()
        assert df["request_plan_id"].is_not_null().all()
        assert df["actual_snapshot_timestamp_utc"].is_not_null().all()

    def test_no_outcome_fields(self, tmp_path):
        raw, ledger, plan = self._write_tree(tmp_path)
        df = build_normalized(raw, ledger, plan)
        banned = {"score", "winner", "result", "ats", "edge", "roi", "profit"}
        cols_lower = {c.lower() for c in df.columns}
        assert not (banned & cols_lower)