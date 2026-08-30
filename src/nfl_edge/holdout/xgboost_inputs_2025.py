"""Holdout input assembly for the frozen XGBoost V1 contract.

This module is input-only.  It never fits or predicts.  It reproduces the
accepted Task03C extraction join exactly: game features plus candidate-rank-1
QB pregame features, split by home/away and prefixed with ``home_qb_`` /
``away_qb_``.  The development parity helper proves that this assembly yields
exactly the frozen 2018-2024 XGBoost predictor surface before the same join is
used to certify 2025 inputs.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Iterable

import polars as pl

from nfl_edge.models.xgboost_contract import QB_FEATURE_COLUMNS


class XGBoostInputContractError(RuntimeError):
    """Raised when the frozen XGBoost input assembly contract is violated."""


def _require_columns(frame: pl.DataFrame, columns: Iterable[str], where: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise XGBoostInputContractError(f"{where} missing columns: {missing}")


def _logical_hash(frame: pl.DataFrame, *, sort_by: list[str]) -> str:
    rows: list[dict[str, Any]] = []
    for row in frame.sort(sort_by).to_dicts():
        normalized: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, float) and math.isnan(value):
                normalized[key] = "NaN"
            else:
                normalized[key] = value
        rows.append(normalized)
    payload = json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def assemble_candidate1_xgboost_surface(
    game_features: pl.DataFrame,
    qb_features: pl.DataFrame,
    *,
    season_min: int,
    season_max: int,
) -> pl.DataFrame:
    """Reproduce the accepted Task03C game+QB join without fitting/predicting."""
    _require_columns(game_features, ["game_id", "season"], "game_features")
    _require_columns(
        qb_features,
        ["game_id", "season", "side", "candidate_rank", *QB_FEATURE_COLUMNS],
        "qb_features",
    )

    games = game_features.filter(pl.col("season").is_between(season_min, season_max))
    qb = qb_features.filter(pl.col("season").is_between(season_min, season_max)).filter(
        pl.col("candidate_rank") == 1
    )
    if games.is_empty():
        raise XGBoostInputContractError(
            f"game_features has no rows for seasons {season_min}..{season_max}"
        )
    if games["game_id"].n_unique() != games.height:
        raise XGBoostInputContractError("game_features contains duplicate game_id rows")

    bad_sides = sorted(
        str(value)
        for value in qb.filter(~pl.col("side").is_in(["home", "away"]))["side"]
        .drop_nulls()
        .unique()
        .to_list()
    )
    if bad_sides:
        raise XGBoostInputContractError(f"unexpected candidate-rank-1 QB sides: {bad_sides}")
    if qb.select("game_id", "side").unique().height != qb.height:
        raise XGBoostInputContractError("candidate-rank-1 QB surface has duplicate game_id/side rows")

    select_cols = ["game_id", "side", *QB_FEATURE_COLUMNS]
    home = (
        qb.filter(pl.col("side") == "home")
        .select(select_cols)
        .rename({name: f"home_qb_{name}" for name in QB_FEATURE_COLUMNS})
        .select(["game_id", *[f"home_qb_{name}" for name in QB_FEATURE_COLUMNS]])
    )
    away = (
        qb.filter(pl.col("side") == "away")
        .select(select_cols)
        .rename({name: f"away_qb_{name}" for name in QB_FEATURE_COLUMNS})
        .select(["game_id", *[f"away_qb_{name}" for name in QB_FEATURE_COLUMNS]])
    )
    expected = games.height
    if home.height != expected or away.height != expected:
        raise XGBoostInputContractError(
            "candidate-rank-1 QB coverage must be exactly one home and one away row per game: "
            f"games={expected} home={home.height} away={away.height}"
        )

    joined = games.join(home, on="game_id", how="left", validate="1:1")
    joined = joined.join(away, on="game_id", how="left", validate="1:1")
    if joined.height != expected:
        raise XGBoostInputContractError("XGBoost input join changed game row count")
    return joined.sort([c for c in ("season", "week", "game_id") if c in joined.columns])


def assert_development_assembly_parity(
    game_features: pl.DataFrame,
    qb_features: pl.DataFrame,
    frozen_development: pl.DataFrame,
    feature_columns: list[str],
) -> str:
    """Prove the assembly reproduces the frozen 2018-2024 predictor values exactly."""
    rebuilt = assemble_candidate1_xgboost_surface(
        game_features,
        qb_features,
        season_min=2018,
        season_max=2024,
    )
    _require_columns(rebuilt, ["game_id", *feature_columns], "rebuilt development surface")
    _require_columns(
        frozen_development,
        ["game_id", *feature_columns],
        "frozen XGBoost development extraction",
    )
    left = rebuilt.select(["game_id", *feature_columns])
    right = frozen_development.select(["game_id", *feature_columns])
    if left.height != right.height:
        raise XGBoostInputContractError(
            f"development parity row-count mismatch: rebuilt={left.height} frozen={right.height}"
        )
    left_hash = _logical_hash(left, sort_by=["game_id"])
    right_hash = _logical_hash(right, sort_by=["game_id"])
    if left_hash != right_hash:
        raise XGBoostInputContractError(
            "accepted Task03C game+QB assembly no longer reproduces the frozen predictor surface: "
            f"rebuilt={left_hash} frozen={right_hash}"
        )
    return left_hash
