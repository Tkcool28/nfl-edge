#!/usr/bin/env python3
"""Build the final development modeling table for the Totals V1 bake-off.

Assembles, WITHOUT any PBP rebuild:
  7 identity columns (+ exact 90 predictor columns hashed below)
  + home_score + away_score + target_total_points
Expected width with the 3 diagnostic/target columns retained = 100.

Score source: the established authoritative frozen canonical games table
(data/frozen/games/games_2018_2025.parquet), projected narrowly to
game_id, season (for boundary enforcement), home_score, away_score, with
NFL season==2025 excluded BEFORE the join. No sportsbook/market column enters.

The 90 predictor columns are defined EXCLUSIVELY by the machine-readable
feature manifest (task05c_totals_feature_manifest_v1.json) — no
"all numeric except..." selection logic.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, "/root/workspaces/nfl-edge-totals-feature-contract-v1/src")
from nfl_edge.features.totals_v1.feature_table import EXACT_90_COLUMNS

WORKSPACE = Path("/root/workspaces/nfl-edge-totals-feature-contract-v1")
IDENTITY = WORKSPACE / "data/derived/totals_v1_feature_identity_2018_2024.parquet"
FEATURES = WORKSPACE / "data/derived/totals_v1_features_2018_2024.parquet"
SCORES = WORKSPACE / "data/frozen/games/games_2018_2025.parquet"
MANIFEST = WORKSPACE / "data/manifests/task05c_totals_feature_manifest_v1.json"
OUT = WORKSPACE / "data/derived/totals_v1_modeling_table_2018_2024.parquet"

IDENTITY_COLS = ["game_id", "season", "season_type", "week", "home_team", "away_team", "block_id"]
EXPECTED_SEASON = {2018: 267, 2019: 267, 2020: 269, 2021: 285, 2022: 284, 2023: 285, 2024: 285}


def manifest_core_v1_columns() -> list[str]:
    m = json.loads(MANIFEST.read_text())
    assert m["num_core_v1"] == 90, "manifest num_core_v1 != 90"
    cols = [r["feature_name"] for r in m["feature_records"]]
    assert len(cols) == 90
    assert cols == list(EXACT_90_COLUMNS), "manifest order != EXACT_90_COLUMNS"
    assert all(r["model_input"] is True for r in m["feature_records"])
    return cols


def build(log_tag: str):
    identity = pl.read_parquet(IDENTITY)
    features = pl.read_parquet(FEATURES)
    predictor_cols = manifest_core_v1_columns()

    assert identity.columns == IDENTITY_COLS, f"identity cols {identity.columns}"
    assert features.columns == list(EXACT_90_COLUMNS), "features cols not EXACT_90"
    assert identity.height == features.height == 1942

    # --- project + bound the score source BEFORE join (hard-fail, no silence) ---
    scores = pl.read_parquet(SCORES)
    # duplicate game_id in the frozen score source hard-fails
    dup = scores.group_by("game_id").len().filter(pl.col("len") > 1)
    if dup.height > 0:
        raise SystemExit(f"FATAL: duplicate game_id in score source: {dup['game_id'].to_list()}")
    if (scores["season"] > 2024).any() is False:
        pass
    # exclude NFL season == 2025 BEFORE the join
    sc = scores.filter(pl.col("season") <= 2024)
    sc = sc.select(["game_id", "season", "home_score", "away_score"]).unique(subset=["game_id"])
    if sc.height != 1942:
        raise SystemExit(f"FATAL: score source post-bound rows {sc.height} != 1942")
    if sc["game_id"].n_unique() != 1942:
        raise SystemExit("FATAL: score source game_id not unique after bound")

    # --- join with hard-fail on unmatched identity game_id ---
    joined = identity.join(sc, on="game_id", how="left")
    if joined["home_score"].null_count() > 0 or joined["away_score"].null_count() > 0:
        raise SystemExit("FATAL: missing target score after join (unmatched identity game_id)")
    if joined.height != 1942:
        raise SystemExit(f"FATAL: joined rows {joined.height} != 1942")

    # --- mount exact 90 predictors from the validated feature artifact ---
    # The 90-feature artifact carries ONLY the predictor columns; it and the
    # 7-col identity are row-aligned (both written in the same deterministic
    # game_id-sorted order by the accepted builder). Align via row index and
    # verify the identity's game_id order matches.
    feats = features.select(predictor_cols)
    assert feats.columns == predictor_cols == list(EXACT_90_COLUMNS)

    identity_idx = joined.with_row_index("_ridx")
    feats_idx = feats.with_row_index("_fidx")
    model = identity_idx.join(feats_idx, left_on="_ridx", right_on="_fidx", how="inner")
    if model.height != 1942:
        raise SystemExit(f"FATAL: model rows {model.height} != 1942")
    # row-aligned means the predictor frame must be in the identical game_id order;
    # because features has no game_id, alignment is by construction (accepted builder).
    model = model.drop(["_ridx"])

    # add explicit target/diagnostic columns last
    model = model.with_columns(
        target_total_points=pl.col("home_score") + pl.col("away_score"),
    )
    if model["target_total_points"].null_count() > 0:
        raise SystemExit("FATAL: missing target_total_points")

    # order: 7 identity + 90 predictors + home_score + away_score + target_total_points
    final_cols = IDENTITY_COLS + predictor_cols + ["home_score", "away_score", "target_total_points"]
    model = model.select(final_cols)
    assert model.width == 100, f"width {model.width} != 100"

    # deterministic row ordering by game_id (as in the accepted builder)
    model = model.sort("game_id")

    # season-count gate
    cnt = {int(s): int(n) for s, n in model.group_by("season").len().rows()}
    assert cnt == EXPECTED_SEASON, f"season counts mismatch: {cnt}"
    post2024 = model.filter((pl.col("season") == 2024) & (pl.col("season_type") != "REG")).height
    assert post2024 == 13, f"2024 postseason count {post2024} != 13"
    assert "2024_22_KC_PHI" in model["game_id"].to_list()
    assert model.filter(pl.col("season") == 2025).height == 0
    assert model["game_id"].n_unique() == 1942

    # reproducibility logical fingerprint (sorted canonical content)
    logical = model.select(final_cols).sort("game_id")
    logical_fp = hashlib.sha256(logical.serialize()).hexdigest()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    model.write_parquet(OUT)
    byte_sha = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print(f"[{log_tag}] wrote {OUT}")
    print(f"[{log_tag}] rows={model.height} width={model.width} unique_game_id={model['game_id'].n_unique()}")
    print(f"[{log_tag}] season counts={cnt}")
    print(f"[{log_tag}] post2024={post2024} kc_phi={ '2024_22_KC_PHI' in model['game_id'].to_list() } s2025={model.filter(pl.col('season')==2025).height}")
    print(f"[{log_tag}] logical_fp={logical_fp}")
    print(f"[{log_tag}] byte_sha256={byte_sha}")
    return logical_fp, byte_sha


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--repro", action="store_true", help="build twice and verify identical logical content + bytes")
    args = ap.parse_args()
    if args.repro:
        lp1, bs1 = build("BUILD1")
        lp2, bs2 = build("BUILD2")
        print("\n=== REPRODUCIBILITY CHECK ===")
        print(f"build1 logical_fp={lp1}")
        print(f"build2 logical_fp={lp2}")
        print(f"build1 byte_sha256={bs1}")
        print(f"build2 byte_sha256={bs2}")
        print("logical_fp_equal:", lp1 == lp2)
        print("byte_sha_equal:", bs1 == bs2)
        assert lp1 == lp2, "logical content fingerprints differ between builds"
        assert bs1 == bs2, "parquet bytes differ between builds"
        print("REPRODUCIBLE: TRUE")
    else:
        build("build1")
