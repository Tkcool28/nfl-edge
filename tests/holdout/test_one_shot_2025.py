from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nfl_edge.holdout.football_2025 import HoldoutBlock
from nfl_edge.holdout.one_shot_2025 import (
    BankrollState,
    OneShotContractError,
    ReplayState,
    run_one_shot,
    sha256_file,
)


def _blocks() -> list[HoldoutBlock]:
    return [
        HoldoutBlock("2025_REG_W01", 2025, "REG", 1, datetime(2025, 9, 1, tzinfo=timezone.utc), ("g1",)),
        HoldoutBlock("2025_REG_W02", 2025, "REG", 2, datetime(2025, 9, 8, tzinfo=timezone.utc), ("g2",)),
    ]


def _callbacks(events: list[str], poison: bool = False):
    outcomes = {"2025_REG_W01": "WIN", "2025_REG_W02": "LOSS"}

    def market(block):
        return f"market-{block.block_id}"

    def predict(block, state):
        events.append(f"predict:{block.block_id}:{len(state.completed_blocks)}")
        return {"game_ids": list(block.game_ids), "probability": 0.6}

    def candidates(block, state, model):
        events.append(f"candidate:{block.block_id}")
        return [{"candidate_id": block.block_id, "supported": True, "probability": model["probability"]}]

    def product(block, state, rows):
        events.append(f"product:{block.block_id}")
        row = dict(rows[0])
        if poison:
            row["settlement"] = "WIN"
        return ({"hit_rate": row, "balanced": None, "value": None}, {"week": block.week, "headline": row})

    def reveal(block, state, bundle):
        events.append(f"reveal:{block.block_id}")
        return {"settlement": outcomes[block.block_id], "units": 1.0}

    def advance(block, state, bundle, result):
        events.append(f"advance:{block.block_id}")
        wins = int(state.record["wins"]) + int(result["settlement"] == "WIN")
        losses = int(state.record["losses"]) + int(result["settlement"] == "LOSS")
        weighted = state.weighted_units + (1.0 if result["settlement"] == "WIN" else -1.0)
        streak = 0 if result["settlement"] == "WIN" else state.losing_streak + 1
        return ReplayState(
            completed_blocks=state.completed_blocks + (block.block_id,),
            model_state={"prior": block.block_id},
            selector_state={},
            bankroll=state.bankroll,
            record={"wins": wins, "losses": losses, "pushes": 0},
            weighted_units=weighted,
            losing_streak=streak,
            longest_losing_streak=max(state.longest_losing_streak, streak),
        )

    return market, predict, candidates, product, reveal, advance


def test_entire_block_is_frozen_before_reveal_and_state_advances_after(tmp_path: Path):
    events: list[str] = []
    state, proof = run_one_shot(
        blocks=_blocks(),
        output_root=tmp_path,
        initial_state=ReplayState(),
        **dict(zip(("market_digest", "predict", "candidates", "product", "reveal", "advance"), _callbacks(events))),
    )
    assert state.completed_blocks == ("2025_REG_W01", "2025_REG_W02")
    assert events == [
        "predict:2025_REG_W01:0", "candidate:2025_REG_W01", "product:2025_REG_W01", "reveal:2025_REG_W01", "advance:2025_REG_W01",
        "predict:2025_REG_W02:1", "candidate:2025_REG_W02", "product:2025_REG_W02", "reveal:2025_REG_W02", "advance:2025_REG_W02",
    ]
    assert [row["outcome_reveal_order"] for row in proof] == [1, 2]
    assert all(row["outcomes_revealed"] for row in proof)
    assert (tmp_path / "weeks/2025_REG_W01/pre_result_manifest.json").exists()
    assert (tmp_path / "weeks/2025_REG_W01/week_result.json").exists()


def test_pre_result_rejects_same_block_outcome_poison(tmp_path: Path):
    events: list[str] = []
    with pytest.raises(OneShotContractError, match="pre-result outcome field"):
        run_one_shot(
            blocks=_blocks()[:1], output_root=tmp_path, initial_state=ReplayState(),
            **dict(zip(("market_digest", "predict", "candidates", "product", "reveal", "advance"), _callbacks(events, poison=True))),
        )
    assert not any(event.startswith("reveal:") for event in events)


def test_future_or_nonchronological_blocks_rejected_before_prediction(tmp_path: Path):
    blocks = list(reversed(_blocks()))
    events: list[str] = []
    with pytest.raises(OneShotContractError, match="not strictly chronological"):
        run_one_shot(
            blocks=blocks, output_root=tmp_path, initial_state=ReplayState(),
            **dict(zip(("market_digest", "predict", "candidates", "product", "reveal", "advance"), _callbacks(events))),
        )
    assert events == []


def test_deterministic_weekly_artifacts(tmp_path: Path):
    hashes = []
    for idx in range(2):
        root = tmp_path / str(idx)
        events: list[str] = []
        run_one_shot(
            blocks=_blocks(), output_root=root, initial_state=ReplayState(),
            **dict(zip(("market_digest", "predict", "candidates", "product", "reveal", "advance"), _callbacks(events))),
        )
        hashes.append([
            sha256_file(root / "weeks" / block.block_id / "pre_result_manifest.json")
            for block in _blocks()
        ])
    assert hashes[0] == hashes[1]


def test_engine_refuses_overwrite_one_spend_style_outputs(tmp_path: Path):
    events: list[str] = []
    kwargs = dict(zip(("market_digest", "predict", "candidates", "product", "reveal", "advance"), _callbacks(events)))
    run_one_shot(blocks=_blocks()[:1], output_root=tmp_path, initial_state=ReplayState(), **kwargs)
    with pytest.raises(OneShotContractError, match="already contains"):
        run_one_shot(blocks=_blocks()[:1], output_root=tmp_path, initial_state=ReplayState(), **kwargs)


def test_five_frozen_bankroll_profiles_start_at_reference_1000():
    state = ReplayState()
    assert set(state.bankroll.values) == {"Cautious", "Conservative", "Normal", "Aggressive", "Ultra"}
    assert all(value == 1000.0 for value in state.bankroll.values.values())
    assert isinstance(state.bankroll, BankrollState)


def test_2025_totals_postgame_input_is_frozen_but_holdout_unexecuted():
    """Task05H superseded the old missing-PBP blocker without opening the holdout."""
    repo_root = Path(__file__).resolve().parents[2]
    certification = json.loads(
        (repo_root / "data/manifests/2025_all_model_input_certification_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert certification["verdict"] == "ALL_2025_MODEL_INPUTS_FROZEN_AND_CERTIFIED"
    assert certification["remaining_missing_2025_input_surfaces"] == []
    assert certification["holdout_predictions_executed"] == 0
    assert certification["2025_HOLDOUT_HAS_NOT_BEEN_EXECUTED"] is True
    totals = certification["new_2025_totals_inputs"]
    assert totals["pbp_game_coverage"] == "285/285"
    assert totals["game_observation_coverage"] == "285/285"
