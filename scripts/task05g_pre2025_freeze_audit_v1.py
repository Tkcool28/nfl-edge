#!/usr/bin/env python3
"""Pre-2025 freeze audit using Git metadata for sealed files.

The audit never opens any path listed under sealed_data_git_metadata. It uses
`git ls-files -s` to verify Git blob identities and reads only code/config/docs.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "config" / "task05g_pre2025_holdout_freeze_v1.yaml"


class AuditFailure(RuntimeError):
    pass


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _tracked_blob(path: str) -> str:
    line = _git("ls-files", "-s", "--", path)
    if not line:
        raise AuditFailure(f"protected path is not tracked: {path}")
    rows = [row for row in line.splitlines() if row.strip()]
    if len(rows) != 1:
        raise AuditFailure(f"unexpected index rows for {path}: {rows}")
    return rows[0].split()[1]


def _load_manifest() -> dict[str, Any]:
    return dict(yaml.safe_load(MANIFEST_PATH.read_text()) or {})


def _assert_guard(path: str, required_fragments: list[str]) -> None:
    text = (ROOT / path).read_text()
    missing = [fragment for fragment in required_fragments if fragment not in text]
    if missing:
        raise AuditFailure(f"2025 firewall guard drift in {path}: missing {missing}")


def audit() -> dict[str, Any]:
    manifest = _load_manifest()
    if str(manifest.get("schema_version")) != "task05g_pre2025_holdout_freeze_v1":
        raise AuditFailure("unexpected freeze schema")
    if int(manifest.get("sealed_holdout_season", -1)) != 2025:
        raise AuditFailure("sealed holdout season must be exactly 2025")
    if bool(manifest.get("authorization_ready", True)):
        raise AuditFailure("v1 prefreeze must remain not authorized until executor is frozen")

    base = str(manifest["reference_main_commit"])
    try:
        subprocess.check_call(
            ["git", "merge-base", "--is-ancestor", base, "HEAD"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        raise AuditFailure(f"reference main commit {base} is not an ancestor of HEAD") from exc

    checked: dict[str, str] = {}
    for path, expected in dict(manifest.get("protected_git_blobs") or {}).items():
        actual = _tracked_blob(path)
        if actual != str(expected):
            raise AuditFailure(f"protected Git blob drift: {path}: {actual} != {expected}")
        checked[path] = actual

    sealed_metadata: dict[str, str] = {}
    for item in list(manifest.get("sealed_data_git_metadata") or []):
        path = str(item["path"])
        expected = str(item["git_blob"])
        actual = _tracked_blob(path)  # Git index metadata only; file bytes are not opened.
        if actual != expected:
            raise AuditFailure(f"sealed data Git blob drift: {path}: {actual} != {expected}")
        sealed_metadata[path] = actual

    guards = dict(manifest.get("firewall_source_guards") or {})
    for path, fragments in guards.items():
        _assert_guard(path, [str(x) for x in fragments])

    existing_freeze = dict(yaml.safe_load(
        (ROOT / "config" / "task05g_final_product_freeze_v1.yaml").read_text()
    ) or {})
    if bool(existing_freeze.get("semantic_changes_after_freeze_allowed", True)):
        raise AuditFailure("existing Task05G production freeze no longer prohibits semantic changes")
    sealed = dict(existing_freeze.get("sealed_boundary") or {})
    if 2025 not in [int(x) for x in sealed.get("not_opened_not_run", [])]:
        raise AuditFailure("existing Task05G freeze no longer records 2025 sealed")

    return {
        "status": "PREFREEZE_AUDIT_PASS__EXECUTION_STILL_BLOCKED",
        "head": _git("rev-parse", "HEAD"),
        "reference_main_commit": base,
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
    except (AuditFailure, subprocess.CalledProcessError) as exc:
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
