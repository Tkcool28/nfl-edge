"""Deterministic NFLverse source retrieval and frozen-baseline normalization."""

from .audit import (
    DEFAULT_SEASONS,
    SOURCE_SPECS,
    build_frozen_baseline,
    retrieve_sources,
)
from .integrity import (
    canonical_schema_fingerprint,
    normalize_player_id,
    normalize_team,
    sha256_file,
    utc_timestamp,
    verify_manifest_file,
)

__all__ = [
    "DEFAULT_SEASONS",
    "SOURCE_SPECS",
    "build_frozen_baseline",
    "canonical_schema_fingerprint",
    "normalize_player_id",
    "normalize_team",
    "retrieve_sources",
    "sha256_file",
    "utc_timestamp",
    "verify_manifest_file",
]
