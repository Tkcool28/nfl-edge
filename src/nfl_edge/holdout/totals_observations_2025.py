"""Holdout-only bridge to the accepted Totals V1 GameObservation builder.

The accepted development PBP machinery is deliberately hard-sealed to NFL
seasons 2018-2024.  Its observation formulas themselves are season-agnostic:
season is checked only at the PBP annotation boundary, while every accepted
predicate, pace/drive primitive, offense/defense inversion, and
``GameObservation`` output is determined by play/game/team fields.

This bridge preserves that firewall rather than weakening it.  It accepts only
already-authorized season-2025 historical PBP, validates that every supplied
frame is exactly 2025, changes only the ``season`` value to the development
sentinel 2024 while the unchanged accepted observation builder executes, and
returns the seasonless ``GameObservation`` result.  No play value, game ID,
team identity, block identity, or formula is changed.

The same pattern is used by the holdout evaluator seam: a boundary-only season
field is shadowed after asserting the real input is exactly the authorized
holdout.  This module performs no prediction, model fit, market access, or
result grading.
"""
from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from nfl_edge.features.totals_v1.block_state import GameObservation
from nfl_edge.features.totals_v1.game_observations import (
    build_game_observations_with_provenance,
)
from nfl_edge.features.totals_v1.provenance import ProvenanceCounters

HOLDOUT_SEASON = 2025
SHADOW_DEVELOPMENT_SEASON = 2024


class HoldoutTotalsObservationError(RuntimeError):
    """Raised when the narrow 2025 observation bridge contract is violated."""


def _shadow_frame(frame: pl.DataFrame, *, game_id: str) -> pl.DataFrame:
    if "season" not in frame.columns:
        raise HoldoutTotalsObservationError(
            f"2025 Totals PBP frame missing season for game_id={game_id}"
        )
    if frame.height == 0:
        raise HoldoutTotalsObservationError(
            f"2025 Totals PBP frame is empty for game_id={game_id}"
        )
    seasons = {int(value) for value in frame["season"].drop_nulls().unique().to_list()}
    if frame["season"].null_count() or seasons != {HOLDOUT_SEASON}:
        raise HoldoutTotalsObservationError(
            f"2025 Totals PBP bridge requires season exactly {HOLDOUT_SEASON} "
            f"for game_id={game_id}: seasons={sorted(seasons)} "
            f"nulls={frame['season'].null_count()}"
        )
    dtype = frame.schema["season"]
    return frame.with_columns(
        pl.lit(SHADOW_DEVELOPMENT_SEASON).cast(dtype).alias("season")
    )


def build_2025_game_observations_with_provenance(
    *,
    block_id: str,
    pbp_frames: dict[str, pl.DataFrame],
    game_to_teams: Mapping[str, tuple[str, str]] | None = None,
) -> tuple[list[GameObservation], ProvenanceCounters]:
    """Build season-2025 observations through the unchanged accepted builder.

    The input dictionary is not mutated.  Every frame must be non-empty and
    season-exact 2025.  Only a temporary copy's ``season`` column is shadowed;
    the returned ``GameObservation`` dataclasses do not contain a season field.
    """
    if not pbp_frames:
        raise HoldoutTotalsObservationError("2025 Totals observation block cannot be empty")
    shadowed = {
        str(game_id): _shadow_frame(frame, game_id=str(game_id))
        for game_id, frame in pbp_frames.items()
    }
    return build_game_observations_with_provenance(
        block_id=block_id,
        pbp_frames=shadowed,
        game_to_teams=game_to_teams,
    )


def prove_development_shadow_parity(
    *,
    block_id: str,
    pbp_frames: dict[str, pl.DataFrame],
    game_to_teams: Mapping[str, tuple[str, str]] | None = None,
    shadow_season: int = 2023,
) -> None:
    """Prove that changing only development-season identity changes no output.

    This helper is development-only evidence for the bridge premise.  It calls
    the accepted builder once on the original development frames and once with
    only ``season`` replaced by another allowed development season.  Exact
    dataclass/provenance equality is required.
    """
    if not pbp_frames:
        raise HoldoutTotalsObservationError("shadow parity proof requires PBP frames")
    if not 2018 <= int(shadow_season) <= 2024:
        raise HoldoutTotalsObservationError("shadow parity sentinel must remain in 2018-2024")
    original, original_prov = build_game_observations_with_provenance(
        block_id=block_id,
        pbp_frames=pbp_frames,
        game_to_teams=game_to_teams,
    )
    shadowed: dict[str, pl.DataFrame] = {}
    for game_id, frame in pbp_frames.items():
        if "season" not in frame.columns or frame.height == 0:
            raise HoldoutTotalsObservationError(
                f"development parity frame missing season/rows for {game_id}"
            )
        seasons = {int(value) for value in frame["season"].drop_nulls().unique().to_list()}
        if frame["season"].null_count() or not seasons or any(s < 2018 or s > 2024 for s in seasons):
            raise HoldoutTotalsObservationError(
                f"development parity proof received non-development seasons for {game_id}: {sorted(seasons)}"
            )
        dtype = frame.schema["season"]
        shadowed[str(game_id)] = frame.with_columns(
            pl.lit(int(shadow_season)).cast(dtype).alias("season")
        )
    shadow, shadow_prov = build_game_observations_with_provenance(
        block_id=block_id,
        pbp_frames=shadowed,
        game_to_teams=game_to_teams,
    )
    if original != shadow or original_prov != shadow_prov:
        raise HoldoutTotalsObservationError(
            "accepted Totals GameObservation output unexpectedly depends on season identity"
        )
