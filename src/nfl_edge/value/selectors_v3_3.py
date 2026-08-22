"""Task05F market-agnostic primary-card selectors V3.3.

Market type is metadata, not primary-card eligibility. Frozen model-native
outputs are normalized to one dimensionless football-confidence axis without
sportsbook price, ROI, or historical selector tuning.
"""
from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any, Iterable, Mapping

from nfl_edge.value.candidate_table import OUTCOME_FIELDS
from nfl_edge.value.selectors import SEALED_SEASONS

PRIMARY_CARDS = ("HIGH_HIT_RATE", "BALANCED", "VALUE")
EXPECTED_MARGIN_RMSE = 13.8145
TOTALS_R4_RMSE = 13.5453379336442
_NORMAL = NormalDist()
_RELIABILITY_PRIORITY = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "UNSUPPORTED": 3}


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
                f"selector v3.3 candidate contains forbidden outcome fields: {sorted(leaked)}"
            )
        season = row.get("season")
        if season is not None and int(season) in SEALED_SEASONS:
            raise RuntimeError(f"sealed season {season} cannot enter selector v3.3")
    return rows


def _market(row: Mapping[str, Any]) -> str:
    return str(row.get("market_type", "")).strip().lower()


def _side(row: Mapping[str, Any]) -> str:
    return str(row.get("selection", row.get("selected_side", ""))).strip().lower()


def _numeric_identity(value: Any) -> tuple[int, float]:
    return (0, float(value)) if _finite(value) else (1, math.inf)


def _identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(row.get("game_id", "")),
        _market(row),
        _side(row),
        str(row.get("actionable_book", row.get("sportsbook", ""))),
        _numeric_identity(row.get("actionable_line", row.get("line"))),
        _numeric_identity(row.get("actionable_price_american", row.get("american_odds"))),
        str(row.get("candidate_id", "")),
    )


def _uncertainty_key(value: Any) -> tuple[int, float]:
    return (0, float(value)) if _finite(value) else (1, math.inf)


def _reliability_priority(row: Mapping[str, Any]) -> int:
    return _RELIABILITY_PRIORITY.get(str(row.get("reliability")), 4)


def _has_actionable_offer(row: Mapping[str, Any]) -> bool:
    return bool(str(row.get("actionable_book", "")).strip()) and _finite(
        row.get("actionable_price_american")
    )


def football_confidence_z(row: Mapping[str, Any]) -> float | None:
    """Normalize a frozen model-native selected-side signal to standard-error units.

    ML uses its selected-side probability directly via probit transform. Spread
    and total use model edge versus the exact actionable line divided by the
    frozen model's pre-Task05F error scale. This is a selector confidence score,
    not the evaluator fair probability.
    """
    market = _market(row)
    side = _side(row)
    raw = row.get("raw_football_output")
    if not _finite(raw):
        return None
    raw_f = float(raw)

    if market == "moneyline":
        if not 0.0 < raw_f < 1.0:
            return None
        p = min(max(raw_f, 1e-9), 1.0 - 1e-9)
        return float(_NORMAL.inv_cdf(p))

    if not _finite(row.get("actionable_line")):
        return None
    line = float(row["actionable_line"])

    if market == "spread":
        if side == "home":
            edge_points = raw_f + line
        elif side == "away":
            edge_points = -raw_f + line
        else:
            return None
        return edge_points / EXPECTED_MARGIN_RMSE

    if market == "total":
        if side == "over":
            edge_points = raw_f - line
        elif side == "under":
            edge_points = line - raw_f
        else:
            return None
        return edge_points / TOTALS_R4_RMSE

    return None


def model_native_cash_confidence_proxy(row: Mapping[str, Any]) -> float | None:
    z = football_confidence_z(row)
    return None if z is None else float(_NORMAL.cdf(z))


def _annotate(row: Mapping[str, Any], card: str) -> dict[str, Any]:
    out = dict(row)
    z = football_confidence_z(row)
    out["selector_version"] = "task05f_selectors_v3_3_market_agnostic"
    out["selector_card"] = card
    out["football_confidence_z"] = z
    out["model_native_cash_confidence_proxy"] = (
        None if z is None else float(_NORMAL.cdf(z))
    )
    out["model_native_cash_confidence_is_evaluator_probability"] = False
    return out


def rank_high_hit_rate_v3_3(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = _validated_rows(candidate_rows)
    eligible: list[dict[str, Any]] = []
    for row in rows:
        z = football_confidence_z(row)
        if z is None or not _has_actionable_offer(row):
            continue
        eligible.append(row)

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (-float(football_confidence_z(row)), _identity(row))

    return [_annotate(row, "HIGH_HIT_RATE") for row in sorted(eligible, key=key)]


def _competition_rank_desc(
    rows: list[dict[str, Any]], values: Mapping[str, float]
) -> dict[str, int]:
    all_values = list(values.values())
    return {
        str(row["candidate_id"]): 1
        + sum(other > values[str(row["candidate_id"])] for other in all_values)
        for row in rows
    }


def rank_balanced_v3_3(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = _validated_rows(candidate_rows)
    eligible: list[dict[str, Any]] = []
    confidence: dict[str, float] = {}
    ev: dict[str, float] = {}

    for row in rows:
        z = football_confidence_z(row)
        if z is None or z <= 0.0:
            continue
        if not bool(row.get("supported")):
            continue
        if str(row.get("reliability")) not in {"HIGH", "MEDIUM", "LOW"}:
            continue
        if str(row.get("price_status")) not in {"VALUE", "PLAYABLE"}:
            continue
        if not _finite(row.get("expected_value")) or not _has_actionable_offer(row):
            continue
        cid = str(row["candidate_id"])
        eligible.append(row)
        confidence[cid] = float(z)
        ev[cid] = float(row["expected_value"])

    if not eligible:
        return []

    hit_rank = _competition_rank_desc(eligible, confidence)
    price_rank = _competition_rank_desc(eligible, ev)

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        cid = str(row["candidate_id"])
        hr = hit_rank[cid]
        pr = price_rank[cid]
        return (
            max(hr, pr),
            hr + pr,
            _reliability_priority(row),
            _uncertainty_key(row.get("uncertainty")),
            -confidence[cid],
            -ev[cid],
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


def _strict_value(row: Mapping[str, Any]) -> bool:
    return (
        bool(row.get("supported"))
        and row.get("strict_positive_value") is True
        and str(row.get("price_status")) == "VALUE"
        and _finite(row.get("expected_value"))
        and float(row["expected_value"]) > 0.0
        and str(row.get("reliability")) in {"HIGH", "MEDIUM", "LOW"}
        and _has_actionable_offer(row)
    )


def rank_value_v3_3(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = _validated_rows(candidate_rows)
    eligible = [row for row in rows if _strict_value(row)]

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        z = football_confidence_z(row)
        return (
            -float(row["expected_value"]),
            _reliability_priority(row),
            _uncertainty_key(row.get("uncertainty")),
            -float(row["evaluated_edge_probability"])
            if _finite(row.get("evaluated_edge_probability"))
            else math.inf,
            -float(z) if z is not None else math.inf,
            _identity(row),
        )

    return [_annotate(row, "VALUE") for row in sorted(eligible, key=key)]


def _first_unused(ranked: list[dict[str, Any]], used: set[str]) -> dict[str, Any] | None:
    for row in ranked:
        cid = str(row["candidate_id"])
        if cid not in used:
            return dict(row)
    return None


def select_primary_cards_v3_3(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any] | None]:
    rows = _validated_rows(candidate_rows)
    rankings = {
        "VALUE": rank_value_v3_3(rows),
        "HIGH_HIT_RATE": rank_high_hit_rate_v3_3(rows),
        "BALANCED": rank_balanced_v3_3(rows),
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
