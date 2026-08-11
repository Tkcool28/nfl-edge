"""Focused tests for Task04C scoring/provenance remediation.

Proves the normal evaluation entry point (``enforce_task04c_gates`` run by the
report builder) actually invokes the oracle coverage gate, that paired
alignment fails closed on universe mismatch / duplicate ids / 2025 rows, that
an incomplete oracle adjustment artifact fails, and that the committed report
carries the correct tie-excluded population and provenance fields.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import polars as pl
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = REPO_ROOT / "data/derived/qb_elo_oracle_comparison_v1"
ORACLE_PARQUET = (
    REPO_ROOT
    / "data/derived/oracle_qb_entering_state_v2"
    / "oracle_qb_pregame_adjustments_by_game_2018_2024_v2.parquet"
)

_spec = importlib.util.spec_from_file_location(
    "task04c_report_builder",
    REPO_ROOT / "scripts" / "task04c_build_oracle_comparison_report.py",
)
assert _spec is not None and _spec.loader is not None
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)

_ONE_GID = "2018_01_ATL_PHI"


def _full_frames() -> tuple[pl.DataFrame, pl.DataFrame]:
    base = pl.read_parquet(BASE / "qb_elo_baseline_predictions_2018_2024.parquet")
    ora = pl.read_parquet(BASE / "qb_elo_oracle_predictions_2018_2024.parquet")
    return base, ora


# ---------------------------------------------------------------------------
# Coverage gate executes through the normal evaluation entry
# ---------------------------------------------------------------------------
def test_assert_coverage_defined_and_callable():
    oracle = builder.OracleQBAdjustments(ORACLE_PARQUET)
    assert hasattr(oracle, "assert_coverage")
    oracle.assert_coverage(sorted(set(_full_frames()[1]["game_id"].to_list())))


def test_normal_evaluator_invokes_coverage_gate(monkeypatch):
    base, ora = _full_frames()
    calls: list[str] = []

    from nfl_edge.backtest.task04c_paired_evaluation import (
        OracleQBAdjustments as RealOracle,
    )

    class Recorder(RealOracle):
        def assert_coverage(self, canonical_game_ids, *, where="coverage"):
            calls.append(where)
            return super().assert_coverage(canonical_game_ids, where=where)

    monkeypatch.setattr(builder, "OracleQBAdjustments", Recorder)
    builder.enforce_task04c_gates(base, ora, oracle_parquet=ORACLE_PARQUET)
    assert calls, "coverage gate was not invoked through the normal entry"
    assert calls == ["task04c.comparison.coverage"]


def test_enforce_gates_passes_on_aligned_universe():
    base, ora = _full_frames()
    adj = builder.enforce_task04c_gates(base, ora, oracle_parquet=ORACLE_PARQUET)
    assert adj.n_rows == 1942


# ---------------------------------------------------------------------------
# Failure modes through the normal entry
# ---------------------------------------------------------------------------
def test_incomplete_oracle_coverage_fails(tmp_path):
    base, ora = _full_frames()
    complete = pl.read_parquet(ORACLE_PARQUET)
    subset = complete.filter(pl.col("game_id") != _ONE_GID)
    incomplete = tmp_path / "incomplete_oracle.parquet"
    subset.write_parquet(incomplete)
    with pytest.raises(Exception) as exc:
        builder.enforce_task04c_gates(base, ora, oracle_parquet=incomplete)
    assert _ONE_GID in str(exc.value)


def test_paired_universe_mismatch_fails():
    base, ora = _full_frames()
    shorter = ora.filter(pl.col("game_id") != _ONE_GID)
    with pytest.raises(AssertionError):
        builder.enforce_task04c_gates(base, shorter, oracle_parquet=ORACLE_PARQUET)


def test_duplicate_game_id_fails():
    base, ora = _full_frames()
    dup = pl.concat([ora, ora.filter(pl.col("game_id") == _ONE_GID)])
    with pytest.raises(AssertionError):
        builder.enforce_task04c_gates(base, dup, oracle_parquet=ORACLE_PARQUET)


def test_2025_row_fails():
    base, ora = _full_frames()
    bad = ora.with_columns(pl.lit(2025).alias("season"))
    with pytest.raises(AssertionError):
        builder.enforce_task04c_gates(base, bad, oracle_parquet=ORACLE_PARQUET)


# ---------------------------------------------------------------------------
# Committed report population / provenance / primary metrics
# ---------------------------------------------------------------------------
def test_report_population_and_provenance():
    rep = json.loads((BASE / "qb_elo_oracle_comparison_report_v1.json").read_text())
    assert rep["coverage_games"] == 1942
    assert rep["tied_games"] == 7
    assert rep["binary_scored_games"] == 1935
    assert rep["binary_scoring_policy"] == "EXCLUDE_TIED_GAMES"
    assert len(rep["tie_game_ids"]) == 7
    assert rep["games_2025_target"] == 0
    assert rep["official_verdict"] == "RESERVED_FOR_MASTER_REVIEW"
    for key in (
        "repository_state_id", "evaluator_source_path", "evaluator_source_sha256",
        "git_commit_sha", "qb_elo_config_path", "qb_elo_config_sha256",
        "oracle_input_path", "oracle_input_sha256",
        "starter_ledger_path", "starter_ledger_sha256",
        "baseline_predictions_path", "baseline_predictions_sha256",
        "oracle_predictions_path", "oracle_predictions_sha256",
        "baseline_transitions_path", "baseline_transitions_sha256",
        "oracle_transitions_path", "oracle_transitions_sha256",
    ):
        assert rep["provenance"][key], f"missing provenance field {key}"


def test_binary_scored_count_and_primary_metrics():
    oracle = pl.read_parquet(BASE / "qb_elo_oracle_predictions_2018_2024.parquet")
    binary = oracle.filter((pl.col("season") <= 2024) & (pl.col("target_margin") != 0.0))
    assert binary.height == 1935
    rep = json.loads((BASE / "qb_elo_oracle_comparison_report_v1.json").read_text())
    ps = rep["primary_scorecard"]
    assert abs(ps["baseline_brier"] - 0.223958291799) < 1e-6
    assert abs(ps["baseline_logloss"] - 0.639657650691) < 1e-6
    assert abs(ps["baseline_accuracy"] - 0.635142118863) < 1e-6
    assert abs(ps["oracle_brier"] - 0.221488519882) < 1e-6
    assert abs(ps["oracle_logloss"] - 0.634516898141) < 1e-6
    assert abs(ps["oracle_accuracy"] - 0.648578811370) < 1e-6
    assert abs(ps["brier_delta"] - (-0.002469771917)) < 1e-6
    assert abs(ps["logloss_delta"] - (-0.005140752550)) < 1e-6
    assert abs(ps["accuracy_delta"] - 0.013436692506) < 1e-6
    assert abs(ps["bss"] - 0.011027820839) < 1e-6
    assert ps["oracle_brier"] < ps["baseline_brier"]  # oracle-better direction