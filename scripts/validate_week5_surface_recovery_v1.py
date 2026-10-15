#!/usr/bin/env python3
"""Acquire only free nflverse inputs, then replay settled materialization offline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import requests  # noqa: E402

from nfl_edge.live.evidence_2026 import (  # noqa: E402
    NFLVERSE_GAMES_URL,
    PBP_URL,
    PLAYER_STATS_URL,
    TEAM_STATS_URL,
    materialize_settled_evidence,
)
from nfl_edge.live.schedule_materializer_2026 import materialize_active_schedule  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    rawroot = root / "raw"
    rawroot.mkdir(exist_ok=True)
    for key in list(os.environ):
        if "ODDS" in key.upper() and ("KEY" in key.upper() or "TOKEN" in key.upper()):
            del os.environ[key]
    names = {
        NFLVERSE_GAMES_URL: "games.csv",
        TEAM_STATS_URL: "team-stats.parquet",
        PLAYER_STATS_URL: "player-stats.parquet",
        PBP_URL: "pbp.parquet",
    }
    cached = {}
    sources = []

    class SourceSession:
        def get(self, url, **kwargs):
            if url not in names:
                raise AssertionError(f"non-nflverse request denied: {url}")
            print("FREE_SOURCE_FETCH", names[url], flush=True)
            response = requests.get(url, timeout=60)
            sources.append(
                {
                    "url": url,
                    "status_code": response.status_code,
                    "bytes": len(response.content),
                    "sha256": hashlib.sha256(response.content).hexdigest(),
                }
            )
            if response.status_code == 200:
                cached[url] = response
                (rawroot / names[url]).write_bytes(response.content)
            return response

    class OfflineSession:
        def get(self, url, **kwargs):
            if url not in cached:
                raise AssertionError(f"uncached offline source: {url}")
            return cached[url]

    result = {
        "verdict": "BLOCKED_NFL_EDGE_WEEK6_RECOVERY",
        "provider_request_count": 0,
        "odds_api_called": False,
        "market_data_read": False,
        "active_as_of_utc": "2026-10-13T12:00:00Z",
    }
    try:
        response = SourceSession().get(NFLVERSE_GAMES_URL)
        response.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(response.content.decode())))
        path, active = materialize_active_schedule(
            output_dir=root / "active-schedule", rows=rows, active_as_of_utc=result["active_as_of_utc"]
        )
        result["week6_schedule"] = {
            "season": active["season"],
            "week": active["week"],
            "game_count": len(active["games"]),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        assert active["week"] == 6 and len(active["games"]) == 14
        # Only this acquisition pass can access the fixed free-source allowlist.
        evidence = materialize_settled_evidence(
            output_dir=root / "acquisition",
            schedule_rows=rows,
            active_as_of_utc=result["active_as_of_utc"],
            session=SourceSession(),
        )
        result["settled_through_week"] = evidence.through_week
        result["settled_row_counts"] = evidence.manifest["row_counts"]
        result["surface_recovery_count"] = len(evidence.manifest.get("surface_recovery", []))
        assert evidence.through_week == 5 and evidence.games["week"].max() == 5
        with patch("requests.sessions.Session.request", side_effect=AssertionError("offline network denied")):
            replay = materialize_settled_evidence(
                output_dir=root / "offline-replay",
                schedule_rows=rows,
                active_as_of_utc=result["active_as_of_utc"],
                session=OfflineSession(),
            )
        assert all(
            getattr(evidence, name).equals(getattr(replay, name)) for name in ("games", "team_stats", "qb_stats", "pbp")
        )
        result["offline_replay"] = "PASS"
        result["verdict"] = "SETTLED_EVIDENCE_READY_PREPROVIDER_PENDING"
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
        result["traceback"] = traceback.format_exc()
    result["free_source_requests"] = sources
    result["observed_at_utc"] = datetime.now(timezone.utc).isoformat()
    (root / "validation-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["verdict"] == "SETTLED_EVIDENCE_READY_PREPROVIDER_PENDING" else 1


if __name__ == "__main__":
    raise SystemExit(main())
