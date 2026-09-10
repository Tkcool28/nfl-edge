"""Pending result contracts and units-based prospective performance economics."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping

from nfl_edge.prospective.common_v1 import (
    BUILDER_VERSION,
    LANE_ORDER,
    OFFICIAL_SCHEMA_VERSION,
    RESULT_SCHEMA_VERSION,
    SUMMARY_SCHEMA_VERSION,
    ProspectiveCardError,
    stable_id,
)


def build_pending_results(official: Mapping[str, Any]) -> dict[str, Any]:
    """Create result references without pretending automatic settlement exists."""
    if official.get("schema_version") != OFFICIAL_SCHEMA_VERSION:
        raise ProspectiveCardError("official record has unexpected schema")

    lane_results: list[dict[str, Any]] = []
    for resolution in official.get("official_wagers") or []:
        wager = resolution["official_wager"]
        lane_results.append(
            {
                "result_id": stable_id(
                    "result",
                    resolution["lane_key"],
                    wager["exact_offer_identity_id"],
                ),
                "lane_key": resolution["lane_key"],
                "game_id": resolution["game_id"],
                "official_source_publication_id": resolution["source_publication_id"],
                "official_source_product_sha256": resolution["source_product_sha256"],
                "grade": "PENDING",
                "official_score": None,
                "result_source": None,
                "result_source_provenance": None,
                "settled_at_utc": None,
                "price_used_for_scoring": wager["american_odds"],
                "units_risked": wager["recommended_units"],
                "realized_units": None,
                "correction": None,
            }
        )

    portfolio_results = [
        {
            "portfolio_entry_id": entry["portfolio_entry_id"],
            "lane_keys": deepcopy(entry["lane_keys"]),
            "game_id": entry["game_id"],
            "grade": "PENDING",
            "price_used_for_scoring": entry["american_odds"],
            "units_risked": entry["recommended_units"],
            "realized_units": None,
        }
        for entry in official.get("portfolio_entries") or []
    ]
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "season": int(official["season"]),
        "week": int(official["week"]),
        "settlement_status": "PENDING",
        "lane_results": lane_results,
        "portfolio_results": portfolio_results,
    }


def realized_profit_units(
    *,
    grade: str,
    american_odds: int,
    units_risked: float,
) -> float | None:
    """Return profit/loss in units using the exact stored official American price."""
    result = str(grade).upper()
    units = float(units_risked)
    price = int(american_odds)
    if units < 0:
        raise ProspectiveCardError("units_risked cannot be negative")
    if price == 0:
        raise ProspectiveCardError("American odds cannot be zero")
    if result == "PENDING":
        return None
    if result == "LOSS":
        return -units
    if result in {"PUSH", "VOID"}:
        return 0.0
    if result != "WIN":
        raise ProspectiveCardError(f"unsupported grade {grade!r}")
    return units * (price / 100.0 if price > 0 else 100.0 / abs(price))


def performance_summary(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize settled economics; pending rows do not pollute denominators."""
    settled = [
        row
        for row in rows
        if str(row.get("grade")).upper() in {"WIN", "LOSS", "PUSH", "VOID"}
    ]
    wins = sum(str(row["grade"]).upper() == "WIN" for row in settled)
    losses = sum(str(row["grade"]).upper() == "LOSS" for row in settled)
    pushes = sum(str(row["grade"]).upper() == "PUSH" for row in settled)
    voids = sum(str(row["grade"]).upper() == "VOID" for row in settled)
    units_risked = sum(float(row.get("units_risked") or 0.0) for row in settled)
    net_units = sum(float(row.get("realized_units") or 0.0) for row in settled)
    decisions = wins + losses
    return {
        "settled_wagers": len(settled),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "voids": voids,
        "hit_rate": None if decisions == 0 else wins / decisions,
        "units_risked": units_risked,
        "net_units": net_units,
        "roi": None if units_risked == 0 else net_units / units_risked,
    }


def build_summary(
    *,
    official: Mapping[str, Any],
    results: Mapping[str, Any],
    episodes: Mapping[str, Any],
) -> dict[str, Any]:
    """Build descriptive lane and overlap-adjusted portfolio summaries."""
    lane_results = list(results.get("lane_results") or [])
    lane_summaries = {
        lane_key: performance_summary(
            row for row in lane_results if row.get("lane_key") == lane_key
        )
        for lane_key in LANE_ORDER
    }
    episode_rows = list(episodes.get("episodes") or [])
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "season": int(official["season"]),
        "week": int(official["week"]),
        "lanes": lane_summaries,
        "portfolio": performance_summary(results.get("portfolio_results") or []),
        "overlap_count": int(official.get("overlap_count") or 0),
        "episode_count": len(episode_rows),
        "card_churn": {
            lane_key: max(
                0,
                sum(row.get("lane_key") == lane_key for row in episode_rows) - 1,
            )
            for lane_key in LANE_ORDER
        },
        "interpretation": "DESCRIPTIVE_PROSPECTIVE_EVIDENCE_ONLY_NO_RETUNING",
    }
