#!/usr/bin/env python3
"""Validate the pinned runtime or replay the reviewed Week 7 evidence offline."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports/historical_surface_recovery_week7_v1"
AUDIT = ROOT / "data/source_audits/sleeper_qb_v1"
CUTOFF = "2026-10-21T13:26:33Z"
FROZEN_PRODUCT_STATE_SHA = "cf5f1a0f255befae56d7ac91d97af8641500a466c1d84097fe401e950020158b"
EVIDENCE_PATH = re.compile(
    r"weekly/(?:settled_evidence_manifest\.json|settled_(?:games|team_stats|qb_stats|pbp)\.parquet"
    r"|week[1-7]_schedule_v1\.json|schedule_checkpoints/[a-f0-9]{64}\.json)"
    r"|sleeper/(?:latest_(?:snapshot|run_status)\.json|normalized/qb_"
    r"(?:snapshots|identity_crosswalk|evidence_states|change_ledger)\.parquet)"
    r"|native/[A-Za-z0-9_.-]+/(?:run-status\.json|product/deterministic-proof\.json)"
)


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def runtime() -> dict[str, str]:
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("Recovery CI requires Python 3.11")
    versions = {"python": sys.version.split()[0]}
    for line in (ROOT / "requirements/recovery-ci.txt").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        package, expected = line.split("==")
        observed = version(package)
        if observed != expected:
            raise RuntimeError(f"{package} version drift: expected {expected}, got {observed}")
        versions[package] = observed
    return versions


def extract(archive: Path, root: Path) -> None:
    seen = set()
    with tarfile.open(archive, "r:gz") as bundle:
        for entry in bundle:
            relative = Path(entry.name)
            if (
                not entry.isfile()
                or entry.name != relative.as_posix()
                or ".." in relative.parts
                or not EVIDENCE_PATH.fullmatch(entry.name)
                or relative in seen
            ):
                raise RuntimeError("Recovery archive contains a disallowed or duplicate entry")
            seen.add(relative)
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(entry) as source, destination.open("xb") as output:
                shutil.copyfileobj(source, output)


def run_preprovider(inputs: Path) -> dict:
    weekly = inputs / "weekly"
    result = subprocess.run(
        [
            sys.executable, str(ROOT / "scripts/verify_live_2026_preprovider_v1.py"),
            "--repository-root", str(ROOT), "--schedule-root", str(weekly),
            "--evidence-root", str(weekly), "--run-root", str(inputs / "native"),
            "--prediction-as-of-utc", CUTOFF,
        ],
        capture_output=True, text=True, check=False,
    )
    try:
        proof = json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError("Pre-provider command did not return structured evidence") from exc
    if result.returncode or proof.get("verdict") != "NFL_EDGE_PREPROVIDER_READY":
        raise RuntimeError(
            f"Pre-provider replay blocked at {proof.get('blocked_stage')} ({proof.get('error_type')})"
        )
    proof.pop("schedule_path")
    return proof


def replay(archive: Path) -> dict:
    accepted = json.loads((REPORTS / "preprovider-result.json").read_text())
    settled = json.loads((REPORTS / "settled-recovery.json").read_text())
    frozen_path = ROOT / "data/live/2026/entering_product_state_v1.json"
    if sha(frozen_path) != FROZEN_PRODUCT_STATE_SHA:
        raise RuntimeError("Frozen entering-2026 decision state hash mismatch")
    audit_names = ("latest_snapshot.json", "latest_run_status.json", "normalized")
    if any((AUDIT / name).exists() for name in audit_names):
        raise RuntimeError("Use a clean checkout without a runtime Sleeper snapshot")
    results = []
    input_hashes = None
    for _ in range(2):
        with tempfile.TemporaryDirectory(prefix="recovery-replay-") as temp:
            inputs = Path(temp)
            extract(archive, inputs)
            manifest = inputs / "weekly/settled_evidence_manifest.json"
            if not manifest.is_file() or sha(manifest) != settled["manifest_sha256"]:
                raise RuntimeError("Missing or mismatched reviewed Weeks 1–6 settled manifest")
            if not (inputs / "sleeper").is_dir() or not (inputs / "native").is_dir():
                raise RuntimeError("Missing authentic historical Sleeper or native selector inputs")
            hashes = sorted(sha(path) for path in inputs.rglob("*") if path.is_file())
            if input_hashes is not None and input_hashes != hashes:
                raise RuntimeError("Independent replay inputs differ")
            input_hashes = hashes
            try:
                shutil.copytree(inputs / "sleeper", AUDIT, dirs_exist_ok=True)
                results.append(run_preprovider(inputs))
            finally:
                for name in audit_names:
                    path = AUDIT / name
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink(missing_ok=True)
    if results[0] != results[1]:
        raise RuntimeError("Independent canonical replay results differ")
    proof = results[0]
    for key in accepted.keys() - {"schedule_path", "football_snapshot_sha256", "football_state_version"}:
        if proof.get(key) != accepted[key]:
            raise RuntimeError(f"Reviewed Week 7 replay mismatch in {key}")
    return {
        "archive_sha256": sha(archive),
        "deterministic_repeat": True,
        "evidence_baseline": "2026 Week 7 historical pre-provider",
        "frozen_product_state_sha256": FROZEN_PRODUCT_STATE_SHA,
        "input_file_sha256": input_hashes,
        "prediction_as_of_utc": CUTOFF,
        "result": proof,
        "runtime": runtime(),
        "settled_manifest_sha256": settled["manifest_sha256"],
        "settled_row_counts": settled["row_counts"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("runtime")
    historical = commands.add_parser("replay")
    historical.add_argument("archive", type=Path)
    historical.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "runtime":
            print(json.dumps(runtime(), sort_keys=True))
            return
        args.manifest.write_text(json.dumps(replay(args.archive), indent=2, sort_keys=True) + "\n")
    except (OSError, RuntimeError, tarfile.TarError) as exc:
        sys.exit(f"Recovery CI blocked: {exc}")


if __name__ == "__main__":
    main()
