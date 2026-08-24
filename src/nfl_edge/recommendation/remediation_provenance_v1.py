"""Frozen Task05E candidate provenance adapter for Task05G remediation V1.

Only candidate identity/tag columns are consulted. Historical wager outcomes,
profit, and historical exact price/line are deliberately irrelevant to whether a
current Task05F exact offer is a model-derived candidate.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

DEV = frozenset({2020, 2021, 2022, 2023, 2024})
SEALED = frozenset({2025})

# These definitions are copied from the already-locked Task05E candidate list;
# they are not selected from Task05G remediation outcomes.
REGION_SPECS: tuple[tuple[str, str, str, frozenset[str]], ...] = (
    ("ML_DOG_VALUE_ZONE_AVG", "ML_DOG_VALUE_ZONE", "AVG", frozenset({"ZONE"})),
    ("ML_DOG_VALUE_ZONE_CORROB", "ML_DOG_VALUE_ZONE", "CORROB", frozenset({"ZONE"})),
    ("ML_AVG_DISAGREEMENT_AVG_0_2", "ML_AVG_DISAGREEMENT", "AVG", frozenset({"0-2"})),
    (
        "SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4",
        "SPREAD_DISAGREEMENT",
        "EXPECTED_MARGIN",
        frozenset({"0-1", "1-2", "2-3", "3-4"}),
    ),
)


def _market_for_family(family: str) -> str | None:
    if family.startswith("ML_"):
        return "moneyline"
    if family == "SPREAD_DISAGREEMENT":
        return "spread"
    return None


def _normalized_bucket(value: Any) -> str:
    # Polars/CSV nulls may surface as None or an empty string; neither can match
    # a frozen candidate specification.
    return "" if value is None else str(value)


def build_candidate_registry(
    ledger_rows: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str, str], tuple[str, ...]]:
    """Build candidate identity -> frozen region tags without outcome leakage.

    The only row values used to admit a candidate are game_id, family, model,
    bucket, selected_side. ``season`` is read solely for the sealed-year firewall.
    Historical line/price and all outcome/economics columns are ignored.
    """
    tags: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for row in ledger_rows:
        season = row.get("season")
        if season is not None and int(season) in SEALED:
            raise RuntimeError("Task05G remediation 2025 firewall: sealed candidate row encountered")
        family = str(row.get("family", ""))
        model = str(row.get("model", ""))
        bucket = _normalized_bucket(row.get("bucket"))
        market = _market_for_family(family)
        if market is None:
            continue
        region_name = None
        for name, expected_family, expected_model, buckets in REGION_SPECS:
            if family == expected_family and model == expected_model and bucket in buckets:
                region_name = name
                break
        if region_name is None:
            continue
        gid = str(row.get("game_id", ""))
        side = str(row.get("selected_side", "")).lower()
        if not gid or side not in {"home", "away"}:
            continue
        tags[(gid, market, side)].add(region_name)
    return {key: tuple(sorted(values)) for key, values in sorted(tags.items())}


def enrich_board_rows(
    board_rows: Iterable[Mapping[str, Any]],
    registry: Mapping[tuple[str, str, str], tuple[str, ...]],
) -> list[dict[str, Any]]:
    """Attach frozen model-candidate provenance to Task05F exact-offer rows."""
    output: list[dict[str, Any]] = []
    for source in board_rows:
        row = dict(source)
        season = int(row.get("season"))
        if season in SEALED:
            raise RuntimeError("Task05G remediation 2025 firewall: sealed evaluator row encountered")
        key = (
            str(row.get("game_id", "")),
            str(row.get("market_type", "")).lower(),
            str(row.get("selected_side", "")).lower(),
        )
        regions = tuple(registry.get(key, ()))
        row["model_candidate"] = bool(regions)
        row["model_candidate_regions"] = ";".join(regions)
        output.append(row)
    return output
