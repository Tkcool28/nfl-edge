"""Point-in-time 2026 feature materialization from frozen history + live QB evidence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import polars as pl

from nfl_edge.contracts.runtime_interfaces_v1 import ExpectedQBResolution
from nfl_edge.features.availability import build_weekly_availability
from nfl_edge.features.pipeline import (
    DATA_VERSION,
    FEATURE_VERSION,
    FeatureInputs,
    _availability_policy,
    _team_wide,
    load_feature_config,
)
from nfl_edge.features.qb import build_qb_pregame_features
from nfl_edge.features.team import build_team_pregame_features
from nfl_edge.holdout.xgboost_inputs_2025 import assemble_candidate1_xgboost_surface
from nfl_edge.live.model_adapters import LiveBlock, build_live_block
from nfl_edge.live.sleeper_qb import SleeperExpectedQBResolver
from nfl_edge.live.week1_2026 import load_week1_schedule, schedule_to_frame

LIVE_AVAILABILITY_RULE = "LIVE_EXPLICIT_PREDICTION_AS_OF_UTC_V1"
QB_SCOREABLE_STATES = frozenset({"RESOLVED", "NEW_PLAYER", "OVERRIDDEN"})


class LiveFeatureError(RuntimeError):
    pass


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise LiveFeatureError(f"invalid UTC timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LiveFeatureError("prediction_as_of_utc must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _override_live_availability(
    availability: pl.DataFrame,
    *,
    block: LiveBlock,
) -> pl.DataFrame:
    mask = (
        (pl.col("season") == block.season)
        & (pl.col("season_type").cast(pl.Utf8).str.to_uppercase() == block.season_type)
        & (pl.col("week") == block.week)
    )
    if availability.filter(mask).height != 1:
        raise LiveFeatureError("live availability row is missing or duplicated")
    cutoff = block.as_of_utc
    return availability.with_columns(
        pl.when(mask).then(pl.lit(cutoff)).otherwise(pl.col("prediction_as_of_utc")).alias(
            "prediction_as_of_utc"
        ),
        pl.when(mask).then(pl.lit(LIVE_AVAILABILITY_RULE)).otherwise(pl.col("availability_rule")).alias(
            "availability_rule"
        ),
        pl.when(mask)
        .then(pl.concat_str([pl.col("availability_quality"), pl.lit("LIVE_EXPLICIT_CUTOFF")], separator=";"))
        .otherwise(pl.col("availability_quality"))
        .alias("availability_quality"),
    )


def _current_qb_scenarios(
    current_games: pl.DataFrame,
    resolutions: Mapping[tuple[str, str], ExpectedQBResolution],
) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    for game in current_games.sort("game_id").to_dicts():
        for side, team, opponent in (
            ("home", str(game["home_team"]), str(game["away_team"])),
            ("away", str(game["away_team"]), str(game["home_team"])),
        ):
            key = (str(game["game_id"]), team)
            resolution = resolutions.get(key)
            if resolution is None:
                raise LiveFeatureError(f"missing expected-QB resolution for {key}")
            player_id = (
                resolution.model_qb_state_id
                if resolution.resolution_status in QB_SCOREABLE_STATES
                else None
            )
            rows.append(
                {
                    "game_id": str(game["game_id"]),
                    "team": team,
                    "opponent": opponent,
                    "side": side,
                    "candidate_rank": 1,
                    "player_id": player_id,
                    "starter_certainty": f"SLEEPER_{resolution.resolution_status}",
                    "season": int(game["season"]),
                    "season_type": str(game["season_type"]),
                    "week": int(game["week"]),
                }
            )
    return pl.DataFrame(rows).sort(["game_id", "side"])


def _current_game_feature_rows(
    *,
    current_games: pl.DataFrame,
    current_team: pl.DataFrame,
    availability: pl.DataFrame,
    resolutions: Mapping[tuple[str, str], ExpectedQBResolution],
) -> pl.DataFrame:
    avail_lookup = {
        (int(row["season"]), str(row["season_type"]), int(row["week"])): row
        for row in availability.to_dicts()
    }
    team_source = {
        (str(row["game_id"]), str(row["team"])): row["source_available_at_utc"]
        for row in current_team.to_dicts()
    }
    base_rows: list[dict[str, Any]] = []
    for game in current_games.sort("game_id").to_dicts():
        timing = avail_lookup[(int(game["season"]), str(game["season_type"]), int(game["week"]))]
        home = resolutions[(str(game["game_id"]), str(game["home_team"]))]
        away = resolutions[(str(game["game_id"]), str(game["away_team"]))]
        source_times = [
            value
            for value in (
                team_source.get((str(game["game_id"]), str(game["home_team"]))),
                team_source.get((str(game["game_id"]), str(game["away_team"]))),
            )
            if value is not None
        ]
        base_rows.append(
            {
                "game_id": str(game["game_id"]),
                "season": int(game["season"]),
                "season_type": str(game["season_type"]),
                "week": int(game["week"]),
                "home_team": str(game["home_team"]),
                "away_team": str(game["away_team"]),
                "feature_as_of_utc": timing["prediction_as_of_utc"],
                "prediction_as_of_utc": timing["prediction_as_of_utc"],
                "source_available_at_utc": max(source_times) if source_times else None,
                "scheduled_start_utc": game["scheduled_start_utc"],
                "availability_rule": timing["availability_rule"],
                "feature_version": FEATURE_VERSION,
                "data_version": f"{DATA_VERSION}+live-2026-week1-v1",
                "expected_home_qb_id": home.model_qb_state_id,
                "expected_away_qb_id": away.model_qb_state_id,
                "qb_status": (
                    "SLEEPER_RESOLVED"
                    if home.resolution_status in QB_SCOREABLE_STATES
                    and away.resolution_status in QB_SCOREABLE_STATES
                    else "SLEEPER_PARTIAL"
                ),
                "target_home_win": None,
                "target_margin": None,
                "target_tie": None,
                "target_total_points": None,
                "target_available": False,
                "neutral_site": bool(game["neutral_site"]),
                "neutral_site_source": str(game["neutral_site_source"]),
                "venue_id": game.get("venue_id"),
                "roof_type": game.get("roof_type"),
                "surface": game.get("surface"),
                "away_rest": game.get("away_rest"),
                "home_rest": game.get("home_rest"),
            }
        )
    base = pl.DataFrame(base_rows).with_columns(
        pl.col("feature_as_of_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("prediction_as_of_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("source_available_at_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("scheduled_start_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("target_home_win").cast(pl.Boolean),
        pl.col("target_margin").cast(pl.Float64),
        pl.col("target_tie").cast(pl.Boolean),
        pl.col("target_total_points").cast(pl.Float64),
    )
    return base.join(_team_wide(current_team), on="game_id", how="left", validate="1:1").sort(
        "game_id"
    )


@dataclass(frozen=True)
class LiveWeek1Features:
    block: LiveBlock
    current_games: pl.DataFrame
    combined_games: pl.DataFrame
    availability: pl.DataFrame
    game_features: pl.DataFrame
    team_features: pl.DataFrame
    qb_features: pl.DataFrame
    xgboost_surface: pl.DataFrame
    resolutions: dict[tuple[str, str], ExpectedQBResolution]
    qb_contexts: dict[tuple[str, str], dict[str, Any]]
    override_audits: tuple[Any, ...]

    @property
    def scoreable_game_ids(self) -> tuple[str, ...]:
        scoreable: list[str] = []
        for game in self.current_games.sort("game_id").to_dicts():
            home = self.resolutions[(str(game["game_id"]), str(game["home_team"]))]
            away = self.resolutions[(str(game["game_id"]), str(game["away_team"]))]
            if (
                home.resolution_status in QB_SCOREABLE_STATES
                and away.resolution_status in QB_SCOREABLE_STATES
            ):
                scoreable.append(str(game["game_id"]))
        return tuple(scoreable)


def build_live_week1_features(
    *,
    repository_root: str | Path,
    prediction_as_of_utc: str,
    resolver: SleeperExpectedQBResolver,
    schedule_path: str | Path = "data/live/2026/week1_schedule_v1.json",
    feature_config_path: str | Path = "config/features.yaml",
) -> LiveWeek1Features:
    root = Path(repository_root)
    cutoff = _parse_utc(prediction_as_of_utc)
    schedule = load_week1_schedule(root / schedule_path)
    current = schedule_to_frame(
        schedule, prediction_as_of_utc=cutoff.isoformat().replace("+00:00", "Z")
    )
    block = build_live_block(current)
    inputs = FeatureInputs.from_repository(root)
    config = load_feature_config(root / feature_config_path)

    combined = pl.concat([inputs.games, current], how="diagonal_relaxed").sort(
        ["season", "week", "game_id"]
    )
    if combined["game_id"].n_unique() != combined.height:
        raise LiveFeatureError("historical + live game identity collision")
    availability = build_weekly_availability(combined, _availability_policy(config))
    availability = _override_live_availability(availability, block=block)
    live_avail = availability.filter(
        (pl.col("season") == 2026) & (pl.col("season_type") == "REG") & (pl.col("week") == 1)
    )
    if live_avail["prediction_as_of_utc"].item() != cutoff:
        raise LiveFeatureError("live feature cutoff drift")

    resolutions: dict[tuple[str, str], ExpectedQBResolution] = {}
    contexts: dict[tuple[str, str], dict[str, Any]] = {}
    audits = []
    for game in current.sort("game_id").to_dicts():
        resolved = resolver.resolve_game(game)
        for side in ("home", "away"):
            resolution = resolved[side]
            key = (resolution.game_id, resolution.team)
            if key in resolutions:
                raise LiveFeatureError(f"duplicate QB resolution {key}")
            resolutions[key] = resolution
            contexts[key] = resolver.to_product_context(resolution)
        audits.extend(resolved["overrides"])
    if len(resolutions) != 32:
        raise LiveFeatureError(f"expected 32 Week 1 team-QB resolutions, got {len(resolutions)}")

    scenarios = _current_qb_scenarios(current, resolutions)
    team_all = build_team_pregame_features(combined, inputs.team_stats, availability, config)
    current_team = team_all.filter(pl.col("season") == 2026).sort(["game_id", "side"])
    if current_team.height != 32:
        raise LiveFeatureError(f"expected 32 live team-feature rows, got {current_team.height}")
    qb = build_qb_pregame_features(combined, inputs.qb_stats, scenarios, availability, config)
    if qb.height != 32:
        raise LiveFeatureError(f"expected 32 live QB-feature rows, got {qb.height}")
    game_features = _current_game_feature_rows(
        current_games=current,
        current_team=current_team,
        availability=availability,
        resolutions=resolutions,
    )
    xgboost = assemble_candidate1_xgboost_surface(
        game_features, qb, season_min=2026, season_max=2026
    )
    if xgboost.height != 16:
        raise LiveFeatureError(f"expected 16 XGBoost rows, got {xgboost.height}")
    for frame_name, frame in (
        ("game_features", game_features), ("xgboost_surface", xgboost)
    ):
        if "target_available" in frame.columns and bool(frame["target_available"].fill_null(False).any()):
            raise LiveFeatureError(f"{frame_name} exposed a current outcome")
    return LiveWeek1Features(
        block=block,
        current_games=current,
        combined_games=combined,
        availability=availability,
        game_features=game_features,
        team_features=current_team,
        qb_features=qb,
        xgboost_surface=xgboost,
        resolutions=resolutions,
        qb_contexts=contexts,
        override_audits=tuple(audits),
    )
