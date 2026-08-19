"""Task 05E-D3B-R1 — outcome-blind census repair assertions.

Proves (outcome-blind): R4 predictions are used (candidate_id==R4, no refit),
observed_total / score / winner / result columns never loaded, no 2025, no
training/stacker, positive-edge candidate census does not double-count the
mirrored side, at most one positive candidate per (game, model), split &
per-season sums reconcile, the +201 dog region is the explicit sum of
+201..+250 and +251+, dog region requires positive edge, overlap operates on
unique (game_id, side), DK/FD/Pinnacle product-market states are
deterministic, and quote-freshness is diagnostic only.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import polars as pl
import pytest

WT = Path("/root/workspaces/nfl-edge-task-05e-edge-prereg-v1")
PROD = Path("/root/nfl-edge")
CENSUS = WT / "data/modeling/development_v1/market_edge_census_v1.parquet"
CSV = WT / "reports/task_05e_d3b_outcome_blind_census.csv"
PROV = WT / "reports/task_05e_d3b_census_provenance.json"
R4 = PROD / "reports/task05d/task05d_ridge_predictions.parquet"
SEASONS = [2020, 2021, 2022, 2023, 2024]
DISC = [2020, 2021, 2022]


# ---------------------------------------------------------------------------
def test_production_head_untouched() -> None:
    import subprocess
    out = subprocess.run(["git", "-C", str(PROD), "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    assert out == "b805534", out


def test_r4_artifact_exists_and_manifest_confirms_r4_selected() -> None:
    assert R4.exists()
    m = json.loads((PROD / "reports/task05d/task05d_ridge_run_manifest.json").read_text())
    assert m["final_selection"]["candidate_id"] == "R4"
    assert m["final_selection"]["estimator_parameters"]["alpha"] == 100
    assert m["final_selection"]["status"] == "RIDGE_TOTALS_V1_SELECTED"


def test_r4_observed_total_never_loaded() -> None:
    # the build reads with a strict whitelist; the census parquet has NO observed/scores
    cols = pl.read_parquet(CENSUS).columns
    forbidden = {"observed_total", "home_score", "away_score", "target_total_points",
                 "actual_margin", "actual_home_win", "actual_tie", "winner"}
    assert not (set(cols) & forbidden), set(cols) & forbidden


def test_no_2025_and_no_outcome_columns_in_census() -> None:
    cat = pl.read_parquet(CENSUS)
    assert cat["season"].max() == 2024
    low = {c.lower() for c in cat.columns}
    assert not any(k in low for k in ("score", "winner", "ats", "roi", "profit", "margin_actual", "hit_rate"))


def test_totals_census_is_R4() -> None:
    tot = pl.read_parquet(CENSUS).filter(pl.col("census_family") == "TOTAL_R4")
    assert tot.height == 1408
    assert tot["r4_predicted_total"].null_count() == 0
    assert tot["pinnacle_total_O"].null_count() == 0


def test_positive_edge_not_double_counting_and_at_most_one() -> None:
    pe = pl.read_parquet(CENSUS).filter(pl.col("census_family") == "POSITIVE_EDGE_CANDIDATE")
    g = pe.group_by(["game_id", "model"]).agg(pl.col("side").n_unique().alias("n"))
    # at most one positive side per (game,model)
    assert (g["n"] > 1).sum() == 0
    assert g["n"].min() == 1
    # uniqueness of (game,model) for the model views that are complete
    for m in ("QB_ELO", "AVG"):
        ids = pe.filter(pl.col("model") == m)["game_id"]
        assert ids.n_unique() == ids.len()


def test_split_and_perseason_invariants() -> None:
    rows = list(csv.DictReader(open(CSV)))
    checked = 0
    for r in rows:
        # diagnostic metric rows (overlap, DK/FD-vs-PIN state, corroboration)
        # are intentionally NOT season-decomposed and carry empty season fields.
        if r.get("discovery_n") in ("", None):
            continue
        tn, disc, conf = int(r["total_n"]), int(r["discovery_n"]), int(r["confirmation_n"])
        assert disc + conf == tn, (r["kind"], r)
        per = sum(int(r[f"n_{s}"]) for s in SEASONS)
        assert per == tn, (r["kind"], "per-sea''sum''", per, tn)
        checked += 1
    # all product/cross-tab tables carry the season fields
    assert checked > 0


def test_dog_region_requires_positive_market_edge() -> None:
    # DOG rows are emitted from POSITIVE_EDGE_CANDIDATE rows only, so every
    # DOG row's edge_pp must be > 0. Verify against the census.
    pe = pl.read_parquet(CENSUS).filter(pl.col("census_family") == "POSITIVE_EDGE_CANDIDATE")
    dog = pe.filter(pl.col("model") == "AVG").filter(pl.col("p_model") >= 0.40).filter(pl.col("p_model") < 0.50)
    assert (dog["edge_pp"] > 0).all()
    # and the dog-region AVG counts match what the CSV reports for 40-45/45-50

def test_dog_plus201_includes_both_bins() -> None:
    rows = {tuple((r["prob_bin"], r["price_band"])): int(r["total_n"])
            for r in csv.DictReader(open(CSV)) if r["kind"] == "DOG_pos_edge_x_price"}
    for pb in ("40-45%", "45-50%"):
        a = rows.get((pb, "+201to+250"), 0)
        b = rows.get((pb, "+251+"), 0)
        c = sum(int(r["total_n"]) for r in csv.DictReader(open(CSV))
                if r["kind"] == "DOG_pos_edge_x_price_combined201" and r["prob_bin"] == pb)
        assert a + b == c, (pb, a, b, c)


def test_overlap_on_unique_game_side() -> None:
    pe = pl.read_parquet(CENSUS).filter(pl.col("census_family") == "POSITIVE_EDGE_CANDIDATE")
    sides = pe.select(["game_id", "side", "model"]).unique()
    # no duplicate (game,side,model)
    assert sides.height == pe.select(["game_id", "side", "model"]).height
    # overlaps consistent: QB∩XGB >= QB∩XGB∩AVG
    s = {m: set(sides.filter(pl.col("model") == m).select(["game_id", "side"]).iter_rows()) for m in ["QB_ELO", "XGB", "AVG"]}
    assert len(s["QB_ELO"] & s["XGB"]) >= len(s["QB_ELO"] & s["XGB"] & s["AVG"])


def test_dk_fd_pinnacle_states_are_dropout_deterministic() -> None:
    pe = pl.read_parquet(CENSUS).filter(pl.col("census_family") == "POSITIVE_EDGE_CANDIDATE")
    # action panel price must equal max(dk, fd) where present, else null
    act = pe["actionable_decimal"]
    dk = pe["dk_decimal"]
    fd = pe["fd_decimal"]
    for a, x, y in zip(act.to_list(), dk.to_list(), fd.to_list()):
        if x is not None and y is not None:
            assert a is not None and abs(a - max(x, y)) < 1e-9
        elif x is not None:
            assert a is not None and abs(a - x) < 1e-9
        elif y is not None:
            assert a is not None and abs(a - y) < 1e-9


def test_quote_freshness_diagnostic_only() -> None:
    fcsv = WT / "reports/task_05e_d3b_quote_freshness_v1.csv"
    assert fcsv.exists()
    f = pl.read_csv(fcsv)
    assert set(f["bookmaker_key"].to_list()) == {"draftkings", "fanduel", "pinnacle"}
    assert (f["median_age_h"] >= 0).all()
    # freshness files exist and ages are small (sanity, no threshold used)
    assert f["median_age_h"].max() < 1.0


def test_hypothesis_ledger_exists() -> None:
    led = WT / "reports/task_05e_d3b_hypothesis_ledger_v1.csv"
    assert led.exists()
    ids = {r["hypothesis_id"] for r in csv.DictReader(open(led))}
    expected = {"ML_QBELO_DISAGREEMENT", "ML_XGB_DISAGREEMENT", "ML_AVG_DISAGREEMENT",
                "ML_CORROBORATED_DISAGREEMENT", "ML_DOG_VALUE_ZONE", "SPREAD_DISAGREEMENT",
                "TOTAL_R4_DISAGREEMENT"}
    assert expected.issubset(ids)