"""Bounded NFLverse retrieval and deterministic compact-table generation."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import nflreadpy as nfl
import polars as pl

from .integrity import canonical_schema_fingerprint, normalize_player_id, normalize_team, sha256_file

DEFAULT_SEASONS = tuple(range(2018, 2026))
DATA_VERSION = "frozen-baseline-v1"
SOURCE_LOCATOR = "https://github.com/nflverse/nflverse-data/releases"

SOURCE_SPECS: dict[str, dict[str, Any]] = {
    "schedules": {"loader": "load_schedules", "purpose": "schedule, results, venue, roof, kickoff source fields"},
    "team_stats_week": {"loader": "load_team_stats", "purpose": "completed team-game statistics"},
    "player_stats_week": {"loader": "load_player_stats", "purpose": "weekly player and quarterback statistics"},
    "rosters": {"loader": "load_rosters", "purpose": "season roster identity and status"},
    "depth_charts": {"loader": "load_depth_charts", "purpose": "depth-chart player/position snapshots"},
    "snap_counts": {"loader": "load_snap_counts", "purpose": "starter/participation evidence"},
    "injuries": {"loader": "load_injuries", "purpose": "injury and practice status availability audit"},
}


def _load(name: str, seasons: list[int]) -> pl.DataFrame:
    if name == "schedules":
        return nfl.load_schedules(seasons)
    if name == "player_stats_week":
        return nfl.load_player_stats(seasons, summary_level="week")
    if name == "team_stats_week":
        return nfl.load_team_stats(seasons, summary_level="week")
    return getattr(nfl, SOURCE_SPECS[name]["loader"])(seasons)


def retrieve_sources(
    seasons: list[int] | tuple[int, ...] = DEFAULT_SEASONS,
    raw_dir: str | Path = "data/raw/source_snapshots/v1",
    manifest_dir: str | Path = "data/manifests",
    retrieved_at_utc: str | None = None,
    retries: int = 3,
    backoff_seconds: float = 1.0,
    loader: Callable[[str, list[int]], pl.DataFrame] = _load,
) -> list[dict[str, Any]]:
    seasons = [int(x) for x in seasons]
    if not seasons:
        raise ValueError("explicit non-empty season list is required")
    raw_dir, manifest_dir = Path(raw_dir), Path(manifest_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    retrieved_at_utc = retrieved_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifests: list[dict[str, Any]] = []
    for name in SOURCE_SPECS:
        path = raw_dir / f"{name}_{seasons[0]}_{seasons[-1]}_{DATA_VERSION}.parquet"
        if path.exists():
            raise FileExistsError(f"frozen source already exists: {path}")
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                frame = loader(name, seasons)
                break
            except Exception as exc:  # pragma: no cover - exercised with injected loader
                last_error = exc
                if attempt + 1 < retries:
                    time.sleep(backoff_seconds * (2**attempt))
        else:
            raise RuntimeError(f"failed to retrieve {name}") from last_error
        frame.write_parquet(path)
        entry = {
            "source_id": f"nflverse-{name}-{DATA_VERSION}",
            "source_name": name,
            "source_locator": SOURCE_LOCATOR,
            "retrieved_at_utc": retrieved_at_utc,
            "seasons": seasons,
            "file_name": str(path),
            "compression": "parquet",
            "byte_size": path.stat().st_size,
            "sha256": sha256_file(path),
            "row_count": frame.height,
            "column_count": len(frame.columns),
            "schema_fingerprint": canonical_schema_fingerprint(frame.columns),
            "columns": frame.columns,
            "license_or_terms_note": "NFLverse data; consult upstream repository terms and attribution requirements.",
        }
        manifests.append(entry)
        (manifest_dir / f"{name}_{DATA_VERSION}.json").write_text(json.dumps(entry, indent=2) + "\n")
    return manifests


def _scheduled_start() -> pl.Expr:
    """Return null until venue timezone and DST conversion is audited."""
    return pl.lit(None, dtype=pl.String)


def _write_frozen(frame: pl.DataFrame, path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    if path.exists():
        raise FileExistsError(f"frozen output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)
    return {
        **metadata,
        "file_name": str(path),
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
        "row_count": frame.height,
        "column_count": len(frame.columns),
        "columns": frame.columns,
        "schema_fingerprint": canonical_schema_fingerprint(frame.columns),
    }


def build_frozen_baseline(
    raw_dir: str | Path = "data/raw/source_snapshots/v1",
    output_root: str | Path = "data/frozen",
    manifest_dir: str | Path = "data/manifests",
    created_at_utc: str | None = None,
) -> list[dict[str, Any]]:
    created_at_utc = created_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    raw_dir, output_root, manifest_dir = Path(raw_dir), Path(output_root), Path(manifest_dir)
    files = {}
    for name in SOURCE_SPECS:
        matches = sorted(raw_dir.glob(f"{name}_*.parquet"))
        if len(matches) != 1:
            raise ValueError(f"expected exactly one frozen snapshot for {name}, found {len(matches)}")
        files[name] = matches[0]
    schedules = pl.read_parquet(files["schedules"])
    games = schedules.select([
        pl.col("game_id"), pl.col("season"), pl.col("game_type").alias("season_type"), pl.col("week"),
        pl.col("away_team").map_elements(normalize_team, return_dtype=pl.String).alias("away_team"),
        pl.col("home_team").map_elements(normalize_team, return_dtype=pl.String).alias("home_team"),
        pl.col("away_score"), pl.col("home_score"), pl.col("location").alias("neutral_site_source"),
        pl.col("stadium_id").alias("venue_id"),
        pl.col("stadium").alias("venue_name"),
        pl.col("roof").alias("roof_type"),
        pl.col("gameday"), pl.col("gametime"), _scheduled_start().alias("scheduled_start_utc"),
        pl.lit(None, dtype=pl.String).alias("game_end_utc"),
        pl.lit("after_official_weekly_publication").alias(
            "completed_game_availability_rule"
        ),
        pl.col("game_id").alias("source_game_id"),
        pl.lit(None, dtype=pl.String).alias("observed_at_utc"),
    ])
    outputs: list[dict[str, Any]] = []
    common = {
        "data_version": DATA_VERSION,
        "source_manifest_ids": [f"nflverse-schedules-{DATA_VERSION}"],
        "transform_version": "normalize-v1",
        "created_at_utc": created_at_utc,
        "min_event_time_utc": str(games.select(pl.col("gameday").min()).item()),
        "max_event_time_utc": str(games.select(pl.col("gameday").max()).item()),
    }
    outputs.append(_write_frozen(games, output_root / "games" / "games_2018_2025.parquet", common))

    team = pl.read_parquet(files["team_stats_week"]).select(
        [
            pl.col("game_id"), pl.col("season"), pl.col("week"),
            pl.col("season_type"),
            pl.col("team").map_elements(normalize_team, return_dtype=pl.String),
            pl.col("opponent_team").map_elements(
                normalize_team, return_dtype=pl.String
            ).alias("opponent"),
            pl.col("passing_epa"), pl.col("rushing_epa"),
            pl.col("passing_yards"), pl.col("rushing_yards"),
            pl.lit(None, dtype=pl.String).alias("game_end_utc"),
            pl.lit(None, dtype=pl.String).alias("observed_at_utc"),
        ]
    )
    outputs.append(_write_frozen(
        team, output_root / "team_game_stats" / "team_game_stats_2018_2025.parquet",
        {**common, "source_manifest_ids": [f"nflverse-team_stats_week-{DATA_VERSION}"]},
    ))

    player = pl.read_parquet(files["player_stats_week"])
    qb = player.filter(pl.col("position").is_in(["QB", "qb"])).select(
        [
            pl.col("game_id"), pl.col("season"), pl.col("week"),
            pl.col("season_type"),
            pl.col("team").map_elements(normalize_team, return_dtype=pl.String),
            pl.col("player_id").map_elements(
                normalize_player_id, return_dtype=pl.String
            ),
            pl.col("player_name"), pl.col("passing_epa"),
            pl.col("passing_cpoe"), pl.col("attempts"),
            pl.col("sacks_suffered"), pl.col("passing_interceptions"),
            pl.lit(None, dtype=pl.String).alias("game_end_utc"),
            pl.lit(None, dtype=pl.String).alias("observed_at_utc"),
        ]
    )
    outputs.append(_write_frozen(
        qb, output_root / "qb_game_stats" / "qb_game_stats_2018_2025.parquet",
        {**common, "source_manifest_ids": [f"nflverse-player_stats_week-{DATA_VERSION}"]},
    ))

    depth = pl.read_parquet(files["depth_charts"]).select(
        [
            pl.col("season"), pl.col("week"),
            pl.col("team").map_elements(normalize_team, return_dtype=pl.String),
            pl.col("gsis_id").map_elements(
                normalize_player_id, return_dtype=pl.String
            ).alias("player_id"),
            pl.col("player_name"), pl.col("pos_name"),
            pl.col("pos_slot"), pl.col("pos_rank"),
            pl.col("dt").alias("source_dt"),
            pl.lit("batch_or_source_defined; record-level historical availability not proven").alias(
                "timestamp_quality"
            ),
            pl.lit(None, dtype=pl.String).alias("observed_at_utc"),
        ]
    )
    outputs.append(_write_frozen(
        depth, output_root / "depth_chart_snapshots" / "depth_chart_snapshots_2018_2025.parquet",
        {**common, "source_manifest_ids": [f"nflverse-depth_charts-{DATA_VERSION}"]},
    ))

    rosters = pl.read_parquet(files["rosters"]).select(
        [
            pl.col("season"), pl.col("week"),
            pl.col("team").map_elements(normalize_team, return_dtype=pl.String),
            pl.col("gsis_id").map_elements(
                normalize_player_id, return_dtype=pl.String
            ).alias("player_id"),
            pl.col("full_name"), pl.col("position"),
            pl.col("status"), pl.col("rookie_year"),
            pl.lit("season_or_week_batch").alias("timestamp_quality"),
        ]
    )
    outputs.append(_write_frozen(
        rosters, output_root / "rosters" / "rosters_2018_2025.parquet",
        {**common, "source_manifest_ids": [f"nflverse-rosters-{DATA_VERSION}"]},
    ))

    venues = schedules.select(
        [
            pl.col("stadium_id").alias("venue_id"),
            pl.col("stadium").alias("venue_name"),
            pl.col("roof").alias("roof_type"),
            pl.col("location").alias("neutral_site_source"),
        ]
    ).unique(subset=["venue_id"], keep="first").sort("venue_id")
    outputs.append(_write_frozen(
        venues, output_root / "venues" / "venues_2018_2025.parquet",
        {**common, "source_manifest_ids": [f"nflverse-schedules-{DATA_VERSION}"]},
    ))
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / f"frozen_outputs_{DATA_VERSION}.json").write_text(json.dumps(outputs, indent=2) + "\n")
    return outputs
