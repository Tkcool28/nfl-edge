"""Deterministic Task05F primary-card selectors.

Contracts:
- config/task05f_selectors_v1_prereg.yaml
- config/task05f_selectors_v1_implementation_lock.yaml

This module is a pure product-selection policy over the common candidate table.
It never consumes historical outcomes and never uses staking probability, ROI,
coverage, Kelly sizing, or sealed-2025 data in ranking.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from nfl_edge.value.candidate_table import OUTCOME_FIELDS


SEALED_SEASONS = {2025}
PRIMARY_CARDS = ("HIGH_HIT_RATE", "BALANCED", "VALUE")
_ALLOWED_RELIABILITY = {"HIGH", "MEDIUM"}
_RELIABILITY_PRIORITY = {"HIGH": 0, "MEDIUM": 1}
_STATUS_PRIORITY = {"VALUE": 0, "PLAYABLE": 1}


def _rows(candidate_rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in candidate_rows]
    for row in rows:
        leaked = OUTCOME_FIELDS.intersection(row)
        if leaked:
            raise RuntimeError(
                f"selector candidate contains forbidden outcome fields: {sorted(leaked)}"
            )
        season = row.get("season")
        if season is not None and int(season) in SEALED_SEASONS:
            raise RuntimeError(f"sealed season {season} cannot enter selector")
    return rows


def _finite(value: Any) -> bool:
    if value is None:
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _uncertainty_key(value: Any) -> tuple[int, float]:
    """Ascending uncertainty with null/non-finite values last."""
    if not _finite(value):
        return (1, math.inf)
    return (0, float(value))


def _numeric_identity(value: Any) -> tuple[int, float]:
    if not _finite(value):
        return (1, math.inf)
    return (0, float(value))


def _identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Parent prereg identity tiebreak using candidate-table aliases."""
    return (
        str(row.get("game_id", "")),
        str(row.get("market_type", "")),
        str(row.get("selection", row.get("selected_side", ""))),
        str(row.get("actionable_book", row.get("sportsbook", ""))),
        _numeric_identity(row.get("actionable_line", row.get("line"))),
        _numeric_identity(
            row.get("actionable_price_american", row.get("american_odds"))
        ),
    )


def _base_eligible(row: Mapping[str, Any]) -> bool:
    return bool(row.get("supported")) and str(row.get("reliability")) in _ALLOWED_RELIABILITY


def _has_required(row: Mapping[str, Any], fields: tuple[str, ...]) -> bool:
    return all(_finite(row.get(field)) for field in fields)


def _strict_value(row: Mapping[str, Any]) -> bool:
    return (
        row.get("strict_positive_value") is True
        and str(row.get("price_status")) == "VALUE"
        and _finite(row.get("expected_value"))
        and float(row["expected_value"]) > 0.0
    )


def _competition_rank_desc(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    """1 + count of eligible values strictly greater; equal values share rank."""
    values = [float(row[field]) for row in rows]
    result: dict[str, int] = {}
    for row in rows:
        value = float(row[field])
        result[str(row["candidate_id"])] = 1 + sum(other > value for other in values)
    return result


def select_high_hit_rate(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any] | None:
    rows = _rows(candidate_rows)
    eligible = [
        row
        for row in rows
        if _base_eligible(row)
        and str(row.get("price_status")) in {"VALUE", "PLAYABLE"}
        and _has_required(row, ("actionable_probability", "expected_value"))
    ]
    if not eligible:
        return None

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            -float(row["actionable_probability"]),
            _RELIABILITY_PRIORITY[str(row["reliability"])],
            _STATUS_PRIORITY[str(row["price_status"])],
            -float(row["expected_value"]),
            _uncertainty_key(row.get("uncertainty")),
            _identity(row),
        )

    return dict(min(eligible, key=key))


def select_balanced(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any] | None:
    rows = _rows(candidate_rows)
    eligible = [
        row
        for row in rows
        if _base_eligible(row)
        and _strict_value(row)
        and _has_required(row, ("actionable_probability", "expected_value"))
    ]
    if not eligible:
        return None

    hit_rank = _competition_rank_desc(eligible, "actionable_probability")
    value_rank = _competition_rank_desc(eligible, "expected_value")

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        cid = str(row["candidate_id"])
        hr = hit_rank[cid]
        vr = value_rank[cid]
        return (
            max(hr, vr),
            hr + vr,
            _RELIABILITY_PRIORITY[str(row["reliability"])],
            _uncertainty_key(row.get("uncertainty")),
            -float(row["actionable_probability"]),
            -float(row["expected_value"]),
            _identity(row),
        )

    pick = dict(min(eligible, key=key))
    cid = str(pick["candidate_id"])
    pick["balanced_hit_rank"] = hit_rank[cid]
    pick["balanced_value_rank"] = value_rank[cid]
    pick["balanced_worst_rank"] = max(hit_rank[cid], value_rank[cid])
    pick["balanced_rank_sum"] = hit_rank[cid] + value_rank[cid]
    return pick


def select_value(candidate_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    rows = _rows(candidate_rows)
    eligible = [
        row
        for row in rows
        if _base_eligible(row)
        and _strict_value(row)
        and _has_required(
            row,
            ("actionable_probability", "expected_value", "evaluated_edge_probability"),
        )
    ]
    if not eligible:
        return None

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            -float(row["expected_value"]),
            _RELIABILITY_PRIORITY[str(row["reliability"])],
            -float(row["evaluated_edge_probability"]),
            _uncertainty_key(row.get("uncertainty")),
            -float(row["actionable_probability"]),
            _identity(row),
        )

    return dict(min(eligible, key=key))


def select_primary_cards(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any] | None]:
    """Return the three global primary-card winners; duplicates are allowed."""
    rows = _rows(candidate_rows)
    return {
        "HIGH_HIT_RATE": select_high_hit_rate(rows),
        "BALANCED": select_balanced(rows),
        "VALUE": select_value(rows),
    }
