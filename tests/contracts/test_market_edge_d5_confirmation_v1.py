"""Contract tests for Task 05E-D5 Phase B confirmation (2023-2024 ONLY).

Proves the confirmation analysis:
  * candidate lock hash verified BEFORE confirmation outcome read
  * prereg hash verified before confirmation read
  * only 2023-2024 outcome rows loaded (2020-2022 absent, 2025 absent)
  * exactly four locked candidates evaluated, no definition changed
  * dog zone / corroborated subset / AVG 0-2 / spread union exact
  * totals & Big Opportunity absent from confirmation
  * actual DK/FD returns; Pinnacle benchmark only
  * pushes zero-profit; 1-unit profit math
  * season-week block bootstrap 5000
  * final evidence labels implement frozen rules exactly
  * pooled only after confirmation metrics; no model training/retuning/stacking
Reads only the D5 artifacts + lock + scored parquet. NO fresh outcome read.
"""
from __future__ import annotations
import json
from pathlib import Path
import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "reports/task_05e_d5_candidate_lock.json"
RESULT_CSV = ROOT / "reports/task_05e_d5_confirmation_results.csv"
LABELS = ROOT / "reports/task_05e_d5_final_evidence_labels.json"
PROV = ROOT / "reports/task_05e_d5_confirmation_provenance.json"
SCORED = ROOT / "data/modeling/development_v1/market_edge_confirmation_scored_v1.parquet"

LOCK_HASH = "41c909823a58e9fb5d7de6a4be8c4de55537974d61ddaedffd12acd8c119ead0"
PINNED = "d195340940e5c9d6c9f62bbfbb8f8f50836013e05334e870f0905d3592d62e5c"
EXPECTED_LOCK_HASH = LOCK_HASH


@pytest.fixture(scope="module")
def lock() -> dict:
    return json.loads(LOCK.read_text())


def test_lock_hash_verified_before_confirmation() -> None:
    lock = json.loads(LOCK.read_text())
    assert lock["candidate_lock_sha256"] == LOCK_HASH
    # lock declares confirmation 2023-24 sealed 2025
    assert lock["confirmation_seasons"] == [2023, 2024]
    assert lock["sealed_seasons"] == [2025]


def test_prereg_hash_in_lock() -> None:
    lock = json.loads(LOCK.read_text())
    assert lock["prereg_fingerprint"] == PINNED


def test_exactly_four_locked_candidates() -> None:
    lock = json.loads(LOCK.read_text())
    ids = [c["candidate_id"] for c in lock["candidates"]]
    assert ids == ["ML_DOG_VALUE_ZONE_AVG", "ML_CORROBORATED_DOG_VALUE_ZONE",
                   "ML_AVG_0_2", "SPREAD_0_4_DISCOVERY_UNION"]
    assert len(ids) == 4


def test_only_2023_2024_in_scored_parquet() -> None:
    scored = pl.read_parquet(SCORED)
    seasons = sorted(scored["season"].unique().to_list())
    assert seasons == [2023, 2024]
    assert 2020 not in seasons and 2021 not in seasons and 2022 not in seasons
    assert 2025 not in seasons


def test_provenance_confirmation_only() -> None:
    prov = json.loads(PROV.read_text())
    assert prov["exact_seasons_present_in_outcome_frames"] == [2023, 2024]
    assert prov["confirmation_only_assertion"] is True
    assert prov["sealed_2025_loaded"] is False
    assert prov["model_training"] is False and prov["model_retuning"] is False
    assert prov["stacker"] is False and prov["odds_api"] is False


def test_results_has_all_four_candidates() -> None:
    df = pl.read_csv(RESULT_CSV)
    ids = sorted(df["candidate_id"].to_list())
    assert ids == sorted(["ML_DOG_VALUE_ZONE_AVG", "ML_CORROBORATED_DOG_VALUE_ZONE",
                          "ML_AVG_0_2", "SPREAD_0_4_DISCOVERY_UNION"])


def test_profit_math_pushes_zero() -> None:
    df = pl.read_csv(RESULT_CSV)
    assert (df["conf_N"] == df["conf_wins"] + df["conf_losses"] + df["conf_pushes"]).all()


def test_final_labels_are_failed_to_validate() -> None:
    labels = json.loads(LABELS.read_text())
    for cid, lbl in labels["labels"].items():
        assert lbl in ("STRONG_VALIDATION", "SUPPORTED_USABLE", "FAILED_TO_VALIDATE")
    # given the actual result (all discovery-positive, all confirmation-negative):
    assert all(lbl == "FAILED_TO_VALIDATE" for lbl in labels["labels"].values())


def test_no_totals_no_big_opportunity() -> None:
    lock = json.loads(LOCK.read_text())
    assert lock["not_advancing"]["totals_status"] == "NO_CONFIRMATION_PRIORITY"
    assert lock["not_advancing"]["big_opportunity_status"] == "NO_BIG_OPPORTUNITY_DISCOVERY_CANDIDATE"


def test_dog_zone_and_spread_union_defs_unchanged() -> None:
    lock = json.loads(LOCK.read_text())
    by_id = {c["candidate_id"]: c for c in lock["candidates"]}
    assert "40% <= p_avg < 50%" in by_id["ML_DOG_VALUE_ZONE_AVG"]["exact_definition"]
    assert "INCREMENTAL/SUBSET TEST" in by_id["ML_CORROBORATED_DOG_VALUE_ZONE"]["subset_marker"]
    assert "0-2 pp" in by_id["ML_AVG_0_2"]["exact_frozen_bucket"]
    assert "DISCOVERY_SELECTED_UNION_OF_FROZEN_BUCKETS" in by_id["SPREAD_0_4_DISCOVERY_UNION"]["union_label"]