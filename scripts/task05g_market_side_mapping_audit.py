#!/usr/bin/env python3
"""Read-only audit that selected ML offer prices belong to the labeled home/away team."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

from nfl_edge.market_data.matching import _NAME_TO_ABBR

DEV = {2020, 2021, 2022, 2023, 2024}


def _parse_game_id(game_id: str) -> tuple[str, str]:
    parts = str(game_id).split("_")
    if len(parts) != 4:
        raise ValueError(game_id)
    return parts[2], parts[3]  # away, home


def run(root: Path, selector_path: Path, out: Path) -> None:
    selected = [
        r for r in pl.read_csv(selector_path, infer_schema_length=10000).to_dicts()
        if not bool(r.get("no_play")) and str(r.get("market_type")) == "moneyline"
    ]
    games = (
        pl.read_parquet(root / "data/market_data/canonical/canonical_games.parquet")
        .filter(pl.col("game_id").is_in([str(r["game_id"]) for r in selected]))
        .select(["game_id", "home_abbr", "away_abbr"])
        .to_dicts()
    )
    game_idx = {str(r["game_id"]): r for r in games}
    mapping_mismatch_games = []
    for gid, row in game_idx.items():
        away_id, home_id = _parse_game_id(gid)
        if str(row["away_abbr"]) != away_id or str(row["home_abbr"]) != home_id:
            mapping_mismatch_games.append({"game_id": gid, "id_away": away_id, "id_home": home_id, "canonical_away": row["away_abbr"], "canonical_home": row["home_abbr"]})

    market = (
        pl.read_parquet(root / "data/market_data/canonical/canonical_book_market.parquet")
        .filter(
            pl.col("game_id").is_in([str(r["game_id"]) for r in selected])
            & (pl.col("market_key") == "h2h")
            & pl.col("bookmaker_key").is_in(["draftkings", "fanduel"])
        )
        .to_dicts()
    )
    by_game_book: dict[tuple[str, str], list[dict]] = {}
    for row in market:
        by_game_book.setdefault((str(row["game_id"]), str(row["bookmaker_key"])), []).append(row)

    expected_team_price_matches = 0
    opposite_team_price_matches = 0
    exact_timestamp_expected_matches = 0
    no_expected_price_match = 0
    ambiguous_same_price_both_teams = 0
    details = []
    for row in selected:
        gid = str(row["game_id"])
        game = game_idx.get(gid)
        if game is None:
            details.append({"game_id": gid, "error": "missing_canonical_game"})
            continue
        side = str(row["selected_side"])
        expected = str(game["home_abbr"] if side == "home" else game["away_abbr"])
        opposite = str(game["away_abbr"] if side == "home" else game["home_abbr"])
        price = int(row["american_odds"])
        candidates = [
            x for x in by_game_book.get((gid, str(row["sportsbook"])), [])
            if x.get("american_price") is not None and int(x["american_price"]) == price
        ]
        expected_rows = [x for x in candidates if _NAME_TO_ABBR.get(str(x.get("outcome_name", "")).strip()) == expected]
        opposite_rows = [x for x in candidates if _NAME_TO_ABBR.get(str(x.get("outcome_name", "")).strip()) == opposite]
        if expected_rows:
            expected_team_price_matches += 1
        else:
            no_expected_price_match += 1
        if opposite_rows:
            opposite_team_price_matches += 1
        if expected_rows and opposite_rows:
            ambiguous_same_price_both_teams += 1
        stamp = str(row.get("market_snapshot_timestamp") or "")
        if any(str(x.get("actual_snapshot_timestamp_utc") or x.get("requested_snapshot_timestamp_utc") or "") == stamp for x in expected_rows):
            exact_timestamp_expected_matches += 1
        if not expected_rows or opposite_rows:
            details.append({
                "game_id": gid,
                "role": row["role"],
                "side": side,
                "sportsbook": row["sportsbook"],
                "price": price,
                "expected_abbr": expected,
                "opposite_abbr": opposite,
                "expected_price_match_count": len(expected_rows),
                "opposite_price_match_count": len(opposite_rows),
            })

    result = {
        "development_seasons": sorted(DEV),
        "selected_moneyline_rows": len(selected),
        "canonical_game_id_home_away_mismatches": len(mapping_mismatch_games),
        "expected_team_price_matches": expected_team_price_matches,
        "no_expected_team_price_match": no_expected_price_match,
        "opposite_team_same_price_matches": opposite_team_price_matches,
        "ambiguous_same_price_both_teams": ambiguous_same_price_both_teams,
        "exact_timestamp_expected_team_matches": exact_timestamp_expected_matches,
        "mapping_mismatch_examples": mapping_mismatch_games[:10],
        "price_mapping_anomaly_examples": details[:20],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--selector-results", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    run(Path(a.root), Path(a.selector_results), Path(a.out))
