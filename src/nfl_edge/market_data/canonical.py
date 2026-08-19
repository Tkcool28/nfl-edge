"""Outcome-blind canonical T-60 market dataset builder (Task 05E-D2, Phase B).

Consumes the NORMALIZED layer and the frozen request plan to produce:

1. one game-level CANONICAL table for the 1,408 frozen target games (identity,
   cluster, kickoff, snapshot, lead minutes, match status, coverage flags);
2. one long-form book/market observation table (game x book x market x side).

No vig removal, no consensus, no edge values, no scores — purely a frozen
near-closing T-60 snapshot dataset for later (preregistered) edge work.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .kickoffs import gameday_gametime_to_utc
from .normalize import _norm_ts

# Match status vocabulary.
MATCHED_EXACT = "MATCHED_EXACT"
MATCHED_ALIAS = "MATCHED_ALIAS"
UNMATCHED_NO_EVENT = "UNMATCHED_NO_EVENT"
AMBIGUOUS = "AMBIGUOUS"
OTHER = "OTHER_EXPLICIT_REASON"

# Quality flag vocabulary
FLAG_MATCH_FAILURE = "MATCH_FAILURE"
FLAG_AMBIGUOUS_ID = "AMBIGUOUS_GAME_IDENTITY"
FLAG_NOT_PREGAME = "SNAPSHOT_NOT_PREGAME"
FLAG_MISSING_H2H = "MISSING_H2H"
FLAG_MISSING_SPREAD = "MISSING_SPREAD"
FLAG_MISSING_TOTAL = "MISSING_TOTAL"
FLAG_MALFORMED_H2H = "MALFORMED_H2H_PAIR"
FLAG_MALFORMED_SPREAD = "MALFORMED_SPREAD_PAIR"
FLAG_MALFORMED_TOTAL = "MALFORMED_TOTAL_PAIR"
FLAG_DUP_BOOK_MARKET = "DUPLICATE_BOOK_MARKET"
FLAG_CONFLICT = "CONFLICTING_OBSERVATION"
FLAG_UNEXPECTED_BOOK = "UNEXPECTED_BOOK"
FLAG_UNEXPECTED_MARKET = "UNEXPECTED_MARKET"
FLAG_RAW_HASH = "RAW_HASH_MISMATCH"

BOOKS = ["draftkings", "fanduel", "pinnacle", "betonlineag", "williamhill_us",
         "betmgm", "betrivers", "bovada", "lowvig", "betus"]
MARKETS = ["h2h", "spreads", "totals"]
PER_BOOK_ABBRV = {
    "draftkings": "DK", "fanduel": "FD", "pinnacle": "PIN", "betonlineag": "BO",
    "williamhill_us": "WH", "betmgm": "MG", "betrivers": "BR", "bovada": "BV",
    "lowvig": "LV", "betus": "BU",
}


def build_canonical(
    normalized: pl.DataFrame,
    request_plan: pl.DataFrame,
    schedule: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Build (game_table, book_market_table) from normalized + plan + schedule.

    ``schedule``: frozen nflverse schedule (game_id, season, gameday, gametime,
    away_team, home_team) for kickoff times.
    """
    # ---- game table: one row per frozen target game ----
    game_rows: list[dict] = []
    for r in request_plan.to_dicts():
        rid = str(r["request_plan_id"])
        season = int(r["season"])
        requested_ts = r["requested_target_timestamp_utc"]
        earliest_kickoff = r["expected_earliest_kickoff_utc"]
        for gid in str(r["target_game_ids"]).split(","):
            if gid:
                game_rows.append({
                    "game_id": gid,
                    "season": season,
                    "request_plan_id": rid,
                    "requested_snapshot_timestamp_utc": requested_ts,
                    "expected_earliest_kickoff_utc": earliest_kickoff,
                })
    games = pl.DataFrame(game_rows, strict=False)

    # kickoff UTC + away/home abbrs from schedule
    sch = schedule.select(["game_id", "gameday", "gametime", "away_team", "home_team"])
    games = games.join(sch, on="game_id", how="left")
    kick = [
        gameday_gametime_to_utc(gd, gt).isoformat() if gd and gt else None
        for gd, gt in zip(games["gameday"].to_list(), games["gametime"].to_list())
    ]
    games = games.with_columns(pl.Series("kickoff_time_utc", kick))
    games = games.with_columns([
        pl.col("away_team").alias("away_abbr"),
        pl.col("home_team").alias("home_abbr"),
    ]).drop(["gameday", "gametime"])

    # index normalized target observations by game
    tg = normalized.filter(pl.col("is_target_event") == True)  # noqa: E712
    obs_by_game: dict[str, list[dict]] = {}
    for row in tg.to_dicts():
        mtg = row.get("matched_target_game_ids")
        if not mtg:
            continue
        for gid in mtg.split(","):
            obs_by_game.setdefault(gid, []).append(row)

    # actual snapshot for a game = snapshot from its cluster request (from normalized)
    snap_by_rid: dict[str, str] = {}
    for row in tg.to_dicts():
        rid = row["request_plan_id"]
        snap_by_rid.setdefault(rid, row.get("actual_snapshot_timestamp_utc"))
    snaps = pl.Series(
        [snap_by_rid.get(rid) for rid in games["request_plan_id"].to_list()],
        dtype=pl.Utf8,
    )
    games = games.with_columns(snaps.alias("actual_snapshot_timestamp_utc"))

    # lead minutes
    lead = []
    for row in games.select(["actual_snapshot_timestamp_utc", "kickoff_time_utc"]).to_dicts():
        a, e = row.get("actual_snapshot_timestamp_utc"), row.get("kickoff_time_utc")
        if a and e:
            from datetime import datetime
            lead.append((datetime.fromisoformat(e) - datetime.fromisoformat(a)).total_seconds() / 60.0)
        else:
            lead.append(None)
    games = games.with_columns(pl.Series("lead_minutes", lead))

    # match status
    status = []
    for row in games.to_dicts():
        status.append(_classify_match(row["game_id"], obs_by_game))
    games = games.with_columns(pl.Series("match_status", status))

    # coverage flags (per book/market presence among target obs)
    cov = []
    for row in games.to_dicts():
        cov.append(_coverage_for_game(row["game_id"], obs_by_game))
    cov_df = pl.DataFrame(cov, strict=False)
    games = pl.concat([games, cov_df], how="horizontal_extend")

    # quality flags column (comma-joined)
    flags = []
    for row in games.to_dicts():
        flags.append(_quality_flags(row, obs_by_game))
    games = games.with_columns(pl.Series("quality_flags", flags))

    # book/market long table: target observations only
    bm = tg.select([
        "request_plan_id", "season", "raw_file_path", "raw_file_sha256",
        "requested_snapshot_timestamp_utc", "actual_snapshot_timestamp_utc",
        "expected_earliest_kickoff_utc", "provider_event_id",
        "event_commence_time_utc", "provider_home_team", "provider_away_team",
        "home_abbr", "away_abbr", "matched_target_game_ids", "bookmaker_key",
        "bookmaker_title", "bookmaker_last_update_utc", "market_key",
        "market_last_update_utc", "side", "outcome_name", "point",
        "american_price", "malformed_market", "malformed_reason",
    ]).rename({"matched_target_game_ids": "game_id"})
    return games, bm


def _classify_match(game_id: str, obs_by_game: dict[str, list[dict]]) -> str:
    obs = obs_by_game.get(game_id)
    if not obs:
        return UNMATCHED_NO_EVENT
    return MATCHED_EXACT


def _coverage_for_game(game_id: str, obs_by_game: dict[str, list[dict]]) -> dict:
    obs = obs_by_game.get(game_id, [])
    books_present = set(o["bookmaker_key"] for o in obs)
    cov = {}
    for b in BOOKS:
        cov[f"has_{PER_BOOK_ABBRV[b]}"] = b in books_present
    # per-market presence per book (any obs)
    for m in MARKETS:
        has = any(o["market_key"] == m for o in obs)
        cov[f"has_market_{m}"] = has
    # complete three-market books
    complete = set()
    for b in books_present:
        bmks = {o["market_key"] for o in obs if o["bookmaker_key"] == b}
        if MARKETS[0] in bmks and MARKETS[1] in bmks and MARKETS[2] in bmks:
            complete.add(b)
    cov["complete_market_books"] = ",".join(sorted(complete))
    cov["n_books"] = len(books_present)
    cov["n_complete_books"] = len(complete)
    return cov


def _quality_flags(row: dict, obs_by_game: dict[str, list[dict]]) -> str | None:
    flags: list[str] = []
    obs = obs_by_game.get(row["game_id"], [])
    if row["match_status"] == UNMATCHED_NO_EVENT:
        flags.append(FLAG_MATCH_FAILURE)
    # market missingness (only if matched)
    if obs:
        book_set = set(o["bookmaker_key"] for o in obs)
        for m in MARKETS:
            if not any(o["market_key"] == m for o in obs):
                if m == "h2h": flags.append(FLAG_MISSING_H2H)
                elif m == "spreads": flags.append(FLAG_MISSING_SPREAD)
                else: flags.append(FLAG_MISSING_TOTAL)
        for b in book_set:
            for m in MARKETS:
                mlist = [o for o in obs if o["bookmaker_key"] == b and o["market_key"] == m]
                # a well-formed market has exactly 2 outcome sides (home/away or over/under).
                # A true duplicate is the SAME side appearing more than once.
                if len(mlist) > 2:
                    flags.append(FLAG_DUP_BOOK_MARKET)
                else:
                    name_counts: dict[str, int] = {}
                    for o in mlist:
                        k = str(o.get("outcome_name"))
                        name_counts[k] = name_counts.get(k, 0) + 1
                    if any(c > 1 for c in name_counts.values()):
                        flags.append(FLAG_DUP_BOOK_MARKET)
                mal = [o for o in mlist if o.get("malformed_market")]
                if mal:
                    if m == "h2h": flags.append(FLAG_MALFORMED_H2H)
                    elif m == "spreads": flags.append(FLAG_MALFORMED_SPREAD)
                    else: flags.append(FLAG_MALFORMED_TOTAL)
    return ",".join(sorted(set(flags))) or None


def write_canonical(games: pl.DataFrame, bm: pl.DataFrame, out_dir: str | Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    games.write_parquet(out_dir / "canonical_games.parquet", compression="zstd")
    bm.write_parquet(out_dir / "canonical_book_market.parquet", compression="zstd")