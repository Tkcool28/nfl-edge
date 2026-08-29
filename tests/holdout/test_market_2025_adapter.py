"""Sealed-safe tests for the 2025 historical-market adapter.

All 2025 rows in this file are synthetic. No repository 2025 data file is
opened. Exposed 2024 synthetic rows prove the new clustering implementation
matches the already-frozen development algorithm.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import polars as pl
import pytest

from nfl_edge.holdout.market_2025 import (
    HOLDOUT_PRODUCT_BOOKS,
    HOLDOUT_RAW_BOOKS,
    HoldoutMarketContractError,
    build_clusters_for_seasons,
    build_holdout_market_plan,
    holdout_market_dry_run_report,
    run_holdout_market_acquisition,
    validate_holdout_plan_contract,
    write_holdout_market_plan,
)
from nfl_edge.market_data.kickoffs import build_clusters as build_frozen_dev_clusters
from nfl_edge.market_data.manifest import MARKETS


def _schedule(season: int) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": [f"{season}_01_A_B", f"{season}_01_C_D", f"{season}_01_E_F", f"{season}_02_G_H"],
            "season": [season, season, season, season],
            "gameday": ["2024-09-08", "2024-09-08", "2024-09-08", "2024-09-09"],
            "gametime": ["13:00", "13:25", "13:35", "20:15"],
        },
        schema={
            "game_id": pl.String,
            "season": pl.Int32,
            "gameday": pl.String,
            "gametime": pl.String,
        },
    )


def _single_cluster_2025() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": ["2025_01_A_B", "2025_01_C_D"],
            "season": [2025, 2025],
            "gameday": ["2025-09-07", "2025-09-07"],
            "gametime": ["13:00", "13:20"],
        },
        schema={
            "game_id": pl.String,
            "season": pl.Int32,
            "gameday": pl.String,
            "gametime": pl.String,
        },
    )


def test_explicit_season_clustering_matches_frozen_2024_algorithm():
    exposed = _schedule(2024)
    frozen = build_frozen_dev_clusters(exposed)
    holdout_impl = build_clusters_for_seasons(exposed, seasons=(2024,))
    assert holdout_impl == frozen


def test_holdout_plan_is_exact_2025_contract():
    plan = build_holdout_market_plan(_single_cluster_2025())
    validate_holdout_plan_contract(plan)
    assert plan.height == 1
    assert plan["season"].to_list() == [2025]
    assert plan["request_plan_id"].to_list() == ["md_2025_001"]
    assert HOLDOUT_RAW_BOOKS == (
        "draftkings",
        "fanduel",
        "pinnacle",
        "betmgm",
        "williamhill_us",
        "caesars",
        "betrivers",
        "pointsbetus",
        "wynnbet",
        "unibet_us",
    )
    assert HOLDOUT_PRODUCT_BOOKS == ("draftkings", "fanduel", "pinnacle")
    assert plan["requested_bookmaker_keys"].to_list() == [",".join(HOLDOUT_RAW_BOOKS)]
    assert plan["requested_markets"].to_list() == [",".join(MARKETS)]
    assert plan["expected_lead_min"].to_list() == [60.0]
    assert plan["expected_lead_max"].to_list() == [80.0]
    assert plan["expected_credits"].to_list() == [30]


def test_holdout_validator_rejects_non_2025_and_contract_mutation():
    plan = build_holdout_market_plan(_single_cluster_2025())
    with pytest.raises(HoldoutMarketContractError, match="seasons"):
        validate_holdout_plan_contract(plan.with_columns(pl.lit(2024).cast(pl.Int32).alias("season")))
    with pytest.raises(HoldoutMarketContractError, match="bookmaker"):
        validate_holdout_plan_contract(
            plan.with_columns(pl.lit("draftkings").alias("requested_bookmaker_keys"))
        )
    with pytest.raises(HoldoutMarketContractError, match="T-60"):
        validate_holdout_plan_contract(
            plan.with_columns(
                pl.col("requested_target_timestamp_utc")
                .str.to_datetime("%Y-%m-%dT%H:%M:%SZ", time_zone="UTC")
                .dt.offset_by("10m")
                .dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                .alias("requested_target_timestamp_utc")
            )
        )


def test_persisted_plan_digest_is_frozen_and_revalidated(tmp_path: Path):
    plan = build_holdout_market_plan(_single_cluster_2025())
    plan_path = tmp_path / "plan.parquet"
    manifest_path = tmp_path / "plan.json"
    digest = write_holdout_market_plan(
        plan,
        plan_path=plan_path,
        manifest_path=manifest_path,
        schedule_source_sha256="a" * 64,
    )
    assert digest == hashlib.sha256(plan_path.read_bytes()).hexdigest()
    payload = json.loads(manifest_path.read_text())
    assert payload["season"] == 2025
    assert payload["books"] == list(HOLDOUT_RAW_BOOKS)
    assert payload["plan_sha256"] == digest
    assert payload["planned_credit_cap"] == 30
    validate_holdout_plan_contract(
        plan, plan_path=plan_path, expected_sha256=digest
    )
    with pytest.raises(HoldoutMarketContractError, match="sha256"):
        validate_holdout_plan_contract(
            plan, plan_path=plan_path, expected_sha256="0" * 64
        )


def test_dry_run_report_never_needs_credentials():
    plan = build_holdout_market_plan(_single_cluster_2025())
    report = holdout_market_dry_run_report(plan)
    assert report["season"] == 2025
    assert report["target_games"] == 2
    assert report["books"] == list(HOLDOUT_RAW_BOOKS)
    assert report["product_books"] == list(HOLDOUT_PRODUCT_BOOKS)
    assert report["planned_credit_cap"] == 30
    assert report["network_calls"] == 0
    assert report["credential_reads"] == 0


class _FakeResponse:
    status_code = 200
    headers = {"x-requests-last": "30", "x-requests-used": "30", "x-requests-remaining": "999"}
    content = json.dumps(
        {
            "timestamp": "2025-09-07T16:55:00Z",
            "previous_timestamp": "2025-09-07T16:50:00Z",
            "next_timestamp": "2025-09-07T17:00:00Z",
            "data": [],
        }
    ).encode()


class _FakeSession:
    def __init__(self):
        self.calls = 0

    def get(self, url, timeout, allow_redirects):
        self.calls += 1
        query = parse_qs(urlsplit(url).query)
        assert query["apiKey"] == ["TEST_KEY"]
        assert query["bookmakers"] == [",".join(HOLDOUT_RAW_BOOKS)]
        assert query["markets"] == [",".join(MARKETS)]
        assert query["regions"] == ["us"]
        assert allow_redirects is False
        return _FakeResponse()


def test_authorized_live_wrapper_reuses_safe_runner_with_dynamic_cap(tmp_path: Path):
    plan = build_holdout_market_plan(_single_cluster_2025())
    plan_path = tmp_path / "plan.parquet"
    manifest_path = tmp_path / "plan.json"
    digest = write_holdout_market_plan(
        plan,
        plan_path=plan_path,
        manifest_path=manifest_path,
        schedule_source_sha256="b" * 64,
    )
    fake = _FakeSession()
    result = run_holdout_market_acquisition(
        plan,
        plan_path=plan_path,
        plan_sha256=digest,
        api_key="TEST_KEY",
        raw_root=tmp_path / "raw",
        ledger_path=tmp_path / "ledger.parquet",
        lock_dir=tmp_path / "lock",
        session=fake,
    )
    assert fake.calls == 1
    assert result["executed"] == 1
    assert result["credit_cap"] == 30
    assert result["holdout_season"] == 2025
    assert (tmp_path / "raw/2025/md_2025_001.json").exists()
