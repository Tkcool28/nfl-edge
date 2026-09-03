"""Materialize and load the frozen entering-2026 market/product decision state.

The one-time materializer consumes only accepted 2020-2024 evaluator evidence
and the already-published 2025 post-V5 V2 diagnostic artifact. Ordinary live
refreshes load the resulting JSON and perform no evaluator/confidence fitting.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path
from typing import Any, Iterable, Mapping

import polars as pl

from nfl_edge.holdout import product_2025
from nfl_edge.recommendation.final_selectors_v1 import ValueSelectorState
from nfl_edge.value.contracts import NormalizedOffer
from nfl_edge.value.state_io import (
    moneyline_state_from_dict,
    moneyline_state_to_dict,
    point_state_from_dict,
    point_state_to_dict,
    reliability_state_from_dict,
    reliability_state_to_dict,
)
from nfl_edge.value.uncertainty import fit_reliability_state

SCHEMA_VERSION = "NFL_EDGE_ENTERING_2026_PRODUCT_STATE_V1"
ARCH_ROOT = Path("reports/architecture_verification/post_v5_v2_2020_2025")
HISTORICAL_ZIP = ARCH_ROOT / "post-v5-v2-historical-e2e.zip"
DIAGNOSTIC_ZIP = ARCH_ROOT / "post-v5-v2-all-years-diagnostic.zip"
EXPECTED_HISTORICAL_SHA256 = "056d349381cf3cf2e2fbe8929c3c5d435d43e0a30be44b8b7febb5f82b9208e0"
EXPECTED_DIAGNOSTIC_SHA256 = "b38eae4df11dc52fe4fc5aeb87a402abcc8ffb9b60e3f252d56f56c9aef78b41"


class Entering2026ProductStateError(RuntimeError):
    """Raised when accepted historical evidence cannot reproduce frozen state."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Entering2026ProductStateError(f"unable to load frozen runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _side(row: Mapping[str, Any]) -> str:
    value = row.get("selected_side")
    if value is None:
        value = row.get("selection")
    return str(value or "").lower()


def _line(row: Mapping[str, Any]) -> float | None:
    value = row.get("line")
    if value is None:
        value = row.get("actionable_line")
    return None if value is None else float(value)


def _with_legacy_aliases(row: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(row)
    aliases = (
        ("selected_side", "selection"),
        ("line", "actionable_line"),
        ("american_odds", "actionable_price_american"),
        ("sportsbook", "actionable_book"),
        ("raw_model_output", "raw_football_output"),
    )
    for legacy, canonical in aliases:
        if out.get(legacy) is None and out.get(canonical) is not None:
            out[legacy] = out[canonical]
    return out


def _context_market_index(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str, str], list[NormalizedOffer]]:
    idx: dict[tuple[str, str, str, str], list[NormalizedOffer]] = {}
    seen: set[tuple[Any, ...]] = set()
    for source in rows:
        row = dict(source)
        gid = str(row.get("game_id") or "")
        market = str(row.get("market_type") or "").lower()
        side = _side(row)
        if not gid or market not in {"moneyline", "spread", "total"} or side not in {"home", "away", "over", "under"}:
            continue
        stamp = str(row.get("market_snapshot_timestamp") or "accepted-evidence")
        for book in ("draftkings", "fanduel", "pinnacle"):
            price = row.get(f"{book}_price_american")
            if price is None:
                continue
            line = None if market == "moneyline" else row.get(f"{book}_line")
            if market != "moneyline" and line is None:
                continue
            signature = (gid, market, side, book, line, int(price), stamp)
            if signature in seen:
                continue
            seen.add(signature)
            idx.setdefault((gid, market, side, book), []).append(
                NormalizedOffer(
                    market_type=market,
                    side=side,
                    book=book,
                    price_american=int(price),
                    line=None if line is None else float(line),
                    snapshot_utc=stamp,
                    source="accepted-post-v5-v2-evidence",
                )
            )
    return idx


def _float_close(a: Any, b: Any, *, tol: float = 1e-10) -> bool:
    if a is None or b is None:
        return a is b
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return a == b


def _assert_state_parity(observed: Mapping[str, Any], expected: Mapping[str, Any], path: str) -> None:
    if set(observed) != set(expected):
        raise Entering2026ProductStateError(
            f"{path} key drift: observed={sorted(observed)} expected={sorted(expected)}"
        )
    for key in expected:
        a, b = observed[key], expected[key]
        here = f"{path}.{key}"
        if isinstance(a, Mapping) and isinstance(b, Mapping):
            _assert_state_parity(a, b, here)
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                raise Entering2026ProductStateError(f"{here} length drift: {len(a)} != {len(b)}")
            for i, (x, y) in enumerate(zip(a, b)):
                if isinstance(x, Mapping) and isinstance(y, Mapping):
                    _assert_state_parity(x, y, f"{here}[{i}]")
                elif not _float_close(x, y):
                    raise Entering2026ProductStateError(f"{here}[{i}] drift: {x!r} != {y!r}")
        elif not _float_close(a, b):
            raise Entering2026ProductStateError(f"{here} drift: {a!r} != {b!r}")


def _read_historical_evidence(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    path = root / HISTORICAL_ZIP
    got = _sha256(path)
    if got != EXPECTED_HISTORICAL_SHA256:
        raise Entering2026ProductStateError(f"historical evidence SHA drift: {got}")
    with zipfile.ZipFile(path) as zf:
        candidates = pl.read_parquet(io.BytesIO(zf.read("upstream/candidate_table.parquet"))).to_dicts()
        board = pl.read_parquet(io.BytesIO(zf.read("upstream/historical_evaluator_board.parquet"))).to_dicts()
        frozen = json.loads(zf.read("upstream/frozen_evaluator_state.json"))
    return candidates, board, frozen


def _read_2025_evidence(root: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    path = root / DIAGNOSTIC_ZIP
    got = _sha256(path)
    if got != EXPECTED_DIAGNOSTIC_SHA256:
        raise Entering2026ProductStateError(f"2025 diagnostic evidence SHA drift: {got}")
    games: dict[str, dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []
    settled: list[dict[str, Any]] = []
    blocks: list[str] = []
    with zipfile.ZipFile(path) as zf:
        week_results = sorted(name for name in zf.namelist() if name.endswith("/week_result.json"))
        for result_name in week_results:
            prefix = result_name[: -len("week_result.json")]
            model_name = prefix + "model_output.json"
            candidate_name = prefix + "candidate_table.json"
            result = json.loads(zf.read(result_name))
            model = json.loads(zf.read(model_name))
            current_candidates = json.loads(zf.read(candidate_name))
            block_id = str(result["block_id"])
            blocks.append(block_id)
            score_by_gid = {str(row["game_id"]): dict(row) for row in result["scores"]}
            for gid, outputs in dict(model["game_models"]).items():
                score = score_by_gid[str(gid)]
                week = int(str(gid).split("_")[1])
                games[str(gid)] = {
                    "game_id": str(gid),
                    "season": 2025,
                    "week": week,
                    "qbelo_home": outputs.get("qbelo_home"),
                    "xgb_home": outputs.get("xgb_home"),
                    "expected_home_margin": outputs.get("expected_home_margin"),
                    "predicted_total": outputs.get("predicted_total"),
                    "home_score": int(score["home_score"]),
                    "away_score": int(score["away_score"]),
                }
            candidates.extend(dict(row) for row in current_candidates)
            settled.extend(_with_legacy_aliases(row) for row in result["settled_board_rows"])
    if len(games) != 285:
        raise Entering2026ProductStateError(f"accepted 2025 evidence game count={len(games)} expected=285")
    if len(set(blocks)) != 22:
        raise Entering2026ProductStateError(f"accepted 2025 block count={len(set(blocks))} expected=22")
    return games, candidates, settled, sorted(set(blocks))


def materialize_entering_2026_product_state(root: Path) -> dict[str, Any]:
    task05f = _load_script("live_2026_task05f", root / "scripts/task05f_evaluator_final_runner.py")
    confidence_v2 = _load_script("live_2026_confidence_v2", root / "scripts/task05g_model_confidence_v2_runner.py")
    spread_v3 = _load_script("live_2026_spread_v3", root / "scripts/task05g_spread_confidence_v3_runner.py")

    historical_candidates, historical_board, frozen_2024 = _read_historical_evidence(root)
    historical_games = task05f.build_inputs(root)
    historical_idx = _context_market_index(historical_candidates)
    config_sha = str(frozen_2024["evaluators"]["moneyline"]["config_sha256"])

    ml_2024, spread_2024, total_2024, _ = task05f._fit_states(
        historical_games,
        historical_idx,
        sorted(historical_games),
        config_sha,
    )
    if ml_2024 is None or spread_2024 is None or total_2024 is None:
        raise Entering2026ProductStateError("reconstructed 2024 Task05F evaluator state is unsupported")
    observed_eval_2024 = {
        "moneyline": moneyline_state_to_dict(ml_2024),
        "spread": point_state_to_dict(spread_2024),
        "total": point_state_to_dict(total_2024),
    }
    _assert_state_parity(observed_eval_2024, frozen_2024["evaluators"], "task05f_2024_evaluators")

    histories = {"moneyline": [], "spread": [], "total": []}
    task05f._history_append(histories, [_with_legacy_aliases(row) for row in historical_board])
    observed_rel_2024 = {
        market: reliability_state_to_dict(fit_reliability_state(histories[market]))
        for market in histories
    }
    _assert_state_parity(observed_rel_2024, frozen_2024["reliability"], "task05f_2024_reliability")

    games_2025, candidates_2025, settled_2025, blocks_2025 = _read_2025_evidence(root)
    all_games = {str(k): dict(v) for k, v in historical_games.items()}
    all_games.update(games_2025)
    all_candidates = [*historical_candidates, *candidates_2025]
    all_idx = _context_market_index(all_candidates)

    ml, spread, total, fit_diag = task05f._fit_states(
        all_games,
        all_idx,
        sorted(all_games),
        config_sha,
    )
    if ml is None or spread is None or total is None:
        raise Entering2026ProductStateError("entering-2026 Task05F evaluator state is unsupported")

    combined_board = [*[_with_legacy_aliases(row) for row in historical_board], *settled_2025]
    combined_histories = {"moneyline": [], "spread": [], "total": []}
    task05f._history_append(combined_histories, combined_board)
    reliability = {
        market: fit_reliability_state(combined_histories[market])
        for market in combined_histories
    }

    history_games = product_2025._history_rows(all_games)
    ml_confidence_state = confidence_v2._fit_ml_state(history_games)
    spread_residuals = [
        float(row["margin_residual"])
        for row in history_games
        if row.get("margin_residual") is not None
    ]

    spread_observations: list[dict[str, Any]] = []
    seen_spreads: set[tuple[str, str, float]] = set()
    for row in combined_board:
        if str(row.get("market_type")) != "spread" or str(row.get("settlement")) not in {"WIN", "LOSS"}:
            continue
        gid = str(row.get("game_id"))
        game = all_games.get(gid)
        line = _line(row)
        side = _side(row)
        if game is None or game.get("expected_home_margin") is None or line is None:
            continue
        key = (gid, side, float(line))
        if key in seen_spreads:
            continue
        seen_spreads.add(key)
        spread_observations.append(
            {
                "model_cover_margin": spread_v3._cover_margin(
                    float(game["expected_home_margin"]), side, float(line)
                ),
                "outcome": 1 if str(row["settlement"]) == "WIN" else 0,
            }
        )
    spread_confidence_state = spread_v3._fit_state(spread_observations)

    return {
        "schema_version": SCHEMA_VERSION,
        "season": 2026,
        "week": 1,
        "source_evidence": {
            "historical_zip": str(HISTORICAL_ZIP),
            "historical_zip_sha256": EXPECTED_HISTORICAL_SHA256,
            "diagnostic_2025_zip": str(DIAGNOSTIC_ZIP),
            "diagnostic_2025_zip_sha256": EXPECTED_DIAGNOSTIC_SHA256,
            "historical_games": len(historical_games),
            "accepted_2025_games": len(games_2025),
            "accepted_2025_blocks": len(blocks_2025),
            "combined_prior_games": len(all_games),
            "combined_prior_board_rows": len(combined_board),
            "reconstructed_2024_state_parity": "PASS",
        },
        "task05f": {
            "evaluators": {
                "moneyline": moneyline_state_to_dict(ml),
                "spread": point_state_to_dict(spread),
                "total": point_state_to_dict(total),
            },
            "reliability": {
                market: reliability_state_to_dict(reliability[market])
                for market in ("moneyline", "spread", "total")
            },
            "fit_support_n": {
                market: int(fit_diag[market].support_n)
                for market in ("moneyline", "spread", "total")
            },
        },
        "model_confidence_v2": {
            "moneyline": dict(ml_confidence_state),
            "spread_residuals": spread_residuals,
        },
        "spread_confidence_v3": dict(spread_confidence_state),
        "value_selector_state": {
            "reset_for_new_season": True,
            "ml_observations": 0,
            "spread_observations": 0,
        },
        "methodology_changed": False,
        "evaluator_methodology_changed": False,
        "selector_methodology_changed": False,
        "staking_methodology_changed": False,
    }


def load_entering_2026_product_state(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise Entering2026ProductStateError(
            f"unsupported entering-2026 product state: {payload.get('schema_version')}"
        )
    task = payload["task05f"]
    return {
        "raw": payload,
        "moneyline": moneyline_state_from_dict(task["evaluators"]["moneyline"]),
        "spread": point_state_from_dict(task["evaluators"]["spread"]),
        "total": point_state_from_dict(task["evaluators"]["total"]),
        "reliability": {
            market: reliability_state_from_dict(task["reliability"][market])
            for market in ("moneyline", "spread", "total")
        },
        "ml_confidence": dict(payload["model_confidence_v2"]["moneyline"]),
        "spread_residuals": [
            float(x) for x in payload["model_confidence_v2"]["spread_residuals"]
        ],
        "spread_v3": dict(payload["spread_confidence_v3"]),
        "value_state": ValueSelectorState(),
    }
