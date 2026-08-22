"""Task05F account-independent evaluated wager board.

This is the final evaluator-side interface consumed by selectors. It enriches
accepted candidate-table rows with a common model-native football-confidence
score and evaluator-assigned units. Selectors should not recreate this math.
"""
from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any, Iterable, Mapping

from nfl_edge.value.candidate_table import OUTCOME_FIELDS, SEALED_SEASONS
from nfl_edge.value.staking_v2_1 import evaluator_units_v2_1

EXPECTED_MARGIN_RMSE = 13.814494036869487
TOTALS_R4_RMSE = 13.5453379336442
_NORMAL = NormalDist()

ADDED_FIELDS = frozenset(
    {
        "football_confidence_z",
        "football_cash_confidence_proxy",
        "football_model_favors_selection",
        "evaluator_recommended_units",
        "evaluator_unit_reason",
        "evaluator_actionable",
    }
)


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
        raise RuntimeError(f"evaluated wager row contains forbidden outcome fields: {sorted(leaked)}")
    season = row.get("season")
    if season is not None and int(season) in SEALED_SEASONS:
        raise RuntimeError(f"sealed season {season} cannot enter evaluated wager board")
    collisions = ADDED_FIELDS.intersection(row)
    if collisions:
        raise RuntimeError(f"candidate already contains evaluator-board fields: {sorted(collisions)}")


def football_confidence_z(row: Mapping[str, Any]) -> float | None:
    """Common model-native confidence in selected-side cashing, before price.

    Moneyline uses the frozen selected-side probability. Point markets use the
    frozen model edge versus the exact actionable line in units of that model's
    pre-Task05F residual RMSE. No sportsbook price, evaluator EV, or selector
    outcome enters this score.
    """
    raw = row.get("raw_football_output")
    if not _finite(raw):
        return None
    raw_f = float(raw)
    market = _market(row)
    side = _side(row)

    if market == "moneyline":
        if not 0.0 < raw_f < 1.0:
            return None
        p = min(max(raw_f, 1e-9), 1.0 - 1e-9)
        return float(_NORMAL.inv_cdf(p))

    line = row.get("actionable_line")
    if not _finite(line):
        return None
    line_f = float(line)

    if market == "spread":
        if side == "home":
            edge_points = raw_f + line_f
        elif side == "away":
            edge_points = -raw_f + line_f
        else:
            return None
        return float(edge_points / EXPECTED_MARGIN_RMSE)

    if market == "total":
        if side == "over":
            edge_points = raw_f - line_f
        elif side == "under":
            edge_points = line_f - raw_f
        else:
            return None
        return float(edge_points / TOTALS_R4_RMSE)

    return None


def football_cash_confidence_proxy(row: Mapping[str, Any]) -> float | None:
    z = football_confidence_z(row)
    return None if z is None else float(_NORMAL.cdf(z))


def evaluate_wager_row(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Attach evaluator-owned confidence/actionability fields without mutation."""
    _validate(candidate)
    out = dict(candidate)
    z = football_confidence_z(candidate)
    proxy = None if z is None else float(_NORMAL.cdf(z))
    units, reason = evaluator_units_v2_1(candidate)
    status = str(candidate.get("price_status", ""))

    out["football_confidence_z"] = z
    out["football_cash_confidence_proxy"] = proxy
    out["football_model_favors_selection"] = None if z is None else bool(z > 0.0)
    out["evaluator_recommended_units"] = float(units)
    out["evaluator_unit_reason"] = reason
    out["evaluator_actionable"] = bool(units > 0.0 and status in {"VALUE", "PLAYABLE"})
    return out


def build_evaluated_wager_board(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = [evaluate_wager_row(row) for row in candidate_rows]
    ids = [str(row.get("candidate_id", "")) for row in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate candidate identity in evaluated wager board")
    rows.sort(key=lambda row: str(row.get("candidate_id", "")))
    return rows


def assert_candidate_fields_preserved(
    candidate_rows: Iterable[Mapping[str, Any]],
    board_rows: Iterable[Mapping[str, Any]],
) -> None:
    source = {str(row["candidate_id"]): dict(row) for row in candidate_rows}
    board = {str(row["candidate_id"]): dict(row) for row in board_rows}
    if source.keys() != board.keys():
        raise RuntimeError("evaluated wager board identity set differs from candidate table")
    for cid, original in source.items():
        enriched = board[cid]
        for key, value in original.items():
            if enriched.get(key) != value:
                raise RuntimeError(f"evaluated wager board modified {key} for {cid}")
