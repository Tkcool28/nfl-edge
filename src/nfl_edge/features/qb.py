"""Leakage-safe pregame quarterback source and shrinkage features."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import polars as pl

from .validation import assert_no_market_columns, assert_unique_keys


def _weighted_mean(rows: list[dict[str, Any]], metric: str, volume_key: str = "attempts") -> float | None:
    pairs = [
        (float(row[metric]), max(float(row.get(volume_key) or 0.0), 1.0))
        for row in rows
        if row.get(metric) is not None
    ]
    total = sum(weight for _, weight in pairs)
    return sum(value * weight for value, weight in pairs) / total if total else None


def _recency(rows: list[dict[str, Any]], metric: str, decay: float) -> float | None:
    values = [float(row[metric]) for row in rows if row.get(metric) is not None]
    if not values:
        return None
    weights = [decay ** (len(values) - index - 1) for index in range(len(values))]
    return sum(value * weight for value, weight in zip(values, weights, strict=True)) / sum(weights)


def build_qb_pregame_features(
    games: pl.DataFrame,
    qb_stats: pl.DataFrame,
    scenarios: pl.DataFrame,
    availability: pl.DataFrame,
    config: dict[str, Any],
) -> pl.DataFrame:
    assert_unique_keys(games, ["game_id"], "game")
    assert_no_market_columns(qb_stats)
    if qb_stats.height:
        assert_unique_keys(
            qb_stats.filter(pl.col("player_id").is_not_null()),
            ["game_id", "team", "player_id"],
            "QB game",
        )
    assert_unique_keys(scenarios, ["game_id", "team", "candidate_rank"], "QB scenario")
    avail = {
        (row["season"], row["season_type"], row["week"]): row
        for row in availability.to_dicts()
    }
    game_lookup = {row["game_id"]: row for row in games.to_dicts()}
    histories: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in qb_stats.to_dicts():
        player_id = row.get("player_id")
        game = game_lookup.get(row.get("game_id"))
        if not player_id or game is None:
            continue
        row = dict(row)
        row["source_available_at_utc"] = avail[(game["season"], game["season_type"], game["week"])][
            "eligible_for_features_at_utc"
        ]
        attempts = float(row.get("attempts") or 0.0)
        sacks = float(row.get("sacks_suffered") or 0.0)
        row["passing_epa_per_dropback"] = (
            float(row["passing_epa"]) / (attempts + sacks)
            if row.get("passing_epa") is not None and attempts + sacks > 0
            else None
        )
        row["sack_rate"] = sacks / (attempts + sacks) if attempts + sacks > 0 else None
        row["interception_rate"] = (
            float(row.get("passing_interceptions") or 0.0) / attempts if attempts > 0 else None
        )
        histories[str(player_id)].append(row)
    for rows in histories.values():
        rows.sort(key=lambda item: (item["source_available_at_utc"], item["season"], item["week"], item["game_id"]))

    qb_config = config["qb_features"]
    shrink = qb_config["shrinkage"]
    priors = {key: float(value) for key, value in shrink["priors"].items()}
    k = float(shrink["k_dropbacks"])
    recency_games = int(qb_config.get("recency_games", 8))
    decay = float(qb_config.get("recency_decay", 0.75))
    low_sample = int(qb_config.get("low_sample_dropbacks", 100))
    rows = []
    scenario_rows = []
    for scenario in scenarios.to_dicts():
        game = game_lookup[scenario["game_id"]]
        scenario_rows.append(
            {
                **scenario,
                "season": int(scenario.get("season", game["season"])),
                "season_type": scenario.get("season_type", game["season_type"]),
                "week": int(scenario.get("week", game["week"])),
            }
        )
    for scenario in sorted(
        scenario_rows,
        key=lambda row: (row["season"], row["week"], row["game_id"], row["side"], row["candidate_rank"]),
    ):
        game = game_lookup[scenario["game_id"]]
        as_of = avail[(game["season"], game["season_type"], game["week"])]["prediction_as_of_utc"]
        player_id = scenario.get("player_id")
        eligible = [
            row
            for row in histories.get(str(player_id), [])
            if player_id is not None
            and row["game_id"] != scenario["game_id"]
            and row["source_available_at_utc"] <= as_of
        ]
        season_rows = [row for row in eligible if row["season"] == scenario["season"]]
        attempts = sum(float(row.get("attempts") or 0.0) for row in eligible)
        dropbacks = sum(
            float(row.get("attempts") or 0.0) + float(row.get("sacks_suffered") or 0.0) for row in eligible
        )
        weight = dropbacks / (dropbacks + k) if dropbacks > 0 else 0.0
        passing_epa_observed = _weighted_mean(eligible, "passing_epa_per_dropback")
        cpoe_observed = _weighted_mean(eligible, "passing_cpoe")
        sack_observed = _weighted_mean(eligible, "sack_rate")
        interception_observed = _weighted_mean(eligible, "interception_rate")

        def shrunk(observed: float | None, name: str) -> float:
            value = priors[name] if observed is None else observed
            return weight * value + (1.0 - weight) * priors[name]

        rows.append(
            {
                **scenario,
                "feature_as_of_utc": as_of,
                "source_available_at_utc": max(
                    (row["source_available_at_utc"] for row in eligible), default=None
                ),
                "prior_games": len(eligible),
                "prior_dropback_or_attempt_volume": dropbacks if dropbacks else attempts,
                "passing_epa_observed": passing_epa_observed,
                "passing_epa_prior": priors["passing_epa_per_dropback"],
                "passing_epa_sample_size": dropbacks,
                "passing_epa_shrinkage_weight": weight,
                "passing_epa": shrunk(passing_epa_observed, "passing_epa_per_dropback"),
                "passing_cpoe": shrunk(cpoe_observed, "passing_cpoe"),
                "sacks_suffered_rate": shrunk(sack_observed, "sack_rate"),
                "interception_rate": shrunk(interception_observed, "interception_rate"),
                "recency_weighted_form": (
                    _recency(eligible[-recency_games:], "passing_epa_per_dropback", decay)
                    if eligible
                    else priors["passing_epa_per_dropback"]
                ),
                "season_to_date_form": (
                    _weighted_mean(season_rows, "passing_epa_per_dropback")
                    if season_rows
                    else priors["passing_epa_per_dropback"]
                ),
                "career_to_date_form": (
                    passing_epa_observed if passing_epa_observed is not None else priors["passing_epa_per_dropback"]
                ),
                "rookie_or_zero_sample": len(eligible) == 0,
                "low_sample": dropbacks < low_sample,
                "missing_player_id": player_id is None,
                "passing_epa_imputed": passing_epa_observed is None,
                "passing_cpoe_imputed": cpoe_observed is None,
                "sack_rate_imputed": sack_observed is None,
                "interception_rate_imputed": interception_observed is None,
            }
        )
    result = pl.DataFrame(rows).with_columns(
        pl.col("feature_as_of_utc").cast(pl.Datetime("us", "UTC")),
        pl.col("source_available_at_utc").cast(pl.Datetime("us", "UTC")),
    )
    assert_unique_keys(result, ["game_id", "team", "candidate_rank"], "QB scenario")
    assert_no_market_columns(result)
    return result.sort(["season", "week", "game_id", "side", "candidate_rank"])
