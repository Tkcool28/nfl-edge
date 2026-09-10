"""Runtime capture of already-published NFL EDGE products.

This module is observational only. It does not acquire markets, score football,
evaluate offers, select lanes, change staking, or publish the product itself.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from nfl_edge.prospective.capture_v1 import (
    build_publication_snapshot,
    write_publication_snapshot,
)

RUNTIME_CAPTURE_SCHEMA_VERSION = "NFL_EDGE_PROSPECTIVE_CARD_RUNTIME_CAPTURE_V1"


def runtime_publications_dir(
    runtime_root: str | Path,
    *,
    season: int,
    week: int,
) -> Path:
    return Path(runtime_root) / str(int(season)) / f"week-{int(week):02d}" / "publications"


def capture_published_product(
    product: Mapping[str, Any],
    *,
    runtime_root: str | Path,
    published_at_utc: str,
    source_commit_sha: str | None = None,
) -> dict[str, Any]:
    """Capture one product that has already become production-authoritative.

    Re-observing the same canonical source product is idempotent. The first
    immutable capture remains authoritative and later encounters return
    DEDUPLICATED rather than creating another historical observation.
    """
    publication = build_publication_snapshot(
        product,
        published_at_utc=published_at_utc,
        source_commit_sha=source_commit_sha,
        capture_mode="NATIVE_PROSPECTIVE",
    )
    target_dir = runtime_publications_dir(
        runtime_root,
        season=int(publication["season"]),
        week=int(publication["week"]),
    )
    path, created = write_publication_snapshot(publication, target_dir)
    return {
        "schema_version": RUNTIME_CAPTURE_SCHEMA_VERSION,
        "status": "CAPTURED" if created else "DEDUPLICATED",
        "publication_id": publication["publication_id"],
        "source_product_version": publication["source_product_version"],
        "source_product_sha256": publication["source_product_sha256"],
        "published_at_utc": publication["published_at_utc"],
        "season": publication["season"],
        "week": publication["week"],
        "runtime_path": str(path),
    }


__all__ = [
    "RUNTIME_CAPTURE_SCHEMA_VERSION",
    "capture_published_product",
    "runtime_publications_dir",
]
