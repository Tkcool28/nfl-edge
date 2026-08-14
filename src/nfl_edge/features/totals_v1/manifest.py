"""Promoted PBP artifact manifest, integrity verification, and deterministic loading.

The seven canonical ``play_by_play_{2018..2024}.parquet`` artifacts are
read-only and promoted upstream. Phase 3 must never re-download or regenerate
them; every read verifies filenames, byte counts, and SHA-256 against this
manifest before the frame may enter any feature pipeline.

This module intentionally stores only the promotion manifest magnitudes that
are supplied by the accepted contract pipeline. It does not invent checksums.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import polars as pl


@dataclass(frozen=True)
class PbpArtifact:
    """Immutable specification of one promoted PBP artifact."""

    filename: str
    byte_size: int
    sha256: str

    @property
    def season(self) -> int:
        # filenames are exactly play_by_play_<YYYY>.parquet
        return int(self.filename.removeprefix("play_by_play_").removesuffix(".parquet"))


# The exact, individually promoted seven-file family supplied upstream.
CANONICAL_PBP_MANIFEST: tuple[PbpArtifact, ...] = (
    PbpArtifact("play_by_play_2018.parquet", 19072097, "2e6f2dce7c7ebd46e985cabe0c17eb72b39a77f98cb4478409294f50b5820150"),  # noqa: E501
    PbpArtifact("play_by_play_2019.parquet", 19119729, "60c3067017db2d28a78f66a79b657268be8578d9a5288e6a827efdcd7fe42540"),  # noqa: E501
    PbpArtifact("play_by_play_2020.parquet", 19311336, "73b7dbf66fa8cb9356f58bf6b1f15a0fee197ecc10cf4983b640cb9679b15cb4"),  # noqa: E501
    PbpArtifact("play_by_play_2021.parquet", 20249925, "333ad34378e5339d5172717cc83378e908daf02c8699416ab3e17c2ec10f78d8"),  # noqa: E501
    PbpArtifact("play_by_play_2022.parquet", 20426548, "931121d8897779d7944e2a293e92ed8799c8e5cceef84096ac42339003fedc09"),  # noqa: E501
    PbpArtifact("play_by_play_2023.parquet", 20534088, "bd3484731408def6b0ec93225bba2bd7b2c65769ca707a2b9444d891abdc6776"),  # noqa: E501
    PbpArtifact("play_by_play_2024.parquet", 20576368, "6d432dd4308329bfddaef633309ea119f9ca46d52cbb3c09f47172a2e8efcd01"),  # noqa: E501
)

# Standard locations. Both are read-only. Order encodes preference only:
# prefer the first if present, otherwise use the second.
ARTIFACT_ROOTS: tuple[Path, ...] = (
    Path("/artifacts/raw/task05c_pbp_v1"),
    Path("/var/lib/chatgpt-vps-mcp/artifacts/nfl-edge/raw/task05c_pbp_v1"),
)


class PbpArtifactError(ValueError):
    """Raised when a promoted PBP artifact fails integrity verification."""


def verify_pbp_artifacts(
    root: Path | str,
    *,
    expected: tuple[PbpArtifact, ...] = CANONICAL_PBP_MANIFEST,
    exact_family_membership: bool = True,
) -> tuple[PbpArtifact, ...]:
    """Verify the promoted PBP family at ``root``.

    Checks, in order:

    - exactly the expected filenames are present (no missing, and -- when
      ``exact_family_membership`` -- no unexpected extra files);
    - each file's byte count matches the manifest;
    - each file's SHA-256 matches the manifest.

    Returns the (unchanged) verified manifest on success. Raises
    :class:`PbpArtifactError` on any mismatch with an actionable message.
    """
    root = Path(root)
    if not root.is_dir():
        raise PbpArtifactError(f"PBP artifact root does not exist: {root}")

    expected_by_name = {a.filename: a for a in expected}
    expected_names = set(expected_by_name)

    present = {p.name for p in root.iterdir() if p.is_file()}
    missing = sorted(expected_names - present)
    if missing:
        raise PbpArtifactError(f"missing PBP season file(s): {missing}")
    if exact_family_membership:
        unexpected = sorted(present - expected_names)
        if unexpected:
            raise PbpArtifactError(
                f"unexpected PBP file(s) present in exact family: {unexpected}"
            )

    for artifact in expected:
        path = root / artifact.filename
        byte_size = path.stat().st_size
        if byte_size != artifact.byte_size:
            raise PbpArtifactError(
                f"{artifact.filename}: byte size {byte_size} != expected {artifact.byte_size}"
            )
        sha256 = _sha256_of(path)
        if sha256 != artifact.sha256:
            raise PbpArtifactError(
                f"{artifact.filename}: SHA-256 {sha256} != expected {artifact.sha256}"
            )
    return expected


def _sha256_of(path: Path, chunk_size: int = 1024 * 1024) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_artifact_root(*, roots: Iterable[Path] = ARTIFACT_ROOTS) -> Path:
    """Return the first artifact root that exists, else raise.

    Prefers the first configured root whenever it is present.
    """
    for root in roots:
        if Path(root).is_dir():
            return Path(root)
    raise PbpArtifactError(
        "no PBP artifact root found among: " + ", ".join(str(p) for p in roots)
    )


def load_pbp_frames(
    root: Path | str | None = None,
    *,
    expected: tuple[PbpArtifact, ...] = CANONICAL_PBP_MANIFEST,
    exact_family_membership: bool = True,
) -> dict[int, pl.DataFrame]:
    """Deterministically load and verify the seven PBP frames.

    Returns a dict keyed by NFL season (2018..2024) in ascending season order.
    Every file is integrity-verified before any frame is read into memory.
    """
    if root is None:
        root = resolve_artifact_root()
    root = Path(root)
    verify_pbp_artifacts(
        root, expected=expected, exact_family_membership=exact_family_membership
    )
    frames: dict[int, pl.DataFrame] = {}
    for artifact in sorted(expected, key=lambda a: a.season):
        frame = pl.read_parquet(root / artifact.filename)
        frames[artifact.season] = frame
    return frames


def seasons_present(frames: dict[int, pl.DataFrame]) -> tuple[int, ...]:
    """Return NFL seasons present in the loaded PBP family, ascending."""
    return tuple(sorted(frames))