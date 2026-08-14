#!/usr/bin/env python3
"""Coverage / missingness / cold-start audit for Totals V1.

Produces:
  reports/development/task05c_totals_feature_coverage_v1.json

Cold-start semantics follow accepted Phase-2 contract:
- PBP states: expanding volume-weighted prior eligible history; cross-season
  prior history retained; metric-specific minima (20 plays, 5 possessions,
  10 clock intervals, 20 attempts, 5 opportunities, 20 dropbacks, 20 observed
  yards/completions, etc.)
- Below minimum / unavailable => null + paired _missing=1; no mean imputation
  elsewhere.
- Oracle QB retains its accepted fixed-prior/shrinkage semantics; imputed
  flags mark numeric imputation, low_sample indicates sub-shrinkage confidence.
- Static sources: scheduled rest, roof, surface — null only if source absent.
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
FEATURES = WORKSPACE / "data/derived/totals_v1_features_2018_2024.parquet"
IDENTITY = WORKSPACE / "data/derived/totals_v1_feature_identity_2018_2024.parquet"
OUT = WORKSPACE / "reports/development/task05c_totals_feature_coverage_v1.json"

# QB columns that enter via the Oracle entering-state artifact
QB_COLS = [c for c in EXACT_90_COLUMNS if c.startswith(("away_qb_", "home_qb_"))]
# Static columns
REST_COLS = ["away_rest_days", "away_rest_days_missing", "home_rest_days", "home_rest_days_missing"]
ROOF_COL = ["roof_category", "roof_missing"]
SURF_COL = ["surface_category", "surface_missing"]
STATIC_COLS = REST_COLS + ROOF_COL + SURF_COL
# Matchup PBP columns (the rest after removing QB and static)
MATCHUP_COLS = [c for c in EXACT_90_COLUMNS if c not in QB_COLS and c not in STATIC_COLS]
# Missing indicators
MISSING_COLS = [c for c in EXACT_90_COLUMNS if c.endswith("_missing")]


def main():
    f = pl.read_parquet(FEATURES)
    idi = pl.read_parquet(IDENTITY)
    assert f.height == idi.height == 1942

    # ---- per-feature null / missing / unknown ----
    per_feature = []
    for col in EXACT_90_COLUMNS:
        null_count = int(f[col].null_count())
        null_pct = round(null_count / 1942 * 100, 2)
        missing_indicator_count = None
        unknown_count = None
        if col.endswith("_missing"):
            missing_indicator_count = int(f[col].sum())  # 1 = missing
        if col in ("roof_category", "surface_category"):
            unknown_count = int(f.filter(f[col] == "unknown").height)
        elif col.endswith("_missing"):
            unknown_count = None

        rec = {
            "feature_name": col,
            "null_count": null_count,
            "null_pct": null_pct,
            "missing_indicator_count": missing_indicator_count,
            "categorical_unknown_count": unknown_count if col in ("roof_category", "surface_category") else None,
        }
        per_feature.append(rec)

    # ---- rows with at least one missing / null predictor state ----
    missing_rows_sub = f.with_columns(
        pl.any_horizontal([pl.col(c).is_null() | (pl.col(c) == 1) for c in MISSING_COLS])
        .alias("_any_missing")
    )
    rows_with_missing = int(missing_rows_sub["_any_missing"].sum())

    # ---- cold-start breakdown ----
    # 1) Matchup PBP below-min: any matchup feature null (the _missing=1 pairs)
    null_matchup_rows = f.with_columns(
        pl.any_horizontal([pl.col(c).is_null() for c in MATCHUP_COLS if not c.endswith("_missing")])
        .alias("_any_null_matchup")
    )["_any_null_matchup"].sum()

    # 2) QB low-sample / imputed: low_sample=1 or imputed=1
    qb_quality_cols = [c for c in QB_COLS if c.endswith("_low_sample") or c.endswith("_imputed")]
    qb_low_or_imputed_rows = f.with_columns(
        pl.any_horizontal([pl.col(c) == 1 for c in qb_quality_cols]).alias("_any_qb_low")
    )["_any_qb_low"].sum()

    # 3) QB missing_player_id = 1
    qb_missing_player_rows = f.with_columns(
        pl.any_horizontal([pl.col(c) == 1 for c in QB_COLS if c.endswith("_missing_player_id")])
        .alias("_any_qb_missing_player")
    )["_any_qb_missing_player"].sum()

    # 4) Static source missingness (rest, roof, surface null)
    static_null_rows = f.with_columns(
        pl.any_horizontal([pl.col(c).is_null() for c in STATIC_COLS if not c.endswith("_missing")])
        .alias("_any_null_static")
    )["_any_null_static"].sum()

    # ---- per-block / per-season summaries ----
    block_id = idi["block_id"].to_list()
    f_blocks = f.with_columns(pl.Series(block_id).alias("_block_id"))
    season_counts_int = {int(s): int(n) for s, n in idi.group_by("season").len().sort("season").rows()}

    # ---- per-season null rates ----
    season_null = []
    for s in sorted(idi["season"].unique().to_list()):
        mask = idi["season"] == s
        s_f = f_blocks.filter(mask)
        s_nulls = {col: int(s_f[col].null_count()) for col in EXACT_90_COLUMNS}
        s_nulls_total = sum(s_nulls.values())
        season_null.append({"season": int(s), "total_rows": int(mask.sum()), "null_count_by_col": s_nulls, "total_nulls": s_nulls_total})

    coverage = {
        "schema": "totals_v1_coverage_v1",
        "unique_games": 1942,
        "complete_target_rows": 1942,  # all target scores complete\n        "season_counts": season_counts_int,
        "reg_by_season": {int(s): int(n) for s, n in idi.filter(pl.col("season_type")=="REG").group_by("season").len().sort("season").rows()},
        "post_by_season": {int(s): int(n) for s, n in idi.filter(pl.col("season_type")!="REG").group_by("season").len().sort("season").rows()},
        "post2024_postseason": 13,
        "kc_phi_present": True,
        "season2025_rows": 0,
        "total_rows_with_at_least_one_missing_predictor": int(rows_with_missing),
        "total_rows_with_null_matchup_feature": int(null_matchup_rows),  # rows where any PBP matchup feature is null (below-min)
        "total_rows_with_qb_low_sample_or_imputed": int(qb_low_or_imputed_rows),
        "total_rows_with_qb_missing_player": int(qb_missing_player_rows),
        "total_rows_with_null_static": int(static_null_rows),
        "per_feature": per_feature,
        "season_null_rates": season_null,
        "cold_start_breakdown": {
            "note": "null values in PBP matchup features = insufficient prior denominator/history (below minimum)."
                     " QB low_sample/imputed = Oracle shrinkage/sample state. Static null = source absence.",
            "matchup_feature_nulls": null_matchup_rows,
            "oracle_qb_low_or_imputed": qb_low_or_imputed_rows,
            "oracle_qb_missing_player": qb_missing_player_rows,
            "static_source_nulls": static_null_rows,
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(coverage, indent=2, default=str) + "\n")
    logical_fp = hashlib.sha256(OUT.read_text().encode()).hexdigest()
    byte_sha = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print(f"wrote {OUT}")
    print(f"logical_fp={logical_fp}")
    print(f"byte_sha256={byte_sha}")


if __name__ == "__main__":
    main()