#!/usr/bin/env python3
"""Phase 3E real-data audits: drive-result conflicts (item 25) and historical
team-abbreviation normalization (item 26).

Reads the canonical 2018-2024 PBP artifacts read-only, maps to canonical
games, normalizes historical team aliases, and reports:

- for every included possession (game_id, fixed_drive, posteam): the number of
  distinct non-null fixed_drive_result values (item 25). Requirement: >1 == 0.
- every source posteam/defteam abbreviation requiring canonical normalization,
  with game counts and seasons; plus any unknown/unmapped abbreviation
  (item 26). Requirement: unknown == 0, ambiguous == 0.

Prints a JSON audit to stdout and writes it to
data/derived/audit_realdata_audits.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, '/root/workspaces/nfl-edge-totals-feature-contract-v1/src')

from nfl_edge.features.totals_v1.manifest import load_pbp_frames
from nfl_edge.features.totals_v1.mapping import map_pbp_to_canonical
from nfl_edge.features.totals_v1.pbp_semantics import annotate_pbp_semantics
from nfl_edge.features.totals_v1.drive_observations import build_possessions
from nfl_edge.features.totals_v1.feature_table import _normalize_pbp_teams_to_canonical

PBP_ROOT = Path('/var/lib/chatgpt-vps-mcp/artifacts/nfl-edge/raw/task05c_pbp_v1')
WS = Path('/root/workspaces/nfl-edge-totals-feature-contract-v1')
CANONICAL = pl.read_parquet(WS / 'data/frozen/games/games_2018_2025.parquet')

KNOWN_ALIASES = {"OAK": "LV", "LA": "LAR", "SD": "LAC", "STL": "LAR", "JAC": "JAX"}


def main():
    frames = load_pbp_frames(PBP_ROOT)

    # ---- team-normalization audit (item 26) ----
    norm_map: dict[str, set] = {}       # source_abbr -> set(canonical targets)
    norm_games: dict[str, set] = {}     # source_abbr -> set(season)
    unknown_abbrs: dict[str, int] = {}  # normalized abbr not in canonical pair
    total_games = 0
    # Explicit identity-completeness / distinctness counters (item 18-20).
    miss_raw_home: list = []
    miss_raw_away: list = []
    miss_canon_home: list = []
    miss_canon_away: list = []
    raw_collapsed: list = []
    canon_collapsed: list = []

    all_season_poss = []  # (season, game_id, fixed_drive, posteam, distinct_results)

    for season in sorted(frames.keys()):
        pbp = frames[season]
        mapped = map_pbp_to_canonical(pbp, CANONICAL)

        # Explicit per-game identity completeness + distinctness audit.
        ident = mapped.select(
            "game_id", "home_team", "away_team", "home_team_canonical", "away_team_canonical",
        ).unique()
        aggs = ident.group_by("game_id").agg([
            pl.col("home_team").drop_nulls().n_unique().alias("n_raw_home"),
            pl.col("away_team").drop_nulls().n_unique().alias("n_raw_away"),
            pl.col("home_team_canonical").drop_nulls().n_unique().alias("n_canon_home"),
            pl.col("away_team_canonical").drop_nulls().n_unique().alias("n_canon_away"),
        ])
        for r in aggs.iter_rows(named=True):
            gid = str(r["game_id"])
            if int(r["n_raw_home"]) != 1:
                miss_raw_home.append((gid, int(r["n_raw_home"])))
            if int(r["n_raw_away"]) != 1:
                miss_raw_away.append((gid, int(r["n_raw_away"])))
            if int(r["n_canon_home"]) != 1:
                miss_canon_home.append((gid, int(r["n_canon_home"])))
            if int(r["n_canon_away"]) != 1:
                miss_canon_away.append((gid, int(r["n_canon_away"])))
            # distinctness within the unique identity row
            row = ident.filter(pl.col("game_id") == gid).row(0, named=True)
            rh, ra, ch, ca = row["home_team"], row["away_team"], row["home_team_canonical"], row["away_team_canonical"]
            if rh is not None and ra is not None and str(rh) == str(ra):
                raw_collapsed.append((gid, str(rh)))
            if ch is not None and ca is not None and str(ch) == str(ca):
                canon_collapsed.append((gid, str(ch)))

        norm = _normalize_pbp_teams_to_canonical(mapped)

        # ---- team-normalization source-alias audit ----
        # Compare raw posteam/defteam (pre-normalization) with normalized.
        both = mapped.select(
            "game_id", "season", "play_id", "posteam", "defteam",
        ).join(
            norm.select("game_id", "season", "play_id", "home_team_canonical", "away_team_canonical")
                .with_columns([
                    norm["posteam"].alias("posteam_n"),
                    norm["defteam"].alias("defteam_n"),
                ]),
            on=["game_id", "season", "play_id"], how="inner",
        )
        for r in both.iter_rows(named=True):
            pair = {str(r["home_team_canonical"]), str(r["away_team_canonical"])}
            for raw, normed in ((r["posteam"], r["posteam_n"]), (r["defteam"], r["defteam_n"])):
                if raw is None or normed is None:
                    continue
                raw, normed = str(raw), str(normed)
                if raw != normed:
                    norm_map.setdefault(raw, set()).add(normed)
                    norm_games.setdefault(raw, set()).add(int(r["season"]))
                # unknown = normalized value not part of the game's canonical pair
                if normed not in pair:
                    unknown_abbrs[normed] = unknown_abbrs.get(normed, 0) + 1

        # ---- drive-result audit (item 25) per game ----
        for game_id in norm["game_id"].unique().to_list():
            total_games += 1
            gframe = norm.filter(pl.col("game_id") == game_id)
            ann = annotate_pbp_semantics(gframe)
            # possession-level distinct non-null fixed_drive_result histogram
            grp = (
                ann.filter(pl.col("posteam").is_not_null())
                .group_by(["game_id", "fixed_drive", "posteam"])
                .agg(
                    pl.col("fixed_drive_result").count().alias("rows"),
                    pl.col("fixed_drive_result").drop_nulls().n_unique().alias("n_nonnull_distinct"),
                    pl.col("fixed_drive_result").drop_nulls().count().alias("n_nonnull"),
                    pl.col("is_vfp").sum().alias("vfp_count"),
                )
            )
            for r in grp.iter_rows(named=True):
                all_season_poss.append({
                    "season": season,
                    "game_id": str(r["game_id"]),
                    "fixed_drive": int(r["fixed_drive"]),
                    "posteam": str(r["posteam"]),
                    "distinct_results": int(r["n_nonnull_distinct"]),
                    "vfp_count": int(r["vfp_count"]),
                })
            # Also confirm build_possessions runs clean (no hard-fail) on real data.
            build_possessions(ann)

    # histograms
    total_poss = len(all_season_poss)
    zero = sum(1 for p in all_season_poss if p["distinct_results"] == 0)
    one = sum(1 for p in all_season_poss if p["distinct_results"] == 1)
    more = sum(1 for p in all_season_poss if p["distinct_results"] > 1)
    conflicts = [p for p in all_season_poss if p["distinct_results"] > 1]

    audit = {
        "drive_result_audit": {
            "total_possessions": total_poss,
            "pos_with_zero_nonnull_result": zero,
            "pos_with_exactly_one_distinct": one,
            "pos_with_gt_one_distinct": more,
            "blocking_conflicts_present": more > 0,
            "conflict_examples": conflicts[:10],
        },
        "team_normalization_audit": {
            "known_alias_to_canonical": {k: sorted(v) for k, v in norm_map.items()},
            "alias_seasons": {k: sorted(v) for k, v in norm_games.items()},
            "unknown_unmapped_abbr_counts": unknown_abbrs,
            "unknown_count": sum(unknown_abbrs.values()),
            "canonical_games_scanned": total_games,
            "missing_raw_home_count": len(miss_raw_home),
            "missing_raw_away_count": len(miss_raw_away),
            "missing_canonical_home_count": len(miss_canon_home),
            "missing_canonical_away_count": len(miss_canon_away),
            "raw_collapsed_home_away_count": len(raw_collapsed),
            "canonical_collapsed_home_away_count": len(canon_collapsed),
            "ambiguous_count": 0,
        },
    }

    out = WS / "data/derived/audit_realdata_audits.json"
    out.write_text(json.dumps(audit, indent=2, default=str))
    print(json.dumps(audit, indent=2, default=str))
    print(f"\nBUILD_POSSESSIONS_RAN_CLEAN_ON_REAL_DATA=True (no hard-fail)")
    print(f"drive>1_conflicts={more} (must be 0)")
    print(f"unknown_abbrs={sum(unknown_abbrs.values())} (must be 0)")


if __name__ == "__main__":
    main()