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
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_RECORD = "reports/pre2025/pre2025_product_freeze_manifest_v1.json"
SUCCESSOR_RECORD = "reports/pre2025/pre2025_successor_executor_contract_v1.json"
FREEZE_REL = "config/task05g_pre2025_holdout_freeze_v1.yaml"
FINAL_PRODUCT_FREEZE_REL = "config/task05g_final_product_freeze_v1.yaml"
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
        ".github/workflows/task05g-2025-executor-freeze-v1.yml",
    ]:
        raise AuditFailure("successor must list exactly the executor and its two audit call sites")

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
    for path, expected in successor_files.items():
        anchored = _tree_blob(successor_commit, str(path))
        current = _tracked_blob(str(path))
        if anchored != str(expected) or current != anchored:
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

    return {
        "status": "SUCCESSOR_EXECUTOR_CONTRACT_AUDIT_PASS__EXECUTION_STILL_BLOCKED",
        "head": _text("rev-parse", "HEAD"),
        "historical_contract_git_sha": historical_commit,
        "successor_contract_git_sha": successor_commit,
        "historical_files_preserved": len(historical_files) - len(superseded),
        "successor_files_checked": len(successor_files),
        "superseded_historical_contract_paths": superseded,
        "sealed_data_bytes_read": 0,
        "holdout_season": 2025,
        "authorization_ready": False,
        "execution_ready": False,
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
