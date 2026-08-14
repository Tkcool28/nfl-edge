"""Tests for canonical PBP game/block mapping (raw REG/POST -> canonical blocks).

``map_pbp_to_canonical`` is safe by construction: a single call performs every
required mapping validation and hard-fails on any violation. These tests prove
each six required gates fire from that single public call, so a caller cannot
obtain an invalid development mapping.
"""

from __future__ import annotations

import polars as pl
import pytest

from nfl_edge.common.errors import SealedHoldoutAccessError
from nfl_edge.features.totals_v1.mapping import (
    CANONICAL_POSTSEASON_TYPES,
    CanonicalMappingError,
    map_pbp_to_canonical,
    season_type_canonical,
    validate_canonical_games,
)


def _canonical_rows():
    return pl.DataFrame(
        {
            "game_id": [
                "2024_01_KC_BAL",  # REG
                "2024_19_LAC_HOU",  # WC
                "2024_20_LA_PHI",  # DIV
                "2024_21_BUF_KC",  # CON
                "2024_22_KC_PHI",  # SB
            ],
            "season": [2024, 2024, 2024, 2024, 2024],
            "season_type": ["REG", "WC", "DIV", "CON", "SB"],
            "week": [1, 19, 20, 21, 22],
            "away_team": ["KC", "LAC", "LA", "BUF", "KC"],
            "home_team": ["BAL", "HOU", "PHI", "KC", "PHI"],
        }
    )


def _pbp_rows(pairs, seasons=None):
    """Build a PBP frame from (game_id, raw_season_type) pairs."""
    return pl.DataFrame(
        {
            "game_id": [g for g, _ in pairs],
            "season": [seasons.get(g, 2024) if isinstance(seasons, dict) else (seasons or 2024) for g, _ in pairs],
            "season_type": [st for _, st in pairs],
            "week": [1] * len(pairs),
            "home_team": ["X"] * len(pairs),
            "away_team": ["Y"] * len(pairs),
        }
    )


# --- Positive paths: valid development mappings succeed in one call. ---


def test_raw_reg_maps_to_canonical_reg():
    canon = _canonical_rows()
    pbp = _pbp_rows([("2024_01_KC_BAL", "REG")])
    mapped = map_pbp_to_canonical(pbp, canon)
    assert mapped["season_type_canonical"].to_list() == ["REG"]


@pytest.mark.parametrize("gid,st", [
    ("2024_19_LAC_HOU", "WC"),
    ("2024_20_LA_PHI", "DIV"),
    ("2024_21_BUF_KC", "CON"),
    ("2024_22_KC_PHI", "SB"),
])
def test_raw_post_maps_to_postseason_block(gid, st):
    canon = _canonical_rows()
    pbp = _pbp_rows([(gid, "POST")])
    mapped = map_pbp_to_canonical(pbp, canon)
    assert mapped["season_type_canonical"].to_list() == [st]
    assert mapped["pbp_season_type"].to_list() == ["POST"]  # raw preserved


def test_all_postseason_types_valid():
    canon = _canonical_rows()
    pbp = _pbp_rows([
        ("2024_19_LAC_HOU", "POST"),
        ("2024_20_LA_PHI", "POST"),
        ("2024_21_BUF_KC", "POST"),
        ("2024_22_KC_PHI", "POST"),
    ])
    mapped = map_pbp_to_canonical(pbp, canon)
    assert set(mapped["season_type_canonical"].unique().to_list()) == set(CANONICAL_POSTSEASON_TYPES)
    # A canonical block is never raw POST.
    assert "POST" not in mapped["season_type_canonical"].unique().to_list()


# --- Negative paths: each gate fires from the single public call. ---


def test_single_call_conflicting_nfl_season_hard_fails():
    canon = _canonical_rows()
    pbp = _pbp_rows([("2024_01_KC_BAL", "REG")], seasons={"2024_01_KC_BAL": 2023})
    with pytest.raises(CanonicalMappingError, match="conflict with canonical season"):
        map_pbp_to_canonical(pbp, canon)


def test_single_call_raw_reg_to_postseason_hard_fails():
    """Raw REG paired with a postseason canonical game must fail the pairing gate."""
    canon = _canonical_rows()
    pbp = pl.DataFrame(
        {
            "game_id": ["2024_19_LAC_HOU"],  # canonical WC
            "season": [2024],
            "season_type": ["REG"],  # raw REG but canonical is WC -- invalid
            "week": [1],
            "home_team": ["X"],
            "away_team": ["Y"],
        }
    )
    with pytest.raises(CanonicalMappingError, match="invalid raw/canonical season-type"):
        map_pbp_to_canonical(pbp, canon)


def test_single_call_raw_post_to_reg_hard_fails():
    canon = _canonical_rows()
    pbp = pl.DataFrame(
        {
            "game_id": ["2024_01_KC_BAL"],  # canonical REG
            "season": [2024],
            "season_type": ["POST"],  # raw POST pointing at a REG game -- invalid
            "week": [1],
            "home_team": ["X"],
            "away_team": ["Y"],
        }
    )
    with pytest.raises(CanonicalMappingError, match="invalid raw/canonical season-type"):
        map_pbp_to_canonical(pbp, canon)


def test_single_call_canonical_2025_hard_fails():
    """Canonical season 2025 is sealed and must fail from the single call."""
    canon = _canonical_rows().vstack(
        pl.DataFrame({"game_id": ["2025_01_KC_BAL"], "season": [2025], "season_type": ["REG"],
                      "week": [1], "away_team": ["KC"], "home_team": ["BAL"]})
    )
    pbp = _pbp_rows([("2025_01_KC_BAL", "REG")], seasons={"2025_01_KC_BAL": 2025})
    with pytest.raises(SealedHoldoutAccessError):
        map_pbp_to_canonical(pbp, canon)


def test_single_call_unmatched_required_pbp_id_hard_fails():
    canon = _canonical_rows()
    pbp = _pbp_rows([("2024_99_MISSING", "REG")])
    with pytest.raises(CanonicalMappingError, match="missing from canonical games"):
        map_pbp_to_canonical(pbp, canon)


def test_single_call_duplicate_canonical_game_hard_fails():
    """A duplicate canonical game_id must fail from the single mapping call."""
    canon = _canonical_rows().vstack(
        pl.DataFrame({"game_id": ["2024_01_KC_BAL"], "season": [2024], "season_type": ["REG"],
                      "week": [1], "away_team": ["KC"], "home_team": ["BAL"]})
    )
    pbp = _pbp_rows([("2024_01_KC_BAL", "REG")])
    with pytest.raises(CanonicalMappingError, match="duplicate canonical game_id"):
        map_pbp_to_canonical(pbp, canon)


# --- Individual validation helpers remain available as supporting gates. ---


def test_validate_canonical_games_detects_duplicate():
    canon = _canonical_rows().vstack(
        pl.DataFrame({"game_id": ["2024_01_KC_BAL"], "season": [2024], "season_type": ["REG"],
                      "week": [1], "away_team": ["KC"], "home_team": ["BAL"]})
    )
    with pytest.raises(CanonicalMappingError, match="duplicate canonical game_id"):
        validate_canonical_games(canon)


def test_season_type_canonical_annotations():
    canon = _canonical_rows()
    pbp = _pbp_rows([("2024_19_LAC_HOU", "POST"), ("2024_01_KC_BAL", "REG")])
    mapped = map_pbp_to_canonical(pbp, canon)
    ann = season_type_canonical(mapped)
    assert "block_type" in ann.columns
    assert "is_postseason_block" in ann.columns
    assert "pbp_season_type" in ann.columns
    assert ann.filter(pl.col("game_id") == "2024_19_LAC_HOU")["is_postseason_block"].to_list() == [True]
    assert ann.filter(pl.col("game_id") == "2024_01_KC_BAL")["is_postseason_block"].to_list() == [False]
    # raw POST flagged
    assert ann.filter(pl.col("game_id") == "2024_19_LAC_HOU")["is_raw_post"].to_list() == [True]
