#!/usr/bin/env python3
"""Materialize the frozen 2025 Oracle-QB input surface.

This is a 2025-only companion to the accepted 2018-2024 Stathead/Oracle-QB
pipeline. It deliberately leaves the historical builders and artifacts
untouched.

Leakage controls:
- Stathead rows are identity evidence only; Result is not present in the stored
  2025 raw source.
- Canonical games are projected to identity/schedule columns only.
- For each 2025 block, the canonical QB pregame feature builder receives only
  pre-2025 QB rows plus already-revealed earlier 2025 blocks. Current/future
  2025 QB-stat rows are physically excluded from the call.
- No market data, selector, staking, Play Through, or holdout executor code is
  imported or executed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import polars as pl

from nfl_edge.data.integrity import TEAM_ALIASES, normalize_team
from nfl_edge.features.availability import AvailabilityPolicy, build_weekly_availability
from nfl_edge.features.pipeline import load_feature_config
from nfl_edge.features.qb import build_qb_pregame_features
from nfl_edge.models.qb_elo_config import load_qb_elo_canonical_config

ROOT = Path(__file__).resolve().parents[1]

RAW_DIR = ROOT / "data/raw/stathead_actual_starters_2025_v1/chat_pastes"
RAW_FILES = (
    RAW_DIR / "ranks_0001_0200.tsv",
    RAW_DIR / "ranks_0201_0400.tsv",
    RAW_DIR / "ranks_0401_0570.tsv",
)
HISTORICAL_CROSSWALK = (
    ROOT
    / "data/derived/stathead_actual_starters_v1/identity_crosswalk/task04a_player_crosswalk_v1.csv"
)
HISTORICAL_STARTERS = (
    ROOT
    / "data/derived/stathead_actual_starters_v1/final_oracle_starters/"
    "actual_starting_qb_game_sides_2018_2024_v1.csv"
)
HISTORICAL_ADJUSTMENTS = (
    ROOT
    / "data/derived/oracle_qb_entering_state_v2/"
    "oracle_qb_pregame_adjustments_by_game_2018_2024_v2.parquet"
)
GAMES = ROOT / "data/frozen/games/games_2018_2025.parquet"
QB_STATS = ROOT / "data/frozen/qb_game_stats/qb_game_stats_2018_2025.parquet"
FEATURE_CONFIG = ROOT / "config/features.yaml"
QB_ELO_CONFIG = ROOT / "config/qb_elo_v1.yaml"

EXPECTED_2025_GAMES = 285
EXPECTED_2025_SIDES = 570
EXPECTED_RAW_RANKS = tuple(range(1, 571))
NFLVERSE_PLAYERS_SHA256 = "bf53b18808097984bfac89ab80fd28ae2416944741230ab0a54277458c704943"
NFLVERSE_PLAYERS_ASSET_ID = 535256661
NFLVERSE_PLAYERS_RELEASE_UPDATED_AT = "2026-08-29T13:33:30Z"
HISTORICAL_STARTER_SHA256 = "38732823861bb1def3c216ce9189b651a2dc4d0737d2f65f88f17e97f40b2a1a"
HISTORICAL_ADJUSTMENT_SHA256 = "268368c81913e183d7e9ea5050c0da0a01be619790b75c5bab9362c97349e886"
HISTORICAL_CROSSWALK_SHA256 = "d554c7c2ab5114bc70d0f04a46feba0ef46ab53c717769f8c04f88b98e976742"

STATHEAD_TEAM_ALIASES = {
    **TEAM_ALIASES,
    "GNB": "GB",
    "KAN": "KC",
    "LVR": "LV",
    "NWE": "NE",
    "NOR": "NO",
    "SFO": "SF",
    "TAM": "TB",
    "SDG": "LAC",
}

HISTORICAL_NAME_ALIASES = {
    "Michael Penix": "Michael Penix Jr.",
    "Gardner Minshew II": "Gardner Minshew",
}

SEASON_TYPE_PRIORITY = {"REG": 0, "WC": 1, "DIV": 2, "CON": 3, "SB": 4}

GAME_IDENTITY_COLUMNS = [
    "game_id",
    "season",
    "season_type",
    "week",
    "gameday",
    "home_team",
    "away_team",
]

ADJUSTMENT_COLUMNS = [
    "season",
    "week",
    "season_type",
    "game_date",
    "game_id",
    "away_team",
    "home_team",
    "away_actual_starting_qb_name",
    "away_actual_starting_qb_pfr_id",
    "away_actual_starting_qb_gsis_id",
    "away_passing_epa",
    "away_qb_adjustment_elo",
    "home_actual_starting_qb_name",
    "home_actual_starting_qb_pfr_id",
    "home_actual_starting_qb_gsis_id",
    "home_passing_epa",
    "home_qb_adjustment_elo",
    "historical_model_usage",
    "starter_evidence_class",
    "away_semantic_exception_flag",
    "home_semantic_exception_flag",
    "oracle_qb_adjustment_net",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_stathead_team(value: object) -> str:
    token = str(value).strip().upper()
    return STATHEAD_TEAM_ALIASES.get(token, normalize_team(token) or token)


def block_key(season_type: object, week: object) -> tuple[int, int]:
    st = str(season_type).upper()
    if st not in SEASON_TYPE_PRIORITY:
        raise ValueError(f"unsupported season_type: {st!r}")
    return (SEASON_TYPE_PRIORITY[st], int(week))


def policy(config: dict[str, Any]) -> AvailabilityPolicy:
    source = config["availability"]
    return AvailabilityPolicy(
        weekday=int(source["weekly_publication_weekday"]),
        hour=int(source["weekly_publication_hour"]),
        minute=int(source["weekly_publication_minute"]),
        timezone_name=str(source["timezone"]),
        unusual_date_policy=str(source["unusual_date_policy"]).upper(),
    )


def qb_adjustment_params() -> dict[str, float]:
    raw = load_qb_elo_canonical_config(QB_ELO_CONFIG)
    return {
        "scale": float(raw["qb_adjustment_scale_elo_per_shrunk_epa"]),
        "max_abs": float(raw["qb_adjustment_max_abs_elo"]),
        "replacement": float(raw["qb_adjustment_replacement_passing_epa"]),
    }


def load_raw_rows() -> pd.DataFrame:
    frames = [
        pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
        for path in RAW_FILES
    ]
    raw = pd.concat(frames, ignore_index=True)
    expected_columns = [
        "Rk",
        "Player",
        "Day",
        "G#",
        "Week",
        "Date",
        "Age",
        "Team",
        "Location",
        "Opp",
        "Pos.",
    ]
    if list(raw.columns) != expected_columns:
        raise ValueError(f"unexpected raw Stathead columns: {list(raw.columns)}")
    if "Result" in raw.columns:
        raise ValueError("Result must not be stored in the 2025 raw starter source")
    ranks = tuple(int(x) for x in raw["Rk"].tolist())
    if ranks != EXPECTED_RAW_RANKS:
        raise ValueError("raw Stathead ranks must be exactly 1..570 in order")
    if raw["Rk"].nunique() != EXPECTED_2025_SIDES:
        raise ValueError("duplicate raw Stathead ranks")
    if set(raw["Pos."].str.strip()) != {"QB"}:
        raise ValueError("raw source contains a non-QB row")
    return raw


def load_game_identity() -> pl.DataFrame:
    games = (
        pl.scan_parquet(GAMES)
        .select(GAME_IDENTITY_COLUMNS)
        .collect()
        .with_columns(
            pl.col("season").cast(pl.Int32),
            pl.col("week").cast(pl.Int32),
            pl.col("season_type").cast(pl.String),
            pl.col("game_id").cast(pl.String),
        )
    )
    if games["game_id"].n_unique() != games.height:
        raise ValueError("canonical game_id values must be unique")
    holdout = games.filter(pl.col("season") == 2025)
    if holdout.height != EXPECTED_2025_GAMES:
        raise ValueError(
            f"expected {EXPECTED_2025_GAMES} canonical 2025 games, got {holdout.height}"
        )
    return games


def reconcile_raw_to_games(raw: pd.DataFrame, games_all: pl.DataFrame) -> pd.DataFrame:
    games = games_all.filter(pl.col("season") == 2025)
    by_date_pair: dict[tuple[str, frozenset[str]], list[dict[str, Any]]] = {}
    for game in games.to_dicts():
        away = normalize_stathead_team(game["away_team"])
        home = normalize_stathead_team(game["home_team"])
        key = (str(game["gameday"])[:10], frozenset((away, home)))
        by_date_pair.setdefault(key, []).append(
            {
                **game,
                "away_team": away,
                "home_team": home,
            }
        )

    rows: list[dict[str, Any]] = []
    for source in raw.to_dict(orient="records"):
        team = normalize_stathead_team(source["Team"])
        opp = normalize_stathead_team(source["Opp"])
        candidates = by_date_pair.get(
            (str(source["Date"]), frozenset((team, opp))), []
        )
        if len(candidates) != 1:
            raise ValueError(
                f"rank {source['Rk']} has {len(candidates)} canonical matches "
                f"for {source['Date']} {team}-{opp}"
            )
        game = candidates[0]
        if team == game["away_team"] and opp == game["home_team"]:
            side = "away"
        elif team == game["home_team"] and opp == game["away_team"]:
            side = "home"
        else:
            raise ValueError(f"rank {source['Rk']} canonical team-pair mismatch")

        location = str(source["Location"])
        if location == "@" and side != "away":
            raise ValueError(f"rank {source['Rk']} away marker contradicts canonical side")
        if location == "" and side != "home":
            raise ValueError(f"rank {source['Rk']} home marker contradicts canonical side")
        if location not in {"", "@", "N"}:
            raise ValueError(f"rank {source['Rk']} unknown location {location!r}")
        if int(source["Week"]) != int(game["week"]):
            raise ValueError(
                f"rank {source['Rk']} week mismatch raw={source['Week']} "
                f"canonical={game['week']}"
            )

        rows.append(
            {
                "rank": int(source["Rk"]),
                "player_name": str(source["Player"]),
                "raw_date": str(source["Date"]),
                "raw_team": str(source["Team"]),
                "raw_location": location,
                "raw_opp": str(source["Opp"]),
                "game_id": str(game["game_id"]),
                "season": 2025,
                "week": int(game["week"]),
                "season_type": str(game["season_type"]),
                "gameday": str(game["gameday"])[:10],
                "away_team": str(game["away_team"]),
                "home_team": str(game["home_team"]),
                "team_side": side,
                "canonical_team": team,
                "canonical_opponent": opp,
            }
        )

    reconciled = pd.DataFrame(rows).sort_values("rank").reset_index(drop=True)
    keys = list(zip(reconciled["game_id"], reconciled["team_side"], strict=True))
    if len(keys) != EXPECTED_2025_SIDES or len(set(keys)) != EXPECTED_2025_SIDES:
        raise ValueError("2025 Stathead source does not resolve to 570 unique game sides")
    canonical_keys = {
        (str(game["game_id"]), side)
        for game in games.to_dicts()
        for side in ("away", "home")
    }
    if set(keys) != canonical_keys:
        missing = sorted(canonical_keys - set(keys))
        extra = sorted(set(keys) - canonical_keys)
        raise ValueError(f"2025 side coverage mismatch missing={missing[:5]} extra={extra[:5]}")
    return reconciled


def resolve_identities(
    reconciled: pd.DataFrame, players_source: Path
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if sha256(players_source) != NFLVERSE_PLAYERS_SHA256:
        raise ValueError(
            f"nflverse players source SHA mismatch: {sha256(players_source)}"
        )
    if sha256(HISTORICAL_CROSSWALK) != HISTORICAL_CROSSWALK_SHA256:
        raise ValueError("historical Task04A crosswalk changed")

    hist = pd.read_csv(HISTORICAL_CROSSWALK, dtype=str, keep_default_na=False)
    hist_by_name = {
        str(row.display_name): row
        for row in hist.itertuples(index=False)
    }
    players = pd.read_csv(players_source, dtype=str, keep_default_na=False, low_memory=False)
    required = {"gsis_id", "display_name", "football_name", "pfr_id", "position"}
    missing = required - set(players.columns)
    if missing:
        raise ValueError(f"nflverse players source missing columns: {sorted(missing)}")

    all_rows: list[dict[str, str]] = []
    new_rows: list[dict[str, str]] = []
    for raw_name in sorted(set(reconciled["player_name"])):
        hist_name = HISTORICAL_NAME_ALIASES.get(raw_name, raw_name)
        if hist_name in hist_by_name:
            row = hist_by_name[hist_name]
            resolved = {
                "raw_player_name": raw_name,
                "display_name": str(row.display_name),
                "pfr_id": str(row.pfr_id),
                "gsis_id": str(row.gsis_id),
                "position": str(row.position),
                "mapping_source": "FROZEN_TASK04A_CROSSWALK",
                "mapping_rule": (
                    "EXACT_HISTORICAL_NAME"
                    if hist_name == raw_name
                    else f"EXPLICIT_HISTORICAL_ALIAS:{raw_name}->{hist_name}"
                ),
            }
        else:
            candidates = players[
                (
                    (players["display_name"] == raw_name)
                    | (players["football_name"] == raw_name)
                )
                & (players["pfr_id"] != "")
                & (players["gsis_id"] != "")
                & (players["position"] == "QB")
            ][["display_name", "pfr_id", "gsis_id", "position"]].drop_duplicates()
            identity_pairs = candidates[["pfr_id", "gsis_id"]].drop_duplicates()
            if len(identity_pairs) != 1:
                raise ValueError(
                    f"new 2025 identity {raw_name!r} resolved to "
                    f"{len(identity_pairs)} nflverse identity pairs"
                )
            chosen = candidates.sort_values(
                ["display_name", "pfr_id", "gsis_id"]
            ).iloc[0]
            resolved = {
                "raw_player_name": raw_name,
                "display_name": str(chosen["display_name"]),
                "pfr_id": str(chosen["pfr_id"]),
                "gsis_id": str(chosen["gsis_id"]),
                "position": str(chosen["position"]),
                "mapping_source": "NFLVERSE_PLAYERS_2026_08_29",
                "mapping_rule": "EXACT_DISPLAY_OR_FOOTBALL_NAME_QB",
            }
            new_rows.append(resolved.copy())
        if not resolved["pfr_id"] or not resolved["gsis_id"]:
            raise ValueError(f"blank identity for {raw_name}")
        all_rows.append(resolved)

    crosswalk = pd.DataFrame(all_rows).sort_values(
        ["raw_player_name", "pfr_id", "gsis_id"]
    ).reset_index(drop=True)
    new_crosswalk = pd.DataFrame(new_rows, columns=crosswalk.columns).sort_values(
        ["raw_player_name", "pfr_id", "gsis_id"]
    ).reset_index(drop=True)
    if crosswalk["raw_player_name"].nunique() != reconciled["player_name"].nunique():
        raise ValueError("starter identity crosswalk does not cover every unique raw name")
    return crosswalk, new_crosswalk


def build_starter_ledgers(
    reconciled: pd.DataFrame, crosswalk: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    mapped = reconciled.merge(
        crosswalk,
        left_on="player_name",
        right_on="raw_player_name",
        how="left",
        validate="many_to_one",
    )
    if mapped[["pfr_id", "gsis_id"]].isna().any().any():
        raise ValueError("unresolved 2025 starter identity after crosswalk join")

    side = pd.DataFrame(
        {
            "season": mapped["season"],
            "week": mapped["week"],
            "season_type": mapped["season_type"],
            "gameday": mapped["gameday"],
            "game_id": mapped["game_id"],
            "away_team": mapped["away_team"],
            "home_team": mapped["home_team"],
            "team_side": mapped["team_side"],
            "canonical_team": mapped["canonical_team"],
            "canonical_opponent": mapped["canonical_opponent"],
            "actual_starting_qb_name": mapped["player_name"],
            "actual_starting_qb_pfr_id": mapped["pfr_id"],
            "actual_starting_qb_gsis_id": mapped["gsis_id"],
            "starter_resolution_class": "STATHEAD_UNAMBIGUOUS_SINGLE_CANDIDATE",
            "starter_source": "STATHEAD_QB_STARTED_QUERY",
            "starter_source_game_id": mapped["game_id"],
            "starter_source_locator": mapped["rank"].map(
                lambda r: f"2025 Stathead pasted rank {int(r)}"
            ),
            "starter_source_rank": mapped["rank"].astype(str),
            "starter_evidence_class": "POSTGAME_ACTUAL_STARTER",
            "historical_model_usage": "ORACLE_STARTER_IDENTITY_ONLY",
            "postseason_flag": mapped["season_type"].ne("REG"),
            "semantic_exception_flag": False,
            "official_qb_start_credit": "CREDITED",
            "notes": "",
        }
    ).sort_values(["game_id", "team_side"]).reset_index(drop=True)

    if len(side) != EXPECTED_2025_SIDES:
        raise ValueError("starter side ledger row count mismatch")
    if side[["game_id", "team_side"]].drop_duplicates().shape[0] != EXPECTED_2025_SIDES:
        raise ValueError("starter side ledger duplicate key")
    if side["actual_starting_qb_pfr_id"].eq("").any() or side[
        "actual_starting_qb_gsis_id"
    ].eq("").any():
        raise ValueError("starter side ledger contains unresolved identity")

    games: list[dict[str, Any]] = []
    for game_id, group in side.groupby("game_id", sort=True):
        if set(group["team_side"]) != {"away", "home"} or len(group) != 2:
            raise ValueError(f"game {game_id} does not have exactly one starter per side")
        away = group[group["team_side"] == "away"].iloc[0]
        home = group[group["team_side"] == "home"].iloc[0]
        games.append(
            {
                "season": int(away["season"]),
                "week": int(away["week"]),
                "season_type": away["season_type"],
                "game_date": away["gameday"],
                "game_id": game_id,
                "away_team": away["away_team"],
                "home_team": away["home_team"],
                "away_actual_starting_qb_name": away["actual_starting_qb_name"],
                "away_actual_starting_qb_pfr_id": away["actual_starting_qb_pfr_id"],
                "away_actual_starting_qb_gsis_id": away["actual_starting_qb_gsis_id"],
                "away_starter_source": away["starter_source"],
                "away_starter_source_locator": away["starter_source_locator"],
                "away_starter_resolution_class": away["starter_resolution_class"],
                "away_semantic_exception_flag": False,
                "away_official_qb_start_credit": "CREDITED",
                "home_actual_starting_qb_name": home["actual_starting_qb_name"],
                "home_actual_starting_qb_pfr_id": home["actual_starting_qb_pfr_id"],
                "home_actual_starting_qb_gsis_id": home["actual_starting_qb_gsis_id"],
                "home_starter_source": home["starter_source"],
                "home_starter_source_locator": home["starter_source_locator"],
                "home_starter_resolution_class": home["starter_resolution_class"],
                "home_semantic_exception_flag": False,
                "home_official_qb_start_credit": "CREDITED",
                "starter_evidence_class": "POSTGAME_ACTUAL_STARTER",
                "historical_model_usage": "ORACLE_STARTER_IDENTITY_ONLY",
                "postseason_flag": away["season_type"] != "REG",
            }
        )
    game_df = pd.DataFrame(games).sort_values("game_id").reset_index(drop=True)
    if len(game_df) != EXPECTED_2025_GAMES:
        raise ValueError("starter game ledger row count mismatch")
    return side, game_df


def build_oracle_state(
    starters: pd.DataFrame, games_all: pl.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    config = load_feature_config(FEATURE_CONFIG)
    availability = build_weekly_availability(games_all, policy(config))
    qb_stats = pl.read_parquet(QB_STATS)
    if "game_id" not in qb_stats.columns or "player_id" not in qb_stats.columns:
        raise ValueError("QB source is missing game_id/player_id")

    game_meta = {
        str(row["game_id"]): (
            int(row["season"]),
            str(row["season_type"]),
            int(row["week"]),
        )
        for row in games_all.select(
            "game_id", "season", "season_type", "week"
        ).to_dicts()
    }
    prior_2025_game_ids_by_block: dict[tuple[int, int], set[str]] = {}
    holdout_games = games_all.filter(pl.col("season") == 2025)
    blocks = sorted(
        {
            block_key(row["season_type"], row["week"])
            for row in holdout_games.select("season_type", "week").to_dicts()
        }
    )
    for current in blocks:
        prior_2025_game_ids_by_block[current] = {
            gid
            for gid, (season, st, week) in game_meta.items()
            if season == 2025 and block_key(st, week) < current
        }

    starter_pl = pl.from_pandas(starters).with_columns(
        pl.col("season").cast(pl.Int32),
        pl.col("week").cast(pl.Int32),
    )

    built_frames: list[pl.DataFrame] = []
    block_audit: list[dict[str, Any]] = []
    for current in blocks:
        current_games = holdout_games.filter(
            pl.struct(["season_type", "week"]).map_elements(
                lambda x: block_key(x["season_type"], x["week"]) == current,
                return_dtype=pl.Boolean,
            )
        )
        current_ids = set(str(x) for x in current_games["game_id"].to_list())
        if not current_ids:
            raise ValueError(f"empty 2025 block {current}")

        current_starters = starter_pl.filter(pl.col("game_id").is_in(sorted(current_ids)))
        prior_2025_ids = prior_2025_game_ids_by_block[current]
        visible_game_ids = {
            gid
            for gid, (season, _st, _week) in game_meta.items()
            if season < 2025
        } | prior_2025_ids | current_ids
        source_game_ids = visible_game_ids - current_ids

        games_view = games_all.filter(pl.col("game_id").is_in(sorted(visible_game_ids)))
        qb_view = qb_stats.filter(pl.col("game_id").is_in(sorted(source_game_ids)))
        availability_view = availability.filter(
            (pl.col("season") < 2025)
            | (
                (pl.col("season") == 2025)
                & pl.struct(["season_type", "week"]).map_elements(
                    lambda x: block_key(x["season_type"], x["week"]) <= current,
                    return_dtype=pl.Boolean,
                )
            )
        )
        scenarios = current_starters.select(
            pl.col("game_id"),
            pl.col("canonical_team").alias("team"),
            pl.col("canonical_opponent").alias("opponent"),
            pl.col("team_side").alias("side"),
            pl.lit(1).cast(pl.Int64).alias("candidate_rank"),
            pl.col("actual_starting_qb_gsis_id").alias("player_id"),
            pl.lit("POSTGAME_ACTUAL_STARTER").alias("starter_certainty"),
            pl.col("season"),
            pl.col("season_type"),
            pl.col("week"),
        )
        features = build_qb_pregame_features(
            games_view, qb_view, scenarios, availability_view, config
        )
        identity = current_starters.select(
            "game_id",
            pl.col("team_side").alias("side"),
            "actual_starting_qb_name",
            "actual_starting_qb_pfr_id",
            "actual_starting_qb_gsis_id",
            "historical_model_usage",
            "starter_evidence_class",
            "semantic_exception_flag",
            "official_qb_start_credit",
        )
        features = features.join(identity, on=["game_id", "side"], how="inner")
        if features.height != current_starters.height:
            raise ValueError(f"block {current} starter/feature row mismatch")
        built_frames.append(features)

        visible_2025_source_ids = {
            gid
            for gid in source_game_ids
            if game_meta[gid][0] == 2025
        }
        illegal = [
            gid
            for gid in visible_2025_source_ids
            if block_key(game_meta[gid][1], game_meta[gid][2]) >= current
        ]
        if illegal:
            raise ValueError(f"block {current} sees current/future 2025 QB rows")
        block_audit.append(
            {
                "block_order": list(current),
                "game_count": len(current_ids),
                "starter_side_count": current_starters.height,
                "visible_prior_2025_game_count": len(visible_2025_source_ids),
                "current_block_qb_stat_game_ids_visible": 0,
                "future_2025_qb_stat_game_ids_visible": 0,
            }
        )

    features_all = pl.concat(built_frames, how="vertical_relaxed").sort(
        ["season", "week", "game_id", "side"]
    )
    if features_all.height != EXPECTED_2025_SIDES:
        raise ValueError("Oracle entering-state side coverage mismatch")
    if features_all.select(["game_id", "side"]).unique().height != EXPECTED_2025_SIDES:
        raise ValueError("Oracle entering-state duplicate game side")

    params = qb_adjustment_params()
    features_all = features_all.with_columns(
        (
            ((pl.col("passing_epa") - params["replacement"]) * params["scale"])
            .clip(-params["max_abs"], params["max_abs"])
            .alias("qb_adjustment_elo")
        ),
        pl.lit("ORACLE_IDENTITY_FROZEN_QB_ELO_FORMULA").alias(
            "qb_adjustment_semantics"
        ),
    )

    side_columns = [
        "season",
        "week",
        "season_type",
        "game_id",
        "side",
        "team",
        "opponent",
        "actual_starting_qb_name",
        "actual_starting_qb_pfr_id",
        "actual_starting_qb_gsis_id",
        "historical_model_usage",
        "starter_evidence_class",
        "semantic_exception_flag",
        "official_qb_start_credit",
        "feature_as_of_utc",
        "source_available_at_utc",
        "prior_games",
        "prior_dropback_or_attempt_volume",
        "passing_epa_observed",
        "passing_epa_prior",
        "passing_epa_sample_size",
        "passing_epa_shrinkage_weight",
        "passing_epa",
        "passing_cpoe",
        "sacks_suffered_rate",
        "interception_rate",
        "recency_weighted_form",
        "season_to_date_form",
        "career_to_date_form",
        "rookie_or_zero_sample",
        "low_sample",
        "missing_player_id",
        "passing_epa_imputed",
        "passing_cpoe_imputed",
        "sack_rate_imputed",
        "interception_rate_imputed",
        "qb_adjustment_elo",
        "qb_adjustment_semantics",
    ]
    side_df = features_all.select(side_columns).to_pandas()

    away = features_all.filter(pl.col("side") == "away").select(
        "game_id",
        "season",
        "week",
        "season_type",
        pl.col("team").alias("away_team"),
        pl.col("actual_starting_qb_name").alias("away_actual_starting_qb_name"),
        pl.col("actual_starting_qb_pfr_id").alias("away_actual_starting_qb_pfr_id"),
        pl.col("actual_starting_qb_gsis_id").alias("away_actual_starting_qb_gsis_id"),
        pl.col("passing_epa").alias("away_passing_epa"),
        pl.col("qb_adjustment_elo").alias("away_qb_adjustment_elo"),
        pl.col("semantic_exception_flag").alias("away_semantic_exception_flag"),
    )
    home = features_all.filter(pl.col("side") == "home").select(
        "game_id",
        pl.col("team").alias("home_team"),
        pl.col("actual_starting_qb_name").alias("home_actual_starting_qb_name"),
        pl.col("actual_starting_qb_pfr_id").alias("home_actual_starting_qb_pfr_id"),
        pl.col("actual_starting_qb_gsis_id").alias("home_actual_starting_qb_gsis_id"),
        pl.col("passing_epa").alias("home_passing_epa"),
        pl.col("qb_adjustment_elo").alias("home_qb_adjustment_elo"),
        pl.col("semantic_exception_flag").alias("home_semantic_exception_flag"),
    )
    gamedays = holdout_games.select(
        "game_id", pl.col("gameday").alias("game_date")
    )
    adjustments = (
        away.join(home, on="game_id", how="inner")
        .join(gamedays, on="game_id", how="inner")
        .with_columns(
            pl.lit("ORACLE_STARTER_IDENTITY_ONLY").alias("historical_model_usage"),
            pl.lit("POSTGAME_ACTUAL_STARTER").alias("starter_evidence_class"),
            (
                pl.col("home_qb_adjustment_elo")
                - pl.col("away_qb_adjustment_elo")
            ).alias("oracle_qb_adjustment_net"),
        )
        .select(ADJUSTMENT_COLUMNS)
        .sort("game_id")
    )
    if adjustments.height != EXPECTED_2025_GAMES:
        raise ValueError("Oracle adjustment game coverage mismatch")

    first_block = block_audit[0]
    if first_block["visible_prior_2025_game_count"] != 0:
        raise ValueError("Week 1 block can see a 2025 QB-stat game")
    if any(x["current_block_qb_stat_game_ids_visible"] for x in block_audit):
        raise ValueError("current block QB-stat rows were visible")
    if any(x["future_2025_qb_stat_game_ids_visible"] for x in block_audit):
        raise ValueError("future 2025 QB-stat rows were visible")

    audit = {
        "chronology_mode": "BLOCK_SEQUENTIAL_PHYSICAL_SOURCE_EXCLUSION",
        "week1_2025_qb_stat_games_visible": 0,
        "current_block_2025_qb_stat_games_visible": 0,
        "future_2025_qb_stat_games_visible": 0,
        "blocks": block_audit,
    }
    return side_df, adjustments.to_pandas(), audit


def write_outputs(output_root: Path, players_source: Path) -> dict[str, Any]:
    if sha256(HISTORICAL_STARTERS) != HISTORICAL_STARTER_SHA256:
        raise ValueError("historical 2018-2024 starter artifact changed")
    if sha256(HISTORICAL_ADJUSTMENTS) != HISTORICAL_ADJUSTMENT_SHA256:
        raise ValueError("historical 2018-2024 Oracle adjustment artifact changed")

    raw = load_raw_rows()
    games_all = load_game_identity()
    reconciled = reconcile_raw_to_games(raw, games_all)
    crosswalk, new_crosswalk = resolve_identities(reconciled, players_source)
    starter_sides, starter_games = build_starter_ledgers(reconciled, crosswalk)
    oracle_sides, adjustments, chronology = build_oracle_state(starter_sides, games_all)

    starter_dir = output_root / "stathead_actual_starters_2025_v1"
    xwalk_dir = starter_dir / "identity_crosswalk"
    final_dir = starter_dir / "final_oracle_starters"
    oracle_dir = output_root / "oracle_qb_entering_state_2025_v1"
    for directory in (xwalk_dir, final_dir, oracle_dir):
        directory.mkdir(parents=True, exist_ok=True)

    crosswalk_path = xwalk_dir / "task05g_2025_starter_crosswalk_v1.csv"
    new_crosswalk_path = xwalk_dir / "task05g_2025_new_player_crosswalk_v1.csv"
    crosswalk.to_csv(crosswalk_path, index=False, lineterminator="\n")
    new_crosswalk.to_csv(new_crosswalk_path, index=False, lineterminator="\n")
    provenance_path = xwalk_dir / "task05g_2025_identity_provenance_v1.json"
    provenance_path.write_text(
        json.dumps(
            {
                "historical_crosswalk_path": str(HISTORICAL_CROSSWALK.relative_to(ROOT)),
                "historical_crosswalk_sha256": sha256(HISTORICAL_CROSSWALK),
                "nflverse_players_url": (
                    "https://github.com/nflverse/nflverse-data/releases/"
                    "download/players/players.csv"
                ),
                "nflverse_players_asset_id": NFLVERSE_PLAYERS_ASSET_ID,
                "nflverse_players_release_updated_at": NFLVERSE_PLAYERS_RELEASE_UPDATED_AT,
                "nflverse_players_sha256": sha256(players_source),
                "mapping_rules": [
                    "reuse frozen Task04A exact display-name identity when present",
                    "reuse explicit reviewed Task04A spelling aliases only",
                    "otherwise require one exact nflverse display_name or football_name QB identity",
                    "no fuzzy matching",
                ],
                "new_2025_identity_count": int(len(new_crosswalk)),
                "new_2025_identities": new_crosswalk[
                    ["raw_player_name", "pfr_id", "gsis_id"]
                ].to_dict(orient="records"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    starter_side_csv = final_dir / "actual_starting_qb_game_sides_2025_v1.csv"
    starter_game_csv = final_dir / "actual_starting_qbs_by_game_2025_v1.csv"
    starter_game_parquet = final_dir / "actual_starting_qbs_by_game_2025_v1.parquet"
    starter_sides.to_csv(starter_side_csv, index=False, lineterminator="\n")
    starter_games.to_csv(starter_game_csv, index=False, lineterminator="\n")
    starter_games.to_parquet(starter_game_parquet, index=False)

    oracle_side_csv = oracle_dir / "oracle_qb_entering_state_game_sides_2025_v1.csv"
    oracle_side_parquet = oracle_dir / "oracle_qb_entering_state_game_sides_2025_v1.parquet"
    adjustment_csv = oracle_dir / "oracle_qb_pregame_adjustments_by_game_2025_v1.csv"
    adjustment_parquet = oracle_dir / "oracle_qb_pregame_adjustments_by_game_2025_v1.parquet"
    oracle_sides.to_csv(oracle_side_csv, index=False, lineterminator="\n")
    oracle_sides.to_parquet(oracle_side_parquet, index=False)
    adjustments.to_csv(adjustment_csv, index=False, lineterminator="\n")
    adjustments.to_parquet(adjustment_parquet, index=False)

    starter_report_path = starter_dir / "validation_report_v1.json"
    starter_report = {
        "raw_rows": int(len(raw)),
        "raw_rank_min": int(raw["Rk"].astype(int).min()),
        "raw_rank_max": int(raw["Rk"].astype(int).max()),
        "canonical_games": EXPECTED_2025_GAMES,
        "canonical_game_sides": EXPECTED_2025_SIDES,
        "matched_raw_rows": int(len(reconciled)),
        "game_sides_with_exactly_one_candidate": EXPECTED_2025_SIDES,
        "unresolved_game_sides": 0,
        "manual_starter_resolutions": 0,
        "unique_starting_qbs": int(starter_sides["actual_starting_qb_gsis_id"].nunique()),
        "new_2025_identity_count": int(len(new_crosswalk)),
        "source_result_column_stored": False,
        "starter_evidence_class": "POSTGAME_ACTUAL_STARTER",
        "historical_model_usage": "ORACLE_STARTER_IDENTITY_ONLY",
        "historical_starter_sha256_unchanged": sha256(HISTORICAL_STARTERS),
    }
    starter_report_path.write_text(
        json.dumps(starter_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    oracle_report_path = oracle_dir / "oracle_qb_entering_state_validation_report_2025_v1.json"
    oracle_report = {
        "side_rows": int(len(oracle_sides)),
        "game_rows": int(len(adjustments)),
        "unique_game_ids": int(adjustments["game_id"].nunique()),
        "starter_identities_unmatched": 0,
        "chronology": chronology,
        "adjustment_schema": list(adjustments.columns),
        "adjustment_schema_matches_historical_contract": list(adjustments.columns) == ADJUSTMENT_COLUMNS,
        "historical_adjustment_sha256_unchanged": sha256(HISTORICAL_ADJUSTMENTS),
        "outcome_columns_selected_from_games": 0,
        "market_data_reads": 0,
        "holdout_executions": 0,
    }
    oracle_report_path.write_text(
        json.dumps(oracle_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    output_files = [
        crosswalk_path,
        new_crosswalk_path,
        provenance_path,
        starter_side_csv,
        starter_game_csv,
        starter_game_parquet,
        starter_report_path,
        oracle_side_csv,
        oracle_side_parquet,
        adjustment_csv,
        adjustment_parquet,
        oracle_report_path,
    ]
    all_hashes = {
        str(path.relative_to(output_root)): sha256(path)
        for path in output_files
    }
    return {
        "verdict": "2025_ORACLE_QB_INPUT_FROZEN_READY_FOR_EXECUTOR_INTEGRATION",
        "canonical_games": EXPECTED_2025_GAMES,
        "canonical_game_sides": EXPECTED_2025_SIDES,
        "unresolved_game_sides": 0,
        "manual_starter_resolutions": 0,
        "new_2025_identity_count": int(len(new_crosswalk)),
        "chronology": chronology,
        "primary_oracle_adjustment_artifact": str(adjustment_parquet.relative_to(output_root)),
        "primary_oracle_adjustment_sha256": sha256(adjustment_parquet),
        "nflverse_players_sha256": sha256(players_source),
        "historical_starter_sha256": sha256(HISTORICAL_STARTERS),
        "historical_adjustment_sha256": sha256(HISTORICAL_ADJUSTMENTS),
        "outputs": all_hashes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--players-source", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "data/derived")
    args = parser.parse_args()
    report = write_outputs(args.output_root, args.players_source)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
