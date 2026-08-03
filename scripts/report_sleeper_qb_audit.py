"""Bounded CLI to print the latest Sleeper QB source-audit report.

This is the entry point a human reviewer (or a test) calls to read the
audit's most recent outputs without having to know the audit tree
layout. The script reads ``config/sleeper_qb_audit_v1.yaml`` and
prints the JSON payload of the latest ``sleeper_qb_live_audit.json``
and ``sleeper_hof_game_observation.json`` reports.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_config(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"audit config not found: {path}")
    return yaml.safe_load(path.read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the latest Sleeper QB source-audit reports.")
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "config" / "sleeper_qb_audit_v1.yaml",
        help="Path to the audit YAML config (default: config/sleeper_qb_audit_v1.yaml).",
    )
    parser.add_argument(
        "--report",
        default="live",
        choices=["live", "hof"],
        help="Which report to print: 'live' or 'hof'.",
    )
    args = parser.parse_args()
    config = _load_config(args.config)
    audit_root = Path(config.get("audit_root", "data/source_audits/sleeper_qb_v1"))
    if args.report == "live":
        report_path = audit_root / "reports" / "sleeper_qb_live_audit.json"
    else:
        report_path = audit_root / "reports" / "sleeper_hof_game_observation.json"
    if not report_path.exists():
        print(f"ERROR: report not found at {report_path}", file=sys.stderr)
        return 1
    payload = json.loads(report_path.read_text())
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
