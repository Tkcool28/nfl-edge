"""Tests for the Totals V1 canonical chronology layer (reuses repo primitives)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import polars as pl
import pytest

from nfl_edge.backtest.blocks import PredictionBlock
from nfl_edge.features.totals_v1.chronology import (
    block_is_available_by,
    build_availability_table,
    build_totals_blocks,
    canonical_block_key,
    eligible_source_blocks,
    eligible_source_game_ids,
    is_strictly_earlier,
    iter_blocks,
)

UTC = timezone.utc


def _block(season, st, week, asof=None):
    asof = asof or datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    gid = f"{season}_{week:02d}_{st}_A_B"
    return PredictionBlock(
        block_id=f"{season}_{st}_W{week:02d}",
        season=season,
        season_type=st,
        week=week,
        as_of_utc=asof,
        game_ids=(gid,),
    )


def test_canonical_block_key_order():
    reg = canonical_block_key(2024, "REG", 1)
    wc = canonical_block_key(2024, "WC", 19)
    div = canonical_block_key(2024, "DIV", 20)
    con = canonical_block_key(2024, "CON", 21)
    sb = canonical_block_key(2024, "SB", 22)
    assert reg < wc < div < con < sb
    # season primary
    assert canonical_block_key(2023, "SB", 22) < canonical_block_key(2024, "REG", 1)
    # week secondary within same type
    assert canonical_block_key(2024, "REG", 1) < canonical_block_key(2024, "REG", 2)


def test_strictly_earlier_same_block_false():
    a = _block(2024, "REG", 1)
    assert not is_strictly_earlier(a, a)


def test_earlier_reg_eligible_than_wc():
    reg = _block(2024, "REG", 17)
    wc = _block(2024, "WC", 19)
    assert is_strictly_earlier(reg, wc)
    assert not is_strictly_earlier(wc, reg)


def test_future_block_not_earlier():
    now = _block(2024, "REG", 10)
    future = _block(2024, "REG", 11)
    assert not is_strictly_earlier(future, now)
    assert is_strictly_earlier(now, future)


@pytest.mark.parametrize("a,b,expected", [
    ("REG", "WC", True),
    ("WC", "DIV", True),
    ("DIV", "CON", True),
    ("CON", "SB", True),
    ("WC", "REG", False),  # postseason backward into REG disallowed
])
def test_postseason_forward_only(a, b, expected):
    src = _block(2024, a, 19)
    tgt = _block(2024, b, 20)
    assert is_strictly_earlier(src, tgt) is expected


def test_eligible_source_blocks_excludes_same_and_future():
    blocks = [
        _block(2024, "REG", 17),
        _block(2024, "REG", 18),
        _block(2024, "WC", 19),
    ]
    games = _games_from_blocks(blocks)
    avail = build_availability_table(games)
    target = _block(2024, "WC", 19)
    eligible = eligible_source_blocks(target, blocks, avail)
    assert [b.block_id for b in eligible] == ["2024_REG_W17", "2024_REG_W18"]


def _games_from_blocks(blocks, prediction_asof=None):
    prediction_asof = prediction_asof or datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    return pl.DataFrame(
        {
            "game_id": [g for b in blocks for g in b.game_ids],
            "season": [b.season for b in blocks for _ in b.game_ids],
            "season_type": [b.season_type for b in blocks for _ in b.game_ids],
            "week": [b.week for b in blocks for _ in b.game_ids],
            "prediction_as_of_utc": [prediction_asof] * sum(len(b.game_ids) for b in blocks),
            "gameday": [
                (datetime(b.season, 9, 1, tzinfo=UTC) + timedelta(days=b.week)).date().isoformat()
                for b in blocks for _ in b.game_ids
            ],
        }
    )


def _availability_for_greg_blocks(blocks):
    """Availability where only strictly-earlier regular blocks are eligible."""
    return build_availability_table(_games_from_blocks(blocks))


def _eligibility_for_block(avail, block):
    """Return the exact eligible_for_features_at_utc for a block from the table."""
    for row in avail.iter_rows(named=True):
        if (int(row["season"]), str(row["season_type"]).strip().upper(), int(row["week"])) == (
            block.season, block.season_type, block.week
        ):
            return row["eligible_for_features_at_utc"]
    raise AssertionError(f"no availability row for block {block.block_id}")


def test_availability_cutoff_boundary_equality_eligible():
    """Cutoff exactly equal to eligibility is eligible; just before is not.

    Deterministic boundary around the exact ``eligible_for_features_at_utc``
    computed by the accepted weekly policy, not a tautological True/False.
    """
    blocks = [_block(2024, "REG", 18), _block(2024, "WC", 19)]
    games = _games_from_blocks(blocks)
    avail = build_availability_table(games)
    src = blocks[0]
    eligible_at = _eligibility_for_block(avail, src)

    # 1. cutoff immediately before eligibility -> False
    assert block_is_available_by(src, avail, cutoff=eligible_at - timedelta(microseconds=1)) is False
    # 2. cutoff exactly equal to eligibility -> True
    assert block_is_available_by(src, avail, cutoff=eligible_at) is True
    # 3. cutoff after eligibility -> True
    assert block_is_available_by(src, avail, cutoff=eligible_at + timedelta(microseconds=1)) is True


def test_availability_cutoff_well_after_eligible():
    """A very late cutoff must make the source block available."""
    blocks = [_block(2024, "REG", 18), _block(2024, "WC", 19)]
    avail = build_availability_table(_games_from_blocks(blocks))
    src = blocks[0]
    late = datetime(2025, 3, 1, 12, 0, tzinfo=UTC)
    assert block_is_available_by(src, avail, cutoff=late) is True


def test_availability_element_missing_raises():
    blocks = [_block(2024, "REG", 18)]
    avail = build_availability_table(_games_from_blocks(blocks))
    other = _block(2024, "SB", 22)
    with pytest.raises(Exception):
        block_is_available_by(other, avail, cutoff=other.as_of_utc)


def test_no_availability_row_for_unknown_block_raises():
    blocks = [_block(2024, "REG", 1)]
    avail = build_availability_table(_games_from_blocks(blocks))
    with pytest.raises(Exception):
        block_is_available_by(_block(2024, "SB", 22), avail, cutoff=datetime(2025, 1, 1, tzinfo=UTC))


def test_deterministic_ordering_under_shuffle():
    blocks = [
        _block(2024, "WC", 19),
        _block(2024, "REG", 1),
        _block(2024, "REG", 18),
        _block(2024, "SB", 22),
    ]
    ordered = list(iter_blocks(blocks))
    assert [b.block_id for b in ordered] == [
        "2024_REG_W01",
        "2024_REG_W18",
        "2024_WC_W19",
        "2024_SB_W22",
    ]


def test_eligible_source_game_ids_sorted():
    blocks = [
        _block(2024, "WC", 19),
        _block(2024, "REG", 2),
        _block(2024, "REG", 1),
    ]
    avail = build_availability_table(_games_from_blocks(blocks))
    target = _block(2024, "WC", 19)
    ids = eligible_source_game_ids(target, blocks, avail)
    assert ids == sorted(ids)


def test_build_totals_blocks_orders_chronologically():
    games = _games_from_blocks([
        _block(2024, "WC", 19),
        _block(2020, "REG", 1),
        _block(2022, "REG", 2),
    ])
    blocks = build_totals_blocks(games)
    seasons = [b.season for b in blocks]
    assert seasons == [2020, 2022, 2024]