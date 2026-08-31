from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.holdout.football_2025 import HoldoutBlock
from nfl_edge.holdout.oracle_qb_game_resolver_2025 import (
    EXPECTED_ARTIFACT_SHA256,
    FrozenOracleQBGameResolver2025,
    OracleQBResolver2025Error,
)


def _load_gate(repo_root: Path):
    path = repo_root / "scripts/task05g_2025_holdout_one_shot_v1.py"
    spec = importlib.util.spec_from_file_location("task05g_gate_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_oracle_resolver_is_only_a_frozen_adjustment_lookup(tmp_path: Path, monkeypatch):
    path = tmp_path / "oracle.parquet"
    rows = [
        {
            "game_id": f"g{idx:03d}",
            "home_qb_adjustment_elo": float(idx % 7),
            "away_qb_adjustment_elo": -float(idx % 5),
            "historical_model_usage": "ORACLE_STARTER_IDENTITY_ONLY",
            "starter_evidence_class": "POSTGAME_ACTUAL_STARTER",
        }
        for idx in range(285)
    ]
    pl.DataFrame(rows).write_parquet(path)
    import nfl_edge.holdout.oracle_qb_game_resolver_2025 as resolver_module

    monkeypatch.setattr(resolver_module, "_sha256", lambda _: EXPECTED_ARTIFACT_SHA256)
    resolver = FrozenOracleQBGameResolver2025(path, repo_root=tmp_path)
    assert resolver("g001") == (1.0, -1.0)
    resolver.assert_coverage(["g000", "g284"], where="synthetic")
    identity = resolver.manifest_identity()
    assert identity["mode"] == "ORACLE"
    assert identity["historical_model_usage"] == "ORACLE_STARTER_IDENTITY_ONLY"
    assert identity["starter_evidence_class"] == "POSTGAME_ACTUAL_STARTER"
    assert identity["oracle_artifact_sha256"] == EXPECTED_ARTIFACT_SHA256
    with pytest.raises(OracleQBResolver2025Error, match="missing Oracle QB"):
        resolver.assert_coverage(["missing"], where="synthetic")


def test_gate_source_orders_development_bootstrap_before_spend_before_runtime():
    repo_root = Path(__file__).resolve().parents[2]
    source = (repo_root / "scripts/task05g_2025_holdout_one_shot_v1.py").read_text(
        encoding="utf-8"
    )
    execute = source[source.index("def execute(") : source.index("def main()")]
    bootstrap = execute.index("prepare_development_state(historical_board_path=history)")
    spend = execute.index("marker = _consume_spend_marker()")
    open_2025 = execute.index("final_state = run_authorized_holdout(")
    assert bootstrap < spend < open_2025


def test_spend_marker_is_exclusive_and_irreversible(tmp_path: Path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    gate = _load_gate(repo_root)
    monkeypatch.setattr(gate, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(gate, "SPEND_MARKER", tmp_path / "HOLDOUT_SPENT.json")
    monkeypatch.setattr(gate, "_git_head", lambda: "synthetic-head")

    first = gate._consume_spend_marker()
    assert gate.SPEND_MARKER.exists()
    payload = json.loads(gate.SPEND_MARKER.read_text(encoding="utf-8"))
    assert payload["marker_semantics"] == "IRREVERSIBLE_BEFORE_FIRST_2025_INPUT_READ"
    assert first["git_head"] == "synthetic-head"

    with pytest.raises(gate.HoldoutGateError, match="HOLDOUT_ALREADY_SPENT"):
        gate._consume_spend_marker()
    assert gate.SPEND_MARKER.exists()


def test_observation_cursor_consumes_exactly_current_block(tmp_path: Path):
    from nfl_edge.holdout.executor_runtime_2025 import _ObservationCursor

    path = tmp_path / "observations.jsonl"
    rows = [
        {
            "block_id": "2025_REG_W01",
            "game_id": "g1",
            "team_updates": {},
        },
        {
            "block_id": "2025_REG_W02",
            "game_id": "g2",
            "team_updates": {},
        },
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    cursor = _ObservationCursor(path)
    block1 = HoldoutBlock(
        "2025_REG_W01", 2025, "REG", 1,
        datetime(2025, 9, 1, tzinfo=timezone.utc), ("g1",),
    )
    block2 = HoldoutBlock(
        "2025_REG_W02", 2025, "REG", 2,
        datetime(2025, 9, 8, tzinfo=timezone.utc), ("g2",),
    )
    assert [obs.game_id for obs in cursor.take(block1)] == ["g1"]
    assert [obs.game_id for obs in cursor.take(block2)] == ["g2"]
    cursor.assert_exhausted()


def test_runtime_market_hashes_match_certified_freeze_evidence():
    """Runtime market identities must remain equal to certified metadata only."""
    repo_root = Path(__file__).resolve().parents[2]
    certification = json.loads(
        (repo_root / "data/manifests/2025_all_model_input_certification_v1.json").read_text(
            encoding="utf-8"
        )
    )
    promotion = json.loads(
        (
            repo_root
            / "reports/pre2025/pre2025_successor_executor_final_freeze_v2.json"
        ).read_text(encoding="utf-8")
    )
    import nfl_edge.holdout.executor_runtime_2025 as runtime

    expected = {
        "canonical_book_market_sha256": "c8499262388fca13d6dfd0a7da2f891c1989ed601c75b6987067013ce8092a62",
        "canonical_games_sha256": "e9d4b9a5302a72d32f767a87b52f86e32044118bfb27900fb4c4217d6edd74ef",
    }
    certified = certification["market_evaluator_certification"]
    assert {
        "canonical_book_market_sha256": certified["canonical_book_market_sha256"],
        "canonical_games_sha256": certified["canonical_games_sha256"],
    } == expected
    assert {
        "canonical_book_market_sha256": promotion["certification_evidence"][
            "canonical_market_book_sha256"
        ],
        "canonical_games_sha256": promotion["certification_evidence"][
            "canonical_market_games_sha256"
        ],
    } == expected
    assert runtime.MARKET_CANONICAL_SHA256 == expected["canonical_book_market_sha256"]
    assert runtime.MARKET_GAMES_SHA256 == expected["canonical_games_sha256"]


def test_runtime_import_is_side_effect_free_for_holdout_outputs(tmp_path: Path):
    # Importing the runtime exposes composition only; it cannot create a spend
    # marker or a weekly holdout artifact by itself.
    import nfl_edge.holdout.executor_runtime_2025 as runtime

    assert callable(runtime.prepare_development_state)
    assert callable(runtime.run_authorized_holdout)
    assert not (tmp_path / "HOLDOUT_SPENT.json").exists()


def test_runtime_task05f_board_identity_matches_final_accepted_freeze():
    repo_root = Path(__file__).resolve().parents[2]
    promotion = json.loads(
        (
            repo_root
            / "reports/pre2025/pre2025_successor_executor_final_freeze_v4.json"
        ).read_text(encoding="utf-8")
    )
    import nfl_edge.holdout.executor_runtime_2025 as runtime

    identity = promotion["task05f_historical_board_identity"]
    expected = "58302290e4dc98d6db13e8e8a46c148e8c58533b2c9930370262982be06ce2a8"
    assert identity["accepted_sha256"] == expected
    assert identity["correction_type"] == "IDENTITY_RECONCILIATION_ONLY"
    assert identity["holdout_spent_marker_created"] is False
    assert identity["holdout_data_bytes_read"] == 0
    assert runtime.HISTORICAL_BOARD_SHA256 == expected
