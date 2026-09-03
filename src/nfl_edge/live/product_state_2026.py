"""Materialize and load the frozen entering-2026 market/product decision state.

The one-time materializer consumes only accepted 2020-2024 evaluator evidence,
the frozen canonical historical market files already used by Task05F, and the
already-published 2025 post-V5 V2 diagnostic artifact. Ordinary live refreshes
load the resulting JSON and perform no evaluator/confidence fitting.
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
import sklearn

from nfl_edge.holdout import product_2025
from nfl_edge.recommendation.final_selectors_v1 import ValueSelectorState
from nfl_edge.value.accepted_calibration import (
    calibrated_market_probability,
    fit_ml_v4,
    fit_point_v3,
    market_implied_mean,
)
from nfl_edge.value.contracts import MoneylineV4State, PointV3State
from nfl_edge.value.reliability import support_feature
from nfl_edge.value.state_io import (
    moneyline_state_from_dict,
    moneyline_state_to_dict,
    point_state_from_dict,
    point_state_to_dict,
    reliability_state_from_dict,
    reliability_state_to_dict,
)
from nfl_edge.value.uncertainty import fit_reliability_state
from nfl_edge.value.wager_economics import line_allows_push

SCHEMA_VERSION = "NFL_EDGE_ENTERING_2026_PRODUCT_STATE_V1"
ARCH_ROOT = Path("reports/architecture_verification/post_v5_v2_2020_2025")
HISTORICAL_ZIP = ARCH_ROOT / "post-v5-v2-historical-e2e.zip"
DIAGNOSTIC_ZIP = ARCH_ROOT / "post-v5-v2-all-years-diagnostic.zip"
EXPECTED_HISTORICAL_SHA256 = "056d349381cf3cf2e2fbe8929c3c5d435d43e0a30be44b8b7febb5f82b9208e0"
EXPECTED_DIAGNOSTIC_SHA256 = "b38eae4df11dc52fe4fc5aeb87a402abcc8ffb9b60e3f252d56f56c9aef78b41"
ACCEPTED_SCIKIT_LEARN_VERSION = "1.8.0"


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


def _read_historical_evidence(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = root / HISTORICAL_ZIP
    got = _sha256(path)
    if got != EXPECTED_HISTORICAL_SHA256:
        raise Entering2026ProductStateError(f"historical evidence SHA drift: {got}")
    with zipfile.ZipFile(path) as zf:
        board = pl.read_parquet(io.BytesIO(zf.read("upstream/historical_evaluator_board.parquet"))).to_dicts()
        frozen = json.loads(zf.read("upstream/frozen_evaluator_state.json"))
    return [dict(row) for row in board], frozen


def _read_2025_evidence(
    root: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[str]]:
    path = root / DIAGNOSTIC_ZIP
    got = _sha256(path)
    if got != EXPECTED_DIAGNOSTIC_SHA256:
        raise Entering2026ProductStateError(f"2025 diagnostic evidence SHA drift: {got}")
    games: dict[str, dict[str, Any]] = {}
    settled: list[dict[str, Any]] = []
    blocks: list[str] = []
    with zipfile.ZipFile(path) as zf:
        week_results = sorted(name for name in zf.namelist() if name.endswith("/week_result.json"))
        for result_name in week_results:
            prefix = result_name[: -len("week_result.json")]
            model_name = prefix + "model_output.json"
            result = json.loads(zf.read(result_name))
            model = json.loads(zf.read(model_name))
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
            settled.extend(_with_legacy_aliases(row) for row in result["settled_board_rows"])
    unique_blocks = sorted(set(blocks))
    if len(games) != 285:
        raise Entering2026ProductStateError(f"accepted 2025 evidence game count={len(games)} expected=285")
    if len(unique_blocks) != 22 or "2025_SB_W22" not in unique_blocks:
        raise Entering2026ProductStateError(
            f"accepted 2025 block inventory drift: count={len(unique_blocks)} terminal={'2025_SB_W22' in unique_blocks}"
        )
    return games, settled, unique_blocks


def _training_material_2025(
    games: Mapping[str, Mapping[str, Any]],
    settled_rows: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int, int]:
    """Recover exact Task05F training observations exposed by accepted settled rows."""
    canonical = {"moneyline": "home", "spread": "home", "total": "over"}
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for source in settled_rows:
        row = _with_legacy_aliases(source)
        market = str(row.get("market_type") or "").lower()
        gid = str(row.get("game_id") or "")
        if market not in canonical or _side(row) != canonical[market] or gid not in games:
            continue
        by_key.setdefault((market, gid), row)

    ml: list[dict[str, Any]] = []
    spread: list[dict[str, Any]] = []
    total: list[dict[str, Any]] = []
    ties = 0
    for gid, game in sorted(games.items()):
        home_score = int(game["home_score"])
        away_score = int(game["away_score"])
        if home_score == away_score:
            ties += 1
        ml_row = by_key.get(("moneyline", gid))
        if (
            home_score != away_score
            and ml_row is not None
            and game.get("qbelo_home") is not None
            and game.get("xgb_home") is not None
            and ml_row.get("pinnacle_anchor_probability") is not None
        ):
            ml.append(
                {
                    "qb": float(game["qbelo_home"]),
                    "xgb": float(game["xgb_home"]),
                    "pin": float(ml_row["pinnacle_anchor_probability"]),
                    "y": int(home_score > away_score),
                }
            )
        spread_row = by_key.get(("spread", gid))
        if (
            spread_row is not None
            and game.get("expected_home_margin") is not None
            and spread_row.get("pinnacle_anchor_threshold") is not None
            and spread_row.get("pinnacle_anchor_probability") is not None
        ):
            threshold = float(spread_row["pinnacle_anchor_threshold"])
            spread.append(
                {
                    "model": float(game["expected_home_margin"]),
                    "threshold": threshold,
                    "q": float(spread_row["pinnacle_anchor_probability"]),
                    "push": line_allows_push(threshold),
                    "actual": float(home_score - away_score),
                }
            )
        total_row = by_key.get(("total", gid))
        if (
            total_row is not None
            and game.get("predicted_total") is not None
            and total_row.get("pinnacle_anchor_threshold") is not None
            and total_row.get("pinnacle_anchor_probability") is not None
        ):
            threshold = float(total_row["pinnacle_anchor_threshold"])
            total.append(
                {
                    "model": float(game["predicted_total"]),
                    "threshold": threshold,
                    "q": float(total_row["pinnacle_anchor_probability"]),
                    "push": line_allows_push(threshold),
                    "actual": float(home_score + away_score),
                }
            )
    return ml, spread, total, ties, len(games)


def _fit_states_from_material(
    *,
    ml_rows: list[dict[str, Any]],
    spread_rows: list[dict[str, Any]],
    total_rows: list[dict[str, Any]],
    ties: int,
    completed: int,
    config_sha: str,
) -> tuple[MoneylineV4State | None, PointV3State | None, PointV3State | None, dict[str, Any]]:
    """Call the exact frozen Task05F calibration functions on accepted observations."""
    ml_fit = fit_ml_v4([(r["qb"] + r["xgb"]) / 2.0, r["pin"], r["y"]] for r in ml_rows)
    spread_fit = fit_point_v3(
        [(r["model"], r["threshold"], r["q"], r["push"], r["actual"]) for r in spread_rows]
    )
    total_fit = fit_point_v3(
        [(r["model"], r["threshold"], r["q"], r["push"], r["actual"]) for r in total_rows]
    )

    ml_state: MoneylineV4State | None = None
    if ml_fit.supported:
        extremity: list[float] = []
        model_gap: list[float] = []
        constituent_gap: list[float] = []
        for row in ml_rows:
            p_model = (row["qb"] + row["xgb"]) / 2.0
            p_market = calibrated_market_probability(row["pin"], ml_fit)
            extremity.append(abs(p_market - 0.5))
            model_gap.append(abs(p_model - p_market))
            constituent_gap.append(abs(row["qb"] - row["xgb"]))
        ml_state = MoneylineV4State(
            market_intercept=float(ml_fit.market_intercept),
            market_slope=float(ml_fit.market_slope),
            model_weight=float(ml_fit.model_weight),
            training_n=int(ml_fit.support_n),
            prior_ties=int(ties),
            prior_games=int(completed),
            support_features=(
                support_feature("pinnacle_extremity", extremity),
                support_feature("model_market_gap", model_gap),
                support_feature("constituent_gap", constituent_gap),
            ),
            config_sha256=config_sha,
            version="ml_v4",
        )

    def point_state(market: str, rows: list[dict[str, Any]], fit: Any) -> PointV3State | None:
        if not fit.supported:
            return None
        model_gap: list[float] = []
        threshold_mag: list[float] = []
        for row in rows:
            mu_market = market_implied_mean(
                row["threshold"],
                row["q"],
                float(fit.sigma),
                push_possible=row["push"],
            )
            model_gap.append(abs(row["model"] - mu_market))
            threshold_mag.append(abs(row["threshold"]))
        return PointV3State(
            market_type=market,
            sigma=float(fit.sigma),
            beta=float(fit.beta),
            residuals=tuple(float(value) for value in fit.residuals),
            training_n=int(fit.support_n),
            support_features=(
                support_feature("model_market_gap", model_gap),
                support_feature("anchor_threshold_magnitude", threshold_mag),
            ),
            config_sha256=config_sha,
            version=f"{market}_v3",
        )

    return (
        ml_state,
        point_state("spread", spread_rows, spread_fit),
        point_state("total", total_rows, total_fit),
        {"moneyline": ml_fit, "spread": spread_fit, "total": total_fit},
    )


def materialize_entering_2026_product_state(root: Path) -> dict[str, Any]:
    if sklearn.__version__ != ACCEPTED_SCIKIT_LEARN_VERSION:
        raise Entering2026ProductStateError(
            "entering-2026 state materialization must use the accepted architecture "
            f"scikit-learn runtime {ACCEPTED_SCIKIT_LEARN_VERSION}; got {sklearn.__version__}"
        )

    task05f = _load_script("live_2026_task05f", root / "scripts/task05f_evaluator_final_runner.py")
    confidence_v2 = _load_script("live_2026_confidence_v2", root / "scripts/task05g_model_confidence_v2_runner.py")
    spread_v3 = _load_script("live_2026_spread_v3", root / "scripts/task05g_spread_confidence_v3_runner.py")

    historical_board, frozen_2024 = _read_historical_evidence(root)
    historical_games = task05f.build_inputs(root)
    historical_idx = task05f.build_market(root, historical_games)
    historical_material = task05f._training_material(
        historical_games,
        historical_idx,
        sorted(historical_games),
    )
    config_sha = str(frozen_2024["evaluators"]["moneyline"]["config_sha256"])
    ml_2024, spread_2024, total_2024, _ = _fit_states_from_material(
        ml_rows=list(historical_material[0]),
        spread_rows=list(historical_material[1]),
        total_rows=list(historical_material[2]),
        ties=int(historical_material[3]),
        completed=int(historical_material[4]),
        config_sha=config_sha,
    )
    if ml_2024 is None or spread_2024 is None or total_2024 is None:
        raise Entering2026ProductStateError("reconstructed 2024 Task05F evaluator state is unsupported")
    observed_eval_2024 = {
        "moneyline": moneyline_state_to_dict(ml_2024),
        "spread": point_state_to_dict(spread_2024),
        "total": point_state_to_dict(total_2024),
    }
    _assert_state_parity(observed_eval_2024, frozen_2024["evaluators"], "task05f_2024_evaluators")

    historical_histories = {"moneyline": [], "spread": [], "total": []}
    task05f._history_append(
        historical_histories,
        [_with_legacy_aliases(row) for row in historical_board],
    )
    observed_rel_2024 = {
        market: reliability_state_to_dict(fit_reliability_state(historical_histories[market]))
        for market in historical_histories
    }
    _assert_state_parity(observed_rel_2024, frozen_2024["reliability"], "task05f_2024_reliability")

    games_2025, settled_2025, blocks_2025 = _read_2025_evidence(root)
    material_2025 = _training_material_2025(games_2025, settled_2025)
    ml_rows = [*historical_material[0], *material_2025[0]]
    spread_rows = [*historical_material[1], *material_2025[1]]
    total_rows = [*historical_material[2], *material_2025[2]]
    ties = int(historical_material[3]) + int(material_2025[3])
    completed = int(historical_material[4]) + int(material_2025[4])
    ml, spread, total, fit_diag = _fit_states_from_material(
        ml_rows=ml_rows,
        spread_rows=spread_rows,
        total_rows=total_rows,
        ties=ties,
        completed=completed,
        config_sha=config_sha,
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

    all_games = {str(k): dict(v) for k, v in historical_games.items()}
    all_games.update(games_2025)
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

    if len(all_games) != 1693:
        raise Entering2026ProductStateError(
            f"entering-2026 prior product game count drift: {len(all_games)} != 1693"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "season": 2026,
        "week": 1,
        "source_evidence": {
            "historical_zip": str(HISTORICAL_ZIP),
            "historical_zip_sha256": EXPECTED_HISTORICAL_SHA256,
            "diagnostic_2025_zip": str(DIAGNOSTIC_ZIP),
            "diagnostic_2025_zip_sha256": EXPECTED_DIAGNOSTIC_SHA256,
            "accepted_scikit_learn_version": ACCEPTED_SCIKIT_LEARN_VERSION,
            "historical_games": len(historical_games),
            "accepted_2025_games": len(games_2025),
            "accepted_2025_blocks": len(blocks_2025),
            "terminal_2025_block": "2025_SB_W22",
            "combined_prior_games": len(all_games),
            "combined_prior_board_rows": len(combined_board),
            "reconstructed_2024_state_parity": "PASS",
            "historical_market_source": "canonical Task05F repository market files",
            "accepted_2025_training_source": "post-V5 V2 settled evaluator rows",
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
