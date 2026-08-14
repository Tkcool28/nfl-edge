"""Tests for promoted PBP manifest/integrity and deterministic loading.

Uses small temporary fixture files (not the ~140MB promoted artifacts).
A single optional smoke test hits the durable promoted path when present.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import polars as pl
import pytest

from nfl_edge.features.totals_v1.manifest import (
    ARTIFACT_ROOTS,
    CANONICAL_PBP_MANIFEST,
    PbpArtifact,
    PbpArtifactError,
    load_pbp_frames,
    verify_pbp_artifacts,
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_fixture_dir(tmp_path: Path, seasons=(2018, 2019, 2020, 2021, 2022, 2023, 2024)):
    """Create a small 7-file PBP family (real small parquet) and return (root, manifest)."""
    root = tmp_path / "pbp"
    root.mkdir()
    artifacts = []
    for season in seasons:
        filename = f"play_by_play_{season}.parquet"
        buf = io.BytesIO()
        pl.DataFrame({"season": [season], "game_id": [f"{season:04d}_01_A_B"]}).write_parquet(buf)
        data = buf.getvalue()
        (root / filename).write_bytes(data)
        artifacts.append(
            PbpArtifact(filename=filename, byte_size=len(data), sha256=_sha256_bytes(data))
        )
    return root, tuple(artifacts)


def test_valid_manifest_succeeds(tmp_path):
    root, manifest = _build_fixture_dir(tmp_path)
    verified = verify_pbp_artifacts(root, expected=manifest)
    assert verified == manifest


def test_byte_mismatch_fails(tmp_path):
    root, manifest = _build_fixture_dir(tmp_path)
    bad = tuple(
        PbpArtifact(a.filename, a.byte_size + 1, a.sha256) if a.filename.endswith("2018.parquet") else a
        for a in manifest
    )
    with pytest.raises(PbpArtifactError, match="byte size"):
        verify_pbp_artifacts(root, expected=bad)


def test_hash_mismatch_fails(tmp_path):
    root, manifest = _build_fixture_dir(tmp_path)
    bad = tuple(
        PbpArtifact(a.filename, a.byte_size, "0" * 64) if a.filename.endswith("2018.parquet") else a
        for a in manifest
    )
    with pytest.raises(PbpArtifactError, match="SHA-256"):
        verify_pbp_artifacts(root, expected=bad)


def test_missing_expected_file_fails(tmp_path):
    root, manifest = _build_fixture_dir(tmp_path)
    (root / "play_by_play_2018.parquet").unlink()
    with pytest.raises(PbpArtifactError, match="missing PBP season file"):
        verify_pbp_artifacts(root, expected=manifest)


def test_extra_file_fails_under_exact_family(tmp_path):
    root, manifest = _build_fixture_dir(tmp_path)
    (root / "unexpected_extra.parquet").write_bytes(b"surprise")
    with pytest.raises(PbpArtifactError, match="unexpected PBP file"):
        verify_pbp_artifacts(root, expected=manifest)


def test_missing_root_fails(tmp_path):
    with pytest.raises(PbpArtifactError, match="does not exist"):
        verify_pbp_artifacts(tmp_path / "nope")


def test_load_pbp_frames_loads_all_seasons(tmp_path):
    root, manifest = _build_fixture_dir(tmp_path)
    frames = load_pbp_frames(root, expected=manifest)
    assert sorted(frames) == [2018, 2019, 2020, 2021, 2022, 2023, 2024]


def test_seasons_present_ascending(tmp_path):
    from nfl_edge.features.totals_v1.manifest import seasons_present

    root, manifest = _build_fixture_dir(tmp_path)
    frames = load_pbp_frames(root, expected=manifest)
    assert seasons_present(frames) == (2018, 2019, 2020, 2021, 2022, 2023, 2024)


def test_canonical_manifest_has_exact_seven():
    assert len(CANONICAL_PBP_MANIFEST) == 7
    assert [a.season for a in CANONICAL_PBP_MANIFEST] == [2018, 2019, 2020, 2021, 2022, 2023, 2024]
    # Filenames unique, byte sizes positive, hashes are 64 hex chars.
    names = {a.filename for a in CANONICAL_PBP_MANIFEST}
    assert len(names) == 7
    assert all(a.byte_size > 0 for a in CANONICAL_PBP_MANIFEST)
    assert all(len(a.sha256) == 64 for a in CANONICAL_PBP_MANIFEST)


@pytest.mark.parametrize("root", [str(p) for p in ARTIFACT_ROOTS])
def test_real_artifact_smoke_if_present(root):
    """Optional integration smoke test on the durable promoted path."""
    if not Path(root).is_dir():
        pytest.skip(f"durable artifact root not present: {root}")
    verified = verify_pbp_artifacts(root)  # uses canonical manifest
    assert len(verified) == 7
    assert [a.season for a in verified] == [2018, 2019, 2020, 2021, 2022, 2023, 2024]
