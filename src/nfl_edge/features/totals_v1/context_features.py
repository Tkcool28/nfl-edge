"""Rest/roof/surface context features for Totals V1.

Extracts the approved context fields and applies the contract-literal
null/missing and normalization rules.

Source authorities (contract-frozen):
- ``away_rest``, ``home_rest``: from the frozen schedule
- ``surface``: from the frozen schedule
- ``roof_type``: from the accepted normalized/canonical games source

The roof field is explicitly ``roof_type`` from the canonical games
table, NOT ``roof`` from the raw schedule.  This was a frozen Phase 2
decision.  Rest and surface remain from the frozen schedule.
"""

from __future__ import annotations


def extract_context_features(
    context_row: dict[str, object],
) -> dict[str, object]:
    """Extract rest/roof/surface features from context inputs.

    The input row must contain:
    - ``away_rest``, ``home_rest``: from the frozen schedule
    - ``surface``: from the frozen schedule
    - ``roof_type``: from the canonical/normalized games table

    Returns a dict with eight keys (in contract order):
    - ``away_rest_days``: source integer value or None
    - ``away_rest_days_missing``: 1 if source null, else 0
    - ``home_rest_days``: source integer value or None
    - ``home_rest_days_missing``: 1 if source null, else 0
    - ``roof_category``: lower-case string, or "unknown" if null
    - ``roof_missing``: 1 if source null, else 0
    - ``surface_category``: lower-case string, or "unknown" if null
    - ``surface_missing``: 1 if source null, else 0

    Contract rules:
    - Rest: use source integer as-is.  If null -> (None, 1).
    - Roof: use ``roof_type`` from canonical games.  Normalize to
      lowercase.  If null -> ("unknown", 1).
    - Surface: use ``surface`` from frozen schedule.  Normalize to
      lowercase.  If null -> ("unknown", 1).
    - No calculation of rest from dates; use the source field directly.
    - No weather fields used.
    """
    # Rest days (from frozen schedule)
    away_rest = context_row.get("away_rest")
    if away_rest is None:
        away_rest_val: int | None = None
        away_rest_missing = 1
    else:
        away_rest_val = int(away_rest)
        away_rest_missing = 0

    home_rest = context_row.get("home_rest")
    if home_rest is None:
        home_rest_val: int | None = None
        home_rest_missing = 1
    else:
        home_rest_val = int(home_rest)
        home_rest_missing = 0

    # Roof (from canonical games roof_type, NOT raw schedule roof)
    roof = context_row.get("roof_type")
    if roof is None:
        roof_category = "unknown"
        roof_missing = 1
    else:
        roof_category = str(roof).lower()
        roof_missing = 0

    # Surface (from frozen schedule)
    surface = context_row.get("surface")
    if surface is None:
        surface_category = "unknown"
        surface_missing = 1
    else:
        surface_category = str(surface).lower()
        surface_missing = 0

    return {
        "away_rest_days": away_rest_val,
        "away_rest_days_missing": away_rest_missing,
        "home_rest_days": home_rest_val,
        "home_rest_days_missing": home_rest_missing,
        "roof_category": roof_category,
        "roof_missing": roof_missing,
        "surface_category": surface_category,
        "surface_missing": surface_missing,
    }
