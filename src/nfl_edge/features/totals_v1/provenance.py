"""Deterministic Phase-3A provenance for the Totals V1 pipeline.

Records, per build, the promoted PBP identity (filename, SHA-256, byte size,
row count), the target block, the eligible source blocks, and violation
counters. For a valid development build every violation counter must be zero:

- same-game source rows used;
- same-block source rows used;
- future-block source rows used;
- NFL-season-2025 source rows used;
- canonical mapping failures.

Serialization is deterministic (sorted keys) so the provenance is
reproducible for later JSON reporting.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class PbpFileProvenance:
    """Identity of one promoted PBP artifact consumed by a build."""

    filename: str
    sha256: str
    byte_size: int
    row_count: int


@dataclass(frozen=True)
class BuildProvenance:
    """Deterministic provenance snapshot for one Totals target block build."""

    target_block_id: str | None = None
    eligible_source_block_ids: tuple[str, ...] = ()
    pb_files: tuple[PbpFileProvenance, ...] = ()

    # Violation counters. For a valid development build all are zero.
    same_game_source_rows: int = 0
    same_block_source_rows: int = 0
    future_block_source_rows: int = 0
    season_2025_source_rows: int = 0
    canonical_mapping_failures: int = 0
    dropback_fallback_rows: int = 0

    def __post_init__(self) -> None:
        # Normalize for deterministic serialization regardless of construction order.
        object.__setattr__(self, "eligible_source_block_ids", tuple(sorted(self.eligible_source_block_ids)))
        object.__setattr__(self, "pb_files", tuple(sorted(self.pb_files, key=lambda f: f.filename)))

    def to_dict(self) -> dict:
        """Return an ordered, deterministic dict representation."""
        return {
            "target_block_id": self.target_block_id,
            "eligible_source_block_ids": list(self.eligible_source_block_ids),
            "pbp_files": [
                {
                    "filename": f.filename,
                    "sha256": f.sha256,
                    "byte_size": f.byte_size,
                    "row_count": f.row_count,
                }
                for f in self.pb_files
            ],
            "violations": {
                "same_game_source_rows": self.same_game_source_rows,
                "same_block_source_rows": self.same_block_source_rows,
                "future_block_source_rows": self.future_block_source_rows,
                "season_2025_source_rows": self.season_2025_source_rows,
                "canonical_mapping_failures": self.canonical_mapping_failures,
            },
            "dropback_fallback_rows": self.dropback_fallback_rows,
        }

    def to_json(self) -> str:
        """Return a deterministic JSON string (sorted keys, compact separators)."""
        payload = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return payload.decode("utf-8")

    def fingerprint(self) -> str:
        """Return a SHA-256 of the deterministic JSON representation."""
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @property
    def valid_development_build(self) -> bool:
        """True iff all violation counters are zero (a valid dev build)."""
        return (
            self.same_game_source_rows == 0
            and self.same_block_source_rows == 0
            and self.future_block_source_rows == 0
            and self.season_2025_source_rows == 0
            and self.canonical_mapping_failures == 0
        )

    def assert_clean_development(self) -> None:
        """Raise if any violation counter is non-zero in a development build."""
        if not self.valid_development_build:
            viol = {k: v for k, v in self.to_dict()["violations"].items() if v}
            raise ValueError(
                "Totals development provenance contains violations: "
                f"{viol} (target={self.target_block_id!r})"
            )


@dataclass(frozen=True)
class ProvenanceCounters:
    """Mutable-accumulating violation counters (frozen after construction).

    Builders accumulate into these counts; a final :class:`BuildProvenance`
    carries a frozen snapshot of them.
    """

    same_game_source_rows: int = 0
    same_block_source_rows: int = 0
    future_block_source_rows: int = 0
    season_2025_source_rows: int = 0
    canonical_mapping_failures: int = 0
    dropback_fallback_rows: int = 0

    def add_same_game(self, count: int = 1) -> "ProvenanceCounters":
        return _bump(self, "same_game_source_rows", count)

    def add_same_block(self, count: int = 1) -> "ProvenanceCounters":
        return _bump(self, "same_block_source_rows", count)

    def add_future(self, count: int = 1) -> "ProvenanceCounters":
        return _bump(self, "future_block_source_rows", count)

    def add_season_2025(self, count: int = 1) -> "ProvenanceCounters":
        return _bump(self, "season_2025_source_rows", count)

    def add_mapping_failures(self, count: int = 1) -> "ProvenanceCounters":
        return _bump(self, "canonical_mapping_failures", count)

    def add_dropback_fallback_rows(self, count: int = 1) -> "ProvenanceCounters":
        return _bump(self, "dropback_fallback_rows", count)

    def to_build_provenance(
        self,
        *,
        target_block_id: str | None = None,
        eligible_source_block_ids: Sequence[str] = (),
        pb_files: Sequence[PbpFileProvenance] = (),
    ) -> BuildProvenance:
        """Freeze these counters into an immutable :class:`BuildProvenance`."""
        return BuildProvenance(
            target_block_id=target_block_id,
            eligible_source_block_ids=tuple(sorted(eligible_source_block_ids)),
            pb_files=tuple(pb_files),
            same_game_source_rows=self.same_game_source_rows,
            same_block_source_rows=self.same_block_source_rows,
            future_block_source_rows=self.future_block_source_rows,
            season_2025_source_rows=self.season_2025_source_rows,
            canonical_mapping_failures=self.canonical_mapping_failures,
            dropback_fallback_rows=self.dropback_fallback_rows,
        )


def _bump(counters: ProvenanceCounters, attr: str, count: int) -> ProvenanceCounters:
    return ProvenanceCounters(
        **{**asdict(counters), attr: getattr(counters, attr) + int(count)}
    )


def pb_files_from_frames(
    *,
    filenames: Mapping[int, str],
    shas: Mapping[int, str],
    byte_sizes: Mapping[int, int],
    row_counts: Mapping[int, int],
) -> tuple[PbpFileProvenance, ...]:
    """Build a sorted (by filename) tuple of PBP file provenance entries.

    All mappings are keyed by NFL season (2018..2024); iteration order is the
    deterministic ascending filename order.
    """
    entries = [
        PbpFileProvenance(
            filename=filenames[season],
            sha256=shas[season],
            byte_size=byte_sizes[season],
            row_count=row_counts[season],
        )
        for season in filenames
    ]
    return tuple(sorted(entries, key=lambda e: e.filename))


def zero_counters() -> ProvenanceCounters:
    """Return a fresh all-zero counter set."""
    return ProvenanceCounters()