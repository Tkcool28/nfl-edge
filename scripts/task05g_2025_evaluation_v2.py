#!/usr/bin/env python3
"""Run-scoped, fail-closed entrypoint for the sealed 2025 evaluation.

This v2 wrapper deliberately composes the frozen v1 runtime without reading or
using its irreversible global spend marker.  It reserves a new, unique run
output directory and writes RUN_STARTED before delegating any 2025 input access.
"""

from __future__ import annotations

# ruff: noqa: E402, I001  # Script path setup must precede package imports.

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from nfl_edge.holdout.executor_runtime_2025 import (
    HISTORICAL_BOARD_SHA256,
    MARKET_ARTIFACT_DIGEST,
    MARKET_ARTIFACT_ID,
    MARKET_CANONICAL_SHA256,
    MARKET_GAMES_SHA256,
    MARKET_RUN_ID,
    OBSERVATIONS_2025,
    prepare_development_state,
    run_authorized_holdout,
)
from nfl_edge.holdout.oracle_qb_game_resolver_2025 import (
    EXPECTED_ARTIFACT_RELATIVE_PATH as ORACLE_ARTIFACT_PATH,
)
from nfl_edge.holdout.oracle_qb_game_resolver_2025 import (
    EXPECTED_ARTIFACT_SHA256 as ORACLE_ARTIFACT_SHA256,
)
from nfl_edge.holdout.oracle_qb_game_resolver_2025 import (
    EXPECTED_HISTORICAL_MODEL_USAGE,
    EXPECTED_STARTER_EVIDENCE_CLASS,
)
from nfl_edge.holdout.oracle_qb_game_resolver_2025 import (
    IMPLEMENTATION as ORACLE_IMPLEMENTATION,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config/task05g_2025_evaluation_v2.yaml"
LEGACY_CONFIG_PATH = ROOT / "config/task05g_2025_acceptance_v1.yaml"
FREEZE_PATH = ROOT / "config/task05g_pre2025_holdout_freeze_v1.yaml"
RUNTIME_PATH = ROOT / "src/nfl_edge/holdout/executor_runtime_2025.py"
AUDIT_PATH = ROOT / "scripts/task05g_successor_executor_contract_audit_v1.py"
OUTPUT_BASE = ROOT / "artifacts/task05g_2025_holdout_v2"
LEGACY_SPEND_MARKER = ROOT / "artifacts/task05g_2025_holdout_v1/HOLDOUT_SPENT.json"
DEFAULT_HISTORICAL_BOARD = ROOT / "artifacts/task05f/evaluator_final_v1/historical_evaluator_board.parquet"
RUN_SCHEMA_VERSION = "task05g_2025_run_scoped_evaluation_v2"
# These are frozen identities, deliberately recorded from promotion/certification
# metadata without opening PBP bytes during preflight or RUN_STARTED creation.
PRE2025_PBP_IDENTITIES = {
    "2018": "2e6f2dce7c7ebd46e985cabe0c17eb72b39a77f98cb4478409294f50b5820150",
    "2019": "60c3067017db2d28a78f66a79b657268be8578d9a5288e6a827efdcd7fe42540",
    "2020": "73b7dbf66fa8cb9356f58bf6b1f15a0fee197ecc10cf4983b640cb9679b15cb4",
    "2021": "333ad34378e5339d5172717cc83378e908daf02c8699416ab3e17c2ec10f78d8",
    "2022": "931121d8897779d7944e2a293e92ed8799c8e5cceef84096ac42339003fedc09",
    "2023": "bd3484731408def6b0ec93225bba2bd7b2c65769ca707a2b9444d891abdc6776",
    "2024": "6d432dd4308329bfddaef633309ea119f9ca46d52cbb3c09f47172a2e8efcd01",
}
PBP_EXPECTED_SHA256 = "c6ecedd6d678cc37ed316b23ef84ee1ec6abb69c514bb11868a7ebd5a367df29"
PBP_EXPECTED_BYTES = 20_337_029
OBSERVATIONS_EXPECTED_SHA256 = "5a78b506a1d2dc14f4948cd316346d09d863e603c61144716a242252df8f84e3"
OBSERVATIONS_PATH = "data/derived/task05c_game_observations_2025_v1/game_observations_2025_v1.jsonl"
PBP_PATH = "data/frozen/task05c_pbp_2025_v1/play_by_play_2025.parquet"
AUTHORIZATION_SHA256 = "f32f7b3a4316dc2f1154bb531b1c496b9958b33291e9e95a95b99767a1190f0a"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class RunScopedHoldoutError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = _canonical_bytes(value)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RunScopedHoldoutError(f"refusing to overwrite lifecycle file: {path.name}") from exc
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def verify_observation_ledger() -> dict[str, Any]:
    """Hash the exact ledger path the runtime cursor will consume."""
    path = Path(OBSERVATIONS_2025)
    if not path.is_file():
        raise RunScopedHoldoutError(f"GAME_OBSERVATION_LEDGER_MISSING: {path}")
    observed = _sha256(path)
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "expected_sha256": OBSERVATIONS_EXPECTED_SHA256,
        "observed_sha256": observed,
        "matches_expected_sha256": observed == OBSERVATIONS_EXPECTED_SHA256,
    }


def validate_run_id(run_id: str) -> str:
    if run_id in {".", ".."} or not RUN_ID_RE.fullmatch(run_id):
        raise RunScopedHoldoutError("safe --run-id required: ASCII [A-Za-z0-9][A-Za-z0-9._-]{0,79}")
    return run_id


def _git(args: list[str]) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RunScopedHoldoutError(f"unable to resolve Git metadata: {' '.join(args)}")
    return completed.stdout.strip()


def _git_identity() -> dict[str, Any]:
    tracked_porcelain = _git(["status", "--porcelain", "--untracked-files=no"])
    return {
        "branch": _git(["branch", "--show-current"]),
        "head": _git(["rev-parse", "HEAD"]),
        "clean_tracked": not bool(tracked_porcelain),
        "tracked_status_porcelain": tracked_porcelain,
    }


def _load_config() -> dict[str, Any]:
    return dict(yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {})


def _run_frozen_integrity_audit() -> None:
    """Prove the frozen development/executor contract before opening v2."""
    completed = subprocess.run(
        [sys.executable, str(AUDIT_PATH), "--quiet"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RunScopedHoldoutError(f"frozen executor integrity audit failed: {detail}")


def preflight() -> dict[str, Any]:
    """Static v2 validation only; it never opens 2025 inputs."""
    config = _load_config()
    if config.get("schema_version") != RUN_SCHEMA_VERSION:
        raise RunScopedHoldoutError("unexpected v2 evaluation schema")
    if int(config.get("holdout_season", -1)) != 2025:
        raise RunScopedHoldoutError("holdout season must be exactly 2025")
    if bool(dict(config.get("execution") or {}).get("tuning_flags_allowed", True)):
        raise RunScopedHoldoutError("tuning flags must remain prohibited")
    if not bool(dict(config.get("authorization") or {}).get("must_be_verified_before_any_2025_file_read")):
        raise RunScopedHoldoutError("authorization-before-read invariant missing")
    if bool(dict(config.get("chronology") or {}).get("same_block_outcomes_available_to_predictions", True)):
        raise RunScopedHoldoutError("same-block outcome firewall disabled")
    _run_frozen_integrity_audit()
    return {"status": "SEALED_V2_PREFLIGHT_PASS", "2025_data_read": False, "run_schema_version": RUN_SCHEMA_VERSION}


def _verify_authorization(value: str | None) -> None:
    if value is None or hashlib.sha256(value.encode()).hexdigest() != AUTHORIZATION_SHA256:
        raise RunScopedHoldoutError("authorization mismatch; 2025 remains sealed")


def _provenance(run_id: str, authorization_mode: str) -> dict[str, Any]:
    # Values here are static identities from source/config/metadata only.  In
    # particular, no PBP or 2025 outcome file is opened to create RUN_STARTED.
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "started_at_utc": _utc_now(),
        **_git_identity(),
        "authorization_mode": authorization_mode,
        "executor": {
            "script": str(Path(__file__).relative_to(ROOT)),
            "script_sha256": _sha256(Path(__file__)),
            "runtime_path": str(RUNTIME_PATH.relative_to(ROOT)),
            "runtime_sha256": _sha256(RUNTIME_PATH),
        },
        "python": {
            "version": sys.version,
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "config_identities": {
            "evaluation_v2_sha256": _sha256(CONFIG_PATH),
            "acceptance_v1_sha256": _sha256(LEGACY_CONFIG_PATH),
            "prefreeze_contract_sha256": _sha256(FREEZE_PATH),
        },
        "task05f_historical_board_sha256": HISTORICAL_BOARD_SHA256,
        "oracle": {
            "path": ORACLE_ARTIFACT_PATH,
            "sha256": ORACLE_ARTIFACT_SHA256,
            "implementation": ORACLE_IMPLEMENTATION,
            "historical_model_usage": EXPECTED_HISTORICAL_MODEL_USAGE,
            "starter_evidence_class": EXPECTED_STARTER_EVIDENCE_CLASS,
        },
        "frozen_task05c_pbp": {
            "promoted_pre2025_sha256": dict(PRE2025_PBP_IDENTITIES),
            "evaluation_2025": {"path": PBP_PATH, "sha256": PBP_EXPECTED_SHA256, "bytes": PBP_EXPECTED_BYTES},
        },
        "frozen_task05c_game_observations": {"path": OBSERVATIONS_PATH, "sha256": OBSERVATIONS_EXPECTED_SHA256},
        "market": {
            "artifact_run_id": MARKET_RUN_ID,
            "artifact_id": MARKET_ARTIFACT_ID,
            "artifact_digest": MARKET_ARTIFACT_DIGEST,
            "canonical_book_market_sha256": MARKET_CANONICAL_SHA256,
            "canonical_market_games_sha256": MARKET_GAMES_SHA256,
        },
        "canonical_book_market_sha256": MARKET_CANONICAL_SHA256,
        "canonical_market_games_sha256": MARKET_GAMES_SHA256,
        "legacy_v1_spend_marker_present": LEGACY_SPEND_MARKER.exists(),
        "legacy_v1_spend_marker_used_as_gate": False,
    }


def create_run_started(run_id: str, *, authorization_mode: str) -> dict[str, Any]:
    run_id = validate_run_id(run_id)
    OUTPUT_BASE.mkdir(parents=True, exist_ok=True)
    output_root = OUTPUT_BASE / run_id
    try:
        output_root.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise RunScopedHoldoutError("RUN_OUTPUT_ALREADY_EXISTS") from exc
    started = {
        "schema_version": RUN_SCHEMA_VERSION,
        "status": "RUN_STARTED",
        "run_id": run_id,
        "output_root": str(output_root.relative_to(ROOT)) if output_root.is_relative_to(ROOT) else str(output_root),
        "provenance": _provenance(run_id, authorization_mode),
    }
    try:
        _exclusive_json(output_root / "RUN_STARTED.json", started)
    except Exception:
        # Keep a reserved directory fail-closed if lifecycle creation ever fails.
        raise
    return started


def _terminalize(
    started: Mapping[str, Any], *, status: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Claim the terminal lifecycle exactly once, then publish its named view."""
    output = OUTPUT_BASE / str(started["run_id"])
    if not (output / "RUN_STARTED.json").is_file():
        raise RunScopedHoldoutError("RUN_STARTED lifecycle state missing")
    terminal = dict(payload)
    try:
        _exclusive_json(output / "RUN_TERMINAL.json", terminal)
    except RunScopedHoldoutError as exc:
        raise RunScopedHoldoutError("lifecycle already terminal") from exc
    # The canonical terminal claim is already durable.  The status-named record
    # is an operator-friendly immutable view and cannot race with the other
    # terminal status because RUN_TERMINAL was created exclusively first.
    _exclusive_json(output / f"{status}.json", terminal)
    return terminal


def complete_run(started: Mapping[str, Any], summary: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": RUN_SCHEMA_VERSION,
        "status": "RUN_COMPLETED",
        "run_id": started["run_id"],
        "completed_at_utc": _utc_now(),
        **dict(summary),
    }
    return _terminalize(started, status="RUN_COMPLETED", payload=payload)


def fail_run(started: Mapping[str, Any], error: BaseException) -> dict[str, Any]:
    payload = {
        "schema_version": RUN_SCHEMA_VERSION,
        "status": "RUN_FAILED",
        "run_id": started["run_id"],
        "failed_at_utc": _utc_now(),
        "failure": {"type": type(error).__name__, "message": str(error)},
    }
    return _terminalize(started, status="RUN_FAILED", payload=payload)


def execute(
    run_id: str, authorization: str | None, *, market_root: Path | None = None, historical_board: Path | None = None
) -> None:
    """Authorize, prepare development-only state, reserve a v2 run, then open 2025."""
    validate_run_id(run_id)
    preflight()
    _verify_authorization(authorization)
    history = (
        Path(historical_board)
        if historical_board is not None
        else Path(os.environ.get("NFL_EDGE_TASK05F_HISTORICAL_BOARD", str(DEFAULT_HISTORICAL_BOARD)))
    )
    market_value = str(market_root) if market_root is not None else os.environ.get("NFL_EDGE_2025_MARKET_ROOT")
    if not market_value:
        raise RunScopedHoldoutError("NFL_EDGE_2025_MARKET_ROOT/--market-root is required")
    market = Path(market_value)
    development = prepare_development_state(historical_board_path=history)
    started = create_run_started(run_id, authorization_mode="sha256_phrase_verified")
    output_root = OUTPUT_BASE / run_id
    try:
        observation = verify_observation_ledger()
        verification = {
            "schema_version": RUN_SCHEMA_VERSION,
            "input": "game_observation_ledger_2025",
            **observation,
        }
        _exclusive_json(output_root / "RUN_INPUT_VERIFICATION.json", verification)
        if not bool(observation["matches_expected_sha256"]):
            raise RunScopedHoldoutError(
                "GAME_OBSERVATION_LEDGER_INTEGRITY_MISMATCH: "
                f"expected={observation['expected_sha256']} observed={observation['observed_sha256']}"
            )
        state = run_authorized_holdout(
            output_root=output_root,
            market_root=market,
            development_state=development,
            opened_marker_identity={
                "schema_version": RUN_SCHEMA_VERSION,
                "run_id": run_id,
                "semantics": "RUN_SCOPED_BEFORE_FIRST_2025_INPUT_READ",
                "run_started_sha256": _sha256(output_root / "RUN_STARTED.json"),
                "game_observation_ledger": observation,
                "input_verification_sha256": _sha256(output_root / "RUN_INPUT_VERIFICATION.json"),
            },
        )
    except Exception as exc:
        fail_run(started, exc)
        raise
    completed = complete_run(
        started,
        {
            "completed_blocks": len(state.completed_blocks),
            "record": dict(state.record),
            "weighted_unit_profit": state.weighted_units,
        },
    )
    print(json.dumps(completed, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
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
            if not args.run_id:
                raise RunScopedHoldoutError("--run-id is required for execution")
            execute(
                args.run_id, args.authorization, market_root=args.market_root, historical_board=args.historical_board
            )
    except RunScopedHoldoutError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
