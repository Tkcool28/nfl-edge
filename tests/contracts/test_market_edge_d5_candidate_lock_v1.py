"""Contract tests for the Task 05E-D5 discovery candidate lock (Phase A).

Proves the lock was created BEFORE any confirmation outcome is opened:
  * exactly 4 confirmation candidates, no fifth
  * candidate definitions match the frozen D5 spec exactly
  * dog-value zone unchanged; corroborated dog marked subset/incremental
  * AVG 0-2 unchanged
  * spread union = exactly four frozen bins, labeled discovery-selected union
  * 4+ absent; totals absent; Big Opportunity absent
  * 2025 sealed; confirmation 2023-24 declared
  * prereg fingerprint correct
  * lock hash deterministic & pinned in the file
Outcome-blind: reads only the lock + prereg config; touches no outcomes.
"""
from __future__ import annotations
import hashlib, importlib.util, json
from pathlib import Path
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "market_edge_validation_v1.yaml"
SCRIPT = ROOT / "scripts" / "freeze_market_edge_prereg.py"
LOCK = ROOT / "reports" / "task_05e_d5_candidate_lock.json"

PINNED = "d195340940e5c9d6c9f62bbfbb8f8f50836013e05334e870f0905d3592d62e5c"
EXPECTED_LOCK_HASH = "41c909823a58e9fb5d7de6a4be8c4de55537974d61ddaedffd12acd8c119ead0"
EXPECTED_IDS = ["ML_DOG_VALUE_ZONE_AVG", "ML_CORROBORATED_DOG_VALUE_ZONE",
                "ML_AVG_0_2", "SPREAD_0_4_DISCOVERY_UNION"]


@pytest.fixture(scope="module")
def lock() -> dict:
    return json.loads(LOCK.read_text())


@pytest.fixture(scope="module")
def cfg() -> dict:
    return yaml.safe_load(CONFIG.read_text())


def test_exact_four_candidates_no_fifth(lock) -> None:
    ids = [c["candidate_id"] for c in lock["candidates"]]
    assert ids == EXPECTED_IDS
    assert len(ids) == 4


def test_prereg_fingerprint_correct(lock, cfg) -> None:
    assert lock["prereg_fingerprint"] == PINNED
    assert cfg["fingerprint"]["sha256_self"] == PINNED
    # recompute prereg fingerprint deterministically
    spec = importlib.util.spec_from_file_location("freeze_mep", SCRIPT)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    d = hashlib.sha256(m.canonicalize(CONFIG.read_bytes().decode("utf-8"))).hexdigest()
    assert d == PINNED


def test_confirmation_and_sealed_declared(lock) -> None:
    assert lock["confirmation_seasons"] == [2023, 2024]
    assert lock["sealed_seasons"] == [2025]


def test_lock_hash_pinned_and_deterministic(lock) -> None:
    # recompute the canonical lock hash (neutralizing the self field)
    key = "candidate_lock_sha256"
    text = LOCK.read_text()
    canon = "\n".join(l for l in text.splitlines() if not l.strip().startswith('"%s"' % key))
    d = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    assert d == EXPECTED_LOCK_HASH
    assert lock[key] == EXPECTED_LOCK_HASH


def test_dog_value_zone_unchanged(lock) -> None:
    c = next(x for x in lock["candidates"] if x["candidate_id"] == "ML_DOG_VALUE_ZONE_AVG")
    assert "40% <= p_avg < 50%" in c["exact_definition"]
    assert "+111" in c["exact_definition"] and "+200" in c["exact_definition"]
    assert "positive edge vs Pinnacle" in c["exact_definition"]
    assert c["model"] == "AVG"
    assert c["discovery"]["N"] == 149


def test_corroborated_dog_marked_subset(lock) -> None:
    c = next(x for x in lock["candidates"] if x["candidate_id"] == "ML_CORROBORATED_DOG_VALUE_ZONE")
    assert c["model"] == "CORROBORATED"
    assert "INCREMENTAL/SUBSET TEST relative to ML_DOG_VALUE_ZONE_AVG" in c["subset_marker"]
    assert "NOT statistically independent" in c["subset_marker"]
    assert c["discovery"]["N"] == 85


def test_avg_0_2_unchanged(lock) -> None:
    c = next(x for x in lock["candidates"] if x["candidate_id"] == "ML_AVG_0_2")
    assert "0 <= AVG disagreement < 2" in c["exact_definition"]
    assert "0-2 pp" in c["exact_frozen_bucket"]
    assert c["discovery"]["N"] == 136


def test_spread_union_four_bins_labeled(lock) -> None:
    c = next(x for x in lock["candidates"] if x["candidate_id"] == "SPREAD_0_4_DISCOVERY_UNION")
    assert "DISCOVERY_SELECTED_UNION_OF_FROZEN_BUCKETS" in c["union_label"]
    assert "[0,1)" in c["exact_frozen_bucket"]
    assert "[1,2)" in c["exact_frozen_bucket"]
    assert "[2,3)" in c["exact_frozen_bucket"]
    assert "[3,4)" in c["exact_frozen_bucket"]
    # 4+ must be absent from the union definition
    assert "4+" not in c["exact_frozen_bucket"].replace("4+ excluded", "")
    assert "NOT an original standalone preregistered bucket" in c["union_note"]
    assert c["discovery"]["N"] == 467


def test_totals_and_big_opportunity_absent() -> None:
    lock = json.loads(LOCK.read_text())
    ids = [c["candidate_id"] for c in lock["candidates"]]
    assert not any("TOTAL" in i or "R4" in i for i in ids)      # totals absent
    assert not any("BIG_OPP" in i.upper() for i in ids)         # big opp absent
    assert lock["not_advancing"]["totals_status"] == "NO_CONFIRMATION_PRIORITY"
    assert lock["not_advancing"]["big_opportunity_status"] == "NO_BIG_OPPORTUNITY_DISCOVERY_CANDIDATE"


def test_spread_4plus_excluded(lock) -> None:
    assert "SPREAD_4+" in lock["not_advancing"]["excluded"]


def test_locked_before_confirmation(lock) -> None:
    for c in lock["candidates"]:
        assert c["locked_before_confirmation"] is True
    # confirmation not yet opened: lock does not contain any confirmation result keys
    blob = LOCK.read_text().lower()
    assert "confirmation_profit" not in blob
    assert "confirmation_roi" not in blob