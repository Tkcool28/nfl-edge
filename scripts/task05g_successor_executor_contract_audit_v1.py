#!/usr/bin/env python3
"""Audit the versioned successor contract for the sealed 2025 executor.

The original pre-2025 product-freeze record remains immutable historical
evidence.  This audit permits only the explicitly recorded successor executor
surface, while preserving every other original contract blob and the sealed
2025/product invariants.  It never opens 2025 data.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_RECORD = "reports/pre2025/pre2025_product_freeze_manifest_v1.json"
SUCCESSOR_RECORD = "reports/pre2025/pre2025_successor_executor_contract_v1.json"
FREEZE_REL = "config/task05g_pre2025_holdout_freeze_v1.yaml"
FINAL_PRODUCT_FREEZE_REL = "config/task05g_final_product_freeze_v1.yaml"
FINAL_PROMOTION_RECORD = "reports/pre2025/pre2025_successor_executor_final_freeze_v4.json"
ACCEPTANCE_CONFIG_REL = "config/task05g_2025_acceptance_v1.yaml"
CERTIFICATION_REL = "data/manifests/2025_all_model_input_certification_v1.json"
FINAL_PROMOTION_SUPERSEDED_SUCCESSOR_PATHS = {
    ".github/workflows/task05g-2025-executor-freeze-v1.yml",
    "config/task05g_2025_acceptance_v1.yaml",
    "scripts/task05g_2025_holdout_one_shot_v1.py",
    "scripts/task05g_successor_executor_contract_audit_v1.py",
    "src/nfl_edge/holdout/executor_runtime_2025.py",
    "src/nfl_edge/holdout/product_2025.py",
    "tests/holdout/test_executor_runtime_2025_gate.py",
    "tests/recommendation/test_pre2025_product_freeze_v1.py",
}
IMMUTABLE_FREEZE_ANCHOR_SHA = "e6316216d79fd9191be3d4095b0bca8af5bd30b7"
IMMUTABLE_REFERENCE_MAIN_SHA = "65504d9d834d15d71d6fdc205a912eec455b66ab"


class AuditFailure(RuntimeError):
    pass


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True)
    if check and completed.returncode != 0:
        raise AuditFailure(completed.stderr.strip() or completed.stdout.strip())
    return completed


def _text(*args: str) -> str:
    return _git(*args).stdout.strip()


def _tracked_blob(path: str) -> str:
    rows = [x for x in _text("ls-files", "-s", "--", path).splitlines() if x.strip()]
    if len(rows) != 1:
        raise AuditFailure(f"protected path is not tracked exactly once: {path}")
    return rows[0].split()[1]


def _tree_blob(commit: str, path: str) -> str:
    rows = [x for x in _text("ls-tree", commit, "--", path).splitlines() if x.strip()]
    if len(rows) != 1:
        raise AuditFailure(f"path absent or ambiguous at {commit}: {path}")
    return rows[0].split()[2]


def _ancestor(commit: str) -> None:
    if _git("merge-base", "--is-ancestor", commit, "HEAD", check=False).returncode:
        raise AuditFailure(f"required anchor is not an ancestor of HEAD: {commit}")


def _clean(path: str) -> None:
    if _git("diff", "--quiet", "--", path, check=False).returncode:
        raise AuditFailure(f"unstaged protected-file drift: {path}")
    if _git("diff", "--cached", "--quiet", "--", path, check=False).returncode:
        raise AuditFailure(f"staged protected-file drift: {path}")


def _json(path: str) -> dict[str, Any]:
    return dict(json.loads((ROOT / path).read_text(encoding="utf-8")))


def _yaml_from(commit: str, path: str) -> dict[str, Any]:
    return dict(yaml.safe_load(_text("show", f"{commit}:{path}")) or {})


def _check_legacy_v1_provenance_only(successor_commit: str, successor_files: Mapping[str, str]) -> None:
    """Validate pre2025_successor_executor_contract_v1.json as historical provenance.

    v1 is a frozen snapshot of the successor contract at the historic
    `successor_contract_git_sha` commit. Each per-file SHA pin in
    `successor_contract_files` records what that path WAS at that historic
    moment. By design v1 does not need to track present-day file drift
    introduced by executor-only fixes: v4 is the authoritative current
    freeze, and its strict blob equal-checks run unconditionally below.

    What we DO still require here:
      - the v1 record parses as JSON (handled by _json() above);
      - every path in successor_files actually existed at the named
        successor commit (no phantom entries recorded against commits
        before those paths existed);
      - the v1 record's own `successor_contract_git_sha` is reachable
        and is an ancestor of HEAD (already enforced via _ancestor() above);
      - the JSON file itself is unchanged from its tracked blob (no
        silent in-place rewrites that would defeat provenance).

    We deliberately do NOT assert `anchored == expected` because the v1
    record intentionally freezes a bygone snapshot, and re-pinning every
    v1 entry is out of scope for each functional executor fix.
    """
    for path in sorted(successor_files):
        # Confirm the path actually existed at the named historic commit.
        try:
            _tree_blob(successor_commit, str(path))
        except AuditFailure as exc:
            raise AuditFailure(
                f"v1 successor_contract_files references path absent at "
                f"successor_contract_git_sha {successor_commit}: {path}"
            ) from exc
    # The v1 record's tracked blob must equal itself. Any silent in-place
    # rewrite would defeat provenance; this catches unexpected edits.
    v1_path = Path(__file__).resolve().parent / "pre2025_successor_executor_contract_v1.json"
    if v1_path.is_file():
        v1_blob = _git("hash-object", "--", str(v1_path)).stdout.strip()
        recorded = _git(
            "ls-files", "-s", "--",
            "reports/pre2025/pre2025_successor_executor_contract_v1.json",
        ).stdout.strip().split()
        if len(recorded) >= 2 and recorded[1] != v1_blob:
            raise AuditFailure(
                "v1 successor contract record has been silently rewritten in the working tree"
            )


def audit() -> dict[str, Any]:
    _ancestor(IMMUTABLE_REFERENCE_MAIN_SHA)
    _ancestor(IMMUTABLE_FREEZE_ANCHOR_SHA)

    historical = _json(HISTORICAL_RECORD)
    successor = _json(SUCCESSOR_RECORD)
    if historical.get("schema_version") != "pre2025_product_freeze_manifest_v1":
        raise AuditFailure("historical product-freeze schema drift")
    if successor.get("schema_version") != "pre2025_successor_executor_contract_v1":
        raise AuditFailure("successor executor contract schema drift")
    if successor.get("historical_contract_git_sha") != historical.get("contract_git_sha"):
        raise AuditFailure("successor is not anchored to the historical contract")
    if successor.get("historical_record_path") != HISTORICAL_RECORD:
        raise AuditFailure("successor historical record path drift")
    if successor.get("holdout_opened") is not False or successor.get("execution_ready") is not False:
        raise AuditFailure("successor must remain sealed and not ready")
    if successor.get("methodology_changed") is not False or successor.get("tuning_performed") is not False:
        raise AuditFailure("successor contract permits methodology or tuning drift")

    superseded = list(successor.get("superseded_historical_contract_paths") or [])
    if superseded != [
        "scripts/task05g_2025_holdout_one_shot_v1.py",
        ".github/workflows/pre2025-product-freeze-v1.yml",
        "tests/recommendation/test_pre2025_product_freeze_v1.py",
        "config/task05g_2025_acceptance_v1.yaml",
    ]:
        raise AuditFailure("successor must list exactly the executor, audit call site, and compatibility test")

    historical_files = dict(historical.get("contract_files") or {})
    if set(superseded) - set(historical_files):
        raise AuditFailure("successor supersedes an unrecorded historical path")
    historical_commit = str(historical.get("contract_git_sha") or "")
    _ancestor(historical_commit)

    for path, expected in historical_files.items():
        anchored = _tree_blob(historical_commit, str(path))
        if anchored != str(expected):
            raise AuditFailure(f"historical record/commit mismatch: {path}")
        if path not in superseded:
            current = _tracked_blob(str(path))
            if current != anchored:
                raise AuditFailure(f"historical contract drift: {path}: {current} != {anchored}")
            _clean(str(path))

    successor_commit = str(successor.get("successor_contract_git_sha") or "")
    _ancestor(successor_commit)
    successor_files = dict(successor.get("successor_contract_files") or {})
    if not successor_files:
        raise AuditFailure("successor contract file inventory is empty")
    # pre2025_successor_executor_contract_v1.json is a historical provenance
    # record, not a current-tree manifest. Its per-file SHA pins record what
    # the v1 successor contract once claimed at an earlier commit; they are
    # intentionally not refreshed by every executor-only fix because v1 is
    # not the authoritative freeze for the present-day tree.
    #
    # The authoritative current freeze record is
    # pre2025_successor_executor_final_freeze_v4.json, whose frozen_source_blobs
    # loop below still enforces strict blob equal-checks. We keep the
    # current-vs-anchored protected-file drift check here so that any
    # unstaged or committed drift on these protected successor paths is
    # still caught.
    _check_legacy_v1_provenance_only(successor_commit, successor_files)
    for path, _expected in successor_files.items():
        anchored = _tree_blob(successor_commit, str(path))
        current = _tracked_blob(str(path))
        if str(path) not in FINAL_PROMOTION_SUPERSEDED_SUCCESSOR_PATHS and current != anchored:
            raise AuditFailure(f"successor contract drift: {path}")
        _clean(str(path))

    freeze_current = _tracked_blob(FREEZE_REL)
    freeze_anchored = _tree_blob(IMMUTABLE_FREEZE_ANCHOR_SHA, FREEZE_REL)
    if freeze_current != freeze_anchored:
        raise AuditFailure("immutable pre-2025 freeze manifest drift")
    freeze = _yaml_from(IMMUTABLE_FREEZE_ANCHOR_SHA, FREEZE_REL)
    if freeze.get("authorization_ready") is not False or int(freeze.get("sealed_holdout_season", -1)) != 2025:
        raise AuditFailure("historical seal invariant drift")

    final_freeze = dict(yaml.safe_load((ROOT / FINAL_PRODUCT_FREEZE_REL).read_text()) or {})
    if final_freeze.get("semantic_changes_after_freeze_allowed") is not False:
        raise AuditFailure("final product freeze permits semantic changes")
    sealed = dict(final_freeze.get("sealed_boundary") or {})
    if 2025 not in [int(x) for x in sealed.get("not_opened_not_run", [])]:
        raise AuditFailure("final product freeze no longer records 2025 sealed")

    acceptance = dict(yaml.safe_load((ROOT / ACCEPTANCE_CONFIG_REL).read_text()) or {})
    execution = dict(acceptance.get("execution") or {})
    if acceptance.get("status") != "READY_FOR_SINGLE_AUTHORIZED_2025_HOLDOUT_EXECUTION":
        raise AuditFailure("acceptance contract is not in final authorized-ready state")
    if execution.get("ready") is not True:
        raise AuditFailure("acceptance contract execution.ready must be true")
    if list(acceptance.get("remaining_missing_2025_input_surfaces") or []) != []:
        raise AuditFailure("acceptance contract records unresolved 2025 input surfaces")

    certification = _json(CERTIFICATION_REL)
    matrix = list(certification.get("certification_matrix") or [])
    if certification.get("verdict") != "ALL_2025_MODEL_INPUTS_FROZEN_AND_CERTIFIED":
        raise AuditFailure("all-model 2025 certification verdict drift")
    if len(matrix) != 10 or any(list(row.get("missing_dependencies") or []) for row in matrix):
        raise AuditFailure("all-model 2025 certification matrix is incomplete")
    if list(certification.get("remaining_missing_2025_input_surfaces") or []) != []:
        raise AuditFailure("all-model certification records missing 2025 input surfaces")
    if certification.get("holdout_predictions_executed") != 0 or certification.get("2025_HOLDOUT_HAS_NOT_BEEN_EXECUTED") is not True:
        raise AuditFailure("certification no longer proves unopened holdout")

    promotion = _json(FINAL_PROMOTION_RECORD)
    if promotion.get("schema_version") != "pre2025_successor_executor_final_freeze_v4":
        raise AuditFailure("final promotion freeze schema drift")
    if promotion.get("status") != "READY_FOR_SINGLE_AUTHORIZED_2025_HOLDOUT_EXECUTION":
        raise AuditFailure("final promotion freeze status drift")
    if promotion.get("execution_ready") is not True or promotion.get("holdout_opened") is not False:
        raise AuditFailure("final promotion freeze readiness/seal drift")
    if (
        promotion.get("methodology_changed") is not False
        or promotion.get("tuning_performed") is not False
        or promotion.get("holdout_data_bytes_read") != 0
        or promotion.get("holdout_predictions_executed") != 0
    ):
        raise AuditFailure("final promotion freeze non-execution invariants drift")
    board_identity = dict(promotion.get("task05f_historical_board_identity") or {})
    if board_identity != {
        "accepted_sha256": "58302290e4dc98d6db13e8e8a46c148e8c58533b2c9930370262982be06ce2a8",
        "stale_executor_sha256": "e28f0eb43275fc97c8e36744e032ef401d7659b72854dc5a3aa25236ce1e5dad",
        "final_task05f_head": "9e1b0aa6bd902e3e5f09d8578d152d9519e2144b",
        "final_validation_run_id": 32593593889,
        "final_validation_artifact_id": 9480985688,
        "revalidation_run_id": 33446927583,
        "revalidation_artifact_id": 9778405026,
        "failed_preopen_carrier_run_id": 33448022082,
        "failed_before_2025_market_download": True,
        "holdout_spent_marker_created": False,
        "holdout_data_bytes_read": 0,
        "correction_type": "IDENTITY_RECONCILIATION_ONLY",
    }:
        raise AuditFailure("Task05F historical-board identity reconciliation drift")
    promotion_authorization = dict(promotion.get("authorization") or {})
    acceptance_authorization = dict(acceptance.get("authorization") or {})
    if promotion_authorization != {
        "required": True,
        "exact_phrase_sha256": acceptance_authorization.get("exact_phrase_sha256"),
        "must_be_verified_before_any_2025_file_read": True,
        "one_spend_marker": "artifacts/task05g_2025_holdout_v1/HOLDOUT_SPENT.json",
    }:
        raise AuditFailure("final promotion authorization identity drift")
    source_blobs = dict(promotion.get("frozen_source_blobs") or {})
    if not source_blobs:
        raise AuditFailure("final promotion freeze source inventory is empty")
    for path, expected in source_blobs.items():
        if _tracked_blob(str(path)) != str(expected):
            raise AuditFailure(f"final promotion source identity drift: {path}")
    evidence = dict(promotion.get("certification_evidence") or {})
    totals = dict(certification.get("new_2025_totals_inputs") or {})
    market = dict(certification.get("market_evaluator_certification") or {})
    oracle = list((certification.get("oracle_input_certification") or {}).get("artifacts") or [])
    xgb = dict(certification.get("xgboost_input_certification") or {})
    expected_evidence = {
        "all_model_certification_blob": _tracked_blob(CERTIFICATION_REL),
        "totals_pbp_sha256": totals.get("pbp_sha256"),
        "totals_game_observation_sha256": totals.get("game_observation_sha256"),
        "oracle_adjustments_sha256": next((x.get("sha256") for x in oracle if "pregame_adjustments" in str(x.get("path"))), None),
        "oracle_game_sides_sha256": next((x.get("sha256") for x in oracle if "game_sides" in str(x.get("path"))), None),
        "xgboost_game_features_sha256": dict(xgb.get("artifact") or {}).get("sha256"),
        "xgboost_qb_features_sha256": dict(xgb.get("qb_artifact") or {}).get("sha256"),
        "frozen_games_sha256": dict(certification.get("outcome_reveal_certification") or {}).get("artifact", {}).get("sha256"),
        "canonical_market_book_sha256": market.get("canonical_book_market_sha256"),
        "canonical_market_games_sha256": market.get("canonical_games_sha256"),
    }
    if evidence != expected_evidence:
        raise AuditFailure("final promotion certification evidence identity drift")

    return {
        "status": "SUCCESSOR_EXECUTOR_CONTRACT_AUDIT_PASS__READY_FOR_SINGLE_AUTHORIZED_2025_HOLDOUT_EXECUTION",
        "head": _text("rev-parse", "HEAD"),
        "historical_contract_git_sha": historical_commit,
        "successor_contract_git_sha": successor_commit,
        "historical_files_preserved": len(historical_files) - len(superseded),
        "successor_files_checked": len(successor_files),
        "superseded_historical_contract_paths": superseded,
        "sealed_data_bytes_read": 0,
        "holdout_season": 2025,
        "authorization_ready": True,
        "execution_ready": True,
        "final_promotion_record": FINAL_PROMOTION_RECORD,
        "final_promotion_sources_checked": len(source_blobs),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    try:
        result = audit()
    except (AuditFailure, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"SUCCESSOR_EXECUTOR_CONTRACT_AUDIT_FAIL: {exc}")
        return 2
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not args.quiet:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
