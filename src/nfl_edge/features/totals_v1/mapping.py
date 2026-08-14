"""Canonical PBP game/block mapping.

Raw nflverse PBP uses broad ``season_type`` semantics: ``"REG"`` and
``"POST"``. NFL Edge uses canonical block types ``REG/WC/DIV/CON/SB``. This
module joins PBP rows to the normalized canonical games table by unique
``game_id`` and uses the canonical game row as the authority for ``season``,
``season_type``, ``week``, ``away_team``, and ``home_team``.

Rules enforced (all hard-fail):

- duplicate canonical ``game_id``;
- a required PBP ``game_id`` missing from the canonical games table;
- conflicting NFL ``season`` between the PBP row and its canonical game row;
- invalid raw ``REG``/``POST`` to canonical season-type pairing;
- canonical season outside the 2018..2024 development window.

Raw PBP ``"POST"`` is broad source semantics: it never becomes a canonical
prediction block. It must map, via ``game_id``, to canonical ``WC``, ``DIV``,
``CON``, or ``SB``. Raw ``"REG"`` must map to canonical ``"REG"``.
"""

from __future__ import annotations

import polars as pl

from ...common.errors import WalkForwardError
from .season import assert_frame_development_only

# Raw nflverse season_type broad semantics.
PBP_ST_REG = "REG"
PBP_ST_POST = "POST"

# Canonical block types that a raw POST maps to via game_id.
CANONICAL_POSTSEASON_TYPES = ("WC", "DIV", "CON", "SB")


class CanonicalMappingError(WalkForwardError):
    """Raised when PBP rows cannot be mapped to canonical games/block identity."""


def _require_column(frame: pl.DataFrame, column: str, where: str) -> None:
    if column not in frame.columns:
        raise WalkForwardError(where, f"missing required column {column!r}")


def validate_canonical_games(
    canonical_games: pl.DataFrame,
    *,
    where: str = "validate_canonical_games",
) -> None:
    """Verify canonical games are unique by ``game_id`` with required columns.

    Raises :class:`CanonicalMappingError` on duplicate ``game_id`` or missing
    required canonical identity columns.
    """
    _require_column(canonical_games, "game_id", where)
    required = {"game_id", "season", "season_type", "week", "away_team", "home_team"}
    missing = sorted(required - set(canonical_games.columns))
    if missing:
        raise CanonicalMappingError(where, f"canonical games missing columns: {missing}")
    if canonical_games["game_id"].null_count():
        raise CanonicalMappingError(where, "canonical games game_id contains nulls")
    dup = canonical_games.group_by("game_id").len().filter(pl.col("len") > 1)
    if dup.height:
        raise CanonicalMappingError(
            where,
            f"duplicate canonical game_id rows ({dup.height}): {dup['game_id'].head(5).to_list()}",
        )


# Canonical identity columns sourced from the canonical games table.
_CANONICAL_IDENTITY = ("season", "season_type", "week", "away_team", "home_team")


def map_pbp_to_canonical(
    pbp: pl.DataFrame,
    canonical_games: pl.DataFrame,
    *,
    pbp_gid_col: str = "game_id",
    pbp_season_col: str = "season",
    pbp_st_col: str = "season_type",
    where: str = "map_pbp_to_canonical",
) -> pl.DataFrame:
    """Join PBP rows to canonical games, returning canonically-mapped PBP rows.

    Safe by construction: this entry point performs every required mapping
    validation itself before returning, so a caller cannot obtain a mapped
    frame without those guarantees having been enforced:

    - PBP NFL season == canonical NFL season (no conflict);
    - canonical NFL season within the 2018..2024 development window;
    - raw ``REG`` maps only to canonical ``REG``;
    - raw ``POST`` maps only to canonical ``WC``/``DIV``/``CON``/``SB``;
    - a required PBP ``game_id`` missing from the canonical games table
      hard-fails (never silently dropped);
    - duplicate canonical ``game_id`` hard-fails.

    The output carries the canonical identity columns (``season``,
    ``season_type``, ``week``, ``away_team``, ``home_team``) sourced from the
    canonical games table. Where those collide with a same-named raw PBP
    column (always true for ``season``/``season_type``/``week`` and usually
    for teams), the canonical column is suffixed ``_canonical``; the raw PBP
    ``season_type`` is preserved as ``pbp_season_type`` for provenance.

    There is no public path that returns an invalid development mapping: any
    violation raises :class:`CanonicalMappingError` (or the sealed-holdout
    error for a 2025 canonical season) from this single call.
    """
    for col in (pbp_gid_col, pbp_season_col, pbp_st_col):
        _require_column(pbp, col, where)

    validate_canonical_games(canonical_games, where=where)

    games_ids = set(canonical_games["game_id"].to_list())
    pbp_ids = set(pbp[pbp_gid_col].unique().to_list())
    unmatched = sorted(pbp_ids - games_ids)
    if unmatched:
        raise CanonicalMappingError(
            where,
            f"{len(unmatched)} PBP game_ids missing from canonical games; first 5: {unmatched[:5]}",
        )

    # Rename canonical identity columns that collide with raw PBP columns.
    rename = {col: f"{col}_canonical" for col in _CANONICAL_IDENTITY if col in pbp.columns}
    games_renamed = canonical_games.rename(rename) if rename else canonical_games

    joined = pbp.join(games_renamed, on=pbp_gid_col, how="inner")

    # Preserve the raw PBP season_type (REG/POST) as pbp_season_type for
    # provenance; the canonical block identity is the *canonical* column.
    if "season_type" in joined.columns:
        # Only rename when the raw PBP column is still present (not overwritten).
        joined = joined.rename({"season_type": "pbp_season_type"})

    for col in ("season_canonical", "season_type_canonical", "week_canonical",
                "away_team_canonical", "home_team_canonical"):
        _require_column(joined, col, where)

    # Hard-fail on any PBP row whose canonical identity is null (a required
    # mapping that did not resolve). Inner join plus the explicit match check
    # above makes this defensive.
    null_ident = joined.filter(
        pl.col("season_canonical").is_null() | pl.col("season_type_canonical").is_null()
    )
    if null_ident.height:
        raise CanonicalMappingError(
            where,
            f"{null_ident.height} PBP rows lack canonical game identity",
        )

    # Safe-by-construction validation: all six required gates enforced before
    # the mapped frame is returned from this single public call.
    assert_pbp_season_consistent(joined, where=where)
    assert_season_type_pairing(joined, where=where)
    assert_canonical_seasons_in_development(joined, where=where)

    return joined


def assert_pbp_season_consistent(
    mapped: pl.DataFrame,
    *,
    pbp_season_col: str = "season",
    canon_season_col: str = "season_canonical",
    where: str = "assert_pbp_season_consistent",
) -> None:
    """Hard-fail if any PBP NFL season conflicts with its canonical season."""
    if pbp_season_col in mapped.columns and canon_season_col in mapped.columns:
        conflict = mapped.filter(pl.col(pbp_season_col) != pl.col(canon_season_col))
        if conflict.height:
            raise CanonicalMappingError(
                where,
                f"{conflict.height} PBP rows conflict with canonical season",
            )


def assert_season_type_pairing(
    mapped: pl.DataFrame,
    *,
    pbp_st_col: str = "pbp_season_type",
    canon_st_col: str = "season_type_canonical",
    where: str = "assert_season_type_pairing",
) -> None:
    """Validate raw ``REG``/``POST`` to canonical season-type pairing.

    - raw ``REG`` must map to canonical ``REG``;
    - raw ``POST`` must map to canonical ``WC``/``DIV``/``CON``/``SB``;
    - raw ``POST`` must never become the canonical prediction block.

    Any other pairing hard-fails.
    """
    for col in (pbp_st_col, canon_st_col):
        _require_column(mapped, col, where)

    bad = mapped.filter(
        ~(
            ((pl.col(pbp_st_col) == "REG") & (pl.col(canon_st_col) == "REG"))
            | (
                (pl.col(pbp_st_col) == "POST")
                & pl.col(canon_st_col).is_in(list(CANONICAL_POSTSEASON_TYPES))
            )
        )
    )
    if bad.height:
        first = bad.select(canon_st_col, pbp_st_col).head(5).to_dicts()
        raise CanonicalMappingError(
            where,
            f"{bad.height} rows have invalid raw/canonical season-type pairing; first: {first}",
        )


def assert_canonical_seasons_in_development(
    mapped: pl.DataFrame,
    *,
    season_col: str = "season_canonical",
    where: str = "assert_canonical_seasons_in_development",
) -> None:
    """Hard-fail if canonical seasons fall outside 2018..2024."""
    assert_frame_development_only(mapped, season_col=season_col, where=where)


def season_type_canonical(mapped: pl.DataFrame) -> pl.DataFrame:
    """Return mapped rows annotated with canonical block type and flags.

    Preserves raw PBP ``season_type`` as ``pbp_season_type`` (provenance),
    adds ``block_type`` (canonical), ``is_postseason_block``, and
    ``is_raw_post`` boolean columns.
    """
    result = mapped
    result = result.with_columns(
        pl.col("season_type_canonical").alias("block_type"),
        pl.col("season_type_canonical").is_in(list(CANONICAL_POSTSEASON_TYPES)).alias("is_postseason_block"),
        (pl.col("pbp_season_type") == "POST").alias("is_raw_post"),
    )
    return result