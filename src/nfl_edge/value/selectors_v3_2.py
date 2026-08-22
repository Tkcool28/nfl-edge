"""Task05F primary-card selectors V3.2.

V3.2 separates two axes that the accepted ML V4 architecture intentionally
keeps distinct:

- model-native football confidence -> High Hit Rate / hit side of Balanced
- evaluator fair-price/value outputs -> price side of Balanced / Value

No historical confidence or ROI threshold is introduced here.
Contract: config/task05f_selectors_v3_2_native_confidence_prereg.yaml
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from nfl_edge.value.candidate_table import OUTCOME_FIELDS
from nfl_edge.value.selectors import SEALED_SEASONS
from nfl_edge.value.selectors_v3_1 import rank_value_v3_1

PRIMARY_CARDS = ("HIGH_HIT_RATE", "BALANCED", "VALUE")
_BALANCED_MARKETS = frozenset({"moneyline", "spread"})
_ALLOWED_RELIABILITY = frozenset({"HIGH", "MEDIUM"})
_RELIABILITY_PRIORITY = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "UNSUPPORTED": 3}
_STATUS_PRIORITY = {"VALUE": 0, "PLAYABLE": 1, "LEAN": 2, "PASS": 3}


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
                f"selector v3.2 candidate contains forbidden outcome fields: {sorted(leaked)}"
            )
        season = row.get("season")
        if season is not None and int(season) in SEALED_SEASONS:
            raise RuntimeError(f"sealed season {season} cannot enter selector v3.2")
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


def _annotate(row: Mapping[str, Any], card: str) -> dict[str, Any]:
    out = dict(row)
    out["selector_version"] = "task05f_selectors_v3_2_native_confidence"
    out["selector_card"] = card
    out["football_confidence_axis_separate_from_evaluator_probability"] = True
    return out


def _reliability_priority(row: Mapping[str, Any]) -> int:
    return _RELIABILITY_PRIORITY.get(str(row.get("reliability")), 4)


def _status_priority(row: Mapping[str, Any]) -> int:
    return _STATUS_PRIORITY.get(str(row.get("price_status")), 4)


def _ml_native_probability(row: Mapping[str, Any]) -> float | None:
    if _market(row) != "moneyline" or not _finite(row.get("raw_football_output")):
        return None
    return float(row["raw_football_output"])


def _spread_native_strength(row: Mapping[str, Any]) -> float | None:
    if _market(row) != "spread":
        return None
    if not _finite(row.get("raw_football_output")) or not _finite(row.get("actionable_line")):
        return None
    raw_margin = float(row["raw_football_output"])
    line = float(row["actionable_line"])
    side = str(row.get("selection", row.get("selected_side", ""))).lower()
    if side == "home":
        return raw_margin + line
    if side == "away":
        return -raw_margin + line
    return None


def model_native_strength(row: Mapping[str, Any]) -> float | None:
    """Return the market-native directional strength used by V3.2 Balanced."""
    market = _market(row)
    if market == "moneyline":
        return _ml_native_probability(row)
    if market == "spread":
        return _spread_native_strength(row)
    return None


def rank_high_hit_rate_v3_2(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Rank HHR strictly by native ML winner probability.

    Evaluator support, reliability, price status, and fair probability are retained
    as context/tiebreaks only. They do not decide whether the football model's
    highest-confidence winner may appear on the HHR card.
    """
    rows = _validated_rows(candidate_rows)
    eligible: list[dict[str, Any]] = []
    for row in rows:
        p = _ml_native_probability(row)
        if p is None or p <= 0.5:
            continue
        eligible.append(row)

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            -float(row["raw_football_output"]),
            _reliability_priority(row),
            _uncertainty_key(row.get("uncertainty")),
            _status_priority(row),
            _identity(row),
        )

    ranked: list[dict[str, Any]] = []
    for row in sorted(eligible, key=key):
        out = _annotate(row, "HIGH_HIT_RATE")
        out["model_native_hit_probability"] = float(row["raw_football_output"])
        out["hhr_price_actionable"] = str(row.get("price_status")) in {"VALUE", "PLAYABLE"}
        ranked.append(out)
    return ranked


def _competition_rank_desc(
    rows: list[dict[str, Any]],
    values: Mapping[str, float],
) -> dict[str, int]:
    all_values = list(values.values())
    return {
        str(row["candidate_id"]): 1 + sum(other > values[str(row["candidate_id"])] for other in all_values)
        for row in rows
    }


def rank_balanced_v3_2(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Balance market-native football strength against evaluator price quality."""
    rows = _validated_rows(candidate_rows)
    eligible: list[dict[str, Any]] = []
    native_values: dict[str, float] = {}

    for row in rows:
        market = _market(row)
        if market not in _BALANCED_MARKETS:
            continue
        if not bool(row.get("supported")):
            continue
        if str(row.get("reliability")) not in _ALLOWED_RELIABILITY:
            continue
        if str(row.get("price_status")) not in {"VALUE", "PLAYABLE"}:
            continue
        if not _finite(row.get("expected_value")):
            continue
        strength = model_native_strength(row)
        if strength is None:
            continue
        # Direction floors are semantic: the football model must actually favor
        # the selected side. No historical magnitude cutoff is applied.
        if market == "moneyline" and strength <= 0.5:
            continue
        if market == "spread" and strength <= 0.0:
            continue
        cid = str(row["candidate_id"])
        eligible.append(row)
        native_values[cid] = strength

    if not eligible:
        return []

    # ML probability and spread margin points are different units. Rank the
    # native signal inside its own market before combining it with common EV rank.
    native_rank: dict[str, int] = {}
    for market in sorted(_BALANCED_MARKETS):
        market_rows = [row for row in eligible if _market(row) == market]
        if not market_rows:
            continue
        market_values = {str(row["candidate_id"]): native_values[str(row["candidate_id"])] for row in market_rows}
        native_rank.update(_competition_rank_desc(market_rows, market_values))

    ev_values = {str(row["candidate_id"]): float(row["expected_value"]) for row in eligible}
    price_rank = _competition_rank_desc(eligible, ev_values)

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        cid = str(row["candidate_id"])
        hr = native_rank[cid]
        pr = price_rank[cid]
        return (
            max(hr, pr),
            hr + pr,
            _reliability_priority(row),
            _status_priority(row),
            _uncertainty_key(row.get("uncertainty")),
            -float(row["expected_value"]),
            _identity(row),
        )

    ranked: list[dict[str, Any]] = []
    for row in sorted(eligible, key=key):
        out = _annotate(row, "BALANCED")
        cid = str(row["candidate_id"])
        out["model_native_strength"] = native_values[cid]
        out["balanced_native_hit_rank_within_market"] = native_rank[cid]
        out["balanced_price_quality_rank"] = price_rank[cid]
        out["balanced_worst_rank"] = max(native_rank[cid], price_rank[cid])
        out["balanced_rank_sum"] = native_rank[cid] + price_rank[cid]
        ranked.append(out)
    return ranked


def rank_value_v3_2(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    ranked = rank_value_v3_1(_validated_rows(candidate_rows))
    out_rows: list[dict[str, Any]] = []
    for row in ranked:
        out = dict(row)
        out["selector_version"] = "task05f_selectors_v3_2_native_confidence"
        out["selector_card"] = "VALUE"
        out["football_confidence_axis_separate_from_evaluator_probability"] = True
        out_rows.append(out)
    return out_rows


def _first_unused(ranked: list[dict[str, Any]], used: set[str]) -> dict[str, Any] | None:
    for row in ranked:
        cid = str(row["candidate_id"])
        if cid not in used:
            return dict(row)
    return None


def select_primary_cards_v3_2(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any] | None]:
    rows = _validated_rows(candidate_rows)
    rankings = {
        "VALUE": rank_value_v3_2(rows),
        "HIGH_HIT_RATE": rank_high_hit_rate_v3_2(rows),
        "BALANCED": rank_balanced_v3_2(rows),
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
