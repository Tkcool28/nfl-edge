#!/usr/bin/env python3
"""Build the final oracle starter ledger from repository-contained inputs.

Fail-closed integrity assertions cover the Stage01 candidate input, the
v2 resolution ledger, the crosswalk subset, exception identity, canonical-team
consistency, final game structure, and the Kendall Hinton semantic exception.
No starter assignment semantics are changed.
"""
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

R = Path(__file__).resolve().parents[2]
B = R / "data/derived/stathead_actual_starters_v1"
OUT = B / "final_oracle_starters"
X = B / "identity_crosswalk" / "task04a_player_crosswalk_v1.csv"

SUBSET_SHA = "d554c7c2ab5114bc70d0f04a46feba0ef46ab53c717769f8c04f88b98e976742"
V2_SHA = "333a399288bda0405e6e8c10ac391740b681cf2de9b55ecc87afe60222df022d"
PRIMARY_SHA = "38732823861bb1def3c216ce9189b651a2dc4d0737d2f65f88f17e97f40b2a1a"
EXPECT_SEASON_COUNTS = {2018: 267, 2019: 267, 2020: 269, 2021: 285, 2022: 284, 2023: 285, 2024: 285}
SEMANTIC_EXCEPTION_KEY = "2020_12_NO_DEN:home"
HINTON = {"pfr_id": "HintKe00", "gsis_id": "00-0035864", "credit": "NONE"}


def sh(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main(B=B):
    g = list(csv.DictReader(open(B / "stage01_canonical_reconciliation/game_side_candidates.csv")))
    v = list(csv.DictReader(open(B / "manual_starter_review/web_researched_starter_resolutions_v2.csv")))
    OUT = B / "final_oracle_starters"
    X = B / "identity_crosswalk" / "task04a_player_crosswalk_v1.csv"

    # ---- Stage01 input contract ----
    assert len(g) == 3884, f"expected 3884 Stage01 game sides, got {len(g)}"
    keys_g = [(x["game_id"], x["team_side"]) for x in g]
    assert len(keys_g) == len(set(keys_g)), "duplicate Stage01 (game_id, team_side) keys"
    seasons = {int(x["season"]) for x in g}
    assert seasons == set(EXPECT_SEASON_COUNTS), f"Stage01 seasons must be exactly 2018-2024, got {sorted(seasons)}"
    assert 2025 not in seasons, "no NFL season 2025 may enter Stage01"
    season_counts = {}
    games_per_season = {}
    for s in sorted(EXPECT_SEASON_COUNTS):
        season_counts[s] = sum(int(x["season"]) == s for x in g)
        assert season_counts[s] == 2 * EXPECT_SEASON_COUNTS[s], (
            f"season {s} side count mismatch: got {season_counts[s]}, expected {2*EXPECT_SEASON_COUNTS[s]}")
        games_per_season[s] = len({x["game_id"] for x in g if int(x["season"]) == s})
        assert games_per_season[s] == EXPECT_SEASON_COUNTS[s], (
            f"season {s} game count mismatch: got {games_per_season[s]}, expected {EXPECT_SEASON_COUNTS[s]}")

    # ---- v2 resolution ledger contract ----
    assert sh(B / "manual_starter_review/web_researched_starter_resolutions_v2.csv") == V2_SHA, "v2 ledger SHA mismatch"
    assert len(v) == 99, f"v2 ledger must have exactly 99 rows, got {len(v)}"
    vk = {(x["game_id"], x["team_side"]): x for x in v}
    assert len(vk) == 99, f"v2 ledger must have 99 unique keys, got {len(vk)} (duplicates present)"
    for x in v:
        assert x["actual_starting_qb_pfr_id"], f"v2 blank PFR: {x['game_id']}:{x['team_side']}"
        assert x["actual_starting_qb_gsis_id"], f"v2 blank GSIS: {x['game_id']}:{x['team_side']}"
        assert x["starter_evidence_class"] == "POSTGAME_ACTUAL_STARTER", (
            f"v2 bad evidence class: {x['game_id']}:{x['team_side']}")
        assert x["historical_model_usage"] == "ORACLE_STARTER_IDENTITY_ONLY", (
            f"v2 bad historical usage: {x['game_id']}:{x['team_side']}")

    # ---- exception keys == Stage01 sides where candidate_count != 1 (exact set) ----
    exc_g = {key for key, x in zip(keys_g, g) if int(x["candidate_count"]) != 1}
    assert len(exc_g) == 99, f"expected 99 exception Stage01 sides, got {len(exc_g)}"
    assert set(vk) == exc_g, (
        "v2 exception key set must equal Stage01 candidate_count!=1 set; "
        f"missing={sorted(exc_g - set(vk))} extra={sorted(set(vk) - exc_g)}")

    # ---- canonical-team consistency ----
    g_by_key = {(x["game_id"], x["team_side"]): x for x in g}
    for k, x in vk.items():
        assert k in g_by_key, f"resolution key not in Stage01: {k}"
        assert x["canonical_team"] == g_by_key[k]["canonical_team"], (
            f"canonical_team mismatch for {k}: v2={x['canonical_team']} stage01={g_by_key[k]['canonical_team']}")

    # ---- crosswalk subset ----
    c = pd.read_csv(X, dtype=str)
    assert sh(X) == SUBSET_SHA and len(c) == 138, "crosswalk subset mismatch"
    cm = dict(zip(c.pfr_id, c.gsis_id))

    # ---- assemble sides ----
    dist = {}
    out = []
    for x in g:
        k = (x["game_id"], x["team_side"])
        n = int(x["candidate_count"])
        dist[n] = dist.get(n, 0) + 1
        assert (n == 1) == (k not in vk), f"candidate_count/exception mismatch for {k}"
        if k in vk:
            r = vk[k]
            name = r["actual_starting_qb_name"]
            pfr = r["actual_starting_qb_pfr_id"]
            gsis = r["actual_starting_qb_gsis_id"]
            cl = ("SPECIAL_KENDALL_HINTON_QB_ROLE_EXCEPTION" if r["identity_mapping_status"].startswith("SPECIAL")
                  else "VALIDATED_MANUAL_WEB_EXCEPTION")
            src = "VALIDATED_MANUAL_WEB_RESEARCH"
            rank = ""
            loc = r["source_locator_note"]
            notes = r["notes"]
        else:
            name, pfr = x["candidate_names"], x["candidate_pfr_ids"]
            gsis = cm[pfr]
            cl = "STATHEAD_UNAMBIGUOUS_SINGLE_CANDIDATE"
            src = "STATHEAD_QB_STARTED_QUERY"
            rank = x["candidate_ranks"]
            loc = f"Stage01 canonical reconciliation rank {rank}"
            notes = ""
        assert name and pfr and gsis, f"blank identity field for {k}"
        sem = cl.startswith("SPECIAL")
        out.append({
            "season": x["season"], "week": x["week"], "season_type": x["season_type"],
            "gameday": x["game_date"], "game_id": x["game_id"], "away_team": x["away_team"],
            "home_team": x["home_team"], "team_side": x["team_side"],
            "canonical_team": x["canonical_team"],
            "canonical_opponent": x["home_team"] if x["team_side"] == "away" else x["away_team"],
            "actual_starting_qb_name": name, "actual_starting_qb_pfr_id": pfr,
            "actual_starting_qb_gsis_id": gsis, "starter_resolution_class": cl,
            "starter_source": src, "starter_source_game_id": x["game_id"],
            "starter_source_locator": loc, "starter_source_rank": rank,
            "starter_evidence_class": "POSTGAME_ACTUAL_STARTER",
            "historical_model_usage": "ORACLE_STARTER_IDENTITY_ONLY",
            "postseason_flag": x["season_type"] != "REG", "semantic_exception_flag": sem,
            "official_qb_start_credit": "NONE" if sem else "CREDITED", "notes": notes,
        })
    assert dist == {0: 49, 1: 3785, 2: 49, 3: 1}, f"candidate-count distribution mismatch: {dist}"
    assert len(out) == 3884, f"expected 3884 side rows, got {len(out)}"
    assert len({(x["game_id"], x["team_side"]) for x in out}) == 3884, "duplicate side in final assembly"

    # ---- write side ledger ----
    p = OUT / "actual_starting_qb_game_sides_2018_2024_v1.csv"
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, out[0], lineterminator="\n")
        w.writeheader()
        w.writerows(out)

    # ---- assemble games (exactly one away + one home per game) ----
    games = {}
    for x in out:
        games.setdefault(x["game_id"], []).append(x)
    assert len(games) == 1942, f"expected 1942 games, got {len(games)}"
    rows = []
    for gid, z in games.items():
        assert len(z) == 2, f"game {gid} must have exactly 2 side rows, got {len(z)}"
        sides_by = {x["team_side"]: x for x in z}
        assert set(sides_by) == {"away", "home"}, f"game {gid} must have one away and one home side"
        a, h = sides_by["away"], sides_by["home"]
        rows.append({
            "season": a["season"], "week": a["week"], "season_type": a["season_type"],
            "game_date": a["gameday"], "game_id": gid, "away_team": a["away_team"],
            "home_team": a["home_team"],
            **{f"{s}_{k}": q[k] for s, q in [("away", a), ("home", h)]
               for k in ["actual_starting_qb_name", "actual_starting_qb_pfr_id",
                         "actual_starting_qb_gsis_id", "starter_source",
                         "starter_source_locator", "starter_resolution_class",
                         "semantic_exception_flag", "official_qb_start_credit"]},
            "starter_evidence_class": "POSTGAME_ACTUAL_STARTER",
            "historical_model_usage": "ORACLE_STARTER_IDENTITY_ONLY",
            "postseason_flag": a["postseason_flag"],
        })
    assert len(rows) == 1942, f"expected 1942 game rows, got {len(rows)}"
    assert all((r["away_team"] and r["home_team"] and r["game_id"]) for r in rows)

    q = OUT / "actual_starting_qbs_by_game_2018_2024_v1.csv"
    with q.open("w", newline="") as f:
        w = csv.DictWriter(f, rows[0], lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    pd.DataFrame(rows).to_parquet(
        OUT / "actual_starting_qbs_by_game_2018_2024_v1.parquet", index=False
    )

    # ---- Kendall Hinton explicit assertions ----
    h = [x for x in out if (x["game_id"], x["team_side"]) == ("2020_12_NO_DEN", "home")]
    assert len(h) == 1, "exactly one Hinton side row expected"
    h = h[0]
    assert h["actual_starting_qb_pfr_id"] == HINTON["pfr_id"], "Hinton PFR mismatch"
    assert h["actual_starting_qb_gsis_id"] == HINTON["gsis_id"], "Hinton GSIS mismatch"
    assert h["official_qb_start_credit"] == HINTON["credit"], "Hinton credit must be NONE"
    assert h["starter_resolution_class"].startswith("SPECIAL"), "Hinton must use special semantic class"

    # ---- semantic exception totals ----
    sem_keys = [f"{x['game_id']}:{x['team_side']}" for x in out if x["semantic_exception_flag"]]
    assert len(sem_keys) == 1, f"expected exactly 1 semantic exception, got {len(sem_keys)}"
    assert sem_keys == [SEMANTIC_EXCEPTION_KEY], (
        f"semantic exception key must be {SEMANTIC_EXCEPTION_KEY}, got {sem_keys}"
    )

    # ---- final unresolved checks ----
    assert all(x["actual_starting_qb_pfr_id"] for x in out), "unresolved PFR present"
    assert all(x["actual_starting_qb_gsis_id"] for x in out), "unresolved GSIS present"

    # ---- report ----
    rep = {
        "canonical_games": 1942, "canonical_game_sides": 3884,
        "ordinary_single_candidate_sides": 3785, "validated_exception_sides": 99,
        "final_game_side_rows": 3884, "final_game_rows": 1942,
        "pfr_resolved": 3884, "pfr_unresolved": 0, "gsis_resolved": 3884, "gsis_unresolved": 0,
        "semantic_exception_count": 1, "semantic_exception_keys": [SEMANTIC_EXCEPTION_KEY],
        "season_game_counts": {s: sum(int(x["season"]) == s for x in rows) for s in sorted(EXPECT_SEASON_COUNTS)},
        "postseason_games": sum(x["season_type"] != "REG" for x in rows),
        "super_bowl_games": sum(x["season_type"] == "SB" for x in rows),
        "crosswalk_path": "data/derived/stathead_actual_starters_v1/identity_crosswalk/task04a_player_crosswalk_v1.csv",
        "crosswalk_sha256": sh(X),
        "output_sha256": {
            z.name: sh(z)
            for z in [p, q, OUT / "actual_starting_qbs_by_game_2018_2024_v1.parquet"]
        },
    }
    (OUT / "final_oracle_starter_validation_report_v1.json").write_text(
        json.dumps(rep, indent=2) + "\n"
    )

    # ---- fail-closed: primary ledger must equal frozen committed hash ----
    assert sh(p) == PRIMARY_SHA, f"primary side ledger changed: {sh(p)}"


if __name__ == "__main__":
    main()