"""Task05D Ridge manifest security and accepted-artifact regressions."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.backtest.totals_bake_off import SAFE_MANIFEST_ENV_KEYS, safe_manifest_environment

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run_task05d_ridge_bake_off.py"


def _runner_module():
    spec = importlib.util.spec_from_file_location("task05d_ridge_runner", RUNNER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_environment_is_explicit_allowlist_and_serialization_safe() -> None:
    environment = {
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "TERMINAL_CONTAINER_CPU": "2",
        "TERMINAL_CONTAINER_MEMORY": "4G",
        "TASK05D_SECRET_SENTINEL": "DO_NOT_SERIALIZE",
        "GITHUB_TOKEN": "DO_NOT_SERIALIZE_EITHER",
        "HOME": "/must-not-serialize",
    }
    snapshot = safe_manifest_environment(environment)
    runner_snapshot = _runner_module().ridge_manifest_environment(environment)
    serialized = json.dumps({"thread_settings": runner_snapshot}, sort_keys=True)
    assert snapshot == runner_snapshot
    assert set(snapshot).issubset(SAFE_MANIFEST_ENV_KEYS)
    assert "TASK05D_SECRET_SENTINEL" not in serialized
    assert "DO_NOT_SERIALIZE" not in serialized
    assert "GITHUB_TOKEN" not in serialized
    assert "HOME" not in serialized


def test_committed_r4_artifacts_preserve_accepted_selection_and_oos_universe() -> None:
    metrics = json.loads((ROOT / "reports/task05d/task05d_ridge_candidate_metrics.json").read_text())
    r4 = next(item for item in metrics if item["candidate_id"] == "R4")
    assert r4["parameters"] == {"alpha": 100}
    assert r4["mae"] == 10.687260596441305
    assert r4["oob_rmse"] == 13.5453379336442
    assert r4["pearson"] == pytest.approx(0.2328146797177685)
    assert r4["spearman"] == pytest.approx(0.22426096614933824)
    predictions = pl.read_parquet(ROOT / "reports/task05d/task05d_ridge_predictions.parquet")
    assert predictions.filter(pl.col("candidate_id") == "R4").height == 1864
    assert set(predictions["season"].unique().to_list()) <= set(range(2018, 2025))
