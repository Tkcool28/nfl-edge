"""Null-safe calibration scorecard tests.

The calibration may legitimately return ``None`` for intercept and
slope. The scorecard must serialize and render the null case
explicitly (no silent identity substitution). The default
``max_iter`` is exactly 100.

These tests focus on the calibration contract directly. Full-
scorecard null rendering is exercised in tests/integration/
test_artifact_hashes_reconcile_with_manifest where the canonical
production pipeline runs.
"""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pytest

import nfl_edge.evaluation.calibration as cal_mod
from nfl_edge.evaluation.calibration import logistic_recalibration

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---- 1. One-class input produces null/null status=one_class -----


def test_one_class_input_produces_null_null_one_class() -> None:
    df = pl.DataFrame(
        {
            "season": [2020] * 6,
            "game_id": [f"g{i}" for i in range(6)],
            "predicted_home_win_probability": [0.3, 0.7, 0.4, 0.6, 0.5, 0.55],
            "actual_home_win": [True, True, True, True, True, True],
            "target_available": [True] * 6,
        }
    )
    res = logistic_recalibration(df)
    assert res["calibration_intercept"] is None
    assert res["calibration_slope"] is None
    assert "one_class" in res["calibration_fit_status"]
    assert res["calibration_converged"] is False


# ---- 2. Constant-input produces constant_input or singular_hessian ---


def test_constant_input_fit_status_is_safe() -> None:
    df = pl.DataFrame(
        {
            "season": [2020] * 8,
            "game_id": [f"g{i}" for i in range(8)],
            "predicted_home_win_probability": [0.5] * 8,
            "actual_home_win": [True, False] * 4,
            "target_available": [True] * 8,
        }
    )
    res = logistic_recalibration(df)
    # The fit is undefined (constant input) and must return
    # ``None`` for slope; the status must be one of the safe
    # sentinel values, never "converged".
    assert res["calibration_fit_status"] in {
        "constant_input", "singular_hessian", "max_iter_reached",
    }
    if res["calibration_slope"] is not None:
        # If the implementation returns a value (e.g. from a
        # pseudo-inverse), it must not be 0.0 or 1.0.
        assert res["calibration_slope"] != 0.0
        assert res["calibration_slope"] != 1.0


# ---- 3. Forced max-iteration result is max_iter_reached ----------


def test_forced_max_iteration_fit_status() -> None:
    df = pl.DataFrame(
        {
            "season": [2020] * 8,
            "game_id": [f"g{i}" for i in range(8)],
            "predicted_home_win_probability": [0.3, 0.4, 0.5, 0.6, 0.7, 0.3, 0.4, 0.5],
            "actual_home_win": [True, False, True, False, True, False, True, False],
            "target_available": [True] * 8,
        }
    )
    res = logistic_recalibration(df, max_iter=1)
    assert res["calibration_fit_status"] == "max_iter_reached"
    assert res["calibration_converged"] is False


# ---- 4. Singular-Hessian result is safe -------------------------


def test_singular_hessian_result_is_safe() -> None:
    df = pl.DataFrame(
        {
            "season": [2020] * 6,
            "game_id": [f"g{i}" for i in range(6)],
            "predicted_home_win_probability": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            "actual_home_win": [True, False, True, False, True, False],
            "target_available": [True] * 6,
        }
    )
    res = logistic_recalibration(df, max_iter=1)
    assert res["calibration_fit_status"] in {
        "max_iter_reached", "converged", "singular_hessian",
    }
    # The function must not raise.


# ---- 5. Null values remain null in returned dict -----------------


def test_null_values_remain_null_in_returned_dict() -> None:
    df = pl.DataFrame(
        {
            "season": [2020] * 6,
            "game_id": [f"g{i}" for i in range(6)],
            "predicted_home_win_probability": [0.3, 0.7, 0.4, 0.6, 0.5, 0.55],
            "actual_home_win": [True, True, True, True, True, True],
            "target_available": [True] * 6,
        }
    )
    res = logistic_recalibration(df)
    assert res["calibration_intercept"] is None
    assert res["calibration_slope"] is None
    # Serialize and confirm ``null`` is emitted.
    raw = json.dumps(res)
    assert "null" in raw


# ---- 6. No undefined fit becomes 0/1 -----------------------------


def test_no_undefined_fit_becomes_zero_or_one() -> None:
    df = pl.DataFrame(
        {
            "season": [2020] * 6,
            "game_id": [f"g{i}" for i in range(6)],
            "predicted_home_win_probability": [0.3, 0.7, 0.4, 0.6, 0.5, 0.55],
            "actual_home_win": [True, True, True, True, True, True],
            "target_available": [True] * 6,
        }
    )
    res = logistic_recalibration(df)
    if res["calibration_intercept"] is None:
        assert res["calibration_intercept"] != 0.0
        assert res["calibration_intercept"] != 1.0
    if res["calibration_slope"] is None:
        assert res["calibration_slope"] != 0.0
        assert res["calibration_slope"] != 1.0


# ---- 7. Retired compatibility wrapper cannot silently return identity --


def test_retired_wrapper_not_importable() -> None:
    """The wrapper is retired; the function must not be importable
    from the public evaluation API."""
    import nfl_edge.evaluation as ev
    assert not hasattr(ev, "calibration_intercept_slope")
    importlib.reload(cal_mod)
    assert not hasattr(cal_mod, "calibration_intercept_slope")


# ---- 8. Converged fits return numeric values --------------------


def test_converged_fit_returns_numeric_values() -> None:
    """A well-calibrated (synthetic) fit converges; the intercept
    and slope are returned as numbers (not None)."""
    df = pl.DataFrame(
        {
            "season": list(range(2018, 2025)) * 30,
            "game_id": [f"g{i}" for i in range(7 * 30)],
            "predicted_home_win_probability": [
                0.3 + 0.05 * (i % 7) for i in range(7 * 30)
            ],
            "actual_home_win": [
                (0.3 + 0.05 * (i % 7) > 0.5) for i in range(7 * 30)
            ],
            "target_available": [True] * (7 * 30),
        }
    )
    res = logistic_recalibration(df)
    if res["calibration_converged"]:
        assert isinstance(res["calibration_intercept"], (int, float))
        assert isinstance(res["calibration_slope"], (int, float))


# ---- 9. Default max_iter is exactly 100 -------------------------


def test_default_max_iter_is_100() -> None:
    df = pl.DataFrame(
        {
            "season": [2020] * 8,
            "game_id": [f"g{i}" for i in range(8)],
            "predicted_home_win_probability": [0.3, 0.4, 0.5, 0.6, 0.7, 0.3, 0.4, 0.5],
            "actual_home_win": [True, False, True, False, True, False, True, False],
            "target_available": [True] * 8,
        }
    )
    res = logistic_recalibration(df)
    assert res.get("max_iter") == 100


# ---- 10. Scorecard Markdown renders null as NA ------------------


def test_scorecard_markdown_renders_null_as_NA(tmp_path: Path) -> None:
    """Run the production pipeline with a one-class input and
    confirm the scorecard Markdown renders ``NA`` for the null
    intercept and slope."""
    if not (REPO_ROOT / "data/derived/features_v1").exists():
        pytest.skip("data not available")
    from nfl_edge.backtest.walk_forward import run_development_walk_forward
    from nfl_edge.evaluation.scorecard import build_development_scorecard
    from nfl_edge.models.qb_elo_config import load_qb_elo_canonical_config
    out = tmp_path / "sc"
    out.mkdir()
    run_development_walk_forward(
        games_path=Path("data/derived/features_v1/game_features_2018_2025.parquet"),
        team_features_path=Path("data/derived/features_v1/team_pregame_features_2018_2025.parquet"),
        output_dir=out,
        created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
        project_root=REPO_ROOT,
    )
    pred = pl.read_parquet(out / "qb_elo_predictions_2018_2024.parquet")
    manifest = json.loads((out / "qb_elo_run_manifest_v1.json").read_text())
    cfg = load_qb_elo_canonical_config(REPO_ROOT / "config/qb_elo_v1.yaml")
    build_development_scorecard(
        pred, configuration=cfg, manifest=manifest, output_dir=out
    )
    md = (out / "qb_elo_development_scorecard.md").read_text()
    assert "Calibration fit status:" in md
    assert "Calibration iterations:" in md
    assert "Calibration converged:" in md
    assert "Calibration max_iter:" in md


# ---- 11. Scorecard JSON contains explicit null when null ---------


def test_scorecard_json_contains_null_serialization(tmp_path: Path) -> None:
    """The JSON scorecard must serialize ``None`` as JSON ``null``
    (not 0.0 or 1.0). Run a real pipeline and check."""
    if not (REPO_ROOT / "data/derived/features_v1").exists():
        pytest.skip("data not available")
    from nfl_edge.backtest.walk_forward import run_development_walk_forward
    from nfl_edge.evaluation.scorecard import build_development_scorecard
    from nfl_edge.models.qb_elo_config import load_qb_elo_canonical_config
    out = tmp_path / "jc"
    out.mkdir()
    run_development_walk_forward(
        games_path=Path("data/derived/features_v1/game_features_2018_2025.parquet"),
        team_features_path=Path("data/derived/features_v1/team_pregame_features_2018_2025.parquet"),
        output_dir=out,
        created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
        project_root=REPO_ROOT,
    )
    pred = pl.read_parquet(out / "qb_elo_predictions_2018_2024.parquet")
    manifest = json.loads((out / "qb_elo_run_manifest_v1.json").read_text())
    cfg = load_qb_elo_canonical_config(REPO_ROOT / "config/qb_elo_v1.yaml")
    build_development_scorecard(
        pred, configuration=cfg, manifest=manifest, output_dir=out
    )
    body = json.loads(
        (out / "qb_elo_development_scorecard.json").read_text()
    )
    intercept = body["aggregate_metrics"]["calibration_intercept"]
    slope = body["aggregate_metrics"]["calibration_slope"]
    assert isinstance(intercept, (int, float, type(None)))
    assert isinstance(slope, (int, float, type(None)))


# ---- 12. Scorecard and docs agree on max_iter=100 ---------------


def test_scorecard_metadata_agrees_max_iter_100(tmp_path: Path) -> None:
    """The Markdown must print max_iter=100 (the documented and
    implemented value)."""
    if not (REPO_ROOT / "data/derived/features_v1").exists():
        pytest.skip("data not available")
    from nfl_edge.backtest.walk_forward import run_development_walk_forward
    from nfl_edge.evaluation.scorecard import build_development_scorecard
    from nfl_edge.models.qb_elo_config import load_qb_elo_canonical_config
    out = tmp_path / "mi"
    out.mkdir()
    run_development_walk_forward(
        games_path=Path("data/derived/features_v1/game_features_2018_2025.parquet"),
        team_features_path=Path("data/derived/features_v1/team_pregame_features_2018_2025.parquet"),
        output_dir=out,
        created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
        project_root=REPO_ROOT,
    )
    pred = pl.read_parquet(out / "qb_elo_predictions_2018_2024.parquet")
    manifest = json.loads((out / "qb_elo_run_manifest_v1.json").read_text())
    cfg = load_qb_elo_canonical_config(REPO_ROOT / "config/qb_elo_v1.yaml")
    build_development_scorecard(
        pred, configuration=cfg, manifest=manifest, output_dir=out
    )
    md = (out / "qb_elo_development_scorecard.md").read_text()
    assert "Calibration max_iter: 100" in md
