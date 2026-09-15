#!/usr/bin/env python3
"""Report-only current nflverse 2026 source-contract diagnostic; no paid calls."""

from __future__ import annotations

import argparse
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import requests

from nfl_edge.live.evidence_2026 import PBP_URL, PLAYER_STATS_URL, TEAM_STATS_URL
from nfl_edge.live.schedule_materializer_2026 import NFLVERSE_GAMES_URL


def _inventory(frame: pl.DataFrame, field: str) -> dict[str, object]:
    if field not in frame.columns:
        return {"present": False}
    values = frame.get_column(field).cast(pl.Utf8, strict=False).str.strip_chars()
    missing = values.is_null() | (values == "")
    affected = frame.filter(missing).group_by("week").len().sort("week").to_dicts() if "week" in frame.columns else []
    return {
        "present": True,
        "blank_or_null_count": int(missing.sum()),
        "weeks_affected": affected,
        "values": values.filter(~missing).unique().sort().to_list(),
    }


def _parquet(url: str) -> pl.DataFrame:
    response = requests.get(url, timeout=180)
    response.raise_for_status()
    return pl.read_parquet(io.BytesIO(response.content))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    schedule_response = requests.get(NFLVERSE_GAMES_URL, timeout=60)
    schedule_response.raise_for_status()
    schedule = pl.DataFrame(list(csv.DictReader(io.StringIO(schedule_response.text)))).filter(
        (pl.col("season").cast(pl.Int64) == 2026) & (pl.col("game_type") == "REG")
    )
    sources = {
        "schedule": schedule,
        "team_weekly": _parquet(TEAM_STATS_URL).filter(pl.col("season") == 2026),
        "player_weekly": _parquet(PLAYER_STATS_URL).filter(pl.col("season") == 2026),
        "pbp": _parquet(PBP_URL).filter(pl.col("season") == 2026),
    }
    fields = {
        "schedule": [
            "game_id",
            "season",
            "game_type",
            "week",
            "gameday",
            "gametime",
            "away_team",
            "home_team",
            "roof",
            "surface",
            "stadium",
            "stadium_id",
            "location",
            "away_rest",
            "home_rest",
        ],
        "team_weekly": [
            "game_id",
            "season",
            "week",
            "team",
            "passing_epa",
            "rushing_epa",
            "passing_yards",
            "rushing_yards",
        ],
        "player_weekly": [
            "game_id",
            "season",
            "week",
            "team",
            "player_id",
            "position",
            "attempts",
            "sacks_suffered",
            "passing_epa",
            "passing_cpoe",
            "passing_interceptions",
        ],
        "pbp": [
            "game_id",
            "home_team",
            "away_team",
            "qtr",
            "play_id",
            "game_seconds_remaining",
            "total_home_score",
            "total_away_score",
        ],
    }
    report = {
        "schema_version": "nfl-edge-live-2026-nflverse-source-audit-v1",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "sources": {
            name: {
                "rows": frame.height,
                "columns": frame.columns,
                "game_counts_by_week": frame.group_by("week").len().sort("week").to_dicts(),
                "fields": {field: _inventory(frame, field) for field in fields[name]},
            }
            for name, frame in sources.items()
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
