#!/usr/bin/env python3
"""Authorization gate for the sealed NFL EDGE 2025 one-shot acceptance run.

No plaintext authorization is stored in the repository.  The irreversible
runtime order is frozen here:

1. code/config-only preflight;
2. verify the out-of-band authorization hash;
3. bootstrap and verify development-only 2018-2024 state/evidence;
4. atomically create the one-spend marker;
5. and only then allow the runtime to read any 2025 input.

CI exercises preflight and synthetic/unit seams only.  It never supplies the
real authorization phrase and never executes the real holdout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config/task05g_2025_acceptance_v1.yaml"
FREEZE_PATH = ROOT / "config/task05g_pre2025_holdout_freeze_v1.yaml"
AUDIT = ROOT / "scripts/task05g_successor_executor_contract_audit_v1.py"
OUTPUT_DIR = ROOT / "artifacts/task05g_2025_holdout_v1"
SPEND_MARKER = OUTPUT_DIR / "HOLDOUT_SPENT.json"
DEFAULT_HISTORICAL_BOARD = ROOT / "artifacts/task05f/evaluator_final_v1/historical_evaluator_board.parquet"
AUTHORIZATION_SHA256 = "f32f7b3a4316dc2f1154bb531b1c496b9958b33291e9e95a95b99767a1190f0a"


class HoldoutGateError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_yaml(path: Path) -> dict[str, Any]:
    return dict(yaml.safe_load(path.read_text()) or {})


def _verify_static_contract(config: dict[str, Any]) -> None:
    if str(config.get("schema_version")) != "task05g_2025_acceptance_v1":
        raise HoldoutGateError("unexpected acceptance schema")
    if int(config.get("holdout_season", -1)) != 2025:
        raise HoldoutGateError("holdout season must be exactly 2025")
    execution = dict(config.get("execution") or {})
    if bool(execution.get("tuning_flags_allowed", True)):
        raise HoldoutGateError("tuning flags must remain prohibited")
    auth = dict(config.get("authorization") or {})
    if not bool(auth.get("must_be_verified_before_any_2025_file_read")):
        raise HoldoutGateError("authorization-before-read invariant missing")
    if str(auth.get("exact_phrase_sha256")) != AUTHORIZATION_SHA256:
        raise HoldoutGateError("authorization phrase hash mismatch")
    if str(auth.get("one_spend_marker")) != "artifacts/task05g_2025_holdout_v1/HOLDOUT_SPENT.json":
        raise HoldoutGateError("one-spend marker contract changed")
    chronology = dict(config.get("chronology") or {})
    if bool(chronology.get("same_block_outcomes_available_to_predictions", True)):
        raise HoldoutGateError("same-block outcome firewall disabled")
    if str(chronology.get("retroactive_knowledge")) != "prohibited":
        raise HoldoutGateError("retroactive knowledge must be prohibited")
    outputs = list((config.get("outputs") or {}).get("required") or [])
    required = {
        "holdout_headline_cards.csv",
        "holdout_weekly_summary.csv",
        "holdout_lane_summary.csv",
        "holdout_market_mix.csv",
        "holdout_bankroll_scenarios.csv",
        "holdout_scenario_ledger.csv",
        "holdout_product_integrity.json",
        "holdout_provenance.json",
        "holdout_acceptance_report.json",
    }
    if set(outputs) != required:
        raise HoldoutGateError("required holdout output contract changed")


def _run_prefreeze_audit() -> None:
    completed = subprocess.run(
        [sys.executable, str(AUDIT), "--quiet"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise HoldoutGateError(f"successor executor contract audit failed: {detail}")


def preflight() -> dict[str, Any]:
    """Code/config/Git-only proof.  This function never opens a 2025 input."""
    config = _load_yaml(CONFIG_PATH)
    _verify_static_contract(config)
    _run_prefreeze_audit()
    freeze = _load_yaml(FREEZE_PATH)
    return {
        "status": "SEALED_PREFLIGHT_PASS",
        "holdout_season": 2025,
        "authorization_required": True,
        "execution_ready": bool((config.get("execution") or {}).get("ready")),
        "freeze_status": freeze.get("status"),
        "2025_data_read": False,
    }


def _verify_authorization(value: str | None) -> None:
    if value is None:
        raise HoldoutGateError("authorization is required; 2025 remains sealed")
    if hashlib.sha256(value.encode()).hexdigest() != AUTHORIZATION_SHA256:
        raise HoldoutGateError("authorization mismatch; 2025 remains sealed")


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True
    )
    if completed.returncode != 0:
        raise HoldoutGateError("unable to resolve execution Git HEAD")
    return completed.stdout.strip()


def _consume_spend_marker() -> dict[str, Any]:
    """Create the irreversible marker with O_EXCL before the first 2025 read."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "task05g_2025_holdout_spend_marker_v1",
        "holdout_season": 2025,
        "authorization_sha256": AUTHORIZATION_SHA256,
        "git_head": _git_head(),
        "acceptance_config_sha256": _sha256(CONFIG_PATH),
        "prefreeze_contract_sha256": _sha256(FREEZE_PATH),
        "marker_semantics": "IRREVERSIBLE_BEFORE_FIRST_2025_INPUT_READ",
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(SPEND_MARKER, flags, 0o600)
    except FileExistsError as exc:
        raise HoldoutGateError("HOLDOUT_ALREADY_SPENT") from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        # The marker is intentionally not removed on a post-create failure.
        # Once creation succeeds, the holdout has been consumed.
        raise
    return {**payload, "marker_sha256": hashlib.sha256(encoded).hexdigest()}


def _runtime_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    market_value = args.market_root or os.environ.get("NFL_EDGE_2025_MARKET_ROOT")
    if not market_value:
        raise HoldoutGateError(
            "NFL_EDGE_2025_MARKET_ROOT/--market-root is required before opening 2025"
        )
    historical_value = (
        args.historical_board
        or os.environ.get("NFL_EDGE_TASK05F_HISTORICAL_BOARD")
        or str(DEFAULT_HISTORICAL_BOARD)
    )
    market_root = Path(market_value)
    historical_board = Path(historical_value)
    if not market_root.is_dir():
        raise HoldoutGateError(f"2025 market artifact root does not exist: {market_root}")
    if not historical_board.is_file():
        raise HoldoutGateError(f"historical Task05F board does not exist: {historical_board}")
    return market_root, historical_board


def execute(
    authorization: str | None,
    *,
    market_root: Path | None = None,
    historical_board: Path | None = None,
) -> None:
    # Through readiness + development bootstrap, no 2025 input may be read.
    preflight()
    _verify_authorization(authorization)
    config = _load_yaml(CONFIG_PATH)
    execution = dict(config.get("execution") or {})
    if not bool(execution.get("ready")):
        raise HoldoutGateError(
            "HOLDOUT_EXECUTOR_NOT_FROZEN; no 2025 read occurred; blockers="
            + json.dumps(execution.get("blocked_reasons") or [], sort_keys=True)
        )
    if SPEND_MARKER.exists():
        raise HoldoutGateError("HOLDOUT_ALREADY_SPENT")

    from nfl_edge.holdout.executor_runtime_2025 import (
        prepare_development_state,
        run_authorized_holdout,
    )

    market = Path(market_root) if market_root is not None else None
    history = Path(historical_board) if historical_board is not None else None
    if market is None:
        env_market = os.environ.get("NFL_EDGE_2025_MARKET_ROOT")
        if not env_market:
            raise HoldoutGateError("NFL_EDGE_2025_MARKET_ROOT is required")
        market = Path(env_market)
    if history is None:
        history = Path(
            os.environ.get("NFL_EDGE_TASK05F_HISTORICAL_BOARD", str(DEFAULT_HISTORICAL_BOARD))
        )
    if not market.is_dir() or not history.is_file():
        raise HoldoutGateError("runtime artifact path missing before development bootstrap")

    # This function is contractually development-only and verifies the accepted
    # historical board SHA before returning.
    development = prepare_development_state(historical_board_path=history)

    # Last gate before any 2025 data read.  O_EXCL closes the race between the
    # earlier existence check and irreversible consumption.
    marker = _consume_spend_marker()

    # From this line onward 2025 is open and cannot be re-run even if a later
    # runtime invariant fails.
    final_state = run_authorized_holdout(
        output_root=OUTPUT_DIR,
        market_root=market,
        development_state=development,
        opened_marker_identity=marker,
    )
    print(
        json.dumps(
            {
                "status": "2025_HOLDOUT_ONE_SHOT_COMPLETE",
                "completed_blocks": len(final_state.completed_blocks),
                "record": dict(final_state.record),
                "weighted_unit_profit": final_state.weighted_units,
            },
            indent=2,
            sort_keys=True,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--authorization")
    parser.add_argument("--market-root", type=Path)
    parser.add_argument("--historical-board", type=Path)
    args = parser.parse_args()
    try:
        if args.preflight:
            print(json.dumps(preflight(), indent=2, sort_keys=True))
        else:
            execute(
                args.authorization,
                market_root=args.market_root,
                historical_board=args.historical_board,
            )
    except HoldoutGateError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
