from __future__ import annotations

import json
from copy import deepcopy
from unittest.mock import patch

import pytest

from nfl_edge.live.schedule_materializer_2026 import ScheduleMaterializationError, build_week_schedule
from nfl_edge.live.week5_surface_evidence_2026 import (
    EVIDENCE_PATH,
    IDENTITY_FIELDS,
    Week5SurfaceEvidenceError,
    load_surface_evidence,
    recover_missing_surface,
)

EXPECTED = {
    "2026_05_PHI_JAX": "artificial",
    "2026_05_CHI_GB": "grass",
    "2026_05_CIN_MIA": "grass",
    "2026_05_LV_NE": "fieldturf",
    "2026_05_MIN_NO": "sportturf",
    "2026_05_CLE_NYJ": "fieldturf",
    "2026_05_IND_PIT": "grass",
    "2026_05_HOU_TEN": "matrixturf",
    "2026_05_NYG_WAS": "grass",
    "2026_05_DEN_LAC": "matrixturf",
    "2026_05_DET_ARI": "grass",
    "2026_05_SF_SEA": "fieldturf",
    "2026_05_BAL_ATL": "fieldturf",
    "2026_05_BUF_LAR": "matrixturf",
}


def row_for(gid):
    r = load_surface_evidence()[gid]
    return {
        **{k: r[k] for k in IDENTITY_FIELDS},
        "surface": "",
        "roof": "outdoors",
        "gametime": "13:00",
        "away_rest": "7",
        "home_rest": "7",
        "location": "Home",
    }


@pytest.mark.parametrize("gid,expected", EXPECTED.items())
def test_all_fourteen(gid, expected):
    row = row_for(gid)
    before = deepcopy(row)
    with patch("requests.sessions.Session.request", side_effect=AssertionError("network forbidden")):
        p = build_week_schedule([row], season=2026, week=5, observed_at_utc="2026-10-15T04:00:00Z")
    assert row == before
    assert p["games"][0]["surface"] == expected
    assert p["games"][0]["game_id"] == gid
    e = p["surface_recovery"][0]
    assert e["original_surface"] == "" and e["evidence"]["source_urls"] and len(e["evidence_sha256"]) == 64


@pytest.mark.parametrize(
    "field,value",
    [
        ("stadium", "EverBank Stadium"),
        ("stadium_id", "LON02"),
        ("game_id", "2026_05_PHI_MIA"),
        ("gameday", "2026-10-12"),
        ("away_team", "MIA"),
        ("home_team", "MIA"),
    ],
)
def test_identity_mismatch(field, value):
    r = row_for("2026_05_PHI_JAX")
    r[field] = value
    with pytest.raises(Week5SurfaceEvidenceError, match="identity mismatch"):
        recover_missing_surface(r, canonical_game_id="2026_05_PHI_JAX")


def test_tottenham_unknown_subtype_and_raw_id():
    r = row_for("2026_05_PHI_JAX")
    v, p = recover_missing_surface(r, canonical_game_id="2026_05_PHI_JAX")
    assert v == "artificial" and r["stadium_id"] == "JAX00"
    assert p["evidence"]["stadium"] == "Tottenham Hotspur Stadium"
    assert p["evidence"]["surface_subtype_known"] is False
    r["stadium"] = "EverBank Stadium"
    with pytest.raises(ScheduleMaterializationError, match="identity mismatch"):
        build_week_schedule([r], season=2026, week=5, observed_at_utc="2026-10-15T04:00:00Z")


@pytest.mark.parametrize("field,value", [("season", "2025"), ("week", "6"), ("game_type", "POST")])
def test_scope(field, value):
    r = row_for("2026_05_PHI_JAX")
    r[field] = value
    assert recover_missing_surface(r, canonical_game_id="2026_05_PHI_JAX") is None


def test_preserve_nonmissing():
    r = row_for("2026_05_PHI_JAX")
    r["surface"] = "fieldturf"
    p = build_week_schedule([r], season=2026, week=5, observed_at_utc="2026-10-15T04:00:00Z")
    assert p["games"][0]["surface"] == "fieldturf" and "surface_recovery" not in p


def test_unknown_game_stays_blocked():
    r = row_for("2026_05_PHI_JAX")
    r.update(away_team="BUF", home_team="MIA", game_id="2026_05_BUF_MIA")
    with pytest.raises(ScheduleMaterializationError, match="missing required surface"):
        build_week_schedule([r], season=2026, week=5, observed_at_utc="2026-10-15T04:00:00Z")


@pytest.mark.parametrize("change", ["unsupported", "no_sources", "no_date", "missing_game", "class_mismatch"])
def test_invalid_evidence(tmp_path, monkeypatch, change):
    p = json.loads(EVIDENCE_PATH.read_text())
    if change == "class_mismatch":
        p["games"][0]["surface"] = "grass"
    if change == "unsupported":
        p["games"][1]["surface"] = "unverified-turf"
    if change == "no_sources":
        p["games"][1]["source_urls"] = []
    if change == "no_date":
        p["games"][1]["retrieved_on"] = ""
    if change == "missing_game":
        p["games"].pop()
    f = tmp_path / "evidence.json"
    f.write_text(json.dumps(p))
    monkeypatch.setattr("nfl_edge.live.week5_surface_evidence_2026.EVIDENCE_PATH", f)
    with pytest.raises(Week5SurfaceEvidenceError):
        load_surface_evidence()
