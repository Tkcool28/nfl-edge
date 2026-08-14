"""Tests for the deterministic Phase-3A provenance structures."""

from __future__ import annotations

import pytest

from nfl_edge.features.totals_v1.provenance import (
    BuildProvenance,
    PbpFileProvenance,
    pb_files_from_frames,
    zero_counters,
)


def _build(files=(), **kw) -> BuildProvenance:
    return BuildProvenance(**kw)


def test_valid_case_reports_zero_violations():
    p = _build(target_block_id="2024_SB_W22", eligible_source_block_ids=("2024_REG_W17",))
    assert p.valid_development_build is True
    p.assert_clean_development()  # no raise


def test_injected_same_block_violation_flagged():
    p = _build(target_block_id="2024_REG_W05", same_block_source_rows=3)
    assert p.valid_development_build is False
    with pytest.raises(ValueError, match="same_block_source_rows"):
        p.assert_clean_development()


def test_injected_future_violation_flagged():
    p = _build(target_block_id="2024_REG_W05", future_block_source_rows=2)
    assert p.valid_development_build is False


def test_injected_season_2025_violation_flagged():
    p = _build(target_block_id="2024_REG_W05", season_2025_source_rows=1)
    assert p.valid_development_build is False


def test_mapping_failure_violation_flagged():
    p = _build(target_block_id="2024_REG_W05", canonical_mapping_failures=4)
    assert p.valid_development_build is False


def test_source_block_ids_deterministic_sorted():
    p = _build(eligible_source_block_ids=("2024_REG_W18", "2024_REG_W17", "2024_WC_W19"))
    assert p.eligible_source_block_ids == ("2024_REG_W17", "2024_REG_W18", "2024_WC_W19")


def test_serialization_deterministic():
    a = _build(
        target_block_id="2024_SB_W22",
        eligible_source_block_ids=("2024_REG_W17", "2024_WC_W19"),
        pb_files=(PbpFileProvenance("x.pq", "sha", 10, 5),),
        same_block_source_rows=0,
    )
    b = _build(
        pb_files=(PbpFileProvenance("x.pq", "sha", 10, 5),),
        target_block_id="2024_SB_W22",
        eligible_source_block_ids=("2024_WC_W19", "2024_REG_W17"),
    )
    assert a.to_json() == b.to_json()
    assert a.fingerprint() == b.fingerprint()
    assert len(a.fingerprint()) == 64


def test_pb_files_order_normalized_in_object():
    """Same PBP entries supplied in different orders serialize identically."""
    files_a = (
        PbpFileProvenance("play_by_play_2018.parquet", "sha1", 100, 10),
        PbpFileProvenance("play_by_play_2019.parquet", "sha2", 200, 20),
        PbpFileProvenance("play_by_play_2020.parquet", "sha3", 300, 30),
    )
    files_b = (
        PbpFileProvenance("play_by_play_2020.parquet", "sha3", 300, 30),
        PbpFileProvenance("play_by_play_2018.parquet", "sha1", 100, 10),
        PbpFileProvenance("play_by_play_2019.parquet", "sha2", 200, 20),
    )
    a = _build(target_block_id="t", pb_files=files_a)
    b = _build(target_block_id="t", pb_files=files_b)
    # ordering normalized inside the object, independent of construction order
    assert a.pb_files == b.pb_files
    filenames = [f.filename for f in a.pb_files]
    assert filenames == sorted(filenames)
    assert a.to_json() == b.to_json()
    assert a.fingerprint() == b.fingerprint()


def test_counters_bump():
    c = zero_counters()
    c2 = c.add_same_game().add_same_block(2).add_future().add_season_2025().add_mapping_failures(3)
    assert c2.same_game_source_rows == 1
    assert c2.same_block_source_rows == 2
    assert c2.future_block_source_rows == 1
    assert c2.season_2025_source_rows == 1
    assert c2.canonical_mapping_failures == 3
    # original still zero (immutable)
    assert c.same_game_source_rows == 0


def test_counters_to_build_provenance_freezes_sorted():
    c = zero_counters().add_same_block(1)
    p = c.to_build_provenance(
        target_block_id="2024_REG_W05",
        eligible_source_block_ids=("2024_REG_W18", "2024_REG_W17"),
    )
    assert p.same_block_source_rows == 1
    assert p.eligible_source_block_ids == ("2024_REG_W17", "2024_REG_W18")
    assert p.target_block_id == "2024_REG_W05"


def test_pb_files_from_frames_orders_by_filename():
    files = pb_files_from_frames(
        filenames={2018: "play_by_play_2018.parquet", 2019: "play_by_play_2019.parquet"},
        shas={2018: "a", 2019: "b"},
        byte_sizes={2018: 1, 2019: 2},
        row_counts={2018: 10, 2019: 20},
    )
    assert [f.filename for f in files] == [
        "play_by_play_2018.parquet", "play_by_play_2019.parquet",
    ]
    assert files[0].row_count == 10


def test_to_dict_shape():
    p = _build(target_block_id="t", eligible_source_block_ids=("a",), same_block_source_rows=0)
    d = p.to_dict()
    assert set(d) == {"target_block_id", "eligible_source_block_ids", "pbp_files",
                      "violations", "dropback_fallback_rows"}
    assert set(d["violations"]) == {
        "same_game_source_rows", "same_block_source_rows", "future_block_source_rows",
        "season_2025_source_rows", "canonical_mapping_failures",
    }