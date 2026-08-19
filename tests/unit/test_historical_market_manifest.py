"""Frozen manifest: exact bookmaker/market allowlists and roles (§F, §M)."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from nfl_edge.market_data.manifest import (
    ALLOWED_BOOKS,
    BOOK_ROLES,
    BOOKS_ACTIONABLE,
    BOOKS_BENCHMARK,
    BOOKS_OTHER,
    BOOKS_SECONDARY,
    EXPECTED_PLAN_SHA256,
    MARKETS,
    SCHEDULE_SOURCE_PATH,
    build_schedule_source_metadata,
    manifest_dict,
    schema_sha256_of,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_BOOKS = [
    "draftkings", "fanduel",           # actionable retail
    "pinnacle",                        # sharp benchmark
    "betonlineag",                     # secondary reference
    "williamhill_us", "betmgm", "betrivers", "bovada", "lowvig", "betus",  # consensus
]


def test_allowed_books_is_exact_allowlist():
    assert list(ALLOWED_BOOKS) == EXPECTED_BOOKS
    assert len(ALLOWED_BOOKS) == 10
    assert len(set(ALLOWED_BOOKS)) == 10


def test_markets_is_exact_allowlist():
    assert list(MARKETS) == ["h2h", "spreads", "totals"]


def test_books_cover_all_roles_exactly():
    # Every allowed book must have one (and only one) role.
    assert set(ALLOWED_BOOKS) == set(BOOK_ROLES)
    assert list(BOOKS_ACTIONABLE) == ["draftkings", "fanduel"]
    assert list(BOOKS_BENCHMARK) == ["pinnacle"]
    assert list(BOOKS_SECONDARY) == ["betonlineag"]
    assert set(BOOKS_OTHER) == {"williamhill_us", "betmgm", "betrivers", "bovada", "lowvig", "betus"}


def test_role_classification():
    assert BOOK_ROLES["pinnacle"] == "PRIMARY_SHARP_BENCHMARK"
    assert BOOK_ROLES["draftkings"] == "ACTIONABLE_RETAIL"
    assert BOOK_ROLES["fanduel"] == "ACTIONABLE_RETAIL"
    assert BOOK_ROLES["betonlineag"] == "SECONDARY_INDEPENDENT_REFERENCE"
    assert BOOK_ROLES["lowvig"] == "OTHER_CONSENSUS_INPUT"


def test_manifest_dict_is_machine_readable_and_frozen():
    m = manifest_dict()
    assert m["version"] == "historical-market-acquisition-manifest-v1"
    assert m["sport"] == "americanfootball_nfl"
    assert m["clustering"]["expected_total_clusters"] == 575
    assert m["credit_contract"]["expected_cost_per_successful_request"] == 30
    assert m["credit_contract"]["initial_planned_credit_cap"] == 17250
    assert list(ALLOWED_BOOKS) == m["books"]["allowed_books"]
    assert list(MARKETS) == m["markets"]
    assert m["secret"]["environment_variable"] == "ODDS_API_KEY"
    assert m["request_plan"]["expected_sha256"] == EXPECTED_PLAN_SHA256
    assert m["request_plan"]["expected_rows"] == 575


def test_generated_manifest_artifacts_contain_no_secret_material():
    # Regression guard: the emitted manifest + plan artifacts must never leak
    # an API key (neither an unredacted param value nor the env name form).
    check_files = [
        REPO_ROOT / "data/manifests/historical_market_acquisition_v1.json",
        REPO_ROOT / "data/manifests/historical_market_request_plan_v1.json",
        REPO_ROOT / "data/manifests/historical_market_request_plan_v1.parquet",
    ]
    for path in check_files:
        assert path.exists(), path
        blob = path.read_bytes()
        assert b"apiKey=" not in blob, path
        assert b"ODDS_API_KEY=" not in blob, path
        assert b"FAKEKEY_" not in blob, path  # a known key would be masked


# --- schema fingerprint (final pre-commit remediation) ----------------------

def test_schema_fingerprint_is_deterministic_and_preserves_file_hash():
    m1 = build_schedule_source_metadata(SCHEDULE_SOURCE_PATH)
    m2 = build_schedule_source_metadata(SCHEDULE_SOURCE_PATH)
    # Preserve the existing full-file SHA-256.
    assert (
        m1["source_file_sha256"]
        == "9fdfa5f3401f0ee834c986b0e61518b01c8e52ac823057f52c76abe6b29c83eb"
    )
    # Deterministic schema fingerprint + representation.
    assert m1["source_schema_sha256"] == m2["source_schema_sha256"]
    assert m1["source_schema"] == m2["source_schema"]
    assert m1["source_schema_canonical"] == m2["source_schema_canonical"]
    # Schema contains only name/dtype (no row values or volatile metadata).
    for col in m1["source_schema"]:
        assert set(col) == {"name", "dtype"}


def test_schema_fingerprint_changes_on_column_order(tmp_path):
    a = pl.DataFrame({"b": [1], "a": ["x"], "c": [1.5]})          # b,a,c
    reordered = a.select(["a", "b", "c"])                         # a,b,c
    p1 = tmp_path / "order1.parquet"
    p2 = tmp_path / "order2.parquet"
    a.write_parquet(p1)
    reordered.write_parquet(p2)
    assert schema_sha256_of(p1) != schema_sha256_of(p2)


def test_schema_fingerprint_changes_on_dtype(tmp_path):
    x = pl.DataFrame({"n": [1, 2]})                               # Int64
    y = x.with_columns(pl.col("n").cast(pl.Int8))                 # Int8
    p1 = tmp_path / "i64.parquet"
    p2 = tmp_path / "i8.parquet"
    x.write_parquet(p1)
    y.write_parquet(p2)
    assert schema_sha256_of(p1) != schema_sha256_of(p2)
