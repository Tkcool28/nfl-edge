#!/usr/bin/env python3
"""Stage 01: identity-only reconciliation of Stathead rows to canonical games.

No starter selection or target-game performance data is used.  The canonical
input is the already sealed 2018-2024 development-game universe only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import polars as pl  # noqa: E402

from nfl_edge.data.integrity import TEAM_ALIASES, normalize_team  # noqa: E402

DEVELOPMENT_SEASONS = frozenset(range(2018, 2025))
# Explicit Stathead/PFR abbreviations not already covered by the shared utility.
STATHEAD_TEAM_ALIASES = {
    **TEAM_ALIASES,
    "GNB": "GB",
    "KAN": "KC",
    "LVR": "LV",
    "NWE": "NE",
    "NOR": "NO",
    "SFO": "SF",
    "TAM": "TB",
    "SDG": "LAC",
}
ROW_COLUMNS = [
    "rank",
    "player_name",
    "pfr_id",
    "raw_date",
    "raw_team",
    "raw_location",
    "raw_opp",
    "raw_pos",
    "match_status",
    "canonical_game_id",
    "canonical_season",
    "canonical_week",
    "canonical_season_type",
    "canonical_away_team",
    "canonical_home_team",
    "team_side",
    "reconciliation_reason",
]
GROUP_COLUMNS = [
    "game_id",
    "season",
    "week",
    "season_type",
    "game_date",
    "away_team",
    "home_team",
    "team_side",
    "canonical_team",
    "candidate_count",
    "candidate_ranks",
    "candidate_names",
    "candidate_pfr_ids",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_stathead_team(value: object) -> str:
    token = str(value).strip().upper()
    return STATHEAD_TEAM_ALIASES.get(token, normalize_team(token) or token)


def _date_from_timestamp(value: object) -> str:
    return str(value)[:10]


def validate_canonical_games(games: list[dict[str, object]]) -> None:
    seasons = {int(game["season"]) for game in games}
    if seasons != DEVELOPMENT_SEASONS:
        raise ValueError(f"canonical seasons must be 2018-2024 only; got {sorted(seasons)}")
    if len(games) != 1942:
        raise ValueError(f"canonical game count must be 1942, got {len(games)}")
    ids = [str(game["game_id"]) for game in games]
    if len(ids) != len(set(ids)):
        raise ValueError("canonical game_id values must be unique")


def load_canonical_games(path: Path) -> list[dict[str, object]]:
    # ``gameday`` is the non-null canonical calendar-date identity field.
    # Filter the frozen source at the canonical boundary before it becomes a
    # reconciliation input, thereby excluding the 2025 NFL-season holdout.
    frame = (
        pl.read_parquet(path)
        .filter(pl.col("season").is_between(2018, 2024))
        .select(
            [
                "game_id",
                "season",
                "season_type",
                "week",
                "gameday",
                "home_team",
                "away_team",
            ]
        )
    )
    games = [
        {
            "game_id": str(row["game_id"]),
            "season": int(row["season"]),
            "season_type": str(row["season_type"]),
            "week": int(row["week"]),
            "game_date": str(row["gameday"]),
            "home_team": normalize_stathead_team(row["home_team"]),
            "away_team": normalize_stathead_team(row["away_team"]),
        }
        for row in frame.to_dicts()
    ]
    validate_canonical_games(games)
    return games


def reconcile_rows(
    raw_rows: list[dict[str, object]], canonical_games: list[dict[str, object]]
) -> list[dict[str, object]]:
    by_date_and_pair: dict[tuple[str, frozenset[str]], list[dict[str, object]]] = defaultdict(list)
    for game in canonical_games:
        by_date_and_pair[(str(game["game_date"]), frozenset((str(game["away_team"]), str(game["home_team"]))))].append(
            game
        )
    output: list[dict[str, object]] = []
    for source in raw_rows:
        rank = str(source["Rk"])
        raw_team, raw_opp = str(source["Team"]), str(source["Opp"])
        location = str(source[""])
        record: dict[str, object] = {
            "rank": rank,
            "player_name": str(source["Player"]),
            "pfr_id": str(source["Player-additional"]),
            "raw_date": str(source["Date"]),
            "raw_team": raw_team,
            "raw_location": location,
            "raw_opp": raw_opp,
            "raw_pos": str(source["Pos."]),
            "match_status": "",
            "canonical_game_id": "",
            "canonical_season": "",
            "canonical_week": "",
            "canonical_season_type": "",
            "canonical_away_team": "",
            "canonical_home_team": "",
            "team_side": "",
            "reconciliation_reason": "",
        }
        if raw_opp == "BYE":
            record.update(
                match_status="NON_GAME_BYE", reconciliation_reason="raw Stathead BYE evidence; no canonical game"
            )
            output.append(record)
            continue
        team, opp = normalize_stathead_team(raw_team), normalize_stathead_team(raw_opp)
        candidates = by_date_and_pair.get((str(source["Date"]), frozenset((team, opp))), [])
        if len(candidates) != 1:
            record.update(
                match_status="AMBIGUOUS_GAME_MATCH" if len(candidates) > 1 else "UNMATCHED",
                reconciliation_reason=(
                    "multiple canonical games share date/team/opponent identity"
                    if len(candidates) > 1
                    else "no canonical date/team/opponent identity match"
                ),
            )
            output.append(record)
            continue
        game = candidates[0]
        if team == game["away_team"] and opp == game["home_team"]:
            side = "away"
        elif team == game["home_team"] and opp == game["away_team"]:
            side = "home"
        else:
            raise AssertionError("pair index returned incompatible teams")
        if location == "@" and side != "away":
            record.update(
                match_status="UNMATCHED", reconciliation_reason="raw away indicator contradicts canonical team side"
            )
        elif location == "" and side != "home":
            record.update(
                match_status="UNMATCHED", reconciliation_reason="raw home indicator contradicts canonical team side"
            )
        elif location not in {"", "@", "N"}:
            record.update(match_status="UNMATCHED", reconciliation_reason="unknown raw location indicator")
        else:
            record.update(
                match_status="MATCHED_CANONICAL_GAME",
                canonical_game_id=game["game_id"],
                canonical_season=game["season"],
                canonical_week=game["week"],
                canonical_season_type=game["season_type"],
                canonical_away_team=game["away_team"],
                canonical_home_team=game["home_team"],
                team_side=side,
                reconciliation_reason=(
                    "neutral-site canonical team identity"
                    if location == "N"
                    else "date/team/opponent/location identity"
                ),
            )
        output.append(record)
    return output


def build_game_side_candidates(
    games: list[dict[str, object]], rows: list[dict[str, object]]
) -> list[dict[str, object]]:
    candidates: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        if row["match_status"] == "MATCHED_CANONICAL_GAME":
            candidates[(str(row["canonical_game_id"]), str(row["team_side"]))].append(row)
    groups: list[dict[str, object]] = []
    for game in sorted(games, key=lambda item: str(item["game_id"])):
        for side, team in (("away", game["away_team"]), ("home", game["home_team"])):
            members = sorted(candidates[(str(game["game_id"]), side)], key=lambda item: int(str(item["rank"])))
            groups.append(
                {
                    "game_id": game["game_id"],
                    "season": game["season"],
                    "week": game["week"],
                    "season_type": game["season_type"],
                    "game_date": game["game_date"],
                    "away_team": game["away_team"],
                    "home_team": game["home_team"],
                    "team_side": side,
                    "canonical_team": team,
                    "candidate_count": len(members),
                    "candidate_ranks": "|".join(str(row["rank"]) for row in members),
                    "candidate_names": "|".join(str(row["player_name"]) for row in members),
                    "candidate_pfr_ids": "|".join(str(row["pfr_id"]) for row in members),
                }
            )
    return groups


def write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(raw_path: Path, canonical_path: Path, output_dir: Path) -> dict[str, Any]:
    with raw_path.open(newline="", encoding="utf-8") as handle:
        raw_rows = list(csv.DictReader(handle))
    if len(raw_rows) != 3921 or {str(row["Rk"]) for row in raw_rows} != {str(i) for i in range(1, 3922)}:
        raise ValueError("Stage 00 input must contain ranks 1..3921 exactly once")
    games = load_canonical_games(canonical_path)
    reconciled = reconcile_rows(raw_rows, games)
    if len(reconciled) != 3921 or len({str(row["rank"]) for row in reconciled}) != 3921:
        raise ValueError("row reconciliation must retain every raw rank exactly once")
    groups = build_game_side_candidates(games, reconciled)
    if len(groups) != 3884:
        raise ValueError(f"canonical game-side count must be 3884, got {len(groups)}")
    row_path, group_path, report_path = (
        output_dir / "row_reconciliation.csv",
        output_dir / "game_side_candidates.csv",
        output_dir / "reconciliation_report.json",
    )
    write_csv(row_path, ROW_COLUMNS, reconciled)
    write_csv(group_path, GROUP_COLUMNS, groups)
    status_counts = Counter(str(row["match_status"]) for row in reconciled)
    distribution = Counter(int(group["candidate_count"]) for group in groups)
    report: dict[str, Any] = {
        "stage": "stage01_canonical_game_reconciliation",
        "raw_row_count": len(raw_rows),
        "matched_raw_rows": status_counts["MATCHED_CANONICAL_GAME"],
        "bye_rows": status_counts["NON_GAME_BYE"],
        "unmatched_raw_rows": status_counts["UNMATCHED"],
        "ambiguous_game_matches": status_counts["AMBIGUOUS_GAME_MATCH"],
        "canonical_game_count": len(games),
        "canonical_game_side_count": len(groups),
        "game_sides_with_0_candidates": distribution[0],
        "game_sides_with_1_candidate": distribution[1],
        "game_sides_with_2plus_candidates": sum(value for count, value in distribution.items() if count >= 2),
        "distribution_of_candidate_counts": {str(key): distribution[key] for key in sorted(distribution)},
        "team_normalization_map_used": STATHEAD_TEAM_ALIASES,
        "neutral_site_rows": sum(row["raw_location"] == "N" for row in reconciled),
        "neutral_site_rows_matched": sum(
            row["raw_location"] == "N" and row["match_status"] == "MATCHED_CANONICAL_GAME" for row in reconciled
        ),
        "postseason_game_count": sum(game["season_type"] != "REG" for game in games),
        "super_bowl_game_count": sum(game["season_type"] == "SB" for game in games),
        "outputs": {},
        "guardrails": [
            "identity fields only",
            "no starter adjudication",
            "BYE rows retained",
            "no 2025 NFL season input",
        ],
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report["outputs"] = {str(path): sha256_file(path) for path in (row_path, group_path, report_path)}
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--raw-input",
        type=Path,
        default=REPO_ROOT
        / "data/derived/stathead_actual_starters_v1/stage00_structural/stathead_qb_started_2018_2024_raw_combined.csv",
    )
    parser.add_argument("--canonical-games", type=Path, default=REPO_ROOT / "data/frozen/games/games_2018_2025.parquet")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "data/derived/stathead_actual_starters_v1/stage01_canonical_reconciliation",
    )
    args = parser.parse_args()
    print(json.dumps(run(args.raw_input, args.canonical_games, args.output_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
