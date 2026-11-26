import gzip
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
import requests

from nfl_edge.live import schedule_verification_2026 as verification
from nfl_edge.live.markets_2026 import MATCH_KICKOFF_TOLERANCE_SECONDS, match_provider_events
from nfl_edge.live.schedule_materializer_2026 import build_week_schedule

NOW = "2026-11-18T05:48:31Z"
FLEX = [
    ("JAX", "NYG", "13:00", "2026-11-22T21:25:00Z", "401873069"),
    ("PIT", "PHI", "16:25", "2026-11-22T18:00:00Z", "401873076"),
]


def kickoff_sources(week_number=11):
    rows, odds, espn_events = [], [], []
    season, week = {"year": 2026, "type": 2}, {"number": week_number}
    for away, home, old, corrected, espn_id in FLEX:
        rows.append({
            "season": "2026", "game_type": "REG", "week": str(week_number), "gameday": "2026-11-22", "gametime": old,
            "game_id": f"2026_{week_number:02d}_{away}_{home}", "away_team": away, "home_team": home,
            "stadium": "Test Stadium", "stadium_id": "TEST", "location": "Home",
            "surface": "grass", "roof": "outdoors", "away_rest": "7", "home_rest": "7",
        })
        odds.append({"id": f"event-{away}", "away_team": away, "home_team": home, "commence_time": corrected})
        espn_events.append({
            "id": espn_id, "date": corrected, "season": season, "week": week,
            "competitions": [{"id": espn_id, "date": corrected, "competitors": [
                {"homeAway": "away", "team": {"abbreviation": "JAC" if away == "JAX" else away}},
                {"homeAway": "home", "team": {"abbreviation": home}},
            ]}],
        })
    schedule = build_week_schedule(rows, season=2026, week=week_number, observed_at_utc=NOW)
    return schedule, odds, {"season": season, "week": week, "events": espn_events}


@pytest.fixture
def sources():
    return kickoff_sources()


@pytest.mark.parametrize("no_events", [False, True])
def test_no_espn_for_agreement_or_absent_odds_event(monkeypatch, sources, no_events):
    schedule, odds, _ = sources
    original = {(g["away_team"], g["home_team"]): g["scheduled_start_utc"] for g in schedule["games"]}
    for event in odds:
        event["commence_time"] = original[event["away_team"], event["home_team"]]
    monkeypatch.setattr(verification, "_espn_scoreboard", lambda *_: pytest.fail("ESPN called without a mismatch"))
    result, report = verification.reconcile_market_kickoffs(schedule, [] if no_events else odds, live=True)
    assert result is schedule and report is None


def test_one_espn_check_confirms_both_flexes_and_preserves_source(monkeypatch, tmp_path, sources):
    schedule, odds, espn = sources
    original = deepcopy(schedule)
    raw = json.dumps(espn).encode()
    calls = []
    monkeypatch.setattr(verification, "_espn_scoreboard", lambda url: calls.append(url) or raw)
    capture = tmp_path / "raw" / "espn.json"
    result, report = verification.reconcile_market_kickoffs(schedule, odds, live=True, capture_path=capture)
    assert calls == [verification.espn_week_url(2026, 11)]
    assert capture.read_bytes() == raw
    assert report["espn"]["response_sha256"] == hashlib.sha256(raw).hexdigest()
    assert report["status"] == "KICKOFF_CONFIRMED"
    assert len(report["discrepancies"]) == 2
    assert result["schedule_version"] != schedule["schedule_version"]
    assert schedule == original
    assert [game["scheduled_start_utc"] for game in result["games"]] == [FLEX[1][3], FLEX[0][3]]
    assert MATCH_KICKOFF_TOLERANCE_SECONDS == 900
    assert match_provider_events(schedule, odds)[1]["matched_canonical_games"] == 0
    assert match_provider_events(result, odds)[1]["matched_canonical_games"] == 2


def test_saved_replay_uses_espn_only_from_disk(tmp_path, monkeypatch, sources):
    schedule, odds, espn = sources
    monkeypatch.setattr(verification, "_espn_scoreboard", lambda *_: pytest.fail("offline replay used the network"))
    assert verification.reconcile_market_kickoffs(schedule, odds, live=False)[1]["status"] == "ESPN_CAPTURE_REQUIRED"
    path = tmp_path / "espn.json"
    path.write_text(json.dumps(espn))
    _, report = verification.reconcile_market_kickoffs(schedule, odds, live=False, espn_response=path)
    assert report["status"] == "KICKOFF_CONFIRMED"


def test_authentic_daily_espn_capture_confirms_both_week_11_games(tmp_path, monkeypatch, sources):
    schedule, odds, _ = sources
    # Exact captured bytes from the November 22 daily scoreboard.
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "espn_nfl_2026-11-22.json.gz"
    raw = gzip.decompress(fixture.read_bytes())
    digest = "cefbc941f6fc0f1b3b584830713411769dc853e9825e16b36adad2c4b04bcfe4"
    assert hashlib.sha256(raw).hexdigest() == digest
    assert "season" not in json.loads(raw)
    response = tmp_path / "daily-espn.json"
    response.write_bytes(raw)
    monkeypatch.setattr(verification, "_espn_scoreboard", lambda *_: pytest.fail("offline replay used the network"))

    revised, report = verification.reconcile_market_kickoffs(schedule, odds, live=False, espn_response=response)

    assert report["status"] == "KICKOFF_CONFIRMED"
    assert report["espn"]["response_sha256"] == digest
    assert {r["game_id"]: r["espn_event_id"] for r in report["discrepancies"]} == {
        "2026_11_JAX_NYG": "401873069", "2026_11_PIT_PHI": "401873076",
    }
    assert match_provider_events(revised, odds)[1]["matched_canonical_games"] == 2


def test_missing_season_week_and_unrelated_incomplete_events_are_ignored(monkeypatch, sources):
    schedule, odds, espn = sources
    for payload in [espn, *espn["events"]]:
        payload.pop("season")
        payload.pop("week")
    espn["events"].extend([{}, {
        "competitions": [{"competitors": [
            {"homeAway": "away", "team": {"abbreviation": "JAX"}},
            {"homeAway": "home", "team": {"abbreviation": "LAR"}},
        ]}],
    }])
    monkeypatch.setattr(verification, "_espn_scoreboard", lambda _: json.dumps(espn).encode())

    _, report = verification.reconcile_market_kickoffs(schedule, odds, live=True)

    assert report["status"] == "KICKOFF_CONFIRMED"
    assert len(report["discrepancies"]) == 2


@pytest.mark.parametrize("fault", [
    "wrong_time", "reversed", "missing", "malformed", "timeout", "duplicate",
    "ambiguous", "invalid_kickoff", "naive_kickoff", "contradictory_dates",
])
def test_unconfirmed_kickoff_never_changes_source(monkeypatch, sources, fault):
    schedule, odds, espn = sources
    first = espn["events"][0]
    if fault == "wrong_time":
        first["date"] = first["competitions"][0]["date"] = "2026-11-22T20:25:00Z"
    elif fault == "reversed":
        for side in first["competitions"][0]["competitors"]:
            side["homeAway"] = "away" if side["homeAway"] == "home" else "home"
    elif fault == "missing":
        espn["events"].pop(0)
    elif fault == "duplicate":
        duplicate = deepcopy(first)
        duplicate["id"] = duplicate["competitions"][0]["id"] = "999"
        espn["events"].append(duplicate)
    elif fault == "ambiguous":
        first["competitions"].append(deepcopy(first["competitions"][0]))
    elif fault == "invalid_kickoff":
        first["date"] = "invalid"
    elif fault == "naive_kickoff":
        first["date"] = "2026-11-22T21:25:00"
    elif fault == "contradictory_dates":
        first["competitions"][0]["date"] = "2026-11-22T20:25:00Z"

    def fetch(_):
        if fault == "timeout":
            raise requests.Timeout("timed out")
        return b"{" if fault == "malformed" else json.dumps(espn).encode()

    monkeypatch.setattr(verification, "_espn_scoreboard", fetch)
    result, report = verification.reconcile_market_kickoffs(schedule, odds, live=True)
    assert result is schedule
    expected = {
        "wrong_time": "KICKOFF_UNCONFIRMED", "reversed": "ESPN_INVALID_RESPONSE",
        "missing": "KICKOFF_UNCONFIRMED", "malformed": "ESPN_INVALID_RESPONSE",
        "timeout": "ESPN_UNAVAILABLE", "duplicate": "ESPN_INVALID_RESPONSE",
        "ambiguous": "ESPN_INVALID_RESPONSE", "invalid_kickoff": "ESPN_INVALID_RESPONSE",
        "naive_kickoff": "ESPN_INVALID_RESPONSE", "contradictory_dates": "ESPN_INVALID_RESPONSE",
    }
    assert report["status"] == expected[fault]


def test_espn_checks_only_disputed_matchups_and_normalizes_timezones(monkeypatch, sources):
    schedule, odds, espn = sources
    odds.pop()
    first = espn["events"][0]
    first["date"] = first["competitions"][0]["date"] = "2026-11-22T16:25:00-05:00"
    espn["events"].pop()
    monkeypatch.setattr(verification, "_espn_scoreboard", lambda _: json.dumps(espn).encode())
    result, report = verification.reconcile_market_kickoffs(schedule, odds, live=True)
    assert report["status"] == "KICKOFF_CONFIRMED"
    assert len(report["discrepancies"]) == 1
    assert [game["scheduled_start_utc"] for game in result["games"]] == [FLEX[0][3], FLEX[0][3]]


def test_ambiguous_odds_event_does_not_trigger_espn(monkeypatch, sources):
    schedule, odds, _ = sources
    odds.append({**odds[0], "id": "duplicate"})
    monkeypatch.setattr(verification, "_espn_scoreboard", lambda *_: pytest.fail("ESPN called for duplicate Odds rows"))
    with pytest.raises(verification.ScheduleVerificationError, match="multiple Odds events"):
        verification.reconcile_market_kickoffs(schedule, odds, live=True)


@pytest.mark.parametrize("odds_at", ["2026-11-22T18:00:00Z", "2026-11-22T18:30:00Z"])
def test_started_discrepancy_uses_frozen_boundary_inclusively(monkeypatch, sources, tmp_path, odds_at):
    schedule, odds, _ = sources
    game = next(g for g in schedule["games"] if g["away_team"] == "JAX")
    game["scheduled_start_utc"] = "2026-11-22T17:55:00Z"
    odds[0]["commence_time"] = odds_at
    before = deepcopy(schedule)
    monkeypatch.setattr(verification, "acquire_espn_evidence", lambda *_: pytest.fail("unexpected ESPN request"))
    result, report = verification.reconcile_market_kickoffs(
        schedule, odds[:1], live=True, evidence_root=tmp_path,
        prediction_as_of_utc="2026-11-22T18:30:00Z", odds_acquired_at_utc="2026-11-22T18:31:00Z",
    )
    assert result is schedule and result == before
    assert report["status"] == "STARTED_GAMES_EXCLUDED"
    assert report["started_game_exclusions"][0]["odds_kickoff_utc"] == odds_at
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("cutoff", ["2026-11-22T17:00:00Z", "2026-11-22T19:00:00Z"])
@pytest.mark.parametrize("index", [0, 1])
def test_disputed_game_still_requires_espn_if_either_kickoff_is_future(monkeypatch, sources, cutoff, index):
    schedule, odds, _ = sources
    calls = []

    def unconfirmed(url):
        calls.append(url)
        return b'{"events":[]}', "2026-11-23T00:01:00Z"

    monkeypatch.setattr(verification, "acquire_espn_evidence", unconfirmed)
    result, report = verification.reconcile_market_kickoffs(
        schedule, [odds[index]], live=True, prediction_as_of_utc=cutoff,
        odds_acquired_at_utc="2026-11-22T23:00:00Z",
    )
    assert calls == [verification.espn_week_url(2026, 11)]
    assert result is schedule and report["status"] == "KICKOFF_UNCONFIRMED"
    assert "started_game_exclusions" not in report


@pytest.mark.parametrize("confirmed", [True, False])
def test_mixed_slate_verifies_only_potentially_eligible_discrepancy(monkeypatch, tmp_path, sources, confirmed):
    schedule, odds, scoreboard = sources
    odds[0]["commence_time"] = "2026-11-22T18:15:28Z"
    future = "2026-11-22T21:40:00Z"
    odds[1]["commence_time"] = future
    scoreboard["events"][1]["date"] = future
    scoreboard["events"][1]["competitions"][0]["date"] = future
    scoreboard["events"][0]["date"] = "unreadable but unrelated"
    if not confirmed:
        scoreboard["events"].pop()
    monkeypatch.setattr(
        verification, "acquire_espn_evidence",
        lambda _: (json.dumps(scoreboard).encode(), "2026-11-22T19:05:30Z"),
    )
    result, report = verification.reconcile_market_kickoffs(
        schedule, odds, live=True, prediction_as_of_utc="2026-11-22T19:00:00Z",
        odds_acquired_at_utc="2026-11-22T19:05:00Z", evidence_root=tmp_path,
    )
    started = report["started_game_exclusions"]
    assert [row["game_id"] for row in started] == ["2026_11_JAX_NYG"]
    assert result["games"][0]["scheduled_start_utc"] == "2026-11-22T18:00:00Z"
    if confirmed:
        assert report["status"] == "KICKOFF_CONFIRMED"
        assert result["games"][1]["scheduled_start_utc"] == future
        saved, = list((tmp_path / "kickoff_reconciliations").glob("*.json"))
        assert json.loads(saved.read_text())["record"]["espn"]["event_id"] == "401873076"
    else:
        assert report["status"] == "KICKOFF_UNCONFIRMED" and result is schedule
        assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("acquired", [None, "2026-11-22T23:30:00", "2026-11-22T22:59:59Z"])
def test_unsafe_acquisition_timing_cannot_grant_exclusion(monkeypatch, sources, acquired):
    schedule, odds, _ = sources
    monkeypatch.setattr(verification, "acquire_espn_evidence", lambda *_: pytest.fail("unsafe timing"))
    result, report = verification.reconcile_market_kickoffs(
        schedule, odds, live=True, prediction_as_of_utc="2026-11-22T23:00:00Z",
        odds_acquired_at_utc=acquired,
    )
    assert result is schedule and report["status"] == "INVALID_ELIGIBILITY_TIMING"
    assert "started_game_exclusions" not in report


def test_authentic_week12_started_matchup_projection(tmp_path, monkeypatch):
    # Exact identity and timestamps from the hash-verified failed-run audit
    # d3b58ece3d00d0da2787c8b9276a2d6aa8f5a607213f873dbef2347262678faf.
    # This is a projection of the production evidence, not the raw priced slate.
    game = {
        "game_id": "2026_12_GB_LAR", "home_team": "LAR", "away_team": "GB",
        "scheduled_start_utc": "2026-11-26T01:00:00Z",
    }
    schedule = {
        "season": 2026, "week": 12, "games": [game],
        "schedule_version": "NFLVERSE_2026_REG_WEEK12_2026-11-26T02:09:28Z",
    }
    events = [{
        "id": "5b612899d6dcdf998107f2c6c6e49a58",
        "away_team": "Green Bay Packers", "home_team": "Los Angeles Rams",
        "commence_time": "2026-11-26T01:15:28Z",
    }]
    monkeypatch.setattr(verification, "_espn_scoreboard", lambda *_: pytest.fail("unexpected network"))
    revised, report = verification.reconcile_market_kickoffs(
        schedule, events, live=False, prediction_as_of_utc="2026-11-26T02:28:40.937249Z",
        odds_acquired_at_utc="2026-11-26T02:32:45Z",
    )
    assert revised is schedule
    assert report["status"] == "STARTED_GAMES_EXCLUDED"
    assert report["started_game_exclusions"][0]["game_id"] == game["game_id"]
    assert not list(tmp_path.iterdir())
