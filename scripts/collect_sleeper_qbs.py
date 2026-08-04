"""Bounded CLI to run one Sleeper QB source-audit pass.

This is the entry point invoked by the bounded systemd timer and by
tests. The CLI:

* reads ``config/sleeper_qb_audit_v1.yaml``;
* acquires the audit lock with a configurable timeout;
* constructs an ``AuditOrchestrator`` rooted at the configured audit
  directory;
* runs the bounded fetch + normalization + crosswalk + change ledger
  + HOF workflow as requested by ``--kind``;
* prints the result JSON to stdout;
* exits with the canonical exit code for the run's ``RunOutcome``.

Real network I/O is opt-in via ``--use-fake-session``; without it,
the CLI uses an injected deterministic stub session in tests.

Exit codes (see ``outcomes.py``):

* ``0`` — SUCCESS
* ``10`` — TRANSPORT_FAILURE
* ``11`` — INCOMPLETE_RESPONSE
* ``12`` — NORMALIZATION_FAILURE
* ``13`` — PERSISTENCE_FAILURE
* ``20`` — LOCK_FAILURE
* ``21`` — REFERENCE_FAILURE
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nfl_edge.source_audits.sleeper_qb_v1.atomic_io import (  # noqa: E402
    ReferenceArtifact,
)
from nfl_edge.source_audits.sleeper_qb_v1.locking import (  # noqa: E402
    LockFailure,
    advisory_lock,
)
from nfl_edge.source_audits.sleeper_qb_v1.outcomes import (  # noqa: E402
    EXIT_CODES,
    RunOutcome,
)
from nfl_edge.source_audits.sleeper_qb_v1.pipeline import (  # noqa: E402
    AuditOrchestrator,
)


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"audit config not found: {path}")
    loaded = yaml.safe_load(path.read_text())
    return loaded if isinstance(loaded, dict) else {}


def _build_orchestrator(
    config: dict[str, Any],
    audit_root: Path,
    *,
    reference_manifest: Sequence[ReferenceArtifact] | None = None,
) -> AuditOrchestrator:
    return AuditOrchestrator(
        audit_root=audit_root,
        endpoint=config.get(
            "endpoint", "https://api.sleeper.app/v1/players/nfl"
        ),
        staleness_threshold_seconds=float(
            config.get("staleness_threshold_seconds", 6 * 3600)
        ),
        nflverse_qb_path=config.get("nflverse_qb_path"),
        hof_fixture_path=config.get("hof_fixture_path"),
        reference_manifest=reference_manifest,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one Sleeper QB source-audit pass."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "config" / "sleeper_qb_audit_v1.yaml",
        help="Path to the audit YAML config.",
    )
    parser.add_argument(
        "--kind",
        default="scheduled",
        choices=["scheduled", "pregame", "postgame"],
        help="Audit run kind.",
    )
    parser.add_argument(
        "--lock-timeout-seconds",
        type=float,
        default=0.0,
        help="Maximum wall-clock seconds to wait for the audit lock; 0 means fail fast.",
    )
    parser.add_argument(
        "--use-fake-session",
        action="store_true",
        help="Use the deterministic stub session (tests only).",
    )
    parser.add_argument(
        "--reference-manifest",
        type=Path,
        default=None,
        help="Optional path to a JSON file listing {path, sha256, row_count} entries to verify before the run.",
    )
    parser.add_argument(
        "--observed-at-utc",
        default=None,
        help="Override the audit's notion of now (ISO 8601). Tests only.",
    )
    parser.add_argument(
        "--snapshot-id",
        default=None,
        help="Override the deterministic snapshot id. Tests only.",
    )
    args = parser.parse_args(argv)

    config = _load_config(args.config)
    audit_root = Path(config.get("audit_root", "data/source_audits/sleeper_qb_v1"))
    audit_root.mkdir(parents=True, exist_ok=True)

    reference_manifest: list[ReferenceArtifact] = []
    # CLI flag overrides config. If neither is set, the audit
    # silently skips reference verification — a deliberate opt-in
    # to keep the default behavior identical to the historical
    # sub-phase A contract.
    manifest_source: Path | None = None
    if args.reference_manifest is not None:
        manifest_source = args.reference_manifest
    elif "reference_manifest" in config:
        manifest_source = Path(str(config["reference_manifest"]))
    if manifest_source is not None and manifest_source.exists():
        raw = json.loads(manifest_source.read_text())
        for entry in raw.get("artifacts", []):
            reference_manifest.append(
                ReferenceArtifact(
                    path=str(entry["path"]),
                    sha256=str(entry["sha256"]),
                    row_count=int(entry["row_count"]),
                )
            )

    session = None
    if args.use_fake_session:
        from scripts._sleeper_fake_session import FakeSleeperSession

        session = FakeSleeperSession()

    try:
        with advisory_lock(
            audit_root,
            kind=args.kind,
            lock_timeout_seconds=args.lock_timeout_seconds,
        ):
            orchestrator = _build_orchestrator(
                config, audit_root, reference_manifest=reference_manifest
            )
            result = orchestrator.run(
                session=session,
                kind=args.kind,
                forced_observed_at_utc=args.observed_at_utc,
                forced_snapshot_id=args.snapshot_id,
            )
    except LockFailure as exc:
        print(
            json.dumps(
                {
                    "run_outcome": RunOutcome.LOCK_FAILURE.value,
                    "exit_code": EXIT_CODES[RunOutcome.LOCK_FAILURE],
                    "error_class": "LockFailure",
                    "error_message": str(exc),
                },
                indent=2,
                default=str,
            ),
            file=sys.stderr,
        )
        return EXIT_CODES[RunOutcome.LOCK_FAILURE]

    print(json.dumps(result, indent=2, default=str))
    return int(result.get("exit_code", EXIT_CODES[RunOutcome.SUCCESS]))


if __name__ == "__main__":
    raise SystemExit(main())
