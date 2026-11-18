import hashlib
import json
from copy import deepcopy

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


@pytest.mark.parametrize("fault", ["wrong_time", "reversed", "missing", "malformed", "timeout", "duplicate"])
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
        espn["events"].append(first)

    def fetch(_):
        if fault == "timeout":
            raise requests.Timeout("timed out")
        return b"{" if fault == "malformed" else json.dumps(espn).encode()

    monkeypatch.setattr(verification, "_espn_scoreboard", fetch)
    result, report = verification.reconcile_market_kickoffs(schedule, odds, live=True)
    assert result is schedule
    expected = {
        "wrong_time": "KICKOFF_UNCONFIRMED", "reversed": "KICKOFF_UNCONFIRMED",
        "missing": "KICKOFF_UNCONFIRMED", "malformed": "ESPN_INVALID_RESPONSE",
        "timeout": "ESPN_UNAVAILABLE", "duplicate": "ESPN_INVALID_RESPONSE",
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
