"""Task05F primary-card selectors V3.

V3 is a capability-policy wrapper around the frozen Selector V1 rankings.
Its market eligibility is derived from evaluator capability status locked before
Selector V1/V2 historical evidence:

- HHR needs an accepted probability capability.
- Balanced and Value need an accepted demonstrated Value capability.
- Raw football direction/disagreement does not gate primary cards.

Contract: config/task05f_selectors_v3_capability_prereg.yaml
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from nfl_edge.value.candidate_table import OUTCOME_FIELDS
from nfl_edge.value.selectors import (
    SEALED_SEASONS,
    select_balanced,
    select_high_hit_rate,
    select_value,
)


PROBABILITY_CAPABLE_MARKETS = frozenset({"moneyline", "spread", "total"})
VALUE_CAPABLE_MARKETS = frozenset({"spread"})


def _validated_rows(candidate_rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in candidate_rows]
    for row in rows:
        leaked = OUTCOME_FIELDS.intersection(row)
        if leaked:
            raise RuntimeError(
                f"selector v3 candidate contains forbidden outcome fields: {sorted(leaked)}"
            )
        season = row.get("season")
        if season is not None and int(season) in SEALED_SEASONS:
            raise RuntimeError(f"sealed season {season} cannot enter selector v3")
    return rows


def _market(row: Mapping[str, Any]) -> str:
    return str(row.get("market_type", "")).strip().lower()


def _annotate(
    pick: dict[str, Any] | None,
    *,
    capability: str,
) -> dict[str, Any] | None:
    if pick is None:
        return None
    out = dict(pick)
    out["selector_version"] = "task05f_selectors_v3_capability"
    out["selector_capability_basis"] = capability
    out["raw_football_direction_gate_applied"] = False
    return out


def select_high_hit_rate_v3(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any] | None:
    rows = _validated_rows(candidate_rows)
    eligible_market_rows = [row for row in rows if _market(row) in PROBABILITY_CAPABLE_MARKETS]
    return _annotate(
        select_high_hit_rate(eligible_market_rows),
        capability="accepted_probability_capability",
    )


def select_balanced_v3(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any] | None:
    rows = _validated_rows(candidate_rows)
    eligible_market_rows = [row for row in rows if _market(row) in VALUE_CAPABLE_MARKETS]
    return _annotate(
        select_balanced(eligible_market_rows),
        capability="accepted_demonstrated_value_capability",
    )


def select_value_v3(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any] | None:
    rows = _validated_rows(candidate_rows)
    eligible_market_rows = [row for row in rows if _market(row) in VALUE_CAPABLE_MARKETS]
    return _annotate(
        select_value(eligible_market_rows),
        capability="accepted_demonstrated_value_capability",
    )


def select_primary_cards_v3(
    candidate_rows: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any] | None]:
    """Return V3 primary-card winners; duplicate wager across cards is allowed."""
    rows = _validated_rows(candidate_rows)
    return {
        "HIGH_HIT_RATE": select_high_hit_rate_v3(rows),
        "BALANCED": select_balanced_v3(rows),
        "VALUE": select_value_v3(rows),
    }
