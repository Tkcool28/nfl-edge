#!/usr/bin/env python3
"""Build the final development modeling table for the Totals V1 bake-off.

Assembles, WITHOUT any PBP rebuild:
  7 identity columns
  + 90 predictor columns (defined ONLY by the machine-readable feature manifest)
  + home_score + away_score + target_total_points
Expected width with the 3 diagnostic/target columns retained = 100.

Score source: the established authoritative frozen canonical games table
(data/frozen/games/games_2018_2025.parquet), projected narrowly to
game_id, season (for boundary enforcement), home_score, away_score, with
NFL season==2025 excluded BEFORE the join. No sportsbook/market column enters.

FAIL-CLOSED ALIGNMENT (PR #14 hardening)
-----------------------------------------
The 90-feature artifact intentionally carries NO game_id. Alignment between a
game and its predictors is therefore made EXPLICIT and fail-closed through the
accepted identity sidecar as the authoritative row-key bridge:

  A. read identity + feature artifacts;
  B. prove equal height and accepted shapes;
  C. create ONE explicit deterministic row key on the ORIGINAL identity frame
     and the ORIGINAL feature frame BEFORE any score join;
  D. join scores to the keyed identity frame by game_id;
  E. after the score join, join predictors back by the preserved explicit
     original row key (NOT by join position/order);
  F. verify row-key uniqueness, no row loss/duplication, and that every
     original identity row is represented exactly once; score-input row order
     therefore cannot alter which predictors attach to which game;
  G. sort only at the very end for deterministic output serialization.

Reusable core functions are pure/near-pure and take in-memory frames, so tests
exercise the exact production assembly path with synthetic/mutated inputs.
"""
from __future__ import annotations

import argparse
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
ROW_KEY = "_row_key"


class TotalsModelingTableError(ValueError):
    """Raised when modeling-table assembly/validation violates a fail-closed invariant."""


def manifest_core_v1_columns(manifest_path: Path = MANIFEST) -> list[str]:
    m = json.loads(Path(manifest_path).read_text())
    if m["num_core_v1"] != 90:
        raise TotalsModelingTableError("manifest num_core_v1 != 90")
    cols = [r["feature_name"] for r in m["feature_records"]]
    if len(cols) != 90:
        raise TotalsModelingTableError(f"manifest records != 90: {len(cols)}")
    if cols != list(EXACT_90_COLUMNS):
        raise TotalsModelingTableError("manifest order != EXACT_90_COLUMNS")
    if not all(r["model_input"] is True for r in m["feature_records"]):
        raise TotalsModelingTableError("manifest contains non-model-input record in predictor set")
    return cols


def validate_and_project_scores(scores: pl.DataFrame,
                                allowed_max_season: int = 2024,
                                expected_rows: int = 1942) -> pl.DataFrame:
    """Project the frozen score source narrowly to game_id/season/scores.

    Fail-closed on: duplicate game_id, out-of-window season handling (NFL
    season==2025 excluded BEFORE any join), and non-unique projection.
    """
    if "game_id" not in scores.columns:
        raise TotalsModelingTableError("score source missing game_id")
    dup = scores.group_by("game_id").len().filter(pl.col("len") > 1)
    if dup.height > 0:
        raise TotalsModelingTableError(
            f"duplicate game_id in score source: {dup['game_id'].to_list()}"
        )
    sc = scores.filter(pl.col("season") <= allowed_max_season)
    sc = sc.select(["game_id", "season", "home_score", "away_score"]).unique(subset=["game_id"])
    if sc.height != expected_rows:
        raise TotalsModelingTableError(
            f"score source post-bound rows {sc.height} != {expected_rows}"
        )
    if sc["game_id"].n_unique() != expected_rows:
        raise TotalsModelingTableError("score source game_id not unique after bound")
    return sc


def _key_frames(identity: pl.DataFrame, features: pl.DataFrame,
                predictor_cols: list[str]):
    """Create one explicit deterministic row key on original identity/feature frames."""
    if list(identity.columns) != IDENTITY_COLS:
        raise TotalsModelingTableError(f"identity schema mismatch: {identity.columns}")
    if list(features.columns) != list(EXACT_90_COLUMNS):
        raise TotalsModelingTableError("feature columns != EXACT_90_COLUMNS")
    if features.select(predictor_cols).columns != predictor_cols:
        raise TotalsModelingTableError("feature predictor projection mismatch")
    n = identity.height
    if features.height != n:
        raise TotalsModelingTableError(f"feature/identity height mismatch: {features.height} != {n}")
    id_keyed = identity.with_row_index(ROW_KEY)
    feat_keyed = features.select(predictor_cols).with_row_index(ROW_KEY)
    for fr, name in ((id_keyed, "identity"), (feat_keyed, "feature")):
        if fr[ROW_KEY].n_unique() != fr.height:
            raise TotalsModelingTableError(f"{name} row key not unique")
    return id_keyed, feat_keyed


def _attach_predictors(id_keyed: pl.DataFrame, feat_keyed: pl.DataFrame,
                       expected_n: int) -> pl.DataFrame:
    """Join predictors back by the preserved explicit row key (fail-closed)."""
    for fr, name in ((id_keyed, "identity"), (feat_keyed, "feature")):
        if ROW_KEY not in fr.columns:
            raise TotalsModelingTableError(f"{name} frame missing row key")
        if fr[ROW_KEY].n_unique() != fr.height:
            raise TotalsModelingTableError(f"duplicate preserved row key ({name})")
    model = id_keyed.join(feat_keyed, on=ROW_KEY, how="inner")
    if model.height != expected_n:
        raise TotalsModelingTableError(
            f"row loss/duplication after predictor attach: {model.height} != {expected_n}"
        )
    if set(id_keyed[ROW_KEY].to_list()) != set(model[ROW_KEY].to_list()):
        raise TotalsModelingTableError("identity row-key set mismatch after assembly")
    return model


def assemble_modeling_table(identity: pl.DataFrame, features: pl.DataFrame,
                            scores: pl.DataFrame,
                            predictor_cols: list[str]) -> pl.DataFrame:
    """Assemble the full modeling table from in-memory frames (fail-closed).

    Order-preserving note: the score join happens on the keyed identity by
    game_id; predictors attach by the preserved explicit row key, so score-input
    row ordering cannot alter game->predictor attachment. The caller (CLI or
    validate_modeling_table) applies deterministic sort at the very end.
    """
    sc = validate_and_project_scores(scores)
    n = identity.height
    id_keyed, feat_keyed = _key_frames(identity, features, predictor_cols)

    joined = id_keyed.join(sc, on="game_id", how="left")
    if joined["home_score"].null_count() > 0 or joined["away_score"].null_count() > 0:
        raise TotalsModelingTableError(
            "missing/unmatched target score after join (unmatched identity game_id or null score)"
        )
    if joined.height != n:
        raise TotalsModelingTableError(f"joined rows {joined.height} != {n}")

    model = _attach_predictors(joined, feat_keyed, n)
    model = model.drop([ROW_KEY])

    # explicit target/diagnostic columns only
    model = model.with_columns(
        target_total_points=pl.col("home_score") + pl.col("away_score"),
    )
    if model["target_total_points"].null_count() > 0:
        raise TotalsModelingTableError("missing target_total_points")

    final_cols = IDENTITY_COLS + predictor_cols + ["home_score", "away_score", "target_total_points"]
    model = model.select(final_cols)
    if model.width != 100:
        raise TotalsModelingTableError(f"modeling-table width {model.width} != 100")
    return model


def validate_modeling_table(model: pl.DataFrame, predictor_cols: list[str],
                            expected_rows: int = 1942) -> pl.DataFrame:
    """Deterministic validation + final game_id sort for serialization."""
    final_cols = IDENTITY_COLS + predictor_cols + ["home_score", "away_score", "target_total_points"]
    assert list(model.columns) == final_cols, f"modeling table columns mismatch: {model.columns}"
    assert model.width == 100, f"width {model.width} != 100"
    assert model.height == expected_rows, f"rows {model.height} != {expected_rows}"
    assert model["game_id"].n_unique() == expected_rows, "game_id not unique"
    cnt = {int(s): int(n) for s, n in model.group_by("season").len().rows()}
    if cnt != EXPECTED_SEASON:
        raise TotalsModelingTableError(f"season counts mismatch: {cnt}")
    post2024 = model.filter((pl.col("season") == 2024) & (pl.col("season_type") != "REG")).height
    if post2024 != 13:
        raise TotalsModelingTableError(f"2024 postseason count {post2024} != 13")
    if "2024_22_KC_PHI" not in model["game_id"].to_list():
        raise TotalsModelingTableError("2024_22_KC_PHI missing")
    if model.filter(pl.col("season") == 2025).height != 0:
        raise TotalsModelingTableError("season 2025 rows present")
    # sportsbook fields must never be present
    sports = ["spread_line", "total_line", "over_odds", "under_odds", "away_moneyline",
              "home_moneyline", "away_spread_odds", "home_spread_odds", "result", "total"]
    offending = [c for c in sports if c in model.columns]
    if offending:
        raise TotalsModelingTableError(f"sportsbook fields present: {offending}")
    return model.sort("game_id")


def full_assembly_from_disk(predictor_cols: list[str], data_paths=None):
    """Read frozen inputs and produce the sorted validated modeling table."""
    data_paths = data_paths or {}
    identity = pl.read_parquet(data_paths.get("identity", IDENTITY))
    features = pl.read_parquet(data_paths.get("features", FEATURES))
    scores = pl.read_parquet(data_paths.get("scores", SCORES))
    model = assemble_modeling_table(identity, features, scores, predictor_cols)
    return validate_modeling_table(model, predictor_cols)


def build(log_tag: str, data_paths=None, out_path: Path = OUT):
    predictor_cols = manifest_core_v1_columns()
    model = full_assembly_from_disk(predictor_cols, data_paths)
    logical_fp = hashlib.sha256(model.serialize()).hexdigest()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    model.write_parquet(out_path)
    byte_sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
    cnt = {int(s): int(n) for s, n in model.group_by("season").len().rows()}
    print(f"[{log_tag}] wrote {out_path}")
    print(f"[{log_tag}] rows={model.height} width={model.width} unique_game_id={model['game_id'].n_unique()}")
    print(f"[{log_tag}] season counts={cnt}")
    print(f"[{log_tag}] post2024={model.filter((pl.col('season')==2024)&(pl.col('season_type')!='REG')).height} "
          f"kc_phi={'2024_22_KC_PHI' in model['game_id'].to_list()} "
          f"s2025={model.filter(pl.col('season')==2025).height}")
    print(f"[{log_tag}] logical_fp={logical_fp}")
    print(f"[{log_tag}] byte_sha256={byte_sha}")
    return logical_fp, byte_sha


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--repro", action="store_true",
                    help="build twice in-memory and verify identical logical content + bytes")
    args = ap.parse_args()
    if args.repro:
        lp1, bs1 = build("BUILD1", out_path=Path("/tmp/totals_repro_1.parquet"))
        lp2, bs2 = build("BUILD2", out_path=Path("/tmp/totals_repro_2.parquet"))
        print("\n=== REPRODUCIBILITY CHECK ===")
        print(f"build1 logical_fp={lp1}")
        print(f"build2 logical_fp={lp2}")
        print(f"build1 byte_sha256={bs1}")
        print(f"build2 byte_sha256={bs2}")
        print("logical_fp_equal:", lp1 == lp2)
        print("byte_sha_equal:", bs1 == bs2)
        if lp1 != lp2:
            raise SystemExit("FATAL: logical content fingerprints differ between builds")
        if bs1 != bs2:
            raise SystemExit("FATAL: parquet bytes differ between builds")
        print("REPRODUCIBLE: TRUE")
    else:
        try:
            build("build1")
        except TotalsModelingTableError as e:
            raise SystemExit(f"FATAL: {e}")
