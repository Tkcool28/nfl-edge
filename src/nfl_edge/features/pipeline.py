"""End-to-end deterministic feature bundle construction and artifact writing."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from .availability import AvailabilityPolicy, build_weekly_availability
from .qb import build_qb_pregame_features
from .starters import resolve_starter_certainty, starter_scenarios
from .team import build_team_pregame_features
from .validation import (
    assert_no_market_columns,
    assert_unique_keys,
    canonical_json_sha256,
    logical_frame_fingerprint,
    schema_fingerprint,
)

FEATURE_VERSION = "features-v1"
DATA_VERSION = "frozen-baseline-v1"
SOURCE_MANIFEST_IDS = [
    "nflverse-schedules-frozen-baseline-v1",
    "nflverse-team_stats_week-frozen-baseline-v1",
    "nflverse-player_stats_week-frozen-baseline-v1",
    "nflverse-rosters-frozen-baseline-v1",
    "nflverse-depth_charts-frozen-baseline-v1",
]
OUTPUT_NAMES = {
    "game_features": "game_features_2018_2025.parquet",
    "team_features": "team_pregame_features_2018_2025.parquet",
    "qb_features": "qb_pregame_features_2018_2025.parquet",
    "starter_certainty": "starter_certainty_2018_2025.parquet",
    "weekly_availability": "weekly_availability_2018_2025.parquet",
    "feature_registry": "feature_registry_v1.json",
}
IDENTITY_COLUMNS = {
    "game_id",
    "season",
    "season_type",
    "week",
    "home_team",
    "away_team",
    "feature_as_of_utc",
    "prediction_as_of_utc",
    "source_available_at_utc",
    "scheduled_start_utc",
    "availability_rule",
    "feature_version",
    "data_version",
    "target_home_win",
    "target_margin",
    "target_tie",
    "target_available",
    "expected_home_qb_id",
    "expected_away_qb_id",
    "qb_status",
}


@dataclass(frozen=True)
class FeatureInputs:
    games: pl.DataFrame
    team_stats: pl.DataFrame
    qb_stats: pl.DataFrame
    depth_charts: pl.DataFrame
    rosters: pl.DataFrame
    postgame_evidence: pl.DataFrame | None = None

    @classmethod
    def from_repository(cls, root: str | Path) -> "FeatureInputs":
        root = Path(root)
        frozen = root / "data" / "frozen"
        return cls(
            games=pl.read_parquet(frozen / "games" / "games_2018_2025.parquet"),
            team_stats=pl.read_parquet(frozen / "team_game_stats" / "team_game_stats_2018_2025.parquet"),
            qb_stats=pl.read_parquet(frozen / "qb_game_stats" / "qb_game_stats_2018_2025.parquet"),
            depth_charts=pl.read_parquet(
                frozen / "depth_chart_snapshots" / "depth_chart_snapshots_2018_2025.parquet"
            ),
            rosters=pl.read_parquet(frozen / "rosters" / "rosters_2018_2025.parquet"),
        )

    def replace(self, **changes: Any) -> "FeatureInputs":
        return dataclass_replace(self, **changes)


@dataclass(frozen=True)
class FeatureBundle:
    game_features: pl.DataFrame
    team_features: pl.DataFrame
    qb_features: pl.DataFrame
    starter_certainty: pl.DataFrame
    weekly_availability: pl.DataFrame
    feature_registry: list[dict[str, Any]]
    model_feature_columns: tuple[str, ...]
    config: dict[str, Any]

    def frames(self) -> tuple[pl.DataFrame, ...]:
        return (
            self.game_features,
            self.team_features,
            self.qb_features,
            self.starter_certainty,
            self.weekly_availability,
        )


def load_feature_config(path: str | Path) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text())
    if config.get("version") != "feature-config-v1":
        raise ValueError("unsupported feature configuration version")
    if config["availability"]["timezone"] != "UTC":
        raise ValueError("feature availability must use UTC")
    return config


def _availability_policy(config: dict[str, Any]) -> AvailabilityPolicy:
    value = config["availability"]
    return AvailabilityPolicy(
        weekday=int(value["weekly_publication_weekday"]),
        hour=int(value["weekly_publication_hour"]),
        minute=int(value["weekly_publication_minute"]),
        timezone_name=value["timezone"],
        unusual_date_policy=value["unusual_date_policy"].upper(),
    )


def _postgame_evidence(qb_stats: pl.DataFrame) -> pl.DataFrame:
    if qb_stats.is_empty():
        return pl.DataFrame(
            schema={"game_id": pl.String, "team": pl.String, "player_id": pl.String, "evidence_type": pl.String}
        )
    return qb_stats.select("game_id", "team", "player_id").with_columns(
        pl.lit("WEEKLY_STATS_POSTGAME").alias("evidence_type")
    )


def _team_wide(team: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for game_id, frame in team.group_by("game_id", maintain_order=True):
        game_key = game_id[0] if isinstance(game_id, tuple) else game_id
        output: dict[str, Any] = {"game_id": game_key}
        for row in frame.to_dicts():
            prefix = "home" if row["side"] == "home" else "away"
            for key, value in row.items():
                if key in {
                    "game_id",
                    "season",
                    "season_type",
                    "week",
                    "team",
                    "opponent",
                    "side",
                    "feature_as_of_utc",
                    "source_available_at_utc",
                    "venue_id",
                    "venue_missing",
                    "roof_category",
                    "roof_missing",
                    "neutral_site",
                }:
                    continue
                output[f"{prefix}_{key}"] = value
            if prefix == "home":
                output.update(
                    {
                        "neutral_site": row["neutral_site"],
                        "venue_id": row["venue_id"],
                        "venue_missing": row["venue_missing"],
                        "roof_category": row["roof_category"],
                        "roof_missing": row["roof_missing"],
                    }
                )
        rows.append(output)
    return pl.DataFrame(rows).sort("game_id")


def _model_feature_columns(frame: pl.DataFrame) -> tuple[str, ...]:
    columns = []
    for column in frame.columns:
        if column in IDENTITY_COLUMNS or column in {"venue_id"}:
            continue
        if column.startswith("home_") or column.startswith("away_") or column in {
            "neutral_site",
            "venue_missing",
            "roof_category",
            "roof_missing",
        }:
            columns.append(column)
    assert_no_market_columns(columns)
    return tuple(columns)


def build_feature_registry(
    game_features: pl.DataFrame,
    config: dict[str, Any],
    model_columns: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    model_columns = model_columns or _model_feature_columns(game_features)
    short = int(config["rolling_windows"]["short_games"])
    medium = int(config["rolling_windows"]["medium_games"])
    count_suffixes = {
        "games_played_before_current_game",
        "prior_season_carryover_games",
        "early_season_sample",
        f"roll{short}_prior_games",
        f"roll{medium}_prior_games",
        "season_to_date_prior_games",
        f"roll{short}_minimum_sample_met",
        f"roll{medium}_minimum_sample_met",
        "season_to_date_minimum_sample_met",
    }
    state_or_context_columns = {
        "is_home",
        "neutral_site",
        "venue_missing",
        "roof_missing",
        "roof_category",
        "rest_or_week_gap",
        "week_gap_proxy",
        "bye_week_proxy",
        "prior_season_carryover_used",
    }
    entries: list[dict[str, Any]] = []
    for column in model_columns:
        suffix = column[len("home_"):] if column.startswith("home_") else (
            column[len("away_"):] if column.startswith("away_") else column
        )
        if suffix in count_suffixes:
            classification = "count_or_sample_size"
            window = "none"
            transformation = "eligible_prior_history_size"
        elif suffix in state_or_context_columns or column in state_or_context_columns:
            classification = "game_state_or_context"
            window = "none"
            transformation = "joined_from_games_or_derived_from_history_size"
        else:
            classification = "rolling_metric"
            if suffix.startswith(f"roll{short}_"):
                window = f"last_{short}_eligible_games"
            elif suffix.startswith(f"roll{medium}_"):
                window = f"last_{medium}_eligible_games"
            elif suffix.startswith("season_to_date_"):
                window = "current_season_prior_eligible_games"
            else:
                window = "none"
            transformation = "shift_before_rolling_then_fixed_prior_if_missing"
        if classification == "rolling_metric":
            if "offensive_total_epa" in column:
                source_columns = ["offensive_total_epa"]
            elif "defensive_epa_allowed" in column:
                source_columns = ["defensive_epa_allowed"]
            else:
                source_columns = [suffix]
        else:
            source_columns = [column]
        source_table = (
            "games"
            if suffix in state_or_context_columns or column in state_or_context_columns
            else "team_game_stats+games"
        )
        description = {
            "count_or_sample_size": f"Sample-size indicator: {column.replace('_', ' ')}.",
            "game_state_or_context": f"Game-level state or context: {column.replace('_', ' ')}.",
            "rolling_metric": f"Leakage-safe pregame rolling {column.replace('_', ' ')}.",
        }[classification]
        entries.append(
            {
                "feature_name": column,
                "description": description,
                "classification": classification,
                "source_table": source_table,
                "source_columns": source_columns,
                "availability_rule": _availability_policy(config).rule_name,
                "transformation": transformation,
                "window": window,
                "minimum_samples": int(config["rolling_windows"]["minimum_games"]),
                "imputation": "fixed_documented_prior_or_explicit_unknown",
                "version_added": FEATURE_VERSION,
                "leakage_risk": "same_game_or_future_week",
                "owner_test": "tests/leakage/test_history_exclusion.py",
            }
        )
    return entries


def build_feature_bundle(inputs: FeatureInputs, config: dict[str, Any]) -> FeatureBundle:
    assert_unique_keys(inputs.games, ["game_id"], "game")
    assert_unique_keys(inputs.team_stats, ["game_id", "team"], "team-game")
    if inputs.qb_stats.height:
        assert_unique_keys(
            inputs.qb_stats.filter(pl.col("player_id").is_not_null()),
            ["game_id", "team", "player_id"],
            "QB game",
        )
    availability = build_weekly_availability(inputs.games, _availability_policy(config))
    postgame = inputs.postgame_evidence if inputs.postgame_evidence is not None else _postgame_evidence(inputs.qb_stats)
    starters = resolve_starter_certainty(
        inputs.games,
        availability,
        depth_evidence=inputs.depth_charts,
        rosters=inputs.rosters,
        postgame_evidence=postgame,
    )
    scenarios = starter_scenarios(starters)
    team = build_team_pregame_features(inputs.games, inputs.team_stats, availability, config)
    qb = build_qb_pregame_features(inputs.games, inputs.qb_stats, scenarios, availability, config)
    team_source_available = {
        (row["game_id"], row["team"]): row["source_available_at_utc"]
        for row in team.to_dicts()
    }
    avail_lookup = {
        (row["season"], row["season_type"], row["week"]): row for row in availability.to_dicts()
    }
    starter_lookup = {row["game_id"]: row for row in starters.to_dicts()}
    base_rows = []
    for game in inputs.games.sort(["season", "week", "game_id"]).to_dicts():
        timing = avail_lookup[(game["season"], game["season_type"], game["week"])]
        starter = starter_lookup[game["game_id"]]
        scores = game.get("home_score"), game.get("away_score")
        target_available = scores[0] is not None and scores[1] is not None
        home_score = float(scores[0]) if scores[0] is not None else None
        away_score = float(scores[1]) if scores[1] is not None else None
        if target_available:
            assert home_score is not None and away_score is not None
            target_home_win = None if home_score == away_score else home_score > away_score
            target_margin = home_score - away_score
            target_tie = home_score == away_score
        else:
            target_home_win = None
            target_margin = None
            target_tie = None
        source_times = [
            value
            for value in (
                team_source_available.get((game["game_id"], game["home_team"])),
                team_source_available.get((game["game_id"], game["away_team"])),
            )
            if value is not None
        ]
        base_rows.append(
            {
                "game_id": game["game_id"],
                "season": int(game["season"]),
                "season_type": game["season_type"],
                "week": int(game["week"]),
                "home_team": game["home_team"],
                "away_team": game["away_team"],
                "feature_as_of_utc": timing["prediction_as_of_utc"],
                "prediction_as_of_utc": timing["prediction_as_of_utc"],
                "source_available_at_utc": max(source_times) if source_times else None,
                "scheduled_start_utc": None,
                "availability_rule": timing["availability_rule"],
                "feature_version": FEATURE_VERSION,
                "data_version": DATA_VERSION,
                "expected_home_qb_id": starter["home_qb_candidate_1"],
                "expected_away_qb_id": starter["away_qb_candidate_1"],
                "qb_status": starter["starter_certainty"],
                "target_home_win": target_home_win,
                "target_margin": target_margin,
                "target_tie": target_tie,
                "target_available": target_available,
            }
        )
    base = pl.DataFrame(base_rows).with_columns(
        pl.col("feature_as_of_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("prediction_as_of_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("source_available_at_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("scheduled_start_utc").cast(pl.Datetime("us", "UTC")),
    )
    game_features = base.join(_team_wide(team), on="game_id", how="left").sort(["season", "week", "game_id"])
    model_columns = _model_feature_columns(game_features)
    registry = build_feature_registry(game_features, config, model_columns)
    assert_no_market_columns(game_features)
    assert_unique_keys(game_features, ["game_id"], "game")
    return FeatureBundle(
        game_features=game_features,
        team_features=team,
        qb_features=qb,
        starter_certainty=starters,
        weekly_availability=availability,
        feature_registry=registry,
        model_feature_columns=model_columns,
        config=config,
    )


def _git_identifier(root: Path) -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def feature_code_fingerprint(repository_root: str | Path) -> str:
    """Deterministic SHA-256 of the Task 02 feature implementation inputs.

    Inputs are repository-relative paths. Each input contributes its UTF-8
    content (decoded as a surrogate-escape-proof bytes string) and the
    relative path. Filesystem metadata (mtime, mode, size-only) and current
    time are never consulted. Sorted paths make the result stable across
    clean checkouts.
    """

    root = Path(repository_root)
    feature_glob = sorted(path for path in (root / "src" / "nfl_edge" / "features").rglob("*.py"))
    config_path = root / "config" / "features.yaml"
    inputs: list[Path] = list(feature_glob)
    if config_path.is_file():
        inputs.append(config_path)
    inputs.sort(key=lambda path: path.relative_to(root).as_posix())
    digest = hashlib.sha256()
    for path in inputs:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\n")
        digest.update(path.read_bytes())
        digest.update(b"\n")
    return digest.hexdigest()


def approved_base_sha() -> str:
    """The Task 02 approved base main SHA is recorded directly in the manifest."""

    return "94b6d55fb166dc542850b0a392340529e2209854"


def _timestamp(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("created_at_utc must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def write_feature_outputs(
    bundle: FeatureBundle,
    output_dir: str | Path,
    repository_root: str | Path,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    root = Path(repository_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = {
        "game_features": bundle.game_features,
        "team_features": bundle.team_features,
        "qb_features": bundle.qb_features,
        "starter_certainty": bundle.starter_certainty,
        "weekly_availability": bundle.weekly_availability,
    }
    for key, frame in frames.items():
        frame.write_parquet(
            output_dir / OUTPUT_NAMES[key],
            compression="zstd",
            statistics=True,
            row_group_size=65536,
        )
    registry_path = output_dir / OUTPUT_NAMES["feature_registry"]
    registry_path.write_text(json.dumps(bundle.feature_registry, indent=2, sort_keys=True) + "\n")

    config_fingerprint = canonical_json_sha256(bundle.config)
    file_entries = []
    for key, frame in frames.items():
        path = output_dir / OUTPUT_NAMES[key]
        relative = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.name
        season_coverage = (
            sorted(int(value) for value in frame["season"].drop_nulls().unique().to_list())
            if "season" in frame.columns
            else []
        )
        feature_times = []
        for column in ("feature_as_of_utc", "prediction_as_of_utc"):
            if column in frame.columns:
                feature_times.extend(frame[column].drop_nulls().to_list())
        minimum_as_of = min(feature_times).isoformat().replace("+00:00", "Z") if feature_times else None
        maximum_as_of = max(feature_times).isoformat().replace("+00:00", "Z") if feature_times else None
        file_entries.append(
            {
                "file_path": relative,
                "row_count": frame.height,
                "column_count": frame.width,
                "byte_size": path.stat().st_size,
                "sha256": _sha256(path),
                "schema_fingerprint": schema_fingerprint(frame),
                "logical_fingerprint": logical_frame_fingerprint(frame),
                "season_coverage": season_coverage,
                "minimum_feature_as_of_utc": minimum_as_of,
                "maximum_feature_as_of_utc": maximum_as_of,
            }
        )
    registry_relative = (
        registry_path.relative_to(root).as_posix()
        if registry_path.is_relative_to(root)
        else registry_path.name
    )
    file_entries.append(
        {
            "file_path": registry_relative,
            "row_count": len(bundle.feature_registry),
            "column_count": len(bundle.feature_registry[0]) if bundle.feature_registry else 0,
            "byte_size": registry_path.stat().st_size,
            "sha256": _sha256(registry_path),
            "schema_fingerprint": canonical_json_sha256(
                sorted(bundle.feature_registry[0]) if bundle.feature_registry else []
            ),
            "logical_fingerprint": canonical_json_sha256(bundle.feature_registry),
            "season_coverage": [],
            "minimum_feature_as_of_utc": None,
            "maximum_feature_as_of_utc": None,
        }
    )
    manifest = {
        "feature_version": FEATURE_VERSION,
        "data_version": DATA_VERSION,
        "source_manifest_ids": SOURCE_MANIFEST_IDS,
        "created_at_utc": _timestamp(created_at_utc),
        "configuration_fingerprint": config_fingerprint,
        "base_commit_sha": approved_base_sha(),
        "feature_code_fingerprint": feature_code_fingerprint(root),
        "files": file_entries,
    }
    (output_dir / "feature_manifest_v1.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
