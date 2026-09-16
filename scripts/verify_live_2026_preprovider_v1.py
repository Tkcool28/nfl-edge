#!/usr/bin/env python3
"""Verify the live 2026 production chain through the final pre-provider gate.

This command intentionally performs no sportsbook market acquisition. It proves
schedule resolution, settled-evidence loading, football-state advancement,
Sleeper readiness, current-week football scoring, and causal selector-state
advancement using the same production components as production_refresh_v1.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nfl_edge.live.evidence_2026 import load_settled_evidence  # noqa: E402
from nfl_edge.live.product_state_2026 import (  # noqa: E402
    advance_live_value_state,
    load_entering_2026_product_state,
)
from nfl_edge.live.schedule_2026 import resolve_active_schedule  # noqa: E402
from nfl_edge.live.scorer_2026 import score_week  # noqa: E402
from nfl_edge.live.sleeper_qb import (  # noqa: E402
    DEFAULT_OVERRIDES,
    SleeperExpectedQBResolver,
    SleeperQBSource,
    load_overrides,
)
from nfl_edge.live.state_advancement_2026 import (  # noqa: E402
    advance_entering_state_through_settled_weeks,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--schedule-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--prediction-as-of-utc", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    root = args.repository_root.resolve()

    active = resolve_active_schedule(
        root,
        prediction_as_of_utc=args.prediction_as_of_utc,
        schedule_root=args.schedule_root,
    )
    evidence = load_settled_evidence(args.evidence_root)
    state = advance_entering_state_through_settled_weeks(
        repository_root=root,
        active_schedule_path=active.path,
        evidence=evidence,
    )
    prior_live_inputs = evidence.feature_inputs()

    sleeper = SleeperQBSource.load(root, prediction_as_of_utc=args.prediction_as_of_utc)
    if sleeper.freshness_state != "FRESH" or sleeper.source_warning_state is not None:
        raise RuntimeError(
            "Sleeper source is not ready: "
            f"freshness={sleeper.freshness_state} warning={sleeper.source_warning_state}"
        )
    resolver = SleeperExpectedQBResolver(
        sleeper,
        overrides=load_overrides(root / DEFAULT_OVERRIDES),
    )
    football = score_week(
        repository_root=root,
        prediction_as_of_utc=args.prediction_as_of_utc,
        resolver=resolver,
        schedule_path=active.path,
        entering_state=state,
        prior_live_inputs=prior_live_inputs,
    )

    decision_state = load_entering_2026_product_state(
        root / "data/live/2026/entering_product_state_v1.json"
    )
    if active.week > 1:
        decision_state["value_state"] = advance_live_value_state(
            entering=decision_state["value_state"],
            evidence=evidence,
            run_root=args.run_root,
            repository_root=root,
        )
    value_state = decision_state["value_state"]

    proof = {
        "verdict": "NFL_EDGE_PREPROVIDER_READY",
        "season": active.season,
        "week": active.week,
        "schedule_version": str(active.payload["schedule_version"]),
        "schedule_path": str(active.path),
        "settled_through_week": evidence.through_week,
        "completed_2026_blocks": list(state.completed_2026_blocks),
        "football_state_version": state.state_version,
        "sleeper_snapshot_id": sleeper.snapshot_id,
        "sleeper_freshness": sleeper.freshness_state,
        "football_game_count": len(football["games"]),
        "football_snapshot_sha256": football["snapshot_sha256"],
        "selector_state_observations": {
            "moneyline": len(value_state.ml_observations),
            "spread": len(value_state.spread_observations),
        },
        "provider_request_count": 0,
        "odds_api_called": False,
        "market_data_read": False,
    }
    print(json.dumps(proof, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
