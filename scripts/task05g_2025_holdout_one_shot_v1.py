#!/usr/bin/env python3
"""Authorization gate for the sealed NFL EDGE 2025 one-shot acceptance run.

Preparation behavior is intentionally fail-closed:
- --preflight never opens any 2025 data.
- missing/wrong authorization fails before any 2025 data access.
- while the frozen config says execution.ready=false, even a value matching the
  frozen authorization hash fails before any 2025 data access.

The plaintext one-shot authorization is deliberately not stored in this
repository or exercised by CI. The future operator supplies it out-of-band;
this entrypoint verifies only its frozen SHA-256 digest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "task05g_2025_acceptance_v1.yaml"
FREEZE_PATH = ROOT / "config" / "task05g_pre2025_holdout_freeze_v1.yaml"
AUDIT = ROOT / "scripts" / "task05g_pre2025_freeze_audit_v1.py"
OUTPUT_DIR = ROOT / "artifacts" / "task05g_2025_holdout_v1"
SPEND_MARKER = OUTPUT_DIR / "HOLDOUT_SPENT.json"
AUTHORIZATION_SHA256 = "7b8fd4a076caf6d97f00435d8b87d97e7f9c71055a25d324821160826be65556"


class HoldoutGateError(RuntimeError):
    pass


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
        raise HoldoutGateError(f"prefreeze audit failed: {detail}")


def preflight() -> dict[str, Any]:
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
    supplied = hashlib.sha256(value.encode()).hexdigest()
    if supplied != AUTHORIZATION_SHA256:
        raise HoldoutGateError("authorization mismatch; 2025 remains sealed")


def execute(authorization: str | None) -> None:
    # IMPORTANT: everything above and through this readiness check is allowed
    # to read only code/config/Git metadata. No sealed input path is touched.
    preflight()
    _verify_authorization(authorization)

    config = _load_yaml(CONFIG_PATH)
    execution = dict(config.get("execution") or {})
    if not bool(execution.get("ready")):
        reasons = execution.get("blocked_reasons") or []
        raise HoldoutGateError(
            "HOLDOUT_EXECUTOR_NOT_FROZEN; no 2025 read occurred; blockers="
            + json.dumps(reasons, sort_keys=True)
        )

    # This branch is intentionally unreachable in v1 preparation. The
    # holdout-only upstream executor must be implemented, reviewed, and pinned
    # in the pre-holdout freeze before execution.ready may become true.
    if SPEND_MARKER.exists():
        raise HoldoutGateError("HOLDOUT_ALREADY_SPENT")
    raise HoldoutGateError(
        "execution.ready=true without a frozen executor implementation; fail closed"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--authorization")
    args = parser.parse_args()
    try:
        if args.preflight:
            print(json.dumps(preflight(), indent=2, sort_keys=True))
        else:
            execute(args.authorization)
    except HoldoutGateError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
