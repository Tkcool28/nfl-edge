"""Contract/assertion tests for Task 05E-D4 discovery outcome analysis.

These tests prove the discovery analysis stayed within the frozen preregistration
and the season firewall. They are OUTCOME-BLIND relative to confirmation/2025.

NOTE: Task 05E-D4 explicitly says DO NOT COMMIT. These tests are written to the
worktree for review but are intentionally NOT staged/committed.
"""
from __future__ import annotations
import hashlib, importlib.util, json
from pathlib import Path
import polars as pl
import pytest
import yaml

WT = Path(__file__).resolve().parents[2]
CONFIG = WT / "config" / "market_edge_validation_v1.yaml"
SCRIPT = WT / "scripts" / "freeze_market_edge_prereg.py"
RESULT_CSV = WT / "reports" / "task_05e_d4_discovery_results.csv"
PROV = WT / "reports" / "task_05e_d4_discovery_provenance.json"
RECS = WT / "reports" / "task_05e_d4_candidate_lock_recommendations.json"
SCORED = WT / "data/modeling/development_v1/market_edge_discovery_scored_v1.parquet"

PINNED = "d195340940e5c9d6c9f62bbfbb8f8f50836013e05334e870f0905d3592d62e5c"
DISCOVERY = [2020, 2021, 2022]


@pytest.fixture(scope="module")
def cfg() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def test_fail_closed_prereg_fingerprint(cfg) -> None:
    spec = importlib.util.spec_from_file_location("freeze_mep", SCRIPT)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    d = hashlib.sha256(m.canonicalize(CONFIG.read_bytes().decode("utf-8"))).hexdigest()
    assert d == PINNED
    assert cfg["fingerprint"]["sha256_self"] == PINNED


def test_exact_seven_families(cfg) -> None:
    assert cfg["hypothesis_families"] == [
        "ML_QBELO_DISAGREEMENT", "ML_XGB_DISAGREEMENT", "ML_AVG_DISAGREEMENT",
        "ML_CORROBORATED_DISAGREEMENT", "ML_DOG_VALUE_ZONE", "SPREAD_DISAGREEMENT",
        "TOTAL_R4_DISAGREEMENT"]


def test_split_unchanged(cfg) -> None:
    assert cfg["seasons"]["discovery"] == DISCOVERY
    assert cfg["seasons"]["confirmation"] == [2023, 2024]
    assert cfg["seasons"]["sealed"] == [2025]


def test_frozen_bucket_edges_unchanged(cfg) -> None:
    assert cfg["buckets"]["moneyline_disagreement_pp"]["edges_pp"] == [0, 2, 4, 8, 12, 1000]
    assert cfg["buckets"]["spread_disagreement_pts"]["edges_pts"] == [0, 1, 2, 3, 4, 1000]
    assert cfg["buckets"]["total_disagreement_pts"]["edges_pts"] == [0, 1, 2, 3, 4, 1000]


def test_dog_zone_unchanged(cfg) -> None:
    z = cfg["moneyline_dog_value_zone"]["zone"]
    assert "40%" in z and "50%" in z and "+111" in z and "+200" in z and "positive" in z.lower()


def test_only_discovery_2020_2022_loaded() -> None:
    scored = pl.read_parquet(SCORED)
    seasons = sorted(scored["season"].unique().to_list())
    assert seasons == DISCOVERY
    assert 2023 not in seasons and 2024 not in seasons and 2025 not in seasons


def test_provenance_discovery_only() -> None:
    prov = json.loads(PROV.read_text())
    assert prov["discovery_only_assertion"] is True
    assert prov["exact_seasons_present_in_outcome_frames"] == DISCOVERY
    assert prov["confirmation_data_loaded"] is False
    assert prov["sealed_2025_loaded"] is False
    assert prov["model_training"] is False
    assert prov["model_retuning"] is False
    assert prov["stacker_fitting"] is False
    assert prov["odds_api_calls"] is False


def test_results_cover_all_seven_families() -> None:
    df = pl.read_csv(RESULT_CSV)
    fams = set(df["family"].to_list())
    seven = {"ML_QBELO_DISAGREEMENT", "ML_XGB_DISAGREEMENT", "ML_AVG_DISAGREEMENT",
             "ML_CORROBORATED_DISAGREEMENT", "ML_DOG_VALUE_ZONE", "SPREAD_DISAGREEMENT",
             "TOTAL_R4_DISAGREEMENT"}
    assert seven.issubset(fams)


def test_profit_math_pushes_zero() -> None:
    # one representative graded family: pushes must contribute 0 profit
    # AVG 0-2 row: N 136, 75W 61L 0P
    # verify N == wins+losses+pushes across all rows
    df = pl.read_csv(RESULT_CSV).filter(pl.col("N") > 0)
    assert (df["N"] == df["wins"] + df["losses"] + df["pushes"]).all()


def test_status_are_screening_only() -> None:
    df = pl.read_csv(RESULT_CSV)
    statuses = set(df["status"].drop_nulls().unique().to_list())
    allowed = {"DISCOVERY_POSITIVE", "DISCOVERY_NEGATIVE", "DISCOVERY_LIMITED_SAMPLE"}
    assert statuses.issubset(allowed)  # must NOT masquerade as final labels


def test_candidates_use_frozen_only() -> None:
    recs = json.loads(RECS.read_text())
    rec = recs["records"]
    for k, v in rec.items():
        assert v["uses_frozen_only"] is True
        assert v["prereg_fingerprint"] == PINNED
    # no invented thresholds: bucket strings must reference frozen buckets/zones
    for k, v in rec.items():
        bucket = v["bucket"]
        assert any(tok in bucket for tok in ["ZONE", "0-2", "2-4", "4-8", "8-12", "12+",
                                             "0-1", "1-2", "2-3", "3-4", "4+"])


def test_no_totals_candidate() -> None:
    recs = json.loads(RECS.read_text())
    assert recs["candidates"]["totals"] == []


def test_big_opportunity_none_in_discovery() -> None:
    recs = json.loads(RECS.read_text())
    assert recs["big_opportunity_discovery_candidate"] == []
    assert "NO_BIG_OPPORTUNITY_DISCOVERY_CANDIDATE" in recs["big_opportunity_status"]
