"""Audited structural roof metadata for blank nflverse 2026 schedule values."""

from __future__ import annotations

from typing import Any, Mapping

VENUE_STRUCTURE_VERSION = "nfl-edge-2026-venue-structure-v1"

# These are the only stadium IDs with blank roof values in the full currently
# published 2026 REG schedule. Structures are venue facts, not current roof
# positions; the live roof resolver remains the sole owner of OPEN/CLOSED.
BLANK_ROOF_VENUES: Mapping[str, tuple[str, str]] = {
    "ATL97": ("Mercedes-Benz Stadium", "RETRACTABLE"),
    "DAL00": ("AT&T Stadium", "RETRACTABLE"),
    "DET00": ("Ford Field", "FIXED"),
    "HOU00": ("Reliant Stadium", "RETRACTABLE"),
    "IND00": ("Lucas Oil Stadium", "RETRACTABLE"),
    "MAD01": ("Bernabeu", "RETRACTABLE"),
    "PHO00": ("State Farm Stadium", "RETRACTABLE"),
    "RIO00": ("Maracana Stadium", "OUTDOOR"),
}


class VenueStructure2026Error(ValueError):
    """Raised when blank upstream roof data has no audited venue structure."""


def structure_for_blank_roof(row: Mapping[str, Any]) -> str:
    venue_id = str(row.get("stadium_id") or "").strip()
    stadium = str(row.get("stadium") or "").strip()
    record = BLANK_ROOF_VENUES.get(venue_id)
    if record is None:
        raise VenueStructure2026Error(f"blank nflverse roof has unknown stadium_id {venue_id!r}")
    expected_stadium, structure = record
    if stadium != expected_stadium:
        raise VenueStructure2026Error(
            f"blank nflverse roof stadium drift for {venue_id!r}: {stadium!r} != {expected_stadium!r}"
        )
    return structure
