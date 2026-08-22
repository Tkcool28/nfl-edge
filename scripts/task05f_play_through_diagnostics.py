#!/usr/bin/env python3
"""Complete preregistered Phase G status-by-reliability diagnostics.

This is report-only. It reads an already-produced Phase G board and writes the
status x reliability cross-tab promised by the Play Through preregistration.
It does not modify candidate rows, statuses, probabilities, or policy.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl


STATUSES = ["VALUE", "PLAYABLE", "LEAN", "PASS"]
RELIABILITY = ["HIGH", "MEDIUM", "LOW", "UNSUPPORTED"]
MARKETS = ["moneyline", "spread", "total"]
SEALED = {2025}


def _mean_or_none(rows: pl.DataFrame, column: str) -> float | None:
    material = rows.filter(pl.col(column).is_not_null())
    if material.height == 0:
        return None
    return float(material[column].mean())


def _roi(rows: pl.DataFrame) -> float | None:
    if rows.height == 0:
        return None
    return float(rows["realized_profit"].mean())


def run(run_dir: Path) -> None:
    board_path = run_dir / "full_board.parquet"
    board = pl.read_parquet(board_path)
    seasons = {int(x) for x in board["season"].unique().to_list()}
    if seasons.intersection(SEALED):
        raise RuntimeError("sealed 2025 row entered Play Through diagnostics")

    rows: list[dict] = []
    for market in MARKETS:
        for status in STATUSES:
            for reliability in RELIABILITY:
                material = board.filter(
                    (pl.col("market_type") == market)
                    & (pl.col("price_status") == status)
                    & (pl.col("reliability") == reliability)
                )
                rows.append(
                    {
                        "market_type": market,
                        "status": status,
                        "reliability": reliability,
                        "n": material.height,
                        "realized_roi": _roi(material),
                        "mean_strict_ev": _mean_or_none(material, "expected_value"),
                        "mean_play_through_concession": _mean_or_none(
                            material, "play_through_break_even_concession"
                        ),
                    }
                )

    pl.DataFrame(rows, infer_schema_length=None).write_csv(
        run_dir / "status_by_reliability.csv"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    args = parser.parse_args()
    run(Path(args.run_dir))
