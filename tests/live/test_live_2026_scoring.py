from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
import yaml

from nfl_edge.live.qb_inputs import adjustment_from_passing_epa
from nfl_edge.live.scorer_2026 import canonical_snapshot_bytes, score_week1
from nfl_edge.live.sleeper_qb import SleeperExpectedQBResolver, SleeperQBSource
from nfl_edge.live.state_2026 import bootstrap_entering_2026_state
from nfl_edge.live.week1_2026 import EXPECTED_TEAMS, load_week1_schedule

ROOT = Path(__file__).resolve().parents[2]
AS_OF = "2026-09-02T13:00:00Z"


def _synthetic_source(*, freshness: str = "FRESH") -> SleeperQBSource:
    rows = []
    crosswalk = []
    evidence = []
    for index, team in enumerate(sorted(EXPECTED_TEAMS), start=1):
        sleeper_id = f"s-{index:02d}"
        gsis_id = f"00-LIVE-{index:02d}"
        rows.append(
            {
                "snapshot_id": "ci-week1-live-qb-fixture-v1",
                "fetched_at_utc": "2026-09-02T12:00:00Z",
                "sleeper_player_id": sleeper_id,
                "gsis_id": gsis_id,
                "full_name": f"CI {team} Quarterback",
                "team": team,
                "active": True,
                "years_exp": 3,
                "injury_status": None,
                "depth_chart_position": "QB",
                "depth_chart_order": 1,
            }
        )
        crosswalk.append(
            {
                "snapshot_id": "ci-week1-live-qb-fixture-v1",
                "sleeper_player_id": sleeper_id,
                "gsis_id": gsis_id,
                "nflverse_player_id": gsis_id,
                "match_method": "exact_sleeper_id",
                "is_matched": True,
                "review_required": False,
                "conflict_reason": None,
            }
        )
        evidence.append(
            {
                "snapshot_id": "ci-week1-live-qb-fixture-v1",
                "sleeper_player_id": sleeper_id,
                "evidence_state": "DEPTH_CHART_EXPECTED_HEALTHY",
            }
        )
    return SleeperQBSource(
        audit_root=Path("data/source_audits/sleeper_qb_v1"),
        snapshot_id="ci-week1-live-qb-fixture-v1",
        observed_at_utc="2026-09-02T12:00:00Z",
        staleness_threshold_seconds=21600.0,
        freshness_state=freshness,
        age_seconds=3600.0 if freshness != "UNAVAILABLE" else None,
        source_warning_state=None,
        snapshots=pl.DataFrame(rows),
        crosswalk=pl.DataFrame(crosswalk),
        evidence=pl.DataFrame(evidence),
        changes=pl.DataFrame(),
    )


@pytest.fixture(scope="module")
def entering_state():
    return bootstrap_entering_2026_state(ROOT)


def test_live_qb_adjustment_formula_matches_frozen_pr70_contract():
    raw = yaml.safe_load((ROOT / "config/qb_elo_v1.yaml").read_text(encoding="utf-8"))
    value = 0.123
    expected = (value - float(raw["qb_adjustment_replacement_passing_epa"])) * float(
        raw["qb_adjustment_scale_elo_per_shrunk_epa"]
    )
    max_abs = float(raw["qb_adjustment_max_abs_elo"])
    expected = max(-max_abs, min(max_abs, expected))
    assert adjustment_from_passing_epa(value, config_path=ROOT / "config/qb_elo_v1.yaml") == expected


def test_entering_2026_state_contains_complete_settled_2025_history(entering_state):
    state = entering_state
    assert state.qb_state.current_season == 2025
    assert state.xgb_history.filter(pl.col("season") == 2025).height == 285
    assert state.expected_history.filter(pl.col("season") == 2025).height == 285
    assert state.totals_training.filter(pl.col("season") == 2025).height == 285
    assert state.completed_2025_blocks[0] == "2025_REG_W01"
    assert state.completed_2025_blocks[-1] == "2025_SB_W22"
    assert state.history_complete_through_utc.endswith("Z")


def test_real_week1_schedule_scores_all_four_models_deterministically(entering_state):
    resolver = SleeperExpectedQBResolver(_synthetic_source())
    first = score_week1(
        repository_root=ROOT,
        prediction_as_of_utc=AS_OF,
        resolver=resolver,
        entering_state=entering_state,
    )
    second = score_week1(
        repository_root=ROOT,
        prediction_as_of_utc=AS_OF,
        resolver=resolver,
        entering_state=entering_state,
    )
    assert canonical_snapshot_bytes(first) == canonical_snapshot_bytes(second)
    assert first["snapshot_sha256"] == second["snapshot_sha256"]
    assert len(first["games"]) == 16
    assert first["qb_resolution_counts"] == {"RESOLVED": 32}
    assert first["model_scoring_counts"] == {
        "expected_margin": {"AVAILABLE": 16},
        "qb_elo": {"AVAILABLE": 16},
        "ridge_totals_r4": {"AVAILABLE": 16},
        "xgboost_v2": {"AVAILABLE": 16},
    }
    for game in first["games"]:
        assert set(game["football_outputs"]) == {
            "qb_elo", "xgboost_v2", "expected_margin", "ridge_totals_r4"
        }
        assert game["football_outputs"]["qb_elo"]["prediction"] is not None
        assert game["football_outputs"]["xgboost_v2"]["prediction"] is not None
        assert game["football_outputs"]["expected_margin"]["prediction"] is not None
        assert game["football_outputs"]["ridge_totals_r4"]["prediction"] is not None
    assert first["guardrails"] == {
        "market_data_read": False,
        "odds_api_called": False,
        "methodology_changed": False,
        "tuning_performed": False,
        "current_outcomes_read": False,
        "xgboost_chronological_refit_preserved": True,
        "expected_margin_chronological_refit_preserved": True,
        "ridge_r4_chronological_refit_preserved": True,
    }


def test_stale_sleeper_suppresses_only_qb_dependent_models(entering_state):
    resolver = SleeperExpectedQBResolver(_synthetic_source(freshness="STALE"))
    snapshot = score_week1(
        repository_root=ROOT,
        prediction_as_of_utc=AS_OF,
        resolver=resolver,
        entering_state=entering_state,
    )
    assert snapshot["model_scoring_counts"]["expected_margin"] == {"AVAILABLE": 16}
    for model in ("qb_elo", "xgboost_v2", "ridge_totals_r4"):
        assert snapshot["model_scoring_counts"][model] == {"STALE_INPUT": 16}


def test_live_scoring_modules_do_not_import_market_or_network_acquisition_clients():
    paths = [
        ROOT / "src/nfl_edge/live/qb_inputs.py",
        ROOT / "src/nfl_edge/live/features_2026.py",
        ROOT / "src/nfl_edge/live/model_adapters.py",
        ROOT / "src/nfl_edge/live/state_2026.py",
        ROOT / "src/nfl_edge/live/totals_features.py",
        ROOT / "src/nfl_edge/live/scorer_2026.py",
        ROOT / "scripts/run_2026_live_football_scoring_v1.py",
    ]
    prohibited = (
        "from nfl_edge.market_data",
        "import nfl_edge.market_data",
        "theoddsapi",
        "the-odds-api",
        "requests.get(",
        "httpx.",
    )
    for path in paths:
        text = path.read_text(encoding="utf-8").lower()
        for token in prohibited:
            assert token.lower() not in text, (path, token)


def test_week1_schedule_fixture_remains_real_16_game_surface():
    schedule = load_week1_schedule(ROOT / "data/live/2026/week1_schedule_v1.json")
    assert schedule["season"] == 2026
    assert schedule["week"] == 1
    assert len(schedule["games"]) == 16
    assert {game["away_team"] for game in schedule["games"]} | {
        game["home_team"] for game in schedule["games"]
    } == EXPECTED_TEAMS
