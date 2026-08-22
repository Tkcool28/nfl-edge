"""Task05F thin primary-card selector V3.4.

All wager construction, football-confidence normalization, valuation, Play
Through classification, reliability, and unit assignment must already exist on
the evaluated-wager board. This module only chooses the three featured cards.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from nfl_edge.value.candidate_table import OUTCOME_FIELDS, SEALED_SEASONS

PRIMARY_CARDS = ("HIGH_HIT_RATE", "BALANCED", "VALUE")
_REQUIRED_BOARD_FIELDS = frozenset(
    {
        "candidate_id",
        "football_confidence_z",
        "football_cash_confidence_proxy",
        "evaluator_recommended_units",
        "evaluator_actionable",
        "price_status",
        "expected_value",
        "strict_positive_value",
        "reliability",
    }
)
_RELIABILITY_PRIORITY = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "UNSUPPORTED": 3}


def _finite(value: Any) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _validate_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = [dict(row) for row in rows]
    for row in output:
        leaked = OUTCOME_FIELDS.intersection(row)
        if leaked:
            raise RuntimeError(f"selector v3.4 contains forbidden outcome fields: {sorted(leaked)}")
        season = row.get("season")
        if season is not None and int(season) in SEALED_SEASONS:
            raise RuntimeError(f"sealed season {season} cannot enter selector v3.4")
        missing = _REQUIRED_BOARD_FIELDS.difference(row)
        if missing:
            raise RuntimeError(f"selector v3.4 requires evaluated-wager board fields: {sorted(missing)}")
    return output


def _identity(row: Mapping[str, Any]) -> tuple[str, str]:
    return (str(row.get("candidate_id", "")), str(row.get("offer_id", "")))


def _uncertainty_key(row: Mapping[str, Any]) -> tuple[int, float]:
    value = row.get("uncertainty")
    return (0, float(value)) if _finite(value) else (1, math.inf)


def _reliability_key(row: Mapping[str, Any]) -> int:
    return _RELIABILITY_PRIORITY.get(str(row.get("reliability", "")), 4)


def _actionable(row: Mapping[str, Any]) -> bool:
    return (
        row.get("evaluator_actionable") is True
        and str(row.get("price_status", "")) in {"VALUE", "PLAYABLE"}
        and _finite(row.get("evaluator_recommended_units"))
        and float(row["evaluator_recommended_units"]) > 0.0
    )


def _annotate(row: Mapping[str, Any], card: str) -> dict[str, Any]:
    out = dict(row)
    out["selector_version"] = "task05f_selectors_v3_4_thin"
    out["selector_card"] = card
    return out


def rank_high_hit_rate_v3_4(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    board = _validate_rows(rows)
    eligible = [
        row
        for row in board
        if _actionable(row)
        and _finite(row.get("football_confidence_z"))
        and _finite(row.get("football_cash_confidence_proxy"))
        and float(row["football_cash_confidence_proxy"]) > 0.5
    ]

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            -float(row["football_confidence_z"]),
            -float(row["evaluator_recommended_units"]),
            -float(row["expected_value"]) if _finite(row.get("expected_value")) else math.inf,
            _identity(row),
        )

    return [_annotate(row, "HIGH_HIT_RATE") for row in sorted(eligible, key=key)]


def _competition_rank_desc(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    values = [float(row[field]) for row in rows]
    return {
        str(row["candidate_id"]): 1 + sum(other > float(row[field]) for other in values)
        for row in rows
    }


def rank_balanced_v3_4(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    board = _validate_rows(rows)
    eligible = [
        row
        for row in board
        if _actionable(row)
        and _finite(row.get("football_confidence_z"))
        and _finite(row.get("expected_value"))
    ]
    if not eligible:
        return []

    hit_rank = _competition_rank_desc(eligible, "football_confidence_z")
    price_rank = _competition_rank_desc(eligible, "expected_value")

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        cid = str(row["candidate_id"])
        hr = hit_rank[cid]
        pr = price_rank[cid]
        return (
            max(hr, pr),
            hr + pr,
            -float(row["evaluator_recommended_units"]),
            _reliability_key(row),
            _uncertainty_key(row),
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


def rank_value_v3_4(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    board = _validate_rows(rows)
    eligible = [
        row
        for row in board
        if _actionable(row)
        and str(row.get("price_status", "")) == "VALUE"
        and row.get("strict_positive_value") is True
        and _finite(row.get("expected_value"))
        and float(row["expected_value"]) > 0.0
    ]

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        z = row.get("football_confidence_z")
        return (
            -float(row["expected_value"]),
            -float(row["evaluator_recommended_units"]),
            _reliability_key(row),
            _uncertainty_key(row),
            -float(z) if _finite(z) else math.inf,
            _identity(row),
        )

    return [_annotate(row, "VALUE") for row in sorted(eligible, key=key)]


def _first_unused(ranked: list[dict[str, Any]], used: set[str]) -> dict[str, Any] | None:
    for row in ranked:
        cid = str(row["candidate_id"])
        if cid not in used:
            return dict(row)
    return None


def select_primary_cards_v3_4(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any] | None]:
    board = _validate_rows(rows)
    rankings = {
        "VALUE": rank_value_v3_4(board),
        "HIGH_HIT_RATE": rank_high_hit_rate_v3_4(board),
        "BALANCED": rank_balanced_v3_4(board),
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
