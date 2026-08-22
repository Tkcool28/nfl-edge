"""Task05F primary selectors V2: V1 rankings + frozen-football direction gate.

Contract: config/task05f_selectors_v2_prereg.yaml

V2 does not rank by football-disagreement magnitude. It only requires the frozen
football inference to support the exact selected wager direction (> 0 margin),
then delegates ranking unchanged to the frozen V1 selector policy.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping

from nfl_edge.value.candidate_table import OUTCOME_FIELDS
from nfl_edge.value.selectors import PRIMARY_CARDS, select_primary_cards


SEALED_SEASONS = {2025}


@dataclass(frozen=True)
class FootballSignalSupport:
    supported: bool
    margin: float | None
    unit: str | None
    reason: str


def _finite(value: Any) -> bool:
    if value is None:
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def football_signal_support(row: Mapping[str, Any]) -> FootballSignalSupport:
    """Return direction-only frozen-football support for the exact wager."""
    market = str(row.get("market_type", "")).lower()
    side = str(row.get("selection", row.get("selected_side", ""))).lower()

    if market == "moneyline":
        value = row.get("model_market_disagreement")
        if not _finite(value):
            return FootballSignalSupport(False, None, "probability", "missing_ml_disagreement")
        margin = float(value)
        return FootballSignalSupport(
            margin > 0.0,
            margin,
            "probability",
            "selected_side_raw_exact_avg_minus_calibrated_fair_probability",
        )

    if market == "spread":
        raw = row.get("raw_football_output")
        line = row.get("actionable_line", row.get("line"))
        if not _finite(raw) or not _finite(line):
            return FootballSignalSupport(False, None, "points", "missing_spread_signal_or_line")
        raw_f = float(raw)
        line_f = float(line)
        if side == "home":
            margin = raw_f + line_f
        elif side == "away":
            margin = -raw_f + line_f
        else:
            return FootballSignalSupport(False, None, "points", "invalid_spread_side")
        return FootballSignalSupport(
            margin > 0.0,
            margin,
            "points",
            "selected_side_expected_margin_cushion_at_exact_line",
        )

    if market == "total":
        raw = row.get("raw_football_output")
        line = row.get("actionable_line", row.get("line"))
        if not _finite(raw) or not _finite(line):
            return FootballSignalSupport(False, None, "points", "missing_total_signal_or_line")
        raw_f = float(raw)
        line_f = float(line)
        if side == "over":
            margin = raw_f - line_f
        elif side == "under":
            margin = line_f - raw_f
        else:
            return FootballSignalSupport(False, None, "points", "invalid_total_side")
        return FootballSignalSupport(
            margin > 0.0,
            margin,
            "points",
            "selected_side_r4_total_cushion_at_exact_line",
        )

    return FootballSignalSupport(False, None, None, "unknown_market")


def _validated_rows(candidate_rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in candidate_rows]
    for row in rows:
        leaked = OUTCOME_FIELDS.intersection(row)
        if leaked:
            raise RuntimeError(
                f"selector V2 candidate contains forbidden outcome fields: {sorted(leaked)}"
            )
        season = row.get("season")
        if season is not None and int(season) in SEALED_SEASONS:
            raise RuntimeError(f"sealed season {season} cannot enter selector V2")
    return rows


def select_primary_cards_v2(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any] | None]:
    """Apply direction gate, then frozen V1 primary-card ranking unchanged."""
    rows = _validated_rows(candidate_rows)
    support_by_id: dict[str, FootballSignalSupport] = {}
    gated: list[dict[str, Any]] = []
    for row in rows:
        assessment = football_signal_support(row)
        cid = str(row.get("candidate_id", ""))
        support_by_id[cid] = assessment
        if assessment.supported:
            gated.append(row)

    picks = select_primary_cards(gated)
    output: dict[str, dict[str, Any] | None] = {}
    for card in PRIMARY_CARDS:
        pick = picks[card]
        if pick is None:
            output[card] = None
            continue
        assessment = support_by_id[str(pick["candidate_id"])]
        enriched = dict(pick)
        enriched["football_signal_supports_wager"] = assessment.supported
        enriched["football_signal_support_margin"] = assessment.margin
        enriched["football_signal_support_unit"] = assessment.unit
        enriched["football_signal_support_reason"] = assessment.reason
        output[card] = enriched
    return output
