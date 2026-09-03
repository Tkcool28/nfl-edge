"""Translate resolved live QB features into frozen model input semantics.

Sleeper supplies expected-starter identity only.  The numerical quarterback
state continues to come from the accepted leakage-safe NFLverse QB feature
builder.  This module applies the same frozen QB-Elo adjustment formula used by
the accepted 2025 Oracle input materializer and exposes the exact game-side QB
surface consumed by Ridge Totals R4.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Iterable

import polars as pl

from nfl_edge.features.totals_v1.feature_table import _ORACLE_QB_CONSUMED_COLUMNS
from nfl_edge.models.qb_elo_config import load_qb_elo_canonical_config

QB_ADJUSTMENT_SEMANTICS = "EXPECTED_STARTER_FROZEN_QB_ELO_FORMULA_V1"


class LiveQBInputError(RuntimeError):
    """Raised when a resolved live QB cannot be translated safely."""


def _parameters(config_path: str | Path) -> dict[str, float]:
    raw = load_qb_elo_canonical_config(Path(config_path))
    params = {
        "scale": float(raw["qb_adjustment_scale_elo_per_shrunk_epa"]),
        "max_abs": float(raw["qb_adjustment_max_abs_elo"]),
        "replacement": float(raw["qb_adjustment_replacement_passing_epa"]),
    }
    if not all(isfinite(value) for value in params.values()) or params["max_abs"] <= 0:
        raise LiveQBInputError("QB-Elo adjustment parameters are malformed")
    return params


def adjustment_from_passing_epa(passing_epa: float, *, config_path: str | Path) -> float:
    """Apply the exact frozen QB-Elo adjustment formula.

    This is byte-for-byte the arithmetic used by the accepted PR #70 2025
    materializer: ``(passing_epa - replacement) * scale`` clipped to the
    configured maximum absolute Elo adjustment.
    """
    value = float(passing_epa)
    if not isfinite(value):
        raise LiveQBInputError("passing_epa must be finite")
    params = _parameters(config_path)
    raw = (value - params["replacement"]) * params["scale"]
    return max(-params["max_abs"], min(params["max_abs"], raw))


@dataclass(frozen=True)
class LiveQBAdjustmentResolver:
    """Deterministic ``game_id -> (home, away)`` QB-Elo adjustment resolver."""

    adjustments: dict[str, tuple[float, float]]
    semantics: str = QB_ADJUSTMENT_SEMANTICS

    def __call__(self, game_id: str) -> tuple[float, float]:
        try:
            return self.adjustments[str(game_id)]
        except KeyError as exc:
            raise LiveQBInputError(f"QB adjustment missing game_id {game_id}") from exc

    def assert_coverage(self, game_ids: Iterable[str]) -> None:
        requested = tuple(str(game_id) for game_id in game_ids)
        if len(requested) != len(set(requested)):
            raise LiveQBInputError("duplicate requested game_id in QB adjustment coverage")
        missing = sorted(set(requested) - set(self.adjustments))
        if missing:
            raise LiveQBInputError(f"QB adjustment coverage missing games: {missing[:12]}")


def build_qb_adjustment_resolver(
    qb_features: pl.DataFrame,
    *,
    game_ids: Iterable[str],
    config_path: str | Path,
) -> LiveQBAdjustmentResolver:
    """Build adjustments only for explicitly scoreable games."""
    ids = tuple(sorted(str(game_id) for game_id in game_ids))
    if not ids:
        return LiveQBAdjustmentResolver({})
    required = {"game_id", "side", "passing_epa"}
    missing = sorted(required - set(qb_features.columns))
    if missing:
        raise LiveQBInputError(f"live QB feature frame missing columns: {missing}")
    selected = qb_features.filter(pl.col("game_id").cast(pl.Utf8).is_in(list(ids))).sort(
        ["game_id", "side"]
    )
    if selected.height != len(ids) * 2:
        raise LiveQBInputError(
            f"expected two QB feature rows per scoreable game: rows={selected.height} games={len(ids)}"
        )
    params = _parameters(config_path)
    by_game: dict[str, dict[str, float]] = {}
    for row in selected.select("game_id", "side", "passing_epa").to_dicts():
        gid, side = str(row["game_id"]), str(row["side"])
        if side not in {"home", "away"} or row["passing_epa"] is None:
            raise LiveQBInputError(f"malformed live QB feature identity for {gid}/{side}")
        value = float(row["passing_epa"])
        if not isfinite(value):
            raise LiveQBInputError(f"non-finite passing_epa for {gid}/{side}")
        adjustment = max(
            -params["max_abs"],
            min(params["max_abs"], (value - params["replacement"]) * params["scale"]),
        )
        bucket = by_game.setdefault(gid, {})
        if side in bucket:
            raise LiveQBInputError(f"duplicate live QB feature side {gid}/{side}")
        bucket[side] = adjustment
    adjustments: dict[str, tuple[float, float]] = {}
    for gid in ids:
        sides = by_game.get(gid, {})
        if set(sides) != {"home", "away"}:
            raise LiveQBInputError(f"incomplete live QB adjustment sides for {gid}")
        adjustments[gid] = (float(sides["home"]), float(sides["away"]))
    resolver = LiveQBAdjustmentResolver(adjustments)
    resolver.assert_coverage(ids)
    return resolver


def build_totals_qb_surface(qb_features: pl.DataFrame, *, game_ids: Iterable[str]) -> pl.DataFrame:
    """Expose only the historically accepted exact QB columns to Totals R4."""
    ids = tuple(sorted(str(game_id) for game_id in game_ids))
    required = {"game_id", "side", *_ORACLE_QB_CONSUMED_COLUMNS}
    missing = sorted(required - set(qb_features.columns))
    if missing:
        raise LiveQBInputError(f"Totals live QB surface missing columns: {missing}")
    selected = qb_features.filter(pl.col("game_id").cast(pl.Utf8).is_in(list(ids))).select(
        ["game_id", "side", *_ORACLE_QB_CONSUMED_COLUMNS]
    ).sort(["game_id", "side"])
    if selected.height != len(ids) * 2:
        raise LiveQBInputError(
            f"Totals live QB surface requires two sides per game: rows={selected.height} games={len(ids)}"
        )
    if selected.select("game_id", "side").is_duplicated().sum():
        raise LiveQBInputError("Totals live QB surface contains duplicate game sides")
    return selected
