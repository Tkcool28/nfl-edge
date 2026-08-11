import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/derived/oracle_qb_entering_state_v2"


def test_artifacts():
    s = pl.read_parquet(OUT / "oracle_qb_entering_state_game_sides_2018_2024_v2.parquet")
    g = pl.read_parquet(OUT / "oracle_qb_pregame_adjustments_by_game_2018_2024_v2.parquet")
    r = json.loads((OUT / "oracle_qb_entering_state_validation_report_v2.json").read_text())

    assert s.height == 3884
    assert s.select("game_id", "team_side").unique().height == 3884
    assert g.height == 1942
    assert g.select("game_id").n_unique() == 1942

    # both adjustment columns non-null.
    assert g["away_qb_adjustment_elo"].null_count() == 0
    assert g["home_qb_adjustment_elo"].null_count() == 0
    # both adjustment columns within [-50, +50].
    for col in ("away_qb_adjustment_elo", "home_qb_adjustment_elo"):
        assert g[col].min() >= -50.0
        assert g[col].max() <= 50.0

    # net == home - away within strict tolerance.
    net_diff = g["oracle_qb_adjustment_net"] - (g["home_qb_adjustment_elo"] - g["away_qb_adjustment_elo"])
    assert net_diff.abs().max() < 1e-12

    assert all(
        r[k] == 0
        for k in [
            "measured_target_game_source_rows_used",
            "measured_same_canonical_block_source_rows_used",
            "measured_future_availability_rows_used",
            "measured_2025_source_rows_used",
        ]
    )
    assert (
        r["season_game_counts"]
        == {"2018": 267, "2019": 267, "2020": 269, "2021": 285, "2022": 284, "2023": 285, "2024": 285}
        and r["postseason_games"] == 87
    )
    h = s.filter((pl.col("game_id") == "2020_12_NO_DEN") & (pl.col("team_side") == "home")).to_dicts()[0]
    assert (
        h["actual_starting_qb_gsis_id"] == "00-0035864"
        and bool(h["semantic_exception_flag"])
        and r["kendall_hinton"]["eligible_prior_qb_source_rows"] == 0
    )
