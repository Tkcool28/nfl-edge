"""Sealed-safe tests for the authorized 2025 market-plan-only command."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts/task05g_2025_market_plan_dry_run_v1.py"
SPEC = importlib.util.spec_from_file_location("market_plan_dry_run_2025", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def _schedule_with_outcomes(path: Path) -> None:
    pl.DataFrame(
        {
            "game_id": ["2025_01_A_B", "2025_01_C_D", "2024_18_X_Y"],
            "season": [2025, 2025, 2024],
            "gameday": ["2025-09-07", "2025-09-07", "2025-01-05"],
            "gametime": ["13:00", "13:20", "13:00"],
            "home_score": [99, 98, 21],
            "away_score": [97, 96, 17],
            "result": ["SEALED_A", "SEALED_B", "EXPOSED"],
        }
    ).write_parquet(path)


def test_wrong_authorization_fails_before_schedule_path_access(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(mod, "_run_prefreeze_audit", lambda: None)
    monkeypatch.setenv(mod.AUTHORIZATION_ENV, "INTENTIONALLY_WRONG")
    missing = tmp_path / "does-not-exist.parquet"
    with pytest.raises(mod.MarketPlanDryRunError, match="authorization mismatch"):
        mod.materialize_plan_only(schedule_path=missing, report_path=tmp_path / "report.json")


def test_schedule_reader_exposes_only_frozen_kickoff_columns(tmp_path: Path):
    schedule_path = tmp_path / "schedule.parquet"
    _schedule_with_outcomes(schedule_path)
    scoped = mod._read_schedule_only(schedule_path)
    assert scoped.columns == list(mod.SCHEDULE_COLUMNS)
    assert scoped.height == 2
    assert scoped["season"].unique().to_list() == [2025]
    assert "home_score" not in scoped.columns
    assert "away_score" not in scoped.columns
    assert "result" not in scoped.columns


def test_plan_only_materialization_spends_zero_credits(monkeypatch, tmp_path: Path):
    schedule_path = tmp_path / "schedule.parquet"
    _schedule_with_outcomes(schedule_path)
    monkeypatch.setattr(mod, "_run_prefreeze_audit", lambda: None)
    monkeypatch.setattr(mod, "_verify_authorization_before_schedule_read", lambda: None)

    plan_path = tmp_path / "market/plan.parquet"
    manifest_path = tmp_path / "market/plan.json"
    report_path = tmp_path / "market/report.json"
    report = mod.materialize_plan_only(
        schedule_path=schedule_path,
        plan_path=plan_path,
        manifest_path=manifest_path,
        report_path=report_path,
    )

    assert report["status"] == "AUTHORIZED_2025_MARKET_PLAN_FROZEN__NO_PAID_CALLS"
    assert report["request_plan_rows"] == 1
    assert report["target_games"] == 2
    assert report["planned_credit_cap"] == 30
    assert report["credits_spent"] == 0
    assert report["network_calls"] == 0
    assert report["credential_reads"] == 0
    assert report["odds_api_key_read"] is False
    assert report["paid_acquisition_executed"] is False
    assert report["score_or_outcome_columns_read"] == []
    assert plan_path.exists()
    assert manifest_path.exists()
    assert report_path.exists()
