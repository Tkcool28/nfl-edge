#!/usr/bin/env python3
"""Chronological 2020-2024 validation for preregistered Task05G remediation V1.

The remediation is deliberately model-first:
  frozen Task05E candidate side -> frozen Task05F exact offer -> selector.

This runner never changes a football model/evaluator, never loads 2025 into the
selection universe, and never uses Task05E outcome/profit columns for candidate
eligibility. Outcome columns are consulted only after the candidate registry is
already frozen in memory, for read-only baseline reporting.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

import polars as pl

from nfl_edge.recommendation.policy import (
    NO_BALANCED_PLAY,
    NO_HIT_RATE_PLAY,
    NO_VALUE_PLAY,
    RISK_PROFILES,
    cap_slate_stakes,
    dollar_stake,
    recommended_units,
    select_headlines as select_original_headlines,
    shop_exact_offers,
)
from nfl_edge.recommendation.remediation_provenance_v1 import (
    DEV,
    REGION_SPECS,
    build_candidate_registry,
    enrich_board_rows,
)
from nfl_edge.recommendation.remediation_v1 import (
    robust_expected_value,
    select_headlines as select_remediation_headlines,
)

ROOT = Path(__file__).resolve().parents[1]
SEALED = {2025}
NO_PLAY = {NO_HIT_RATE_PLAY, NO_BALANCED_PLAY, NO_VALUE_PLAY}


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _values(rows: Iterable[dict[str, Any]], key: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        value = row.get(key)
        if value is not None:
            out.append(float(value))
    return out


def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
    values = _values(rows, key)
    return None if not values else float(mean(values))


def _roi(rows: list[dict[str, Any]]) -> float | None:
    return _avg(rows, "realized_profit")


def _hit_rate(rows: list[dict[str, Any]]) -> float | None:
    decisions = [row for row in rows if row.get("settlement") in {"WIN", "LOSS"}]
    if not decisions:
        return None
    return sum(row["settlement"] == "WIN" for row in decisions) / len(decisions)


def _market_mix(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {market: sum(str(row.get("market_type")) == market for row in rows) for market in ("moneyline", "spread", "total")}


def _region_mix(rows: list[dict[str, Any]]) -> dict[str, int]:
    names = [spec[0] for spec in REGION_SPECS]
    counts = {name: 0 for name in names}
    for row in rows:
        tags = {x for x in str(row.get("model_candidate_regions", "")).split(";") if x}
        for name in tags:
            if name in counts:
                counts[name] += 1
    return counts


def _summary(rows: list[dict[str, Any]], total_blocks: int | None = None) -> dict[str, Any]:
    output = {
        "plays": len(rows),
        "market_mix": _market_mix(rows),
        "candidate_region_membership_counts": _region_mix(rows),
        "average_american_odds": _avg(rows, "american_odds"),
        "average_actionable_probability": _avg(rows, "actionable_probability"),
        "average_expected_value": _avg(rows, "expected_value"),
        "average_robust_expected_value": _avg(rows, "robust_expected_value"),
        "hit_rate_nonpush": _hit_rate(rows),
        "roi_per_unit_risked": _roi(rows),
        "push_rate": None if not rows else sum(row.get("settlement") == "PUSH" for row in rows) / len(rows),
        "reliability_mix": {
            tier: sum(str(row.get("reliability")) == tier for row in rows)
            for tier in ("HIGH", "MEDIUM", "LOW", "UNSUPPORTED")
        },
    }
    if total_blocks is not None:
        played = len({str(row["block"]) for row in rows})
        output["weeks_with_play"] = played
        output["weeks_no_play"] = total_blocks - played
    return output


def _season(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        str(season): _summary([row for row in rows if int(row["season"]) == season])
        for season in sorted(DEV)
    }


def _exact_offer_id(row: dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("game_id", "")),
            str(row.get("market_type", "")),
            str(row.get("selected_side", "")),
            str(row.get("sportsbook", "")),
            str(row.get("line")),
            str(row.get("american_odds")),
        ]
    )


def _pack(role: str, selected: dict[str, Any], block: str, policy_name: str) -> dict[str, Any]:
    row = dict(selected)
    row["role"] = role
    row["block"] = str(block)
    row["policy"] = policy_name
    row["no_play"] = False
    row["robust_expected_value"] = robust_expected_value(row)
    row["recommended_units"] = recommended_units(row)
    row["offer_id"] = _exact_offer_id(row)
    return row


def _run_policy(
    rows: list[dict[str, Any]],
    blocks: list[str],
    selector,
    policy_name: str,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    selected: dict[str, list[dict[str, Any]]] = {"hit_rate": [], "balanced": [], "value": []}
    output: list[dict[str, Any]] = []
    for block in blocks:
        block_rows = [row for row in rows if str(row["block"]) == block]
        heads = selector(block_rows)
        for role in ("hit_rate", "balanced", "value"):
            choice = heads[role]
            if isinstance(choice, str):
                output.append({"block": block, "policy": policy_name, "role": role, "no_play": True, "no_play_code": choice})
                continue
            packed = _pack(role, dict(choice), block, policy_name)
            selected[role].append(packed)
            output.append(packed)
    return selected, output


def _unique_wagers(selected: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    material = sorted(
        [row for rows in selected.values() for row in rows],
        key=lambda row: (str(row["block"]), str(row["offer_id"]), str(row["role"])),
    )
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for row in material:
        unique.setdefault((str(row["block"]), str(row["offer_id"])), row)
    return list(unique.values())


def _risk_simulation(wagers: list[dict[str, Any]], profile_name: str, starting_bankroll: float = 1000.0) -> dict[str, Any]:
    bankroll = float(starting_bankroll)
    peak = bankroll
    max_drawdown = 0.0
    total_risked = 0.0
    stakes: list[float] = []
    peak_exposure = 0.0
    losing_streak = 0
    worst_losing_streak = 0
    by_block: dict[str, list[dict[str, Any]]] = {}
    for row in wagers:
        by_block.setdefault(str(row["block"]), []).append(row)

    for block in sorted(by_block):
        block_rows = sorted(by_block[block], key=lambda row: str(row["offer_id"]))
        opening = bankroll
        proposed = [
            (str(row["offer_id"]), dollar_stake(opening, profile_name, float(row["recommended_units"])))
            for row in block_rows
        ]
        capped = cap_slate_stakes(opening, proposed)
        exposure = sum(capped.values())
        peak_exposure = max(peak_exposure, 0.0 if opening <= 0 else exposure / opening)
        block_profit = 0.0
        for row in block_rows:
            stake = float(capped[str(row["offer_id"])])
            stakes.append(stake)
            total_risked += stake
            block_profit += stake * float(row["realized_profit"])
            if row.get("settlement") == "LOSS":
                losing_streak += 1
                worst_losing_streak = max(worst_losing_streak, losing_streak)
            elif row.get("settlement") == "WIN":
                losing_streak = 0
        bankroll += block_profit
        peak = max(peak, bankroll)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - bankroll) / peak)

    return {
        "profile": profile_name,
        "starting_bankroll": starting_bankroll,
        "ending_bankroll": bankroll,
        "max_drawdown_pct": max_drawdown,
        "worst_losing_streak": worst_losing_streak,
        "peak_slate_exposure_pct": peak_exposure,
        "average_wager_size": None if not stakes else float(mean(stakes)),
        "total_risked": total_risked,
        "wagers": len(stakes),
    }


def _role_overlap(selected: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    by_role_block = {
        role: {str(row["block"]): str(row["offer_id"]) for row in rows}
        for role, rows in selected.items()
    }
    roles = ("hit_rate", "balanced", "value")
    pairs: dict[str, int] = {}
    for i, left in enumerate(roles):
        for right in roles[i + 1 :]:
            common = set(by_role_block[left]).intersection(by_role_block[right])
            pairs[f"{left}__{right}"] = sum(by_role_block[left][b] == by_role_block[right][b] for b in common)
    common_all = set.intersection(*(set(by_role_block[role]) for role in roles))
    return {
        "same_exact_offer_by_pair": pairs,
        "all_three_same_exact_offer": sum(
            len({by_role_block[role][block] for role in roles}) == 1 for block in common_all
        ),
    }


def _robust_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    vals = sorted(_values(rows, "robust_expected_value"))
    if not vals:
        return {"n": 0, "min": None, "p25": None, "median": None, "p75": None, "max": None, "mean": None}

    def pick(frac: float) -> float:
        return vals[round((len(vals) - 1) * frac)]

    return {
        "n": len(vals),
        "min": vals[0],
        "p25": pick(0.25),
        "median": pick(0.50),
        "p75": pick(0.75),
        "max": vals[-1],
        "mean": float(mean(vals)),
    }


def _candidate_survival(enriched: list[dict[str, Any]], blocks: list[str]) -> dict[str, Any]:
    model_rows = [row for row in enriched if bool(row.get("model_candidate"))]
    shopped: list[dict[str, Any]] = []
    for block in blocks:
        block_rows = [row for row in enriched if str(row["block"]) == block]
        shopped.extend(dict(row) for row in shop_exact_offers(block_rows) if bool(row.get("model_candidate")))
    return {
        "task05f_exact_rows_tagged_model_candidate": len(model_rows),
        "unique_model_candidate_sides_on_task05f_board": len({(str(r["game_id"]), str(r["market_type"]), str(r["selected_side"])) for r in model_rows}),
        "shopped_model_candidate_sides": len(shopped),
        "shopped_supported": sum(bool(r.get("supported")) for r in shopped),
        "shopped_high_or_medium_reliability": sum(str(r.get("reliability")) in {"HIGH", "MEDIUM"} for r in shopped),
        "shopped_value_or_playable": sum(str(r.get("price_status")) in {"VALUE", "PLAYABLE"} for r in shopped),
        "shopped_strict_value": sum(str(r.get("price_status")) == "VALUE" for r in shopped),
        "market_mix": _market_mix(shopped),
        "region_membership_counts": _region_mix(shopped),
    }


def _task05e_baseline(ledger: pl.DataFrame) -> dict[str, Any]:
    # Reporting only. Candidate eligibility was already frozen by
    # build_candidate_registry before this function is called.
    output: dict[str, Any] = {}
    for name, family, model, buckets in REGION_SPECS:
        rr = ledger.filter(
            (pl.col("family") == family)
            & (pl.col("model") == model)
            & pl.col("bucket").cast(pl.Utf8).is_in(sorted(buckets))
        ).to_dicts()
        output[name] = {
            "overall": {
                "plays": len(rr),
                "roi_per_unit_risked": None if not rr else float(mean(float(r["profit"]) for r in rr)),
            },
            "per_season": {
                str(season): {
                    "plays": len([r for r in rr if int(r["season"]) == season]),
                    "roi_per_unit_risked": None if not [r for r in rr if int(r["season"]) == season] else float(mean(float(r["profit"]) for r in rr if int(r["season"]) == season)),
                }
                for season in sorted(DEV)
            },
        }
    return output


def run(task05f_dir: Path, discovery_path: Path, confirmation_path: Path, out: Path) -> None:
    board = pl.read_parquet(task05f_dir / "historical_evaluator_board.parquet")
    seasons = {int(x) for x in board["season"].unique().to_list()}
    if seasons != set(DEV) or seasons.intersection(SEALED):
        raise RuntimeError(f"Task05G remediation 2025 firewall: unexpected Task05F seasons {sorted(seasons)}")

    discovery = pl.read_csv(discovery_path, infer_schema_length=10000)
    confirmation = pl.read_csv(confirmation_path, infer_schema_length=10000)
    ledger = pl.concat([discovery, confirmation], how="vertical_relaxed")
    ledger_seasons = {int(x) for x in ledger["season"].unique().to_list()}
    if ledger_seasons != set(DEV) or ledger_seasons.intersection(SEALED):
        raise RuntimeError(f"Task05G remediation 2025 firewall: unexpected Task05E seasons {sorted(ledger_seasons)}")

    # Freeze registry BEFORE any reporting reads Task05E outcome columns.
    registry = build_candidate_registry(ledger.to_dicts())
    if not registry:
        raise RuntimeError("frozen Task05E candidate registry is empty")
    if any(key[1] == "total" for key in registry):
        raise RuntimeError("totals entered preregistered headline candidate registry")

    enriched = enrich_board_rows(board.to_dicts(), registry)
    blocks = sorted({str(row["block"]) for row in enriched})

    remediation_selected, remediation_rows = _run_policy(
        enriched, blocks, select_remediation_headlines, "remediation_v1"
    )
    original_selected, original_rows = _run_policy(
        enriched, blocks, select_original_headlines, "original_task05g_v1"
    )

    out.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(remediation_rows, infer_schema_length=None).write_csv(out / "chronological_remediation_results.csv")
    pl.DataFrame(original_rows, infer_schema_length=None).write_csv(out / "chronological_original_policy_results.csv")

    diagnostics = {
        "development_seasons": sorted(DEV),
        "sealed_seasons": sorted(SEALED),
        "chronological_blocks": len(blocks),
        "registry_candidate_sides": len(registry),
        "remediation": {
            role: {
                "overall": _summary(rows, len(blocks)),
                "per_season": _season(rows),
                "robust_ev_distribution": _robust_distribution(rows),
            }
            for role, rows in remediation_selected.items()
        },
        "original_task05g_v1_same_board": {
            role: {"overall": _summary(rows, len(blocks)), "per_season": _season(rows)}
            for role, rows in original_selected.items()
        },
        "role_overlap": _role_overlap(remediation_selected),
        "candidate_survival": _candidate_survival(enriched, blocks),
    }
    _write_json(out / "remediation_diagnostics.json", diagnostics)
    _write_json(out / "task05e_candidate_baseline.json", _task05e_baseline(ledger))

    wagers = _unique_wagers(remediation_selected)
    _write_json(
        out / "unit_risk_profile_simulation.json",
        {
            "selector_identity_shared_across_profiles": True,
            "recommended_units_shared_across_profiles": True,
            "overlapping_headline_offer_counted_once": True,
            "profiles": [_risk_simulation(wagers, profile.name) for profile in RISK_PROFILES],
        },
    )

    value_longshot_violations = [
        row for row in remediation_selected["value"]
        if int(row["american_odds"]) > 250 or float(row["actionable_probability"]) < 0.35
    ]
    _write_json(
        out / "guardrail_report.json",
        {
            "selected_value_longshot_guardrail_violations": len(value_longshot_violations),
            "totals_headline_selections": sum(
                str(row.get("market_type")) == "total"
                for rows in remediation_selected.values()
                for row in rows
            ),
            "non_model_candidate_headline_selections": sum(
                not bool(row.get("model_candidate"))
                for rows in remediation_selected.values()
                for row in rows
            ),
        },
    )

    artifact_names = [
        "chronological_remediation_results.csv",
        "chronological_original_policy_results.csv",
        "remediation_diagnostics.json",
        "task05e_candidate_baseline.json",
        "unit_risk_profile_simulation.json",
        "guardrail_report.json",
    ]
    _write_json(out / "artifact_hashes.json", {name: _sha(out / name) for name in artifact_names})
    print(json.dumps(diagnostics, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task05f-dir", required=True)
    parser.add_argument(
        "--discovery-ledger",
        default=str(ROOT / "reports/task05e_remediated/market_edge_discovery_corrected_ledger_v1.csv"),
    )
    parser.add_argument(
        "--confirmation-ledger",
        default=str(ROOT / "reports/task05e_remediated/market_edge_confirmation_corrected_ledger_v1.csv"),
    )
    parser.add_argument("--out", default=str(ROOT / "artifacts/task05g/remediation_v1"))
    args = parser.parse_args()
    run(Path(args.task05f_dir), Path(args.discovery_ledger), Path(args.confirmation_ledger), Path(args.out))
