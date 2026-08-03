"""Point-in-time-safe team rolling features."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import polars as pl

from .validation import assert_no_market_columns, assert_unique_keys

BASE_METRICS = (
    "win",
    "loss",
    "tie",
    "win_rate",
    "points_scored",
    "points_allowed",
    "point_differential",
    "passing_epa",
    "rushing_epa",
    "offensive_total_epa",
    "defensive_epa_allowed",
    "passing_yards",
    "rushing_yards",
)
STD_METRICS = ("offensive_total_epa", "defensive_epa_allowed")


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _mean(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def _sum(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _stddev(values: list[float | None]) -> float | None:
    """Population standard deviation of non-null values; None when fewer than two."""

    present = [float(value) for value in values if value is not None]
    if len(present) < 2:
        return None
    mean = sum(present) / len(present)
    variance = sum((value - mean) ** 2 for value in present) / len(present)
    return variance ** 0.5


def _game_context(games: pl.DataFrame, availability: pl.DataFrame) -> dict[str, dict[str, Any]]:
    avail = {
        (row["season"], row["season_type"], row["week"]): row
        for row in availability.to_dicts()
    }
    result = {}
    for game in games.to_dicts():
        boundary = avail[(game["season"], game["season_type"], game["week"])]
        result[game["game_id"]] = {**game, **boundary}
    return result


def _team_completed_rows(games: pl.DataFrame, stats: pl.DataFrame, availability: pl.DataFrame) -> list[dict[str, Any]]:
    assert_unique_keys(games, ["game_id"], "game")
    assert_unique_keys(stats, ["game_id", "team"], "team-game")
    assert_no_market_columns(stats)
    context = _game_context(games, availability)
    stats_by_key = {(row["game_id"], row["team"]): row for row in stats.to_dicts()}
    rows = []
    for game_id, game in context.items():
        if game.get("home_score") is None or game.get("away_score") is None:
            continue
        for team, opponent, scored, allowed in (
            (game["home_team"], game["away_team"], game["home_score"], game["away_score"]),
            (game["away_team"], game["home_team"], game["away_score"], game["home_score"]),
        ):
            source = stats_by_key.get((game_id, team), {})
            opponent_source = stats_by_key.get((game_id, opponent), {})
            passing_epa = _as_float(source.get("passing_epa"))
            rushing_epa = _as_float(source.get("rushing_epa"))
            opponent_passing = _as_float(opponent_source.get("passing_epa"))
            opponent_rushing = _as_float(opponent_source.get("rushing_epa"))
            rows.append(
                {
                    "game_id": game_id,
                    "season": int(game["season"]),
                    "season_type": game["season_type"],
                    "week": int(game["week"]),
                    "team": team,
                    "opponent": opponent,
                    "source_available_at_utc": game["eligible_for_features_at_utc"],
                    "win": 1.0 if scored > allowed else 0.0,
                    "loss": 1.0 if scored < allowed else 0.0,
                    "tie": 1.0 if scored == allowed else 0.0,
                    "win_rate": 1.0 if scored > allowed else (0.5 if scored == allowed else 0.0),
                    "points_scored": float(scored),
                    "points_allowed": float(allowed),
                    "point_differential": float(scored - allowed),
                    "passing_epa": passing_epa,
                    "rushing_epa": rushing_epa,
                    "offensive_total_epa": (
                        passing_epa + rushing_epa if passing_epa is not None and rushing_epa is not None else None
                    ),
                    "defensive_epa_allowed": (
                        opponent_passing + opponent_rushing
                        if opponent_passing is not None and opponent_rushing is not None
                        else None
                    ),
                    "passing_yards": _as_float(source.get("passing_yards")),
                    "rushing_yards": _as_float(source.get("rushing_yards")),
                }
            )
    return rows


def _aggregate(history: list[dict[str, Any]], prefix: str, priors: dict[str, float], minimum: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        f"{prefix}_prior_games": len(history),
        f"{prefix}_minimum_sample_met": len(history) >= minimum,
    }
    for metric in BASE_METRICS:
        observed = _sum([row.get(metric) for row in history]) if metric in {"win", "loss", "tie"} else _mean(
            [row.get(metric) for row in history]
        )
        imputed = observed is None
        value = float(priors.get(metric, 0.0)) if imputed else float(observed)
        result[f"{prefix}_{metric}"] = value
        result[f"{prefix}_{metric}_missing"] = observed is None
        result[f"{prefix}_{metric}_imputed"] = imputed
    for metric in STD_METRICS:
        std = _stddev([row.get(metric) for row in history])
        result[f"{prefix}_{metric}_std"] = std
        result[f"{prefix}_{metric}_std_missing"] = std is None
    return result


def build_team_pregame_features(
    games: pl.DataFrame,
    stats: pl.DataFrame,
    availability: pl.DataFrame,
    config: dict[str, Any],
) -> pl.DataFrame:
    """Create two pregame rows per game using only earlier eligible game-weeks."""

    context = _game_context(games, availability)
    completed = _team_completed_rows(games, stats, availability)
    history_by_team: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in completed:
        history_by_team[row["team"]].append(row)
    for rows in history_by_team.values():
        rows.sort(key=lambda row: (row["source_available_at_utc"], row["season"], row["week"], row["game_id"]))

    windows = config["rolling_windows"]
    short = int(windows["short_games"])
    medium = int(windows["medium_games"])
    minimum = int(windows["minimum_games"])
    carryover_config = config.get("prior_season_carryover", {})
    carryover_enabled = bool(carryover_config.get("enabled", False))
    carryover_max = int(carryover_config.get("max_games", short))
    priors = {key: float(value) for key, value in config["fixed_priors"].items()}

    rows = []
    for game in sorted(context.values(), key=lambda row: (row["season"], row["week"], row["game_id"])):
        as_of = game["prediction_as_of_utc"]
        neutral = str(game.get("neutral_site_source") or "").strip().lower() == "neutral"
        for side, team, opponent in (
            ("home", game["home_team"], game["away_team"]),
            ("away", game["away_team"], game["home_team"]),
        ):
            eligible = [
                item
                for item in history_by_team.get(team, [])
                if item["game_id"] != game["game_id"] and item["source_available_at_utc"] <= as_of
            ]
            current_season = [item for item in eligible if item["season"] == game["season"]]
            prior_season = [item for item in eligible if item["season"] < game["season"]]
            carryover = prior_season[-carryover_max:] if carryover_enabled and len(current_season) < minimum else []
            combined = carryover + current_season
            row = {
                "game_id": game["game_id"],
                "season": int(game["season"]),
                "season_type": game["season_type"],
                "week": int(game["week"]),
                "team": team,
                "opponent": opponent,
                "side": side,
                "feature_as_of_utc": as_of,
                "source_available_at_utc": max(
                    (item["source_available_at_utc"] for item in combined), default=None
                ),
                "games_played_before_current_game": len(current_season),
                "prior_season_carryover_used": bool(carryover),
                "prior_season_carryover_games": len(carryover),
                "early_season_sample": len(current_season) < minimum,
                "rest_or_week_gap": (
                    int(game["week"]) - int(current_season[-1]["week"]) if current_season else None
                ),
                "week_gap_proxy": (
                    int(game["week"]) - int(current_season[-1]["week"]) if current_season else None
                ),
                "bye_week_proxy": (
                    int(game["week"]) - int(current_season[-1]["week"]) > 1 if current_season else False
                ),
                "is_home": side == "home" and not neutral,
                "neutral_site": neutral,
                "venue_id": game.get("venue_id"),
                "venue_missing": game.get("venue_id") is None,
                "roof_category": (game.get("roof_type") or "unknown").strip().lower(),
                "roof_missing": game.get("roof_type") is None,
            }
            row.update(_aggregate(combined[-short:], f"roll{short}", priors, minimum))
            row.update(_aggregate(combined[-medium:], f"roll{medium}", priors, minimum))
            row.update(_aggregate(current_season, "season_to_date", priors, minimum))
            rows.append(row)
    result = pl.DataFrame(rows).sort(["season", "week", "game_id", "side"])
    result = result.with_columns(
        pl.col("feature_as_of_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("source_available_at_utc").cast(pl.Datetime("us", "UTC")),
    )
    assert_unique_keys(result, ["game_id", "team"], "team-game")
    assert_no_market_columns(result)
    return result
