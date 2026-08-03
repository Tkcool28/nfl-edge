"""Bounded CLI to run one Sleeper QB source-audit pass.

This is the entry point invoked by the bounded systemd timer. The
script:

* reads ``config/sleeper_qb_audit_v1.yaml``;
* constructs an ``AuditOrchestrator`` rooted at the configured audit
  directory;
* runs the bounded fetch + normalization + crosswalk + change ledger;
* writes the live-audit markdown and JSON reports.

The script is intentionally small. All real work lives in
``nfl_edge.source_audits.sleeper_qb_v1``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nfl_edge.source_audits.sleeper_qb_v1.pipeline import AuditOrchestrator  # noqa: E402


def _load_config(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"audit config not found: {path}")
    return yaml.safe_load(path.read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one Sleeper QB source-audit pass.")
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "config" / "sleeper_qb_audit_v1.yaml",
        help="Path to the audit YAML config (default: config/sleeper_qb_audit_v1.yaml).",
    )
    parser.add_argument(
        "--kind",
        default="scheduled",
        choices=["scheduled", "pregame", "postgame"],
        help="Audit run kind (controls snapshot id suffix and freshness policy).",
    )
    parser.add_argument(
        "--lock-timeout-seconds",
        type=float,
        default=0.0,
        help="Optional lock acquisition timeout; 0 means fail fast if the lock is held.",
    )
    parser.add_argument(
        "--use-fake-session",
        action="store_true",
        help="Internal: short-circuit the network and return a deterministic stub response (tests only).",
    )
    args = parser.parse_args()
    config = _load_config(args.config)
    audit_root = Path(config.get("audit_root", "data/source_audits/sleeper_qb_v1"))
    endpoint = config.get("endpoint", "https://api.sleeper.app/v1/players/nfl")
    staleness_threshold = float(config.get("staleness_threshold_seconds", 6 * 3600))
    nflverse_qb_path = config.get("nflverse_qb_path")
    audit_root.mkdir(parents=True, exist_ok=True)
    lock_path = audit_root / "audit.lock"
    if lock_path.exists():
        if args.lock_timeout_seconds <= 0:
            print(f"ERROR: audit lock already held at {lock_path}", file=sys.stderr)
            return 2
    if not lock_path.exists():
        lock_path.write_text(json.dumps({"pid": os.getpid(), "kind": args.kind}))
    try:
        orchestrator = AuditOrchestrator(
            audit_root=audit_root,
            endpoint=endpoint,
            staleness_threshold_seconds=staleness_threshold,
            nflverse_qb_path=nflverse_qb_path,
        )
        session = None
        if args.use_fake_session:
            from scripts._sleeper_fake_session import FakeSleeperSession
            session = FakeSleeperSession()
        result = orchestrator.run(session=session, kind=args.kind)
        print(json.dumps(result, indent=2, default=str))
        return 0
    finally:
        if lock_path.exists():
            try:
                lock_path.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
