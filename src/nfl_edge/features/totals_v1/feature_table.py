"""Totals V1 feature table builder (Phase 3D).

Orchestrates expanding entering-state aggregation, matchup combination,
context joins, Oracle QB joins, and the exact 90-column feature table
emission using the Phase 3A block-start freeze/commit mechanics.

Builds features for NFL seasons 2018-2024 (development window).
Never uses NFL season 2025.

This module does NOT train a model or build a stacker.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import polars as pl

from ...common.errors import WalkForwardError
from .block_state import BlockStartSnapshot, GameObservation, TeamEntState, TotalsBlockState
from .chronology import (
    build_availability_table,
    build_totals_blocks,
    eligible_source_blocks,
)
from .context import project_totals_context
from .context_features import extract_context_features
from .entering_state import MATCHUP_FAMILIES, MetricFamilyConfig, compute_matchup_pair
from .game_observations import build_game_observations_with_provenance
from .mapping import map_pbp_to_canonical, validate_canonical_games
from .manifest import CANONICAL_PBP_MANIFEST, load_pbp_frames
from .provenance import BuildProvenance, PbpFileProvenance, ProvenanceCounters
from .season import DEVELOPMENT_SEASON_MAX

# ---------------------------------------------------------------------------
# Oracle QB consumed columns (contract Section 11)
# ---------------------------------------------------------------------------
# These are the only numerical entering-state/quality columns consumed
# from the accepted Oracle QB v2 artifact.
_ORACLE_QB_CONSUMED_COLUMNS: tuple[str, ...] = (
    "passing_epa",
    "passing_cpoe",
    "sacks_suffered_rate",
    "interception_rate",
    "recency_weighted_form",
    "low_sample",
    "missing_player_id",
    "passing_epa_imputed",
    "passing_cpoe_imputed",
    "sack_rate_imputed",
    "interception_rate_imputed",
)

# Prohibited Oracle QB columns that must NOT be consumed.
_ORACLE_QB_PROHIBITED_COLUMNS: frozenset[str] = frozenset(
    {
        "qb_adjustment_elo",
        "oracle_qb_adjustment_net",
        "actual_starting_qb_name",
        "actual_starting_qb_pfr_id",
        "actual_starting_qb_gsis_id",
        "away_qb_id",
        "home_qb_id",
        "away_qb_name",
        "home_qb_name",
    }
)

# Oracle QB source-to-output column mapping for each side.
# source column name -> feature column suffix (without away_/home_ prefix)
_ORACLE_QB_SOURCE_TO_SUFFIX: dict[str, str] = {
    "passing_epa": "qb_passing_epa",
    "passing_epa_imputed": "qb_passing_epa_imputed",
    "passing_cpoe": "qb_passing_cpoe",
    "passing_cpoe_imputed": "qb_passing_cpoe_imputed",
    "sacks_suffered_rate": "qb_sacks_suffered_rate",
    "sack_rate_imputed": "qb_sack_rate_imputed",
    "interception_rate": "qb_interception_rate",
    "interception_rate_imputed": "qb_interception_rate_imputed",
    "recency_weighted_form": "qb_recency_weighted_form",
    "low_sample": "qb_low_sample",
    "missing_player_id": "qb_missing_player_id",
}

# ---------------------------------------------------------------------------
# Exact 90-column feature table (contract Section 13)
# ---------------------------------------------------------------------------
EXACT_90_COLUMNS: tuple[str, ...] = (
    # Context: rest (4 cols)
    "away_rest_days",
    "away_rest_days_missing",
    "home_rest_days",
    "home_rest_days_missing",
    # Context: roof (2 cols)
    "roof_category",
    "roof_missing",
    # Context: surface (2 cols)
    "surface_category",
    "surface_missing",
    # Oracle QB: away (11 cols)
    "away_qb_passing_epa",
    "away_qb_passing_epa_imputed",
    "away_qb_passing_cpoe",
    "away_qb_passing_cpoe_imputed",
    "away_qb_sacks_suffered_rate",
    "away_qb_sack_rate_imputed",
    "away_qb_interception_rate",
    "away_qb_interception_rate_imputed",
    "away_qb_recency_weighted_form",
    "away_qb_low_sample",
    "away_qb_missing_player_id",
    # Oracle QB: home (11 cols)
    "home_qb_passing_epa",
    "home_qb_passing_epa_imputed",
    "home_qb_passing_cpoe",
    "home_qb_passing_cpoe_imputed",
    "home_qb_sacks_suffered_rate",
    "home_qb_sack_rate_imputed",
    "home_qb_interception_rate",
    "home_qb_interception_rate_imputed",
    "home_qb_recency_weighted_form",
    "home_qb_low_sample",
    "home_qb_missing_player_id",
    # Matchup features: 15 families x 4 cols each (60 cols)
    "away_matchup_epa_per_play",
    "away_matchup_epa_per_play_missing",
    "home_matchup_epa_per_play",
    "home_matchup_epa_per_play_missing",
    "away_matchup_success_rate",
    "away_matchup_success_rate_missing",
    "home_matchup_success_rate",
    "home_matchup_success_rate_missing",
    "away_matchup_points_per_drive",
    "away_matchup_points_per_drive_missing",
    "home_matchup_points_per_drive",
    "home_matchup_points_per_drive_missing",
    "away_matchup_scoring_drive_rate",
    "away_matchup_scoring_drive_rate_missing",
    "home_matchup_scoring_drive_rate",
    "home_matchup_scoring_drive_rate_missing",
    "away_matchup_seconds_per_play",
    "away_matchup_seconds_per_play_missing",
    "home_matchup_seconds_per_play",
    "home_matchup_seconds_per_play_missing",
    "away_matchup_neutral_seconds_per_play",
    "away_matchup_neutral_seconds_per_play_missing",
    "home_matchup_neutral_seconds_per_play",
    "home_matchup_neutral_seconds_per_play_missing",
    "away_matchup_neutral_pass_rate",
    "away_matchup_neutral_pass_rate_missing",
    "home_matchup_neutral_pass_rate",
    "home_matchup_neutral_pass_rate_missing",
    "away_matchup_red_zone_td_rate",
    "away_matchup_red_zone_td_rate_missing",
    "home_matchup_red_zone_td_rate",
    "home_matchup_red_zone_td_rate_missing",
    "away_matchup_goal_to_go_td_rate",
    "away_matchup_goal_to_go_td_rate_missing",
    "home_matchup_goal_to_go_td_rate",
    "home_matchup_goal_to_go_td_rate_missing",
    "away_matchup_turnovers_per_drive",
    "away_matchup_turnovers_per_drive_missing",
    "home_matchup_turnovers_per_drive",
    "home_matchup_turnovers_per_drive_missing",
    "away_matchup_sacks_per_dropback",
    "away_matchup_sacks_per_dropback_missing",
    "home_matchup_sacks_per_dropback",
    "home_matchup_sacks_per_dropback_missing",
    "away_matchup_air_yards_per_attempt",
    "away_matchup_air_yards_per_attempt_missing",
    "home_matchup_air_yards_per_attempt",
    "home_matchup_air_yards_per_attempt_missing",
    "away_matchup_yac_per_completion",
    "away_matchup_yac_per_completion_missing",
    "home_matchup_yac_per_completion",
    "home_matchup_yac_per_completion_missing",
    "away_matchup_explosive_pass_rate",
    "away_matchup_explosive_pass_rate_missing",
    "home_matchup_explosive_pass_rate",
    "home_matchup_explosive_pass_rate_missing",
    "away_matchup_explosive_rush_rate",
    "away_matchup_explosive_rush_rate_missing",
    "home_matchup_explosive_rush_rate",
    "home_matchup_explosive_rush_rate_missing",
)

assert len(EXACT_90_COLUMNS) == 90, f"Expected 90 columns, got {len(EXACT_90_COLUMNS)}"


class FeatureTableError(WalkForwardError):
    """Raised when feature table construction cannot proceed."""


class TeamNormalizationError(WalkForwardError):
    """Raised when a PBP team abbreviation cannot be mapped deterministically
    to its game's accepted canonical identity."""


@dataclass(frozen=True)
class TotalsV1FeatureTable:
    """Result of a Totals V1 feature build.

    ``features`` contains exactly the 90 declared feature columns in
    contract order.  ``identity`` contains the seven metadata columns
    (game_id, season, season_type, week, home_team, away_team, block_id)
    aligned row-for-row with ``features``.  ``provenance`` carries
    per-block build provenance.
    """

    features: pl.DataFrame
    identity: pl.DataFrame
    provenance: tuple[BuildProvenance, ...]


def _load_oracle_qb(
    path: Path,
) -> pl.DataFrame:
    """Load and validate the Oracle QB v2 artifact.

    Returns the loaded frame with only the consumed columns and the key
    columns (game_id, side).  Prohibited columns are never loaded.
    """
    if not path.exists():
        raise FeatureTableError("_load_oracle_qb", f"Oracle QB artifact not found: {path}")

    full = pl.read_parquet(path)

    # Validate unique (game_id, side) key.
    key_dups = full.select("game_id", "side").is_duplicated().sum()
    if key_dups:
        raise FeatureTableError(
            "_load_oracle_qb",
            f"Oracle QB has {key_dups} duplicate (game_id, side) rows",
        )

    # Select only the consumed columns plus key columns.
    keep_cols = ["game_id", "side"] + list(_ORACLE_QB_CONSUMED_COLUMNS)
    missing = sorted(set(keep_cols) - set(full.columns))
    if missing:
        raise FeatureTableError("_load_oracle_qb", f"Oracle QB missing consumed columns: {missing}")

    return full.select(keep_cols)


def _join_oracle_qb(
    game_id: str,
    oracle_qb: pl.DataFrame,
) -> dict[str, object]:
    """Extract Oracle QB features for one game (both sides).

    Returns a dict with22 QB columns (11 away + 11 home).
    If a side is missing, all columns for that side are None.
    """
    result: dict[str, object] = {}

    for side in ("away", "home"):
        rows = oracle_qb.filter(
            (pl.col("game_id") == game_id) & (pl.col("side") == side)
        )
        if rows.height == 0:
            # Missing side: all QB columns None
            for src_col, suffix in _ORACLE_QB_SOURCE_TO_SUFFIX.items():
                result[f"{side}_{suffix}"] = None
        else:
            row = rows.row(0, named=True)
            for src_col, suffix in _ORACLE_QB_SOURCE_TO_SUFFIX.items():
                val = row.get(src_col)
                # Cast Boolean to int for consistency with the numeric column contract
                if isinstance(val, bool):
                    val = int(val)
                result[f"{side}_{suffix}"] = val

    return result


def _emit_feature_row(
    *,
    game_id: str,
    home_team: str,
    away_team: str,
    snapshot: BlockStartSnapshot,
    context_row: dict[str, object],
    oracle_qb: pl.DataFrame,
) -> dict[str, object]:
    """Emit one90-column feature row for a target game.

    Uses the frozen entering-state snapshot (no current-game information),
    context from the projected schedule, and Oracle QB state.
    """
    home_state = snapshot.team(home_team)
    away_state = snapshot.team(away_team)

    # Context features
    row = extract_context_features(context_row)

    # Oracle QB features
    row.update(_join_oracle_qb(game_id, oracle_qb))

    # Matchup features for all 15 families
    for family in MATCHUP_FAMILIES:
        row.update(compute_matchup_pair(home_state, away_state, family))

    return row


def _split_pbp_by_game(
    mapped_pbp: pl.DataFrame,
) -> dict[str, pl.DataFrame]:
    """Split a mapped PBP frame into per-game DataFrames keyed by game_id."""
    result: dict[str, pl.DataFrame] = {}
    for game_id in mapped_pbp["game_id"].unique().sort().to_list():
        result[str(game_id)] = mapped_pbp.filter(pl.col("game_id") == game_id)
    return result


def _build_game_to_teams(
    canonical_games: pl.DataFrame,
) -> dict[str, tuple[str, str]]:
    """Build game_id -> (home_team, away_team) mapping from canonical games."""
    result: dict[str, tuple[str, str]] = {}
    for row in canonical_games.iter_rows(named=True):
        result[str(row["game_id"])] = (str(row["home_team"]), str(row["away_team"]))
    return result


def _normalize_pbp_teams_to_canonical(
    mapped_pbp: pl.DataFrame,
) -> pl.DataFrame:
    """Deterministically normalize ``posteam``/``defteam`` using EACH game's own
    accepted source -> canonical identity mapping (per-game, not global).

    Frozen contract authority: for a given ``game_id`` the only accepted
    canonical mapping is

        raw/PBP ``home_team``      -> ``home_team_canonical``
        raw/PBP ``away_team``      -> ``away_team_canonical``

    ``posteam`` and ``defteam`` may normalize ONLY through that game's own
    two-team mapping. There is NO global franchise alias dictionary, no
    inference from another game, no "most common", no last-write-wins, and
    no guessing.

    Algorithm per row:
      1. identify the row's ``game_id``;
      2. load that game's accepted two source->canonical mappings;
      3. for non-null ``posteam``: it must equal one of the game's accepted
         source identities (then normalized) OR already equal the game's
         corresponding accepted canonical identity (kept); otherwise
         HARD-FAIL;
      4. apply the same rule independently to ``defteam``.

    Null ``posteam``/``defteam`` remain null. ``game_id`` never changes.

    Unambiguity safety: before normalizing, each game_id is validated to have
    a single raw home, a single raw away, a single canonical home, a single
    canonical away, and no source identity that maps to more than one
    canonical identity within that game. Any of these HARD-FAILS with the
    offending game(s); ambiguity is never resolved heuristically.
    """
    required = {"game_id", "home_team", "away_team", "home_team_canonical", "away_team_canonical"}
    missing = sorted(required - set(mapped_pbp.columns))
    if missing:
        raise TeamNormalizationError(
            "_normalize_pbp_teams_to_canonical",
            f"mapped PBP missing canonical identity columns for per-game "
            f"normalization: {missing}",
        )

    # 1. Per-game unique team identity rows.
    ident = (
        mapped_pbp
        .select("game_id", "home_team", "away_team", "home_team_canonical", "away_team_canonical")
        .unique()
    )

    # 2. Completeness + unambiguity pre-validation.
    # Every game_id must have EXACTLY ONE complete two-team identity: each of
    # the four slots (raw home, raw away, canonical home, canonical away) must
    # be present exactly once -- not 0 and not >1. A missing identity is a
    # gap that hard-fails before normalization begins (never deferred until a
    # posteam/defteam row happens to reference it).
    aggs = ident.group_by("game_id").agg([
        pl.col("home_team").drop_nulls().n_unique().alias("n_raw_home"),
        pl.col("away_team").drop_nulls().n_unique().alias("n_raw_away"),
        pl.col("home_team_canonical").drop_nulls().n_unique().alias("n_canon_home"),
        pl.col("away_team_canonical").drop_nulls().n_unique().alias("n_canon_away"),
    ])
    incomplete = aggs.filter(
        (pl.col("n_raw_home") != 1)
        | (pl.col("n_raw_away") != 1)
        | (pl.col("n_canon_home") != 1)
        | (pl.col("n_canon_away") != 1)
    )
    if incomplete.height:
        rows = sorted(incomplete.iter_rows(named=True), key=lambda r: str(r["game_id"]))
        raise TeamNormalizationError(
            "_normalize_pbp_teams_to_canonical",
            f"{incomplete.height} game(s) lack an EXACTLY-ONE complete two-team "
            f"identity (each slot must be present exactly once, never 0 or >1); "
            f"offending=({rows[:10]})",
        )

    # 2b. Two distinct teams per side. A football game cannot have the same
    #     team occupying both slots of the accepted identity: raw home != raw
    #     away AND canonical home != canonical away. After the exactly-one
    #     guard above, each game has exactly one identity row.
    collapsed: list[tuple] = []
    for row in ident.iter_rows(named=True):
        rh, ra, ch, ca = (row["home_team"], row["away_team"],
                          row["home_team_canonical"], row["away_team_canonical"])
        if rh is not None and ra is not None and str(rh) == str(ra):
            collapsed.append((str(row["game_id"]), "raw", str(rh)))
        if ch is not None and ca is not None and str(ch) == str(ca):
            collapsed.append((str(row["game_id"]), "canonical", str(ch)))
    if collapsed:
        raise TeamNormalizationError(
            "_normalize_pbp_teams_to_canonical",
            f"{len(collapsed)} game(s) have a collapsed one-team identity "
            f"(raw home==raw away or canonical home==canonical away); "
            f"offending=({collapsed[:10]})",
        )

    # 3. Build the per-game (game_id, source_abbr) -> canonical mapping.
    #    Already-canonical identities are added as identity passthroughs so a
    #    value already equal to the accepted canonical team is kept unchanged.
    mapping_rows: list[tuple[str, str, str]] = []
    for row in ident.iter_rows(named=True):
        gid = str(row["game_id"])
        rh, ra = row["home_team"], row["away_team"]
        ch, ca = row["home_team_canonical"], row["away_team_canonical"]
        if rh is not None and ch is not None:
            mapping_rows.append((gid, str(rh), str(ch)))
            mapping_rows.append((gid, str(ch), str(ch)))
        if ra is not None and ca is not None:
            mapping_rows.append((gid, str(ra), str(ca)))
            mapping_rows.append((gid, str(ca), str(ca)))
    map_df = pl.DataFrame(mapping_rows, schema=["game_id", "src", "canon"], orient="row").unique()

    # 4. A source identity that maps to >1 canonical within one game is
    #    ambiguous -> hard-fail (covers raw-home == raw-away collapse and any
    #    source identity resolving to two distinct canonicals).
    dup = map_df.group_by(["game_id", "src"]).agg(pl.col("canon").n_unique().alias("n"))
    ambig = dup.filter(pl.col("n") > 1)
    if ambig.height:
        first = sorted(ambig.iter_rows(named=True), key=lambda r: str(r["game_id"]))[:10]
        raise TeamNormalizationError(
            "_normalize_pbp_teams_to_canonical",
            f"{ambig.height} (game_id, source_abbr) pair(s) resolve to >1 "
            f"canonical identity (ambiguous); {first}",
        )

    # 5. Apply per-row normalization by joining each team column through the
    #    per-game mapping. Non-null values without a mapping HARD-FAIL.
    result = mapped_pbp
    for col in ("posteam", "defteam"):
        if col not in result.columns:
            continue
        canon_key = f"_canon_{col}"
        canon_map = map_df.select(
            pl.col("game_id"),
            pl.col("src").alias(col),
            pl.col("canon").alias(canon_key),
        )
        # Cast the team column to String so null-typed columns join cleanly
        # against the string mapping (real PBP is already String; harmless).
        joined = result.with_columns(pl.col(col).cast(pl.String).alias(col)) \
            .join(canon_map, on=["game_id", col], how="left")
        unknown = joined.filter(pl.col(col).is_not_null() & pl.col(canon_key).is_null())
        if unknown.height:
            values = sorted(set(str(v) for v in unknown[col].to_list()))
            raise TeamNormalizationError(
                "_normalize_pbp_teams_to_canonical",
                f"{unknown.height} row(s) have non-null {col} with no unambiguous "
                f"canonical identity for their game; unknown values={values} "
                f"(never guessed or preserved as-is)",
            )
        result = joined.with_columns(pl.col(canon_key).alias(col)).drop(canon_key)

    return result


def build_totals_v1_feature_table(
    pbp_root: Path | str,
    schedule: pl.DataFrame,
    canonical_games: pl.DataFrame,
    oracle_qb_path: Path | str,
    *,
    allowed_max_season: int = DEVELOPMENT_SEASON_MAX,
) -> TotalsV1FeatureTable:
    """Build the Totals V1 feature table for the development window.

    This is the Phase 3D main entry point.  It orchestrates:

    1. PBP manifest verification and loading
    2. Canonical game mapping
    3. Chronology (blocks, availability)
    4. Context projection (rest/roof/surface from schedule)
    5. Oracle QB state loading
    6. Block-by-block entering-state aggregation with exact minima
    7. Matchup combination for 15 families
    8. Exact90-column feature table emission

    Parameters
    ----------
    pbp_root:
        Root directory containing the promoted PBP parquet artifacts.
    schedule:
        Raw frozen schedule frame (contains prohibited fields that will
        be projected out).
    canonical_games:
        Canonical games table with game_id, season, season_type, week,
        home_team, away_team.
    oracle_qb_path:
        Path to the Oracle QB v2 parquet artifact.
    allowed_max_season:
        Maximum NFL season to include (default: 2024).

    Returns
    -------
    TotalsV1FeatureTable
        The feature DataFrame and per-block provenance records.
    """
    pbp_root = Path(pbp_root)
    oracle_qb_path = Path(oracle_qb_path)

    # 1. Validate canonical games
    validate_canonical_games(canonical_games)

    # 2. Load Oracle QB
    oracle_qb = _load_oracle_qb(oracle_qb_path)

    # 3. Project context from schedule (applies development boundary,
    #    removes prohibited columns, selects only approved fields)
    # Pre-filter schedule to development seasons only to avoid triggering
    # the sealed-holdout assertion in project_totals_context.
    dev_schedule = schedule.filter(pl.col("season") <= allowed_max_season)
    context = project_totals_context(dev_schedule)

    # 4. Build context lookup by game_id (rest + surface from schedule)
    context_lookup: dict[str, dict[str, object]] = {}
    for row in context.iter_rows(named=True):
        context_lookup[str(row["game_id"])] = row

    # 4b. Build roof_type lookup from canonical games (the authoritative
    #     roof source per the frozen Phase 2 contract).
    roof_type_lookup: dict[str, str | None] = {}
    for row in canonical_games.iter_rows(named=True):
        roof_type_lookup[str(row["game_id"])] = row.get("roof_type")

    # 5. Build chronology
    dev_games = canonical_games.filter(pl.col("season") <= allowed_max_season)
    availability = build_availability_table(dev_games)

    # Join prediction_as_of_utc onto the dev_games frame so
    # build_development_blocks can find it.
    avail_join = availability.select(
        "season", "season_type", "week", "prediction_as_of_utc"
    )
    dev_games_with_asof = dev_games.join(
        avail_join, on=["season", "season_type", "week"], how="left"
    )
    if dev_games_with_asof["prediction_as_of_utc"].null_count():
        raise FeatureTableError(
            "build_totals_v1_feature_table",
            "some dev_games lack prediction_as_of_utc after availability join",
        )

    blocks = build_totals_blocks(dev_games_with_asof, allowed_max_season=allowed_max_season)

    # 6. Build game_to_teams
    game_to_teams = _build_game_to_teams(dev_games)

    # 7. Load PBP frames and map to canonical
    # The schedule has game_type (canonical); PBP has season_type (REG/POST).
    # We need the canonical games table for the mapping.
    # For the mapping, the schedule's game_type maps to canonical season_type.
    # We'll build a mapping table from the canonical games.
    pbp_frames_by_season = load_pbp_frames(pbp_root)

    # Map PBP to canonical for each season
    all_mapped_parts: list[pl.DataFrame] = []
    for season in sorted(pbp_frames_by_season.keys()):
        if season > allowed_max_season:
            continue
        pbp = pbp_frames_by_season[season]
        mapped = map_pbp_to_canonical(pbp, canonical_games)
        all_mapped_parts.append(mapped)

    if not all_mapped_parts:
        empty_features = pl.DataFrame(schema={c: pl.Float64 for c in EXACT_90_COLUMNS}).select(list(EXACT_90_COLUMNS))
        empty_identity = pl.DataFrame(
            schema={"game_id": pl.String, "season": pl.Int32, "season_type": pl.String,
                     "week": pl.Int32, "home_team": pl.String, "away_team": pl.String, "block_id": pl.String}
        )
        return TotalsV1FeatureTable(
            features=empty_features,
            identity=empty_identity,
            provenance=(),
        )

    all_mapped = pl.concat(all_mapped_parts)

    # Normalize PBP team abbreviations to canonical ones.
    # The PBP data uses historical abbreviations (OAK, LA, JAX, etc.)
    # while the canonical games table uses the standardized abbreviations
    # (LV, LAR, JAX, etc.). We use the canonical identity columns
    # (home_team_canonical, away_team_canonical) paired with the PBP
    # home_team/away_team to build a per-game alias map.
    all_mapped = _normalize_pbp_teams_to_canonical(all_mapped)
    per_game_pbp = _split_pbp_by_game(all_mapped)

    # 8. Block-by-block feature emission
    state = TotalsBlockState()
    feature_rows: list[dict[str, object]] = []
    identity_rows: list[dict[str, object]] = []
    provenance_records: list[BuildProvenance] = []

    for target_block in blocks:
        # 8a. Determine eligible source blocks (for provenance)
        eligible_sources = eligible_source_blocks(target_block, blocks, availability)
        eligible_source_ids = tuple(s.block_id for s in eligible_sources)

        # 8b. Snapshot current state (before this block)
        snapshot = state.snapshot_for_block(target_block)

        # 8c. Emit feature rows for each game in the target block
        for game_id in target_block.game_ids:
            game_id_str = str(game_id)
            teams = game_to_teams.get(game_id_str)
            if teams is None:
                raise FeatureTableError(
                    "build_totals_v1_feature_table",
                    f"game_id {game_id_str!r} not in canonical games",
                )
            home_team, away_team = teams

            ctx = context_lookup.get(game_id_str)
            if ctx is None:
                raise FeatureTableError(
                    "build_totals_v1_feature_table",
                    f"game_id {game_id_str!r} not in context projection",
                )

            # Inject roof_type from canonical games (authoritative roof source)
            ctx_with_roof = {**ctx, "roof_type": roof_type_lookup.get(game_id_str)}

            feature_row = _emit_feature_row(
                game_id=game_id_str,
                home_team=home_team,
                away_team=away_team,
                snapshot=snapshot,
                context_row=ctx_with_roof,
                oracle_qb=oracle_qb,
            )

            # Build the output row: identity + features
            # Identity columns are outside the 90-column feature matrix
            block_game = dev_games.filter(pl.col("game_id") == game_id_str)
            if block_game.height:
                bg = block_game.row(0, named=True)
                identity_rows.append(
                    {
                        "game_id": game_id_str,
                        "season": int(bg["season"]),
                        "season_type": str(bg["season_type"]),
                        "week": int(bg["week"]),
                        "home_team": str(bg["home_team"]),
                        "away_team": str(bg["away_team"]),
                        "block_id": target_block.block_id,
                    }
                )
            else:
                identity_rows.append(
                    {
                        "game_id": game_id_str,
                        "season": target_block.season,
                        "season_type": target_block.season_type,
                        "week": target_block.week,
                        "home_team": home_team,
                        "away_team": away_team,
                        "block_id": target_block.block_id,
                    }
                )

            feature_rows.append(feature_row)

        # 8d. Build and commit this block's game observations
        # Filter PBP to this block's games
        block_pbp = {
            gid: per_game_pbp[gid]
            for gid in target_block.game_ids
            if gid in per_game_pbp
        }

        if block_pbp:
            observations, block_counters = build_game_observations_with_provenance(
                block_id=target_block.block_id,
                pbp_frames=block_pbp,
                game_to_teams=game_to_teams,
            )
        else:
            # No PBP for this block (shouldn't happen in dev, but be safe)
            observations = [
                GameObservation(block_id=target_block.block_id, game_id=gid, team_updates={})
                for gid in target_block.game_ids
            ]
            block_counters = ProvenanceCounters()

        # Commit block observations to state
        state.commit_block(target_block, observations)

        # Record provenance
        pb_files = []
        for season, frame in pbp_frames_by_season.items():
            from .manifest import CANONICAL_PBP_MANIFEST as manifest

            for artifact in manifest:
                if artifact.season == season:
                    pb_files.append(
                        PbpFileProvenance(
                            filename=artifact.filename,
                            sha256=artifact.sha256,
                            byte_size=artifact.byte_size,
                            row_count=frame.height,
                        )
                    )
                    break

        prov = block_counters.to_build_provenance(
            target_block_id=target_block.block_id,
            eligible_source_block_ids=eligible_source_ids,
            pb_files=pb_files,
        )
        provenance_records.append(prov)

    # 9. Assemble the final feature table
    # Build the feature matrix with exact 90-column order
    feature_dicts = feature_rows
    feature_frame = pl.DataFrame(feature_dicts)

    # Ensure all 90 columns exist (some may be missing if no data)
    for col in EXACT_90_COLUMNS:
        if col not in feature_frame.columns:
            feature_frame = feature_frame.with_columns(pl.lit(None).alias(col))

    # Select exactly the 90 columns in order — nothing more
    feature_frame = feature_frame.select(list(EXACT_90_COLUMNS))

    # Build identity frame (separate from the 90-column feature matrix)
    identity_frame = pl.DataFrame(identity_rows)

    # Validate invariants before returning
    assert feature_frame.width == 90, (
        f"Feature matrix width {feature_frame.width} != 90"
    )
    assert feature_frame.columns == list(EXACT_90_COLUMNS), (
        "Feature matrix columns do not match EXACT_90_COLUMNS"
    )
    assert identity_frame.height == feature_frame.height, (
        f"Identity row count {identity_frame.height} != feature row count {feature_frame.height}"
    )

    return TotalsV1FeatureTable(
        features=feature_frame,
        identity=identity_frame,
        provenance=tuple(provenance_records),
    )
