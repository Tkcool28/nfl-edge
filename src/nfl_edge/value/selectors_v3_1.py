"""Task05F primary-card selectors V3.1.

Product correction made before any Selector V3/V3.1 historical outcome scoring:
- High Hit Rate: probability-first VALUE/PLAYABLE across probability-capable markets.
- Balanced: independent probability/price-quality compromise, VALUE or PLAYABLE.
- Value: strict positive Value inside demonstrated Value capability.
- Featured primary cards use distinct candidate identities when possible.

Contract: config/task05f_selectors_v3_1_product_prereg.yaml
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from nfl_edge.value.candidate_table import OUTCOME_FIELDS
from nfl_edge.value.selectors import SEALED_SEASONS


PROBABILITY_CAPABLE_MARKETS = frozenset({"moneyline", "spread", "total"})
VALUE_CAPABLE_MARKETS = frozenset({"spread"})
PRIMARY_CARDS = ("HIGH_HIT_RATE", "BALANCED", "VALUE")
_ALLOWED_RELIABILITY = frozenset({"HIGH", "MEDIUM"})
_RELIABILITY_PRIORITY = {"HIGH": 0, "MEDIUM": 1}
_STATUS_PRIORITY = {"VALUE": 0, "PLAYABLE": 1}


def _finite(value: Any) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _validated_rows(candidate_rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in candidate_rows]
    for row in rows:
        leaked = OUTCOME_FIELDS.intersection(row)
        if leaked:
            raise RuntimeError(
                f"selector v3.1 candidate contains forbidden outcome fields: {sorted(leaked)}"
            )
        season = row.get("season")
        if season is not None and int(season) in SEALED_SEASONS:
            raise RuntimeError(f"sealed season {season} cannot enter selector v3.1")
    return rows


def _market(row: Mapping[str, Any]) -> str:
    return str(row.get("market_type", "")).strip().lower()


def _uncertainty_key(value: Any) -> tuple[int, float]:
    return (0, float(value)) if _finite(value) else (1, math.inf)


def _numeric_identity(value: Any) -> tuple[int, float]:
    return (0, float(value)) if _finite(value) else (1, math.inf)


def _identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(row.get("game_id", "")),
        str(row.get("market_type", "")),
        str(row.get("selection", row.get("selected_side", ""))),
        str(row.get("actionable_book", row.get("sportsbook", ""))),
        _numeric_identity(row.get("actionable_line", row.get("line"))),
        _numeric_identity(row.get("actionable_price_american", row.get("american_odds"))),
        str(row.get("candidate_id", "")),
    )


def _base_eligible(row: Mapping[str, Any]) -> bool:
    return bool(row.get("supported")) and str(row.get("reliability")) in _ALLOWED_RELIABILITY


def _strict_value(row: Mapping[str, Any]) -> bool:
    return (
        row.get("strict_positive_value") is True
        and str(row.get("price_status")) == "VALUE"
        and _finite(row.get("expected_value"))
        and float(row["expected_value"]) > 0.0
    )


def _annotate(row: Mapping[str, Any], card: str) -> dict[str, Any]:
    out = dict(row)
    out["selector_version"] = "task05f_selectors_v3_1_product"
    out["selector_card"] = card
    out["raw_football_direction_gate_applied"] = False
    return out


def rank_high_hit_rate_v3_1(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = _validated_rows(candidate_rows)
    eligible = [
        row
        for row in rows
        if _market(row) in PROBABILITY_CAPABLE_MARKETS
        and _base_eligible(row)
        and str(row.get("price_status")) in {"VALUE", "PLAYABLE"}
        and _finite(row.get("actionable_probability"))
        and _finite(row.get("expected_value"))
    ]

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            -float(row["actionable_probability"]),
            _RELIABILITY_PRIORITY[str(row["reliability"])],
            _STATUS_PRIORITY[str(row["price_status"])],
            -float(row["expected_value"]),
            _uncertainty_key(row.get("uncertainty")),
            _identity(row),
        )

    return [_annotate(row, "HIGH_HIT_RATE") for row in sorted(eligible, key=key)]


def _competition_rank_desc(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    values = [float(row[field]) for row in rows]
    return {
        str(row["candidate_id"]): 1 + sum(other > float(row[field]) for other in values)
        for row in rows
    }


def rank_balanced_v3_1(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = _validated_rows(candidate_rows)
    eligible = [
        row
        for row in rows
        if _market(row) in PROBABILITY_CAPABLE_MARKETS
        and _base_eligible(row)
        and str(row.get("price_status")) in {"VALUE", "PLAYABLE"}
        and _finite(row.get("actionable_probability"))
        and _finite(row.get("expected_value"))
    ]
    if not eligible:
        return []

    hit_rank = _competition_rank_desc(eligible, "actionable_probability")
    price_rank = _competition_rank_desc(eligible, "expected_value")

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        cid = str(row["candidate_id"])
        hr = hit_rank[cid]
        pr = price_rank[cid]
        return (
            max(hr, pr),
            hr + pr,
            _RELIABILITY_PRIORITY[str(row["reliability"])],
            _uncertainty_key(row.get("uncertainty")),
            -float(row["actionable_probability"]),
            -float(row["expected_value"]),
            _identity(row),
        )

    ranked: list[dict[str, Any]] = []
    for row in sorted(eligible, key=key):
        out = _annotate(row, "BALANCED")
        cid = str(row["candidate_id"])
        out["balanced_hit_rank"] = hit_rank[cid]
        out["balanced_price_quality_rank"] = price_rank[cid]
        out["balanced_worst_rank"] = max(hit_rank[cid], price_rank[cid])
        out["balanced_rank_sum"] = hit_rank[cid] + price_rank[cid]
        ranked.append(out)
    return ranked


def rank_value_v3_1(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = _validated_rows(candidate_rows)
    eligible = [
        row
        for row in rows
        if _market(row) in VALUE_CAPABLE_MARKETS
        and _base_eligible(row)
        and _strict_value(row)
        and _finite(row.get("actionable_probability"))
        and _finite(row.get("evaluated_edge_probability"))
    ]

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            -float(row["expected_value"]),
            _RELIABILITY_PRIORITY[str(row["reliability"])],
            -float(row["evaluated_edge_probability"]),
            _uncertainty_key(row.get("uncertainty")),
            -float(row["actionable_probability"]),
            _identity(row),
        )

    return [_annotate(row, "VALUE") for row in sorted(eligible, key=key)]


def _first_unused(ranked: list[dict[str, Any]], used: set[str]) -> dict[str, Any] | None:
    for row in ranked:
        cid = str(row["candidate_id"])
        if cid not in used:
            return dict(row)
    return None


def select_primary_cards_v3_1(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any] | None]:
    """Allocate three distinct featured wagers when the eligible slate permits.

    Duplicate-resolution order is VALUE -> HIGH_HIT_RATE -> BALANCED. This order
    only resolves candidate identity collisions; each card's internal ranking is
    unchanged from its own product objective.
    """
    rows = _validated_rows(candidate_rows)
    rankings = {
        "VALUE": rank_value_v3_1(rows),
        "HIGH_HIT_RATE": rank_high_hit_rate_v3_1(rows),
        "BALANCED": rank_balanced_v3_1(rows),
    }
    used: set[str] = set()
    allocated: dict[str, dict[str, Any] | None] = {}
    for card in ("VALUE", "HIGH_HIT_RATE", "BALANCED"):
        pick = _first_unused(rankings[card], used)
        allocated[card] = pick
        if pick is not None:
            used.add(str(pick["candidate_id"]))
    return {
        "HIGH_HIT_RATE": allocated["HIGH_HIT_RATE"],
        "BALANCED": allocated["BALANCED"],
        "VALUE": allocated["VALUE"],
    }
