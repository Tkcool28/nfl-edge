from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.features.totals_v1.block_state import GameObservation
from nfl_edge.features.totals_v1.game_observations import build_game_observations_with_provenance
from nfl_edge.holdout.totals_observations_2025 import (
    HoldoutTotalsObservationError,
    build_2025_game_observations_with_provenance,
    prove_development_shadow_parity,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/task05h_2025_complete_model_inputs_v1.py"
spec = importlib.util.spec_from_file_location("task05h_2025_complete_model_inputs_v1", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_source_identity_is_pinned_to_official_nflverse_2025_parquet():
    assert mod.PBP_URL.endswith("/pbp/play_by_play_2025.parquet")
    assert mod.PBP_ASSET_ID == 512957613
    assert mod.PBP_EXPECTED_BYTES == 20_337_029
    assert mod.PBP_EXPECTED_SHA256 == "c6ecedd6d678cc37ed316b23ef84ee1ec6abb69c514bb11868a7ebd5a367df29"


def test_2025_mapping_reuses_per_game_canonical_team_normalization():
    pbp = pl.DataFrame(
        {
            "game_id": ["2025_01_AAA_BBB", "2025_01_AAA_BBB"],
            "season": [2025, 2025],
            "season_type": ["REG", "REG"],
            "week": [1, 1],
            "home_team": ["BBB", "BBB"],
            "away_team": ["AAA", "AAA"],
            "posteam": ["AAA", "BBB"],
            "defteam": ["BBB", "AAA"],
        }
    )
    canonical = pl.DataFrame(
        {
            "game_id": ["2025_01_AAA_BBB"],
            "season": [2025],
            "season_type": ["REG"],
            "week": [1],
            "home_team": ["BBB"],
            "away_team": ["AAA"],
        }
    )
    mapped = mod.map_2025_pbp(pbp, canonical)
    assert mapped["posteam"].to_list() == ["AAA", "BBB"]
    assert mapped["defteam"].to_list() == ["BBB", "AAA"]
    assert mapped["season_type_canonical"].unique().to_list() == ["REG"]
    assert mapped["pbp_season_type"].unique().to_list() == ["REG"]


def test_game_observation_ledger_round_trips_without_synthesizing_updates(tmp_path: Path):
    path = tmp_path / "ledger.jsonl"
    rows = [
        {
            "block_id": "2025_REG_W01",
            "game_id": "g1",
            "season": 2025,
            "season_type": "REG",
            "week": 1,
            "team_updates": {},
        },
        {
            "block_id": "2025_REG_W01",
            "game_id": "g2",
            "season": 2025,
            "season_type": "REG",
            "week": 1,
            "team_updates": {"AAA": {"epa_play_offense": [3.0, 6.0, 6]}},
        },
    ]
    path.write_text("".join(mod.canonical_json(row) + "\n" for row in rows), encoding="utf-8")
    loaded = mod.load_observation_rows(path)
    assert loaded == [
        GameObservation(block_id="2025_REG_W01", game_id="g1", team_updates={}),
        GameObservation(
            block_id="2025_REG_W01",
            game_id="g2",
            team_updates={"AAA": {"epa_play_offense": (3.0, 6.0, 6)}},
        ),
    ]


def test_certification_report_language_prohibits_holdout_execution(tmp_path: Path):
    cert = {
        "new_2025_totals_inputs": {"pbp_sha256": "a", "game_observation_sha256": "b"},
        "certification_matrix": [],
    }
    path = tmp_path / "report.md"
    mod.build_report(cert, path)
    text = path.read_text(encoding="utf-8")
    assert "remaining_missing_2025_input_surfaces: []" in text
    assert "2025 HOLDOUT HAS NOT BEEN EXECUTED" in text
    assert "ALL_2025_MODEL_INPUTS_FROZEN_AND_CERTIFIED" in text


def _minimal_observation_pbp(season: int) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": ["g1"],
            "season": [season],
            "posteam": [None],
            "defteam": [None],
            "play_type": [None],
            "play_deleted": [0.0],
            "aborted_play": [0.0],
            "pass_attempt": [None],
            "rush_attempt": [None],
            "complete_pass": [None],
            "qb_dropback": [None],
            "qb_kneel": [0.0],
            "qb_spike": [0.0],
            "sack": [None],
            "epa": [None],
            "success": [None],
            "interception": [None],
            "fumble_lost": [None],
            "fixed_drive": [1.0],
            "fixed_drive_result": [None],
            "play_id": [1.0],
            "qtr": [None],
            "score_differential": [None],
            "game_seconds_remaining": [None],
            "yardline_100": [None],
            "goal_to_go": [None],
            "yards_gained": [None],
            "air_yards": [None],
            "yards_after_catch": [None],
        }
    )


def test_holdout_observation_bridge_changes_only_season_gate():
    dev = _minimal_observation_pbp(2024)
    accepted, accepted_prov = build_game_observations_with_provenance(
        block_id="blk", pbp_frames={"g1": dev}
    )
    holdout, holdout_prov = build_2025_game_observations_with_provenance(
        block_id="blk", pbp_frames={"g1": _minimal_observation_pbp(2025)}
    )
    assert holdout == accepted
    assert holdout_prov == accepted_prov
    prove_development_shadow_parity(block_id="blk", pbp_frames={"g1": dev})


def test_holdout_observation_bridge_rejects_non_2025_input():
    with pytest.raises(HoldoutTotalsObservationError):
        build_2025_game_observations_with_provenance(
            block_id="blk", pbp_frames={"g1": _minimal_observation_pbp(2024)}
        )
