"""Task05F Evaluated Wager Board V2.

This is the evaluator-owned interface consumed by selectors. It enriches the
locked candidate table with a market-agnostic frozen-football confidence axis
and evaluator-owned units. Selectors must not recompute this math.
"""
from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any, Iterable, Mapping

from nfl_edge.value.candidate_table import OUTCOME_FIELDS
from nfl_edge.value.staking_v2_1 import evaluator_units_v2_1

EXPECTED_MARGIN_RMSE = 13.814494036869487
TOTALS_R4_RMSE = 13.5453379336442
_ALLOWED_RELIABILITY = frozenset({"HIGH", "MEDIUM", "LOW"})
_NORMAL = NormalDist()


def _finite(value: Any) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _market(row: Mapping[str, Any]) -> str:
    return str(row.get("market_type", "")).strip().lower()


def _side(row: Mapping[str, Any]) -> str:
    return str(row.get("selection", row.get("selected_side", ""))).strip().lower()


def _validate(row: Mapping[str, Any]) -> None:
    leaked = OUTCOME_FIELDS.intersection(row)
    if leaked:
        raise RuntimeError(f"evaluated wager contains forbidden outcome fields: {sorted(leaked)}")
    season = row.get("season")
    if season is not None and int(season) == 2025:
        raise RuntimeError("sealed season 2025 cannot enter evaluated wager board")


def football_confidence_components(row: Mapping[str, Any]) -> tuple[float | None, float | None]:
    """Return (z_score, selected_side_edge_points).

    ML probability is transformed with the standard-normal inverse CDF. Spread
    and total model edge versus the exact actionable line are standardized by
    frozen pre-Task05F model error scales. The resulting z is a comparative
    football-confidence score, not the evaluator fair probability.
    """
    _validate(row)
    raw = row.get("raw_football_output")
    if not _finite(raw):
        return None, None
    raw_f = float(raw)
    market = _market(row)
    side = _side(row)

    if market == "moneyline":
        if not 0.0 < raw_f < 1.0:
            return None, None
        p = min(max(raw_f, 1e-9), 1.0 - 1e-9)
        return float(_NORMAL.inv_cdf(p)), None

    line = row.get("actionable_line")
    if not _finite(line):
        return None, None
    line_f = float(line)

    if market == "spread":
        if side == "home":
            edge = raw_f + line_f
        elif side == "away":
            edge = -raw_f + line_f
        else:
            return None, None
        return edge / EXPECTED_MARGIN_RMSE, edge

    if market == "total":
        if side == "over":
            edge = raw_f - line_f
        elif side == "under":
            edge = line_f - raw_f
        else:
            return None, None
        return edge / TOTALS_R4_RMSE, edge

    return None, None


def enrich_evaluated_wager(row: Mapping[str, Any]) -> dict[str, Any]:
    """Attach evaluator-owned comparison/unit fields without changing upstream fields."""
    _validate(row)
    out = dict(row)
    z, edge_points = football_confidence_components(row)
    units, unit_reason = evaluator_units_v2_1(row)
    proxy = None if z is None else float(_NORMAL.cdf(z))

    reliability_ok = str(row.get("reliability", "")) in _ALLOWED_RELIABILITY
    status = str(row.get("price_status", ""))
    primary_actionable = (
        bool(row.get("supported"))
        and reliability_ok
        and status in {"VALUE", "PLAYABLE"}
        and units > 0.0
    )
    strict_value_actionable = (
        primary_actionable
        and status == "VALUE"
        and row.get("strict_positive_value") is True
        and _finite(row.get("expected_value"))
        and float(row["expected_value"]) > 0.0
    )

    out.update(
        {
            "evaluated_wager_board_version": "task05f_evaluated_wager_board_v2",
            "football_confidence_z": z,
            "football_cash_confidence_proxy": proxy,
            "football_selected_side_edge_points": edge_points,
            "football_cash_confidence_proxy_is_fair_probability": False,
            "evaluator_units": float(units),
            "evaluator_unit_reason": unit_reason,
            "primary_actionable": bool(primary_actionable),
            "strict_value_actionable": bool(strict_value_actionable),
        }
    )
    return out


def build_evaluated_wager_board(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Build a deterministic fully-evaluated board for a selector refresh."""
    output = [enrich_evaluated_wager(row) for row in rows]
    output.sort(key=lambda row: str(row.get("candidate_id", "")))
    return output
