#!/usr/bin/env python3
"""Pre-2025 freeze audit using Git metadata for sealed files.

Protected expectations are loaded from an immutable, already-existing Git
commit rather than trusted from the mutable working-tree freeze YAML. Sealed
parquet contents are never opened. Executable code/config guard paths must also
be clean in both the index and worktree so the future command cannot import
bytes different from the audited Git identity.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
FREEZE_REL = "config/task05g_pre2025_holdout_freeze_v1.yaml"
CONTRACT_RECORD_REL = "reports/pre2025/pre2025_product_freeze_manifest_v1.json"
FINAL_PRODUCT_FREEZE_REL = "config/task05g_final_product_freeze_v1.yaml"

# Immutable identities established before this security-hardening patch.
# The freeze YAML at this commit already contains the reviewed production and
# sealed-data blob inventory. Never replace this SHA merely to make drift pass.
IMMUTABLE_FREEZE_ANCHOR_SHA = "e6316216d79fd9191be3d4095b0bca8af5bd30b7"
IMMUTABLE_REFERENCE_MAIN_SHA = "65504d9d834d15d71d6fdc205a912eec455b66ab"


class AuditFailure(RuntimeError):
    pass


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise AuditFailure(f"git {' '.join(args)} failed: {detail}")
    return completed


def _git_text(*args: str) -> str:
    return _git(*args).stdout.strip()


def _tracked_blob(path: str) -> str:
    line = _git_text("ls-files", "-s", "--", path)
    if not line:
        raise AuditFailure(f"protected path is not tracked: {path}")
    rows = [row for row in line.splitlines() if row.strip()]
    if len(rows) != 1:
        raise AuditFailure(f"unexpected index rows for {path}: {rows}")
    return rows[0].split()[1]


def _tree_blob(commit: str, path: str) -> str:
    line = _git_text("ls-tree", commit, "--", path)
    if not line:
        raise AuditFailure(f"path absent from immutable commit {commit}: {path}")
    rows = [row for row in line.splitlines() if row.strip()]
    if len(rows) != 1:
        raise AuditFailure(f"unexpected tree rows for {path} at {commit}: {rows}")
    return rows[0].split()[2]


def _yaml_from_commit(commit: str, path: str) -> dict[str, Any]:
    text = _git_text("show", f"{commit}:{path}")
    return dict(yaml.safe_load(text) or {})


def _assert_commit_ancestor(commit: str) -> None:
    completed = _git("merge-base", "--is-ancestor", commit, "HEAD", check=False)
    if completed.returncode != 0:
        raise AuditFailure(f"immutable commit {commit} is not an ancestor of HEAD")


def _assert_clean_executable_path(path: str) -> None:
    # Intentionally used only for executable/code/config paths, never sealed
    # parquet paths. git diff may read worktree bytes; sealed data remains
    # metadata-only during preparation.
    unstaged = _git("diff", "--quiet", "--", path, check=False)
    if unstaged.returncode != 0:
        raise AuditFailure(f"unstaged protected-file drift: {path}")
    staged = _git("diff", "--cached", "--quiet", "--", path, check=False)
    if staged.returncode != 0:
        raise AuditFailure(f"staged protected-file drift: {path}")


def _assert_guard(path: str, required_fragments: list[str]) -> None:
    text = (ROOT / path).read_text()
    missing = [fragment for fragment in required_fragments if fragment not in text]
    if missing:
        raise AuditFailure(f"2025 firewall guard drift in {path}: missing {missing}")


def _load_contract_record() -> dict[str, Any]:
    return dict(json.loads((ROOT / CONTRACT_RECORD_REL).read_text()))


def _validate_contract_record(record: dict[str, Any]) -> tuple[str, int]:
    if str(record.get("schema_version")) != "pre2025_product_freeze_manifest_v1":
        raise AuditFailure("unexpected product-freeze record schema")
    if str(record.get("reference_main_sha")) != IMMUTABLE_REFERENCE_MAIN_SHA:
        raise AuditFailure("product-freeze record reference-main identity drift")
    if bool(record.get("holdout_opened", True)):
        raise AuditFailure("product-freeze record says holdout opened")
    if bool(record.get("authorization_ready", True)):
        raise AuditFailure("product-freeze record unexpectedly authorizes execution")

    contract_sha = str(record.get("contract_git_sha") or "")
    if len(contract_sha) != 40:
        raise AuditFailure("missing/invalid contract_git_sha")
    _assert_commit_ancestor(contract_sha)

    files = dict(record.get("contract_files") or {})
    if not files:
        raise AuditFailure("contract_files inventory is empty")
    for path, recorded_blob in files.items():
        anchored = _tree_blob(contract_sha, str(path))
        current = _tracked_blob(str(path))
        if anchored != str(recorded_blob):
            raise AuditFailure(
                f"contract record does not match contract_git_sha: {path}: "
                f"{recorded_blob} != {anchored}"
            )
        if current != anchored:
            raise AuditFailure(
                f"contract file changed after contract_git_sha: {path}: {current} != {anchored}"
            )
        if not str(path).endswith((".parquet", ".csv")):
            _assert_clean_executable_path(str(path))
    return contract_sha, len(files)


def audit() -> dict[str, Any]:
    _assert_commit_ancestor(IMMUTABLE_REFERENCE_MAIN_SHA)
    _assert_commit_ancestor(IMMUTABLE_FREEZE_ANCHOR_SHA)

    # First pin the working-tree freeze YAML itself to the immutable anchor,
    # then load expectations from that anchor rather than trusting HEAD.
    current_freeze_blob = _tracked_blob(FREEZE_REL)
    anchored_freeze_blob = _tree_blob(IMMUTABLE_FREEZE_ANCHOR_SHA, FREEZE_REL)
    if current_freeze_blob != anchored_freeze_blob:
        raise AuditFailure(
            "freeze manifest drift from immutable anchor: "
            f"{current_freeze_blob} != {anchored_freeze_blob}"
        )
    _assert_clean_executable_path(FREEZE_REL)
    manifest = _yaml_from_commit(IMMUTABLE_FREEZE_ANCHOR_SHA, FREEZE_REL)

    if str(manifest.get("schema_version")) != "task05g_pre2025_holdout_freeze_v1":
        raise AuditFailure("unexpected freeze schema")
    if str(manifest.get("reference_main_commit")) != IMMUTABLE_REFERENCE_MAIN_SHA:
        raise AuditFailure("freeze reference-main identity drift")
    if int(manifest.get("sealed_holdout_season", -1)) != 2025:
        raise AuditFailure("sealed holdout season must be exactly 2025")
    if bool(manifest.get("authorization_ready", True)):
        raise AuditFailure("v1 prefreeze must remain not authorized until executor is frozen")

    checked: dict[str, str] = {}
    for path, expected in dict(manifest.get("protected_git_blobs") or {}).items():
        path = str(path)
        actual = _tracked_blob(path)
        base_blob = _tree_blob(IMMUTABLE_REFERENCE_MAIN_SHA, path)
        if actual != str(expected) or base_blob != str(expected):
            raise AuditFailure(
                f"protected Git blob drift: {path}: current={actual} "
                f"reference_main={base_blob} expected={expected}"
            )
        _assert_clean_executable_path(path)
        checked[path] = actual

    sealed_metadata: dict[str, str] = {}
    for item in list(manifest.get("sealed_data_git_metadata") or []):
        path = str(item["path"])
        expected = str(item["git_blob"])
        actual = _tracked_blob(path)  # Git index metadata only; bytes never opened.
        base_blob = _tree_blob(IMMUTABLE_REFERENCE_MAIN_SHA, path)
        if actual != expected or base_blob != expected:
            raise AuditFailure(
                f"sealed data Git blob drift: {path}: current={actual} "
                f"reference_main={base_blob} expected={expected}"
            )
        sealed_metadata[path] = actual

    guards = dict(manifest.get("firewall_source_guards") or {})
    for path, fragments in guards.items():
        path = str(path)
        # Pin the whole guard file to the immutable pre-hardening anchor, not
        # merely the presence of a few strings.
        current = _tracked_blob(path)
        anchored = _tree_blob(IMMUTABLE_FREEZE_ANCHOR_SHA, path)
        if current != anchored:
            raise AuditFailure(f"firewall source blob drift: {path}: {current} != {anchored}")
        _assert_clean_executable_path(path)
        _assert_guard(path, [str(x) for x in fragments])

    record = _load_contract_record()
    contract_sha, contract_files_checked = _validate_contract_record(record)

    existing_freeze = dict(
        yaml.safe_load((ROOT / FINAL_PRODUCT_FREEZE_REL).read_text()) or {}
    )
    if bool(existing_freeze.get("semantic_changes_after_freeze_allowed", True)):
        raise AuditFailure("existing Task05G production freeze no longer prohibits semantic changes")
    sealed = dict(existing_freeze.get("sealed_boundary") or {})
    if 2025 not in [int(x) for x in sealed.get("not_opened_not_run", [])]:
        raise AuditFailure("existing Task05G freeze no longer records 2025 sealed")

    return {
        "status": "PREFREEZE_AUDIT_PASS__EXECUTION_STILL_BLOCKED",
        "head": _git_text("rev-parse", "HEAD"),
        "reference_main_commit": IMMUTABLE_REFERENCE_MAIN_SHA,
        "immutable_freeze_anchor": IMMUTABLE_FREEZE_ANCHOR_SHA,
        "contract_git_sha": contract_sha,
        "contract_files_checked": contract_files_checked,
        "protected_git_blobs_checked": len(checked),
        "sealed_git_metadata_checked": len(sealed_metadata),
        "sealed_data_bytes_read": 0,
        "holdout_season": 2025,
        "authorization_ready": False,
        "blockers": list(manifest.get("blockers") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    try:
        result = audit()
    except (AuditFailure, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"PREFREEZE_AUDIT_FAIL: {exc}")
        return 2
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if not args.quiet:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
