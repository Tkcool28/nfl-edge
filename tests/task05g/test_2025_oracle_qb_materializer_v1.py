from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]

RAW_FILES = (
    ROOT / "data/raw/stathead_actual_starters_2025_v1/chat_pastes/ranks_0001_0200.tsv",
    ROOT / "data/raw/stathead_actual_starters_2025_v1/chat_pastes/ranks_0201_0400.tsv",
    ROOT / "data/raw/stathead_actual_starters_2025_v1/chat_pastes/ranks_0401_0570.tsv",
)
STARTER_SIDES = (
    ROOT
    / "data/derived/stathead_actual_starters_2025_v1/final_oracle_starters/"
    "actual_starting_qb_game_sides_2025_v1.csv"
)
NEW_IDENTITIES = (
    ROOT
    / "data/derived/stathead_actual_starters_2025_v1/identity_crosswalk/"
    "task05g_2025_identity_provenance_v1.json"
)
STARTER_REPORT = (
    ROOT / "data/derived/stathead_actual_starters_2025_v1/validation_report_v1.json"
)
ORACLE_REPORT = (
    ROOT
    / "data/derived/oracle_qb_entering_state_2025_v1/"
    "oracle_qb_entering_state_validation_report_2025_v1.json"
)
ORACLE_ADJUSTMENTS = (
    ROOT
    / "data/derived/oracle_qb_entering_state_2025_v1/"
    "oracle_qb_pregame_adjustments_by_game_2025_v1.parquet"
)
HISTORICAL_STARTERS = (
    ROOT
    / "data/derived/stathead_actual_starters_v1/final_oracle_starters/"
    "actual_starting_qb_game_sides_2018_2024_v1.csv"
)
HISTORICAL_ORACLE = (
    ROOT
    / "data/derived/oracle_qb_entering_state_v2/"
    "oracle_qb_pregame_adjustments_by_game_2018_2024_v2.parquet"
)

PRIMARY_SHA256 = "8e73dfab9ffd84bf4a926f55dd757de2c59ca81d0462a0ed422ac6c53e58d84d"
HISTORICAL_STARTER_SHA256 = "38732823861bb1def3c216ce9189b651a2dc4d0737d2f65f88f17e97f40b2a1a"
HISTORICAL_ORACLE_SHA256 = "268368c81913e183d7e9ea5050c0da0a01be619790b75c5bab9362c97349e886"
NFLVERSE_PLAYERS_SHA256 = "bf53b18808097984bfac89ab80fd28ae2416944741230ab0a54277458c704943"

EXPECTED_ADJUSTMENT_COLUMNS = [
    "season",
    "week",
    "season_type",
    "game_date",
    "game_id",
    "away_team",
    "home_team",
    "away_actual_starting_qb_name",
    "away_actual_starting_qb_pfr_id",
    "away_actual_starting_qb_gsis_id",
    "away_passing_epa",
    "away_qb_adjustment_elo",
    "home_actual_starting_qb_name",
    "home_actual_starting_qb_pfr_id",
    "home_actual_starting_qb_gsis_id",
    "home_passing_epa",
    "home_qb_adjustment_elo",
    "historical_model_usage",
    "starter_evidence_class",
    "away_semantic_exception_flag",
    "home_semantic_exception_flag",
    "oracle_qb_adjustment_net",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_raw_stathead_source_is_starter_only_and_rank_complete() -> None:
    frames = [
        pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
        for path in RAW_FILES
    ]
    assert all("Result" not in frame.columns for frame in frames)
    raw = pd.concat(frames, ignore_index=True)
    assert tuple(raw["Rk"].astype(int)) == tuple(range(1, 571))
    assert len(raw) == 570
    assert raw["Rk"].nunique() == 570
    assert set(raw["Pos."]) == {"QB"}


def test_2025_starter_coverage_and_identity_are_complete() -> None:
    sides = pd.read_csv(STARTER_SIDES, dtype=str, keep_default_na=False)
    report = json.loads(STARTER_REPORT.read_text(encoding="utf-8"))

    assert len(sides) == 570
    assert sides[["game_id", "team_side"]].drop_duplicates().shape[0] == 570
    assert sides["game_id"].nunique() == 285
    grouped = sides.groupby("game_id")["team_side"].agg(lambda values: set(values))
    assert all(value == {"away", "home"} for value in grouped)
    assert not sides["actual_starting_qb_pfr_id"].eq("").any()
    assert not sides["actual_starting_qb_gsis_id"].eq("").any()
    assert set(sides["starter_source"]) == {"STATHEAD_QB_STARTED_QUERY"}
    assert set(sides["starter_evidence_class"]) == {"POSTGAME_ACTUAL_STARTER"}
    assert set(sides["historical_model_usage"]) == {"ORACLE_STARTER_IDENTITY_ONLY"}
    assert report["unresolved_game_sides"] == 0
    assert report["manual_starter_resolutions"] == 0


def test_new_2025_identities_are_exact_versioned_mappings() -> None:
    provenance = json.loads(NEW_IDENTITIES.read_text(encoding="utf-8"))
    assert provenance["new_2025_identity_count"] == 11
    assert provenance["nflverse_players_sha256"] == NFLVERSE_PLAYERS_SHA256
    assert provenance["mapping_rules"][-1] == "no fuzzy matching"
    rows = provenance["new_2025_identities"]
    assert len(rows) == 11
    assert len({row["raw_player_name"] for row in rows}) == 11
    assert all(row["pfr_id"] and row["gsis_id"] for row in rows)


def test_strict_prior_2025_chronology_is_frozen() -> None:
    report = json.loads(ORACLE_REPORT.read_text(encoding="utf-8"))
    chronology = report["chronology"]

    assert chronology["chronology_mode"] == "BLOCK_SEQUENTIAL_PHYSICAL_SOURCE_EXCLUSION"
    assert chronology["week1_2025_qb_stat_games_visible"] == 0
    assert chronology["current_block_2025_qb_stat_games_visible"] == 0
    assert chronology["future_2025_qb_stat_games_visible"] == 0
    blocks = chronology["blocks"]
    assert blocks[0]["block_order"] == [0, 1]
    assert blocks[0]["visible_prior_2025_game_count"] == 0
    assert all(block["current_block_qb_stat_game_ids_visible"] == 0 for block in blocks)
    assert all(block["future_2025_qb_stat_game_ids_visible"] == 0 for block in blocks)
    prior_counts = [block["visible_prior_2025_game_count"] for block in blocks]
    assert prior_counts == sorted(prior_counts)
    assert prior_counts[-1] == 284


def test_oracle_adjustment_schema_and_nonexecution_gates_are_frozen() -> None:
    report = json.loads(ORACLE_REPORT.read_text(encoding="utf-8"))
    schema = pq.read_schema(ORACLE_ADJUSTMENTS)

    assert schema.names == EXPECTED_ADJUSTMENT_COLUMNS
    assert report["adjustment_schema"] == EXPECTED_ADJUSTMENT_COLUMNS
    assert report["adjustment_schema_matches_historical_contract"] is True
    assert report["side_rows"] == 570
    assert report["game_rows"] == 285
    assert report["unique_game_ids"] == 285
    assert report["starter_identities_unmatched"] == 0
    assert report["outcome_columns_selected_from_games"] == 0
    assert report["market_data_reads"] == 0
    assert report["holdout_executions"] == 0


def test_primary_artifact_sha_is_frozen() -> None:
    assert _sha256(ORACLE_ADJUSTMENTS) == PRIMARY_SHA256


def test_historical_2018_2024_artifacts_are_byte_unchanged() -> None:
    assert _sha256(HISTORICAL_STARTERS) == HISTORICAL_STARTER_SHA256
    assert _sha256(HISTORICAL_ORACLE) == HISTORICAL_ORACLE_SHA256
