#!/usr/bin/env python3
"""Task05F locked evaluator consolidation runner.

This is a reproduction/consolidation layer, not a new evaluator candidate.
It composes the already-accepted component probability architectures:

- moneyline: ML V4
- spread: V3
- total: V3

The runner executes the frozen component runners, selects only their accepted
market rows, and fails closed unless the consolidated rows exactly reproduce
the component rows logically.  It does not fit a new probability family, tune
any football model, search any betting bucket, or load sealed 2025 outcomes.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import polars as pl
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEV = [2020, 2021, 2022, 2023, 2024]
SEALED = {2025}
VERSION = "task05f_evaluator_locked_v1"

LOCKED_CONFIG = ROOT / "config" / "task05f_evaluator_locked_v1.yaml"
V3_CONFIG = ROOT / "config" / "task05f_evaluator_rebuild_v3_prereg.yaml"
V4_CONFIG = ROOT / "config" / "task05f_ml_v4_prereg.yaml"
V3_RUNNER = ROOT / "scripts" / "task05f_evaluator_rebuild_v3_runner.py"
V4_RUNNER = ROOT / "scripts" / "task05f_ml_v4_runner.py"


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_yaml(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    return yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()


def _json_read(path: Path) -> Any:
    return json.loads(path.read_text())


def _json_write(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_unsealed(seasons: list[int]) -> None:
    bad = SEALED.intersection({int(x) for x in seasons})
    if bad:
        raise RuntimeError(f"SEALED season requested: {sorted(bad)}")


def _sort_board(df: pl.DataFrame) -> pl.DataFrame:
    return df.sort(
        ["season", "week", "game_id", "market_type", "selected_side", "sportsbook", "line"],
        nulls_last=False,
    )


def _logical_equal(left: pl.DataFrame, right: pl.DataFrame) -> bool:
    """Compare deterministic row content while allowing consolidation null columns."""
    if left.height != right.height:
        return False
    if any(c not in left.columns for c in right.columns):
        return False
    a = _sort_board(left.select(right.columns))
    b = _sort_board(right)
    return a.to_dicts() == b.to_dicts()


def _merge_calibration_states(v3_path: Path, v4_path: Path) -> list[dict[str, Any]]:
    v3_rows = pl.read_ndjson(v3_path).to_dicts()
    v4_rows = pl.read_ndjson(v4_path).to_dicts()
    v3_by_block = {str(r["block"]): r for r in v3_rows}
    v4_by_block = {str(r["block"]): r for r in v4_rows}
    if set(v3_by_block) != set(v4_by_block):
        raise RuntimeError("V3/V4 calibration block sets differ")

    merged: list[dict[str, Any]] = []
    for block in sorted(v3_by_block):
        a = v3_by_block[block]
        b = v4_by_block[block]
        if int(a["current_games"]) != int(b["current_games"]):
            raise RuntimeError(f"component current-game count differs at {block}")
        if int(a["prior_games"]) != int(b["prior_games"]):
            raise RuntimeError(f"component prior-game count differs at {block}")
        merged.append(
            {
                "block": block,
                "current_games": int(a["current_games"]),
                "prior_games": int(a["prior_games"]),
                "moneyline_v4": {
                    k: v
                    for k, v in b.items()
                    if k not in {"block", "current_games", "prior_games"}
                },
                "spread_v3": a["spread"],
                "total_v3": a["total"],
            }
        )
    return merged


def run(root: Path, config_path: Path, out: Path) -> None:
    cfg, config_sha = _read_yaml(config_path)
    _assert_unsealed([int(x) for x in cfg["development_seasons"]])
    if cfg["accepted_probability_architecture"]["moneyline"]["version"] != "ml_v4":
        raise RuntimeError("locked moneyline version is not ml_v4")
    if cfg["accepted_probability_architecture"]["spread"]["version"] != "spread_v3":
        raise RuntimeError("locked spread version is not spread_v3")
    if cfg["accepted_probability_architecture"]["total"]["version"] != "total_v3":
        raise RuntimeError("locked total version is not total_v3")

    v3 = _load_script("task05f_locked_component_v3", V3_RUNNER)
    v4 = _load_script("task05f_locked_component_v4", V4_RUNNER)

    with tempfile.TemporaryDirectory(prefix="task05f_locked_components_") as tmp:
        tmp_root = Path(tmp)
        v3_out = tmp_root / "v3"
        v4_out = tmp_root / "v4"

        v3.run(root, V3_CONFIG, v3_out)
        v4.run(root, V4_CONFIG, v4_out)

        v3_board = pl.read_parquet(v3_out / "full_board.parquet")
        v4_board = pl.read_parquet(v4_out / "full_board.parquet")
        v3_points = v3_board.filter(pl.col("market_type").is_in(["spread", "total"]))
        v4_ml = v4_board.filter(pl.col("market_type") == "moneyline")

        combined = pl.concat([v4_ml, v3_points], how="diagonal_relaxed")
        combined = _sort_board(combined)

        ml_reproduced = _logical_equal(
            combined.filter(pl.col("market_type") == "moneyline"), v4_ml
        )
        points_reproduced = _logical_equal(
            combined.filter(pl.col("market_type").is_in(["spread", "total"])), v3_points
        )
        if not ml_reproduced or not points_reproduced:
            raise RuntimeError(
                f"locked component reproduction failed ml={ml_reproduced} points={points_reproduced}"
            )

        out.mkdir(parents=True, exist_ok=True)
        combined.write_parquet(out / "full_board.parquet", compression="zstd")

        calibration_states = _merge_calibration_states(
            v3_out / "calibration_state_by_block.ndjson",
            v4_out / "calibration_state_by_block.ndjson",
        )
        with (out / "calibration_state_by_block.ndjson").open("w") as fh:
            for row in calibration_states:
                fh.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")

        v3_score = _json_read(v3_out / "scorecard.json")
        v4_score = _json_read(v4_out / "scorecard.json")
        locked_markets = {
            "moneyline": v4_score["moneyline"],
            "spread": v3_score["markets"]["spread"],
            "total": v3_score["markets"]["total"],
        }
        benchmark_metrics = dict(v4_score["benchmark_probability_metrics"])
        benchmark_metrics.update(
            {
                k: v
                for k, v in v3_score["benchmark_probability_metrics"].items()
                if k.startswith("spread_") or k.startswith("total_")
            }
        )

        v4_ev = pl.read_csv(v4_out / "ev_calibration.csv")
        v3_ev = pl.read_csv(v3_out / "ev_calibration.csv").filter(
            pl.col("market_type").is_in(["spread", "total"])
        )
        pl.concat([v4_ev, v3_ev], how="diagonal_relaxed").write_csv(
            out / "ev_calibration.csv"
        )

        frozen_v4 = _json_read(v4_out / "frozen_ml_edge_preservation.json")
        frozen_v3 = _json_read(v3_out / "frozen_edge_preservation.json")
        frozen = dict(frozen_v4)
        frozen.update({k: v for k, v in frozen_v3.items() if k.startswith("SPREAD_")})
        _json_write(out / "frozen_edge_preservation.json", frozen)

        reproduction = {
            "moneyline_source": "task05f_ml_v4",
            "spread_source": "task05f_evaluator_rebuild_v3",
            "total_source": "task05f_evaluator_rebuild_v3",
            "moneyline_rows_equal_v4": ml_reproduced,
            "spread_total_rows_equal_v3": points_reproduced,
            "moneyline_rows": v4_ml.height,
            "spread_total_rows": v3_points.height,
            "locked_rows": combined.height,
            "component_artifact_sha256": {
                "v4_scorecard": _sha256(v4_out / "scorecard.json"),
                "v4_full_board": _sha256(v4_out / "full_board.parquet"),
                "v3_scorecard": _sha256(v3_out / "scorecard.json"),
                "v3_full_board": _sha256(v3_out / "full_board.parquet"),
            },
        }
        _json_write(out / "component_reproduction.json", reproduction)

        scorecard = {
            "version": VERSION,
            "locked_config_sha256": config_sha,
            "development_seasons": DEV,
            "sealed_seasons": [2025],
            "chronology": "expanding prior season-week blocks only",
            "accepted_probability_architecture": {
                market: cfg["accepted_probability_architecture"][market]["version"]
                for market in ("moneyline", "spread", "total")
            },
            "markets": locked_markets,
            "benchmark_probability_metrics": benchmark_metrics,
            "value_semantics": "strict expected_value > 0",
            "play_through": "NOT_YET_LOCKED",
            "component_reproduction": reproduction,
            "promotion_status": "LOCKED_PENDING_PLAY_THROUGH_AND_INDEPENDENT_REVIEW",
        }
        _json_write(out / "scorecard.json", scorecard)
        _json_write(
            out / "provenance.json",
            {
                "version": VERSION,
                "github_sha": os.environ.get("GITHUB_SHA"),
                "scope": "evaluator_only_consolidation",
                "locked_config_path": str(config_path.relative_to(root)),
                "locked_config_sha256": config_sha,
                "component_configs": {
                    "moneyline": str(V4_CONFIG.relative_to(root)),
                    "spread_total": str(V3_CONFIG.relative_to(root)),
                },
                "development_seasons": DEV,
                "sealed_seasons": [2025],
                "new_observation_policy": "OBSERVATIONAL_ONLY_NOT_TUNED",
            },
        )
        _json_write(
            out / "observations.json",
            {
                "label": "OBSERVATIONAL_ONLY_NOT_TUNED",
                "items": [],
                "note": "Locked consolidation performs no new probability fitting or selector/price search beyond the frozen V3/V4 components.",
            },
        )

    print(
        json.dumps(
            {
                "version": VERSION,
                "rows": reproduction["locked_rows"],
                "moneyline_rows_equal_v4": reproduction["moneyline_rows_equal_v4"],
                "spread_total_rows_equal_v3": reproduction["spread_total_rows_equal_v3"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(LOCKED_CONFIG))
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "task05f" / "locked_v1"))
    args = parser.parse_args()
    run(ROOT, Path(args.config), Path(args.out))
