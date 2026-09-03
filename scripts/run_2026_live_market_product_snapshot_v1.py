#!/usr/bin/env python3
"""Acquire/replay 2026 Week 1 markets and materialize NFL_EDGE_PRODUCT_API_V1.

Ordinary invocation is replay-only. A billable The Odds API request is possible
only with the explicit --live flag and is exactly one bounded HTTP attempt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from nfl_edge.live.markets_2026 import (
    acquire_live_response,
    build_request_plan,
    load_capture,
    market_snapshot_bytes,
    normalize_market_snapshot,
)
from nfl_edge.live.product_2026 import build_product_snapshot, product_snapshot_bytes
from nfl_edge.live.product_state_2026 import load_entering_2026_product_state
from nfl_edge.live.week1_2026 import load_week1_schedule

ROOT = Path(__file__).resolve().parents[1]
SCHEDULE = ROOT / "data/live/2026/week1_schedule_v1.json"
DEFAULT_STATE = ROOT / "data/live/2026/entering_product_state_v1.json"


def _json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON root must be an object: {path}")
    return payload


def _write_json(path: Path, payload: dict) -> bytes:
    raw = (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--football-snapshot", type=Path, required=True)
    parser.add_argument("--decision-state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--output-dir", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--live", action="store_true")
    source.add_argument("--market-response", type=Path)
    parser.add_argument("--market-metadata", type=Path)
    parser.add_argument(
        "--acquired-at-utc",
        help="Required only when replay response has no metadata sidecar.",
    )
    args = parser.parse_args()

    schedule = load_week1_schedule(SCHEDULE)
    football = _json(args.football_snapshot)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.live:
        capture = acquire_live_response(
            schedule=schedule,
            output_dir=args.output_dir / "raw",
            live=True,
        )
        events, metadata = load_capture(
            capture.response_path,
            metadata_path=capture.metadata_path,
        )
        billable_requests = 1
        raw_response_path = capture.response_path
        metadata_path = capture.metadata_path
    else:
        events, metadata = load_capture(
            args.market_response,
            metadata_path=args.market_metadata,
            acquired_at_utc=args.acquired_at_utc,
        )
        billable_requests = 0
        raw_response_path = args.market_response
        metadata_path = args.market_metadata

    market = normalize_market_snapshot(
        schedule=schedule,
        events=events,
        acquired_at_utc=str(metadata["acquired_at_utc"]),
        response_sha256=str(metadata["response_sha256"]),
        credits_consumed=metadata.get("credits_consumed"),
        credits_remaining=metadata.get("credits_remaining"),
    )
    market_raw = market_snapshot_bytes(market)
    market_path = args.output_dir / "NFL_EDGE_LIVE_MARKET_V1.json"
    market_path.write_bytes(market_raw)

    decision_state = load_entering_2026_product_state(args.decision_state)
    first, first_proof = build_product_snapshot(
        root=ROOT,
        football_snapshot=football,
        market_snapshot=market,
        decision_state=decision_state,
    )
    second, second_proof = build_product_snapshot(
        root=ROOT,
        football_snapshot=football,
        market_snapshot=market,
        decision_state=decision_state,
    )
    first_bytes = product_snapshot_bytes(first)
    second_bytes = product_snapshot_bytes(second)
    if first_bytes != second_bytes:
        raise RuntimeError("deterministic product replay failed: canonical output bytes differ")
    if first_proof != second_proof:
        raise RuntimeError("deterministic product replay failed: proof objects differ")

    product_path = args.output_dir / "NFL_EDGE_PRODUCT_API_V1.json"
    product_path.write_bytes(first_bytes)
    proof = {
        **first_proof,
        "market_snapshot_sha256": market["snapshot_sha256"],
        "market_response_sha256": metadata["response_sha256"],
        "raw_market_response_path": str(raw_response_path),
        "market_metadata_path": None if metadata_path is None else str(metadata_path),
        "provider_events": market["audit"]["provider_events_returned"],
        "canonical_game_matches": market["audit"]["matched_canonical_games"],
        "coverage_by_book": market["coverage_by_book"],
        "coverage_by_market": market["coverage_by_market"],
        "unmatched_provider_events": len(market["audit"]["unmatched_provider_event_ids"]),
        "unmatched_canonical_games": len(market["audit"]["unmatched_canonical_game_ids"]),
        "ambiguous_provider_events": len(market["audit"]["ambiguous_provider_events"]),
        "duplicate_mappings": len(market["audit"]["duplicate_mappings"]),
        "exact_duplicates": int(market["audit"]["exact_duplicates"]),
        "live_billable_request_count": billable_requests,
        "expected_credit_cost_per_live_request": int(build_request_plan(schedule)["expected_credit_cost"]),
        "credits_consumed": metadata.get("credits_consumed"),
        "credits_remaining": metadata.get("credits_remaining"),
        "deterministic_replay": "PASS",
        "replay_additional_market_api_calls": 0,
        "ordinary_ci_live_market_api_calls": 0,
        "methodology_changed": False,
        "evaluator_methodology_changed": False,
        "selector_methodology_changed": False,
        "staking_methodology_changed": False,
    }
    proof_path = args.output_dir / "proof.json"
    proof_raw = _write_json(proof_path, proof)

    print(
        json.dumps(
            {
                "status": "2026_LIVE_PRODUCT_SNAPSHOT_MATERIALIZED",
                "mode": "LIVE" if args.live else "REPLAY",
                "product": str(product_path),
                "product_sha256": hashlib.sha256(first_bytes).hexdigest(),
                "market": str(market_path),
                "market_sha256": hashlib.sha256(market_raw).hexdigest(),
                "proof": str(proof_path),
                "proof_sha256": hashlib.sha256(proof_raw).hexdigest(),
                "billable_requests": billable_requests,
                "credits_consumed": metadata.get("credits_consumed"),
                "credits_remaining": metadata.get("credits_remaining"),
                "matched_games": market["audit"]["matched_canonical_games"],
                "headline_states": first_proof["headline_states"],
                "deterministic_replay": "PASS",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
