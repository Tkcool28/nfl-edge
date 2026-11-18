from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import polars as pl
import pytest
import requests

from nfl_edge.features.totals_v1.pbp_semantics import REQUIRED_PBP_COLUMNS
from nfl_edge.live import evidence_2026 as evidence
from nfl_edge.live import schedule_verification_2026 as verify
from nfl_edge.live.historical_schedule_2026 import checkpoint, reuse, sha
from nfl_edge.live.markets_2026 import MATCH_KICKOFF_TOLERANCE_SECONDS, match_provider_events
from nfl_edge.live.product_state_2026 import Entering2026ProductStateError, _final_pregame_selector_rows
from nfl_edge.live.schedule_materializer_2026 import (
    NFLVERSE_GAMES_URL,
    ScheduleMaterializationError,
    build_week_schedule,
)
from nfl_edge.live.week11_flex_2026 import CORRECTION_ID, FLEX_GAMES
from nfl_edge.prospective.capture_v1 import PUBLICATION_SCHEMA_VERSION
from nfl_edge.prospective.common_v1 import ProspectiveCardError
from nfl_edge.prospective.runtime_v1 import require_prospective_kickoff_compatibility, runtime_publications_dir

OBSERVED = "2026-11-18T12:01:01Z"
RETRIEVED = "2026-11-18T12:01:03Z"
AS_OF = "2026-11-18T12:05:00Z"
PRIMARY = {"url": NFLVERSE_GAMES_URL, "retrieved_at_utc": RETRIEVED, "response_sha256": "a" * 64}
ESPN_URL = verify.espn_week_url(2026, 11)


def _source(week, day, away, home, local):
    return {
        "season": "2026", "game_type": "REG", "week": str(week), "gameday": day, "gametime": local,
        "game_id": f"2026_{week:02d}_{away}_{home}", "away_team": away, "home_team": home,
        "stadium": "Test Stadium", "stadium_id": "TEST", "location": "Home",
        "surface": "grass", "roof": "outdoors", "away_rest": "7", "home_rest": "7",
        "away_score": "14", "home_score": "17", "away_qb_id": "away", "home_qb_id": "home",
        "away_qb_name": "Away", "home_qb_name": "Home",
    }


@pytest.fixture
def flex_rows():
    return [_source(11, "2026-11-22", flex.away, flex.home, flex.old_local) for flex in FLEX_GAMES.values()]


def _schedule(rows, *, corrected=True, observed=OBSERVED):
    return build_week_schedule(rows, season=2026, week=11, observed_at_utc=observed, reconcile_flex=corrected)


def _espn_payload():
    season, week = {"year": 2026, "type": 2}, {"number": 11}
    events = [{
        "id": flex.espn_id, "date": flex.new_utc, "season": season.copy(), "week": week.copy(),
        "competitions": [{"id": flex.espn_id, "date": flex.new_utc, "competitors": [
            {"homeAway": "away", "team": {"abbreviation": "JAC" if flex.away == "JAX" else flex.away}},
            {"homeAway": "home", "team": {"abbreviation": flex.home}},
        ]}],
    } for flex in FLEX_GAMES.values()]
    return {"season": season, "week": week, "events": events}


def _report(schedule, raw):
    if not isinstance(raw, bytes):
        raw = json.dumps(raw).encode()
    return verify.verify_espn_response(schedule, raw, primary=PRIMARY, retrieved_at_utc=AS_OF, url=ESPN_URL)


def test_exact_flex_and_market_matching_tolerance(flex_rows):
    initial = deepcopy(flex_rows)
    original = _schedule(flex_rows, corrected=False)
    revised = _schedule(flex_rows)
    assert revised["kickoff_reconciliation"]["correction_id"] == CORRECTION_ID
    assert original["schedule_version"] != revised["schedule_version"]
    assert _schedule(flex_rows, observed=AS_OF)["schedule_version"] == revised["schedule_version"]
    assert flex_rows == initial
    assert {g["game_id"]: g["scheduled_start_utc"] for g in revised["games"]} == {
        gid: flex.new_utc for gid, flex in FLEX_GAMES.items()
    }
    assert MATCH_KICKOFF_TOLERANCE_SECONDS == 900
    for seconds, expected in ((0, 2), (900, 2), (901, 0)):
        events = [{
            "id": flex.espn_id, "home_team": flex.home, "away_team": flex.away,
            "commence_time": (
                datetime.fromisoformat(flex.new_utc) + timedelta(seconds=seconds)
            ).isoformat().replace("+00:00", "Z"),
        } for flex in FLEX_GAMES.values()]
        assert match_provider_events(revised, events)[1]["matched_canonical_games"] == expected
        assert match_provider_events(original, events)[1]["matched_canonical_games"] == 0


@pytest.mark.parametrize("field,value", [
    ("game_id", "2026_11_JAX_BUF"), ("season", "2025"), ("week", "12"), ("game_type", "POST"),
    ("gametime", "13:05"), ("gameday", "2026-11-21"), ("away_team", "NYG"), ("home_team", "JAX"),
])
def test_flex_rejects_any_drift_in_source_identity(flex_rows, field, value):
    flex_rows[0][field] = value
    with pytest.raises(ScheduleMaterializationError, match=CORRECTION_ID):
        _schedule(flex_rows)


def test_espn_approved_flex_unreviewed_difference_and_source_agreement(flex_rows):
    raw = json.dumps(_espn_payload()).encode()
    revised = _report(_schedule(flex_rows), raw)
    assert revised["status"] == "VERIFIED"
    assert revised["primary"] == PRIMARY
    assert revised["secondary"] == {
        "url": ESPN_URL, "retrieved_at_utc": AS_OF, "response_sha256": hashlib.sha256(raw).hexdigest(),
    }
    assert len(revised["discrepancies"]) == 2
    assert all(row["approved_correction"] for row in revised["discrepancies"])
    assert _report(_schedule(flex_rows, corrected=False), raw)["status"] == "KICKOFF_DISCREPANCY"
    for row in flex_rows:
        row["gametime"] = FLEX_GAMES[row["game_id"]].new_local
    assert _report(_schedule(flex_rows), raw)["discrepancies"] == []
    assert _report(_schedule(flex_rows, corrected=False), raw)["status"] == "VERIFIED"


@pytest.mark.parametrize("fault,status", [
    ("absent", "ESPN_SLATE_MISMATCH"), ("orientation", "ESPN_SLATE_MISMATCH"),
    ("duplicate_id", "ESPN_INVALID_RESPONSE"), ("duplicate_game", "ESPN_INVALID_RESPONSE"),
    ("event_date_drift", "ESPN_INVALID_RESPONSE"), ("competition_id", "ESPN_INVALID_RESPONSE"),
    ("wrong_week", "ESPN_INVALID_RESPONSE"), ("wrong_season_type", "ESPN_INVALID_RESPONSE"),
    ("wrong_flex_id", "KICKOFF_DISCREPANCY"), ("non_utc_equivalent", "VERIFIED"),
    ("shifted_date", "KICKOFF_DISCREPANCY"),
])
def test_espn_fails_closed_on_schema_or_slate_drift(flex_rows, fault, status):
    payload = _espn_payload()
    first = payload["events"][0]
    competition = first["competitions"][0]
    if fault == "absent":
        payload["events"].pop()
    elif fault == "orientation":
        for team, direction in zip(competition["competitors"], ("home", "away"), strict=True):
            team["homeAway"] = direction
    elif fault in {"duplicate_id", "duplicate_game"}:
        duplicate = deepcopy(first)
        if fault == "duplicate_game":
            duplicate["id"] = duplicate["competitions"][0]["id"] = "123"
        payload["events"].append(duplicate)
    elif fault == "wrong_week":
        first["week"]["number"] = 12
    elif fault == "wrong_season_type":
        payload["season"]["type"] = 3
    elif fault == "competition_id":
        competition["id"] = "123"
    elif fault == "wrong_flex_id":
        first["id"] = competition["id"] = "123"
    elif fault == "event_date_drift":
        first["date"] = "2026-11-22T20:25:00Z"
    elif fault == "non_utc_equivalent":
        first["date"] = competition["date"] = "2026-11-22T16:25:00-05:00"
    else:
        first["date"] = competition["date"] = "2026-11-23T21:25:00Z"
    assert _report(_schedule(flex_rows), payload)["status"] == status


def test_malformed_json_records_raw_digest(flex_rows):
    report = _report(_schedule(flex_rows), b"{")
    assert report["status"] == "ESPN_INVALID_RESPONSE"
    assert report["secondary"]["response_sha256"] == hashlib.sha256(b"{").hexdigest()


@pytest.mark.parametrize("outcome", ["timeout", "connection", "http"])
def test_source_failure_is_distinct_from_disagreement(monkeypatch, flex_rows, outcome):
    class Unavailable:
        status_code = 503

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def get(url, **kwargs):
        assert url == ESPN_URL and kwargs == {"timeout": (6, 6), "stream": True, "allow_redirects": False}
        if outcome == "timeout":
            raise requests.Timeout("read timed out")
        if outcome == "connection":
            raise requests.ConnectionError("connection refused")
        return Unavailable()

    monkeypatch.setattr(verify.requests, "get", get)
    report = verify.verify_independent_schedule(_schedule(flex_rows), primary=PRIMARY)
    assert report["status"] == ("ESPN_TIMEOUT" if outcome == "timeout" else "ESPN_UNAVAILABLE")


@pytest.fixture
def corrected_cohort(tmp_path, monkeypatch, flex_rows):
    older = [
        _source(week, (datetime(2026, 9, 10, tzinfo=timezone.utc) + timedelta(weeks=week - 1)).date().isoformat(),
                "SEA", "DEN", "20:15")
        for week in range(1, 11)
    ]
    games = evidence._canonical_games(older, through_week=10).to_dicts()
    team = pl.DataFrame([
        dict(game_id=g["game_id"], season=2026, week=g["week"], team=t,
             passing_epa=1., rushing_epa=1., passing_yards=100., rushing_yards=50.)
        for g in games for t in ("SEA", "DEN")
    ])
    qb = team.with_columns(pl.lit("QB").alias("position"), pl.col("team").alias("player_id"),
                           pl.lit(20).alias("attempts"), pl.lit(1).alias("sacks_suffered"),
                           pl.lit(0.).alias("passing_cpoe"), pl.lit(0).alias("passing_interceptions"))
    pbp_rows = []
    for g in games:
        row = dict.fromkeys(REQUIRED_PBP_COLUMNS, 0)
        row.update(game_id=g["game_id"], season=2026, week=g["week"], qtr=5, play_id=200,
                   game_seconds_remaining=100., total_home_score=17, total_away_score=14,
                   posteam="SEA", defteam="DEN", home_team="DEN", away_team="SEA")
        pbp_rows.append(row)
    by_url = {evidence.TEAM_STATS_URL: team, evidence.PLAYER_STATS_URL: qb, evidence.PBP_URL: pl.DataFrame(pbp_rows)}
    monkeypatch.setattr(evidence, "_now", lambda: OBSERVED)
    monkeypatch.setattr(evidence, "fetch_nflverse_schedule", lambda **kw: (older + flex_rows, PRIMARY))
    monkeypatch.setattr(evidence, "_download_parquet", lambda url, **kw: (by_url[url], "a" * 64))
    old = _schedule(flex_rows, corrected=False)
    old_bundle = checkpoint(flex_rows, old)
    prior_ref = sha(old_bundle)
    old_manifest = {"schema_version": evidence.EVIDENCE_SCHEMA, "season": 2026, "active_week": 11,
                    "through_week": 10, "schedule_checkpoints": {"11": prior_ref}}
    old_path = tmp_path / "schedule_checkpoints" / f"{prior_ref}.json"
    old_path.parent.mkdir()
    old_path.write_text(json.dumps(old_bundle))
    (tmp_path / evidence.MANIFEST_NAME).write_text(json.dumps(old_manifest))
    evidence._write_json_atomic(tmp_path / "week11_schedule_v1.json", old)
    cohort = evidence.materialize_settled_evidence(output_dir=tmp_path, active_as_of_utc=AS_OF)
    return cohort, old_path, old_bundle, old_manifest


def test_corrected_cohort_preserves_original_checkpoint_and_manifest(corrected_cohort):
    cohort, old_path, old_bundle, old_manifest = corrected_cohort
    root = cohort.root
    schedule_path = root / "week11_schedule_v1.json"
    active = json.loads(schedule_path.read_text())
    assert old_path.read_bytes() == json.dumps(old_bundle).encode()
    archive = cohort.manifest["week11_pre_flex_manifest_sha256"]
    assert json.loads((root / "schedule_manifest_history" / f"{archive}.json").read_text()) == old_manifest
    new = cohort.manifest["schedule_checkpoints"]["11"]
    assert new != sha(old_bundle)
    assert evidence.require_current_schedule_cohort(cohort, active, schedule_path, as_of_utc=AS_OF) == {
        **PRIMARY, "checkpoint_sha256": new, "cohort_observed_at_utc": OBSERVED,
    }
    # nflverse may catch up to the reviewed official times without rewriting
    # the source bytes recorded by either historical checkpoint.
    upstream = deepcopy(old_bundle["source_rows"])
    for row in upstream:
        row["gametime"] = FLEX_GAMES[row["game_id"]].new_local
    assert reuse(root, upstream, 11)["schedule"] == active


def test_cohort_rejects_stale_or_mixed_artifacts(corrected_cohort):
    cohort, *_ = corrected_cohort
    schedule_path = cohort.root / "week11_schedule_v1.json"
    schedule = json.loads(schedule_path.read_text())
    with pytest.raises(evidence.SettledEvidenceError, match="stale"):
        evidence.require_current_schedule_cohort(
            cohort, schedule, schedule_path, as_of_utc="2026-11-19T00:05:00Z",
        )
    schedule_path.write_text(json.dumps({**schedule, "schedule_version": "unselected"}))
    with pytest.raises(evidence.SettledEvidenceError, match="checkpoint"):
        evidence.require_current_schedule_cohort(cohort, schedule, schedule_path, as_of_utc=AS_OF)
    schedule_path.write_text(json.dumps(schedule))
    with (cohort.root / "settled_games.parquet").open("ab") as handle:
        handle.write(b"unexpected bytes")
    with pytest.raises(evidence.SettledEvidenceError, match="cohort digest mismatch"):
        evidence.load_settled_evidence(cohort.root)


def test_prospective_kickoff_drift_leaves_prior_record_immutable(flex_rows, tmp_path):
    path = runtime_publications_dir(tmp_path, season=2026, week=11) / "publication.json"
    path.parent.mkdir(parents=True)
    flex = FLEX_GAMES["2026_11_PIT_PHI"]
    record = {
        "schema_version": PUBLICATION_SCHEMA_VERSION, "season": 2026, "week": 11,
        "publication_id": "original", "source_product_sha256": "a" * 64,
        "published_at_utc": AS_OF,
        "lanes": {"value": {"game_id": flex.game_id, "kickoff_at_utc": flex.old_utc}},
    }
    path.write_text(json.dumps(record))
    require_prospective_kickoff_compatibility(_schedule(flex_rows, corrected=False), runtime_root=tmp_path)
    with pytest.raises(ProspectiveCardError, match="prospective kickoff drift"):
        require_prospective_kickoff_compatibility(_schedule(flex_rows), runtime_root=tmp_path)
    assert path.read_text() == json.dumps(record)


@pytest.mark.parametrize("game_id", sorted(FLEX_GAMES))
def test_original_selector_proof_is_immutable_and_never_gains_eligibility(tmp_path, game_id):
    path = tmp_path / "run" / "product" / "deterministic-proof.json"
    path.parent.mkdir(parents=True)
    flex = FLEX_GAMES[game_id]
    row = {"game_id": game_id}
    proof = {"selector_evidence": {
        "schema_version": "NFL_EDGE_LIVE_SELECTOR_EVIDENCE_V1", "season": 2026, "week": 11,
        "captured_at_utc": AS_OF, "games": [{"game_id": game_id, "kickoff_at_utc": flex.old_utc}], "rows": [row],
    }}
    path.write_text(json.dumps(proof))
    original = path.read_bytes()

    def rows_for(payload):
        return _final_pregame_selector_rows(
            run_root=tmp_path, week=11, required_game_ids={game_id}, successful_proofs=[(path, payload)],
        )

    assert rows_for(proof) == [row]
    disputed = deepcopy(proof)
    disputed["selector_evidence"]["captured_at_utc"] = "2026-11-22T19:00:00Z"
    message = "captured after official kickoff" if flex.away == "PIT" else "missing successful final"
    with pytest.raises(Entering2026ProductStateError, match=message):
        rows_for(disputed)
    assert path.read_bytes() == original
