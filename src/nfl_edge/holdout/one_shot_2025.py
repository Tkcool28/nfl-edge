"""Deterministic freeze-before-reveal engine for the sealed 2025 walkthrough.

This module is intentionally I/O-light and outcome-agnostic. The authorized
entrypoint owns sealed-file access; model/evaluator/product adapters are passed
in as callbacks. The engine enforces the chronology contract shared by every
adapter: produce and persist the entire pre-result block first, then and only
then reveal the block and advance state.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .football_2025 import HoldoutBlock

SCHEMA_VERSION = "task05g_2025_one_shot_engine_v1"
WEEK_REPORT_SCHEMA = "task05g_2025_week_user_view_v1"
PROFILES: tuple[tuple[str, float], ...] = (
    ("Cautious", 0.0050),
    ("Conservative", 0.0075),
    ("Normal", 0.0100),
    ("Aggressive", 0.0125),
    ("Ultra", 0.0150),
)
PROHIBITED_PRE_RESULT_FIELDS = {
    "home_score",
    "away_score",
    "target_margin",
    "target_home_win",
    "target_tie",
    "target_total_points",
    "settlement",
    "realized_profit",
    "result",
}


class OneShotContractError(RuntimeError):
    """Raised when freeze/reveal chronology or deterministic state is violated."""


HoldoutOneShotError = OneShotContractError


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def atomic_json(path: Path, value: Any) -> str:
    payload = canonical_json_bytes(value)
    atomic_write(path, payload)
    return hashlib.sha256(payload).hexdigest()


def assert_pre_result_surface(value: Any, *, path: str = "") -> None:
    """Recursively reject any populated result/outcome field before reveal."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_s = str(key)
            if key_s in PROHIBITED_PRE_RESULT_FIELDS and child is not None:
                raise OneShotContractError(
                    f"pre-result outcome field populated at {path}{key_s}"
                )
            assert_pre_result_surface(child, path=path + key_s + ".")
    elif isinstance(value, (list, tuple)):
        for idx, child in enumerate(value):
            assert_pre_result_surface(child, path=f"{path}{idx}.")


@dataclass(frozen=True)
class BankrollState:
    values: Mapping[str, float] = field(
        default_factory=lambda: {name: 1000.0 for name, _ in PROFILES}
    )
    peaks: Mapping[str, float] = field(
        default_factory=lambda: {name: 1000.0 for name, _ in PROFILES}
    )
    max_drawdowns: Mapping[str, float] = field(
        default_factory=lambda: {name: 0.0 for name, _ in PROFILES}
    )


@dataclass(frozen=True)
class ReplayState:
    """State committed only after a block has been revealed and graded."""

    completed_blocks: tuple[str, ...] = ()
    model_state: Mapping[str, Any] = field(default_factory=dict)
    selector_state: Mapping[str, Any] = field(default_factory=dict)
    bankroll: BankrollState = field(default_factory=BankrollState)
    record: Mapping[str, int] = field(
        default_factory=lambda: {"wins": 0, "losses": 0, "pushes": 0}
    )
    weighted_units: float = 0.0
    losing_streak: int = 0
    longest_losing_streak: int = 0

    def digest(self) -> str:
        return sha256_json(asdict(self))


@dataclass(frozen=True)
class PreResultBundle:
    block_id: str
    entering_state_sha256: str
    market_input_sha256: str
    model_output: Mapping[str, Any]
    candidate_rows: Sequence[Mapping[str, Any]]
    headline_card: Mapping[str, Any]
    user_view: Mapping[str, Any]


PredictCallback = Callable[[HoldoutBlock, ReplayState], Mapping[str, Any]]
CandidatesCallback = Callable[[HoldoutBlock, ReplayState, Mapping[str, Any]], Sequence[Mapping[str, Any]]]
ProductCallback = Callable[[HoldoutBlock, ReplayState, Sequence[Mapping[str, Any]]], tuple[Mapping[str, Any], Mapping[str, Any]]]
RevealCallback = Callable[[HoldoutBlock, ReplayState, PreResultBundle], Mapping[str, Any]]
AdvanceCallback = Callable[[HoldoutBlock, ReplayState, PreResultBundle, Mapping[str, Any]], ReplayState]
MarketDigestCallback = Callable[[HoldoutBlock], str]


def _validate_blocks(blocks: Sequence[HoldoutBlock]) -> None:
    if not blocks:
        raise OneShotContractError("one-shot replay requires at least one block")
    seen: set[str] = set()
    last: tuple[int, int, int] | None = None
    for block in blocks:
        if block.block_id in seen:
            raise OneShotContractError(f"duplicate block id: {block.block_id}")
        if last is not None and block.order_key <= last:
            raise OneShotContractError(
                f"blocks not strictly chronological: {block.order_key} <= {last}"
            )
        seen.add(block.block_id)
        last = block.order_key


def _validate_pre_result(bundle: PreResultBundle, state: ReplayState, block: HoldoutBlock) -> None:
    if bundle.block_id != block.block_id:
        raise OneShotContractError("pre-result block identity drift")
    if bundle.entering_state_sha256 != state.digest():
        raise OneShotContractError("pre-result entering state hash drift")
    if block.block_id in state.completed_blocks:
        raise OneShotContractError("attempt to predict an already-completed block")
    for surface in (
        bundle.model_output,
        bundle.candidate_rows,
        bundle.headline_card,
        bundle.user_view,
    ):
        assert_pre_result_surface(surface)


def freeze_pre_result(output_root: Path, block: HoldoutBlock, bundle: PreResultBundle) -> dict[str, Any]:
    """Persist immutable block surfaces and return their content identities."""
    block_dir = output_root / "weeks" / block.block_id
    if block_dir.exists():
        raise OneShotContractError(f"pre-result block already exists: {block.block_id}")
    block_dir.mkdir(parents=True, exist_ok=False)

    model_sha = atomic_json(block_dir / "model_output.json", bundle.model_output)
    candidate_sha = atomic_json(block_dir / "candidate_table.json", list(bundle.candidate_rows))
    headline_sha = atomic_json(block_dir / "headline_card.json", bundle.headline_card)
    user_sha = atomic_json(block_dir / "pre_result_user_view.json", bundle.user_view)
    manifest = {
        "schema_version": WEEK_REPORT_SCHEMA,
        "block_id": block.block_id,
        "season": block.season,
        "season_type": block.season_type,
        "week": block.week,
        "game_ids": list(block.game_ids),
        "entering_state_sha256": bundle.entering_state_sha256,
        "market_input_sha256": bundle.market_input_sha256,
        "model_output_sha256": model_sha,
        "candidate_table_sha256": candidate_sha,
        "headline_card_sha256": headline_sha,
        "pre_result_user_view_sha256": user_sha,
        "outcomes_revealed": False,
    }
    manifest_sha = atomic_json(block_dir / "pre_result_manifest.json", manifest)
    manifest["pre_result_artifact_sha256"] = manifest_sha
    return manifest


def commit_revealed_block(
    output_root: Path,
    block: HoldoutBlock,
    pre_manifest: Mapping[str, Any],
    result: Mapping[str, Any],
    state: ReplayState,
    reveal_order: int,
) -> dict[str, Any]:
    block_dir = output_root / "weeks" / block.block_id
    result_sha = atomic_json(block_dir / "week_result.json", result)
    state_payload = asdict(state)
    state_sha = atomic_json(block_dir / "post_block_state.json", state_payload)
    committed = {
        **dict(pre_manifest),
        "outcomes_revealed": True,
        "outcome_reveal_order": int(reveal_order),
        "result_sha256": result_sha,
        "post_block_state_sha256": state_sha,
    }
    atomic_json(block_dir / "completed_block_manifest.json", committed)
    return committed


def run_one_shot(
    *,
    blocks: Sequence[HoldoutBlock],
    output_root: Path,
    initial_state: ReplayState,
    market_digest: MarketDigestCallback,
    predict: PredictCallback,
    candidates: CandidatesCallback,
    product: ProductCallback,
    reveal: RevealCallback,
    advance: AdvanceCallback,
) -> tuple[ReplayState, list[dict[str, Any]]]:
    """Run all blocks in one process while preserving weekly pre-result freezes."""
    _validate_blocks(blocks)
    output_root.mkdir(parents=True, exist_ok=True)
    if any((output_root / "weeks" / b.block_id).exists() for b in blocks):
        raise OneShotContractError("one-shot output already contains a target block")

    state = initial_state
    proof: list[dict[str, Any]] = []
    for reveal_order, block in enumerate(blocks, start=1):
        if state.completed_blocks and state.completed_blocks[-1] == block.block_id:
            raise OneShotContractError("current block already in entering state")
        entering_sha = state.digest()
        model = dict(predict(block, state))
        rows = [dict(row) for row in candidates(block, state, model)]
        headline, user_view = product(block, state, rows)
        bundle = PreResultBundle(
            block_id=block.block_id,
            entering_state_sha256=entering_sha,
            market_input_sha256=str(market_digest(block)),
            model_output=model,
            candidate_rows=rows,
            headline_card=dict(headline),
            user_view=dict(user_view),
        )
        _validate_pre_result(bundle, state, block)
        pre_manifest = freeze_pre_result(output_root, block, bundle)

        revealed = dict(reveal(block, state, bundle))
        next_state = advance(block, state, bundle, revealed)
        if next_state.completed_blocks != state.completed_blocks + (block.block_id,):
            raise OneShotContractError(
                "state advancement must append exactly the just-revealed block"
            )
        completed = commit_revealed_block(
            output_root, block, pre_manifest, revealed, next_state, reveal_order
        )
        proof.append(completed)
        state = next_state

    atomic_json(
        output_root / "weekly_state_hash_manifest.json",
        {"schema_version": SCHEMA_VERSION, "blocks": proof},
    )
    return state, proof
