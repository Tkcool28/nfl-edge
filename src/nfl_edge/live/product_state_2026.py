"""Materialize and load the frozen entering-2026 market/product decision state.

The one-time materializer reproduces the accepted Task05F historical starting
state and board fingerprints used by the standard 2025 evaluation, then carries
forward the already-published prospective V2 2025 evidence into an entering-2026
state. Ordinary live refreshes load the resulting JSON and perform no
evaluator/confidence fitting.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import zipfile
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import polars as pl
import sklearn

from nfl_edge.holdout import product_2025
from nfl_edge.live.week11_flex_2026 import FLEX_GAMES
from nfl_edge.recommendation.final_selectors_v1 import ValueSelectorState, advance_value_state
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
DIAGNOSTIC_ZIP = ARCH_ROOT / "post-v5-v2-all-years-diagnostic.zip"
EXPECTED_TASK05F_HISTORICAL_BOARD_SHA256 = "58302290e4dc98d6db13e8e8a46c148e8c58533b2c9930370262982be06ce2a8"
EXPECTED_TASK05F_FROZEN_STATE_SHA256 = "34ac985835ce4ceb65c6135b07851cd4f7e3ab2cc311315ae11efc773d1aa8c9"
EXPECTED_DIAGNOSTIC_SHA256 = "b38eae4df11dc52fe4fc5aeb87a402abcc8ffb9b60e3f252d56f56c9aef78b41"
ACCEPTED_SCIKIT_LEARN_VERSION = "1.8.0"
SELECTOR_TRUST_START_WEEK = 2


_WEEK9_CHECKPOINT = "b35fb2e0cabb01ef7d829e447c53918c69fe2922c76eabe908bb5c2f7b6cb191"
_WEEK9_GAME_IDS = frozenset(
    f"2026_09_{matchup}" for matchup in (
        "ARI_SEA", "BUF_MIN", "CIN_ATL", "CLE_NO", "DAL_IND",
        "DEN_CAR", "DET_MIA", "GB_NE", "HOU_LAC", "JAX_BAL",
        "LAR_WAS", "LV_SF", "NYG_PHI", "NYJ_KC", "TB_CHI",
    )
)
# Read-only inventory of the original 14 HTTP 401 acquisition failures
# identified by isolated preflight 57b3d6bd-a7e4-4e9c-8c7d-e87a94701a19.
_WEEK9_FAILED_STATUS_SHA256 = {
    "refresh-20261104T000503.538859Z": "cf5a2ecbc11c568b0af1a64cffeea2fec16605a8915a0929e0c30889df764bd0",
    "refresh-20261104T120503.830759Z": "f93c5914493c47cd744f1f20552ee05b6c6689d7b45525d17eb45df1a74fd705",
    "refresh-20261105T000504.032698Z": "e4b395f03780575bb1cceb5ab277e7fb2f44304249b5486ab2c5b0eef22b9241",
    "refresh-20261105T120504.370044Z": "d6e98304925fe0d14d124fbd189a3968951d68cdbd7a0a243ac7f68243e8414f",
    "refresh-20261106T000504.543755Z": "e7b2bc1a4d8b50ab6d696d120c9a5aa2011bc5de96a1f3bdaa11f6bc67884921",
    "refresh-20261106T120505.089715Z": "6277215395a066d6842de543c3222fa2904a8bfaa50754321d425e5747746e08",
    "refresh-20261107T000504.408016Z": "c22f92ad372899ac4505425d8b8e8b06635e1b1432efcc0535e2c39cc8a93358",
    "refresh-20261107T120504.539312Z": "fe1bfbbf5f0d8193926038d8286dcdadad026f3aeeb58a5306f7659435abd6fc",
    "refresh-20261108T000504.164262Z": "313efcdf65d0fef2f5290e05736ec2a9630758ec170e9133c83b6a46e89258a3",
    "refresh-20261108T120504.235225Z": "ae6e19a02fd4a0ab10f7f061caf50e0ffe695d852e9c509f8f01dd2050b5941b",
    "refresh-20261109T000504.577736Z": "202ed5a6da7ca9f183214e20b8276c7b1191508f075580daf8d3559b226db691",
    "refresh-20261109T120503.902418Z": "40bfa8c056922ec19e8181d6e4fae78b3af4ce7da4ed71a81f8a5180e99d14f0",
    "refresh-20261110T000503.882715Z": "797900676f2861f5b50c378f9af2af921f4686819ff0f0230d554e4434410d84",
    "refresh-20261110T120504.007935Z": "19856038ae1161b1587fb6f1937b7fb104c47492573c408e78e8cd22012141b6",
}


_WEEK10_CHECKPOINT = "28066c8c30623acc93f95df5814d2fc6aec1d026c49dc9e8d6660c7142070173"
_WEEK10_EXCLUDED_GAME = "2026_10_WAS_NYG"
_WEEK10_KICKOFFS = {
    "2026_10_BUF_NYJ": "2026-11-15T18:00:00Z",
    "2026_10_CAR_NO": "2026-11-15T18:00:00Z",
    "2026_10_HOU_CLE": "2026-11-15T18:00:00Z",
    "2026_10_JAX_TEN": "2026-11-15T18:00:00Z",
    "2026_10_KC_ATL": "2026-11-15T18:00:00Z",
    "2026_10_LAC_BAL": "2026-11-17T01:15:00Z",
    "2026_10_LAR_ARI": "2026-11-15T21:05:00Z",
    "2026_10_MIA_IND": "2026-11-15T18:00:00Z",
    "2026_10_MIN_GB": "2026-11-15T18:00:00Z",
    "2026_10_NE_DET": "2026-11-15T14:30:00Z",
    "2026_10_PIT_CIN": "2026-11-16T01:20:00Z",
    "2026_10_SEA_LV": "2026-11-15T21:05:00Z",
    "2026_10_SF_DAL": "2026-11-15T21:25:00Z",
    "2026_10_WAS_NYG": "2026-11-13T01:15:00Z",
}
# Original production run-status and deterministic-proof SHA-256 values.
# The nine football-state failures had no deterministic product proof.
_WEEK10_RUN_HASHES = {
    "refresh-20261111T000503.973105Z": (
        "3d7c43ce14c44b1f0408f9eaee9d8189bb897ec6348dd0ae55b906a84b0db0f4",
        None,
    ),
    "refresh-20261111T120503.847881Z": (
        "7c0a33f643a02932a4357a854e1338c37b8727af4a5fb6cf847e9c355785e423",
        None,
    ),
    "refresh-20261112T000503.893432Z": (
        "1f11da046f42a4437bd50dc3c259789080478b0c5132765e28ef2974b42e6344",
        None,
    ),
    "refresh-20261112T120503.955761Z": (
        "fa87c09c4259778a1ae1d692ff8d771a8821f9b417764bce264539c4631f0b4c",
        None,
    ),
    "refresh-20261113T000503.858360Z": (
        "260d3e3d924640246541af79afe94230314687ce4d63b934292fc335c9be334e",
        None,
    ),
    "refresh-20261113T120503.993233Z": (
        "4e3bac91e6aa798bebd15b4a34eca4fa2a179a114737fd98ede02b13526e0971",
        None,
    ),
    "refresh-20261114T000504.083825Z": (
        "cc16196c344af3f90e40632ba4b741a15a7682c2d1317200c5d62099f9c51012",
        None,
    ),
    "refresh-20261114T120504.271445Z": (
        "fb09dddee524c53055a3e6817db02fe8acf1abf0a672e40b91c088a8e79bfcbe",
        None,
    ),
    "refresh-20261115T000503.493466Z": (
        "76d208d6bf6d02aaff55091f367585ec70c7ca59f73f04fe05f312cc29379a13",
        None,
    ),
    "refresh-20261115T120503.492203Z": (
        "b207fd8c68048078699169b7494700bf84f0d18632ade92a8872531781845c9d",
        "3a70588704b94abe2d15fce7e17f78e9e37a32c33fc37e37d1b9ed70b10bb051",
    ),
    "refresh-20261116T000503.421702Z": (
        "d372fa9dbbebde08d181237c24c7978323e3f2941d3f7e897e2365fdf054ff38",
        "ab36b44302603edb69598ea67a8aa50f1b899ba5b8766b977833161f82e7add7",
    ),
    "refresh-20261116T120503.369973Z": (
        "1a0ebc445568d2144d04f7856b5132af91d0e6748bfd67bc48fd82eefa99cd4b",
        "55987812a3f33a9b121ec9dccdc82d0b947869be09de124a9e8fd1c8345e39c3",
    ),
    "refresh-20261117T000503.332182Z": (
        "91918b3b3d8dc33a4ba1ae5d62b25d32696a4843ba6e3cc705378db606124e56",
        "fe2a9c76f505b23f533fdc01dfa8c584a205ce374916320a057e845a1b5d67b9",
    ),
    "refresh-20261117T120503.333058Z": (
        "3236593ebf1775bed9be60ccfd54fea7a3d759071fa5f206f441e19b4b1dfb1d",
        "787c1eaba6cee6d30b3b143f7a2fcea9d406dce9c558c6f806ebfae2b25d9fdd",
    ),
}


class Entering2026ProductStateError(RuntimeError):
    """Raised when accepted historical evidence cannot reproduce frozen state."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _selector_state_sha256(state: ValueSelectorState) -> str:
    return hashlib.sha256(
        json.dumps(asdict(state), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


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


def _materialize_task05f_starting_evidence(
    root: Path, task05f: Any
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Reproduce the exact Task05F state/board used to open standard 2025."""
    with tempfile.TemporaryDirectory(prefix="nfl-edge-task05f-start-") as tmp:
        out = Path(tmp)
        # The accepted standard 2025 workflow performs this same materialization
        # before execution. Suppress the runner scorecard here so this one-time
        # state materializer emits only its own bounded status output.
        with contextlib.redirect_stdout(io.StringIO()):
            task05f.run(
                root,
                root / "config/task05f_evaluator_final_v1.yaml",
                out,
            )
        board_path = out / "historical_evaluator_board.parquet"
        state_path = out / "frozen_evaluator_state.json"
        board_sha = _sha256(board_path)
        state_sha = _sha256(state_path)
        if board_sha != EXPECTED_TASK05F_HISTORICAL_BOARD_SHA256:
            raise Entering2026ProductStateError(
                "accepted Task05F historical board SHA drift: "
                f"{board_sha} != {EXPECTED_TASK05F_HISTORICAL_BOARD_SHA256}"
            )
        if state_sha != EXPECTED_TASK05F_FROZEN_STATE_SHA256:
            raise Entering2026ProductStateError(
                "accepted Task05F frozen state SHA drift: "
                f"{state_sha} != {EXPECTED_TASK05F_FROZEN_STATE_SHA256}"
            )
        board = pl.read_parquet(board_path).to_dicts()
        frozen = json.loads(state_path.read_text(encoding="utf-8"))
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

    historical_board, frozen_2024 = _materialize_task05f_starting_evidence(root, task05f)
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
            "task05f_historical_board_sha256": EXPECTED_TASK05F_HISTORICAL_BOARD_SHA256,
            "task05f_frozen_state_sha256": EXPECTED_TASK05F_FROZEN_STATE_SHA256,
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
            "task05f_starting_state_parity": "PASS",
            "historical_market_source": "accepted Task05F canonical repository market files",
            "accepted_2025_training_source": "post-V5 V2 settled evaluator rows",
            "accepted_2025_advancement": "CAUSAL_PROSPECTIVE",
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


def _parse_utc(value: object) -> datetime:
    text = str(value)
    if not text.endswith("Z"):
        raise Entering2026ProductStateError(f"selector evidence timestamp is not UTC Z: {text!r}")
    return datetime.fromisoformat(text[:-1] + "+00:00").astimezone(timezone.utc)


def _game_week(row: Mapping[str, Any]) -> int:
    value = row.get("week")
    if value is not None:
        return int(value)
    game_id = str(row.get("game_id") or "")
    try:
        return int(game_id.split("_")[1])
    except (IndexError, ValueError) as exc:
        raise Entering2026ProductStateError(
            f"selector evidence game has no usable week identity: {game_id!r}"
        ) from exc


def _final_pregame_selector_rows(
    *,
    run_root: Path,
    week: int,
    required_game_ids: set[str],
    successful_proofs: Iterable[tuple[Path, Mapping[str, Any]]] | None = None,
    selected_runs: dict[str, str] | None = None,
) -> list[dict[str, Any]] | None:
    """Assemble one final causal selector board from per-game pre-kickoff states.

    Production refreshes can occur multiple times while a weekly slate is still
    open. For each game independently, choose the latest successful native
    selector-evidence snapshot captured strictly before that game kickoff.
    Rows from the chosen snapshots are assembled into one settled-week board.
    advance_value_state still contributes at most one moneyline-family and one
    spread-family frontier observation for the completed week. Only Week 9
    returns None for zero coverage so the separately verified outage can be checked.
    """
    latest_by_game: dict[str, tuple[datetime, str, list[dict[str, Any]]]] = {}

    if successful_proofs is None:
        successful_proofs = _successful_selector_proofs(run_root)
    for proof_path, payload in successful_proofs:
        selector = payload.get("selector_evidence")
        if not isinstance(selector, Mapping):
            # Selector trust begins prospectively in Week 2. Pre-PR131 Week 1
            # products are intentionally not reconstructed or backfilled.
            continue
        if selector.get("schema_version") != "NFL_EDGE_LIVE_SELECTOR_EVIDENCE_V1":
            continue
        if int(selector.get("week", -1)) != week:
            continue

        if week == 9 and selector.get("season") != 2026:
            raise Entering2026ProductStateError(f"Week 9 selector season mismatch: {proof_path}")

        rows = selector.get("rows")
        games = selector.get("games")
        if not isinstance(rows, list) or not isinstance(games, list) or not games:
            continue
        if any(not isinstance(row, Mapping) or _game_week(row) != week for row in rows):
            continue

        if week == 9 and any(str(row.get("game_id")) not in required_game_ids for row in rows):
            raise Entering2026ProductStateError(f"Week 9 selector row game mismatch: {proof_path}")

        try:
            captured = _parse_utc(selector["captured_at_utc"])
        except (KeyError, TypeError, ValueError, Entering2026ProductStateError):
            continue

        rows_by_game: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            gid = str(row.get("game_id") or "")
            if gid:
                rows_by_game.setdefault(gid, []).append(dict(row))

        seen_games: set[str] = set()
        valid_games = True
        for game in games:
            if not isinstance(game, Mapping):
                valid_games = False
                break
            gid = str(game.get("game_id") or "")
            if not gid or gid in seen_games:
                valid_games = False
                break
            seen_games.add(gid)
            if week == 9 and gid not in required_game_ids:
                raise Entering2026ProductStateError(f"Week 9 selector game mismatch: {proof_path}")
            try:
                kickoff = _parse_utc(game["kickoff_at_utc"])
            except (KeyError, TypeError, ValueError, Entering2026ProductStateError):
                valid_games = False
                break
            if captured < kickoff and gid in required_game_ids and week == 11 and gid in FLEX_GAMES:
                flex = FLEX_GAMES[gid]
                official_kickoff = _parse_utc(flex.new_utc)
                if kickoff not in {_parse_utc(flex.old_utc), official_kickoff}:
                    raise Entering2026ProductStateError(f"{gid}: unexpected Week 11 proof kickoff: {proof_path}")
                if captured >= official_kickoff:
                    if rows_by_game.get(gid):
                        raise Entering2026ProductStateError(
                            f"{gid}: Week 11 selector rows captured after official kickoff under old schedule: "
                            f"{proof_path}"
                        )
                    continue  # An old empty board after official kickoff cannot supersede an eligible board.
            if captured >= kickoff or gid not in required_game_ids:
                continue
            candidate = (captured, str(proof_path), rows_by_game.get(gid, []))
            previous = latest_by_game.get(gid)
            if previous is None or candidate[:2] > previous[:2]:
                latest_by_game[gid] = candidate

        if not valid_games:
            if week == 9:
                raise Entering2026ProductStateError(f"Week 9 selector game identity is invalid: {proof_path}")
            continue

    missing = sorted(required_game_ids.difference(latest_by_game))
    if missing:
        if week == 9:
            if not latest_by_game:
                return None
            raise Entering2026ProductStateError(
                f"partial Week 9 selector coverage requires review: "
                f"covered={sorted(latest_by_game)} missing={missing}"
            )
        raise Entering2026ProductStateError(
            f"missing successful final pre-kickoff selector evidence for settled Week {week}: {missing}"
        )

    assembled: list[dict[str, Any]] = []
    for gid in sorted(required_game_ids):
        _, proof_path, rows = latest_by_game[gid]
        assembled.extend(rows)
        if selected_runs is not None:
            selected_runs[gid] = Path(proof_path).parents[1].name
    return assembled


def _successful_selector_proofs(run_root: Path) -> Iterable[tuple[Path, Mapping[str, Any]]]:
    for proof_path in sorted(run_root.glob("*/product/deterministic-proof.json")):
        status_path = proof_path.parents[1] / "run-status.json"
        if status_path.is_file() and json.loads(status_path.read_bytes()).get("outcome") == "SUCCESS":
            yield proof_path, json.loads(proof_path.read_bytes())


def _week9_gap_audit(
    *,
    state: ValueSelectorState,
    evidence,
    game_rows: list[dict[str, Any]],
    run_root: Path,
) -> dict[str, Any]:
    # Both live callers have already loaded and advanced validated settled
    # football evidence. Bind this decision to the exact immutable Week 9 slate.
    manifest = getattr(evidence, "manifest", {})
    if (
        manifest.get("season") != 2026
        or manifest.get("schedule_checkpoints", {}).get("9") != _WEEK9_CHECKPOINT
        or {str(row["game_id"]) for row in game_rows} != _WEEK9_GAME_IDS
        or len(game_rows) != len(_WEEK9_GAME_IDS)
        or any(row.get("season") != 2026 or row.get("season_type") != "REG" for row in game_rows)
    ):
        raise Entering2026ProductStateError("Week 9 selector gap has mismatched settled evidence")
    if (len(state.ml_observations), len(state.spread_observations)) != (1, 7):
        raise Entering2026ProductStateError("Week 9 selector gap has mismatched Week 8 selector continuity")

    for run_id, digest in _WEEK9_FAILED_STATUS_SHA256.items():
        run = run_root / run_id
        status = run / "run-status.json"
        if not status.is_file() or _sha256(status) != digest:
            raise Entering2026ProductStateError(f"Week 9 selector outage status missing or changed: {run_id}")
        if any((run / name).exists() for name in ("raw", "market", "product")):
            raise Entering2026ProductStateError(f"Week 9 acquisition artifacts require review: {run_id}")

    for status_path in sorted(run_root.glob("*/run-status.json")):
        if status_path.parent.name in _WEEK9_FAILED_STATUS_SHA256:
            continue
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if str(status.get("week")) == "9":
            raise Entering2026ProductStateError(f"unreviewed Week 9 selector run: {status_path.parent.name}")

    # Inspect proofs even when status is missing or failed. A native or
    # conflicting Week 9 record anywhere in the archive requires review.
    for proof_path in sorted(run_root.glob("*/product/deterministic-proof.json")):
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        selector = proof.get("selector_evidence")
        if isinstance(selector, Mapping) and (
            str(selector.get("week")) == "9" or "2026_09_" in json.dumps(selector)
        ):
            raise Entering2026ProductStateError(
                f"Week 9 selector proof requires review: {proof_path.parents[1].name}"
            )

    state_sha = _selector_state_sha256(state)
    return {
        "reason": "NO_AUTHENTIC_PREGAME_MARKET_OBSERVATION",
        "season": 2026,
        "week": 9,
        "season_type": "REG",
        "settled_game_ids": sorted(_WEEK9_GAME_IDS),
        "schedule_checkpoint_sha256": _WEEK9_CHECKPOINT,
        "failed_acquisition_status_sha256": dict(_WEEK9_FAILED_STATUS_SHA256),
        "accepted_pregame_games": 0,
        "entering_observations": {"moneyline": 1, "spread": 7},
        "observations_appended": {"moneyline": 0, "spread": 0},
        "selector_state_before_sha256": state_sha,
        "selector_state_after_sha256": state_sha,
    }


def _week10_gap_board(
    *,
    evidence,
    game_rows: list[dict[str, Any]],
    run_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # The callers have already validated all settled football artifacts and
    # the checkpoint bundle. Keep this exception scoped to that exact slate.
    manifest = getattr(evidence, "manifest", {})
    settled_ids = {str(row["game_id"]) for row in game_rows}
    if (
        manifest.get("season") != 2026
        or manifest.get("schedule_checkpoints", {}).get("10") != _WEEK10_CHECKPOINT
        or settled_ids != _WEEK10_KICKOFFS.keys()
        or len(game_rows) != len(_WEEK10_KICKOFFS)
        or any(row.get("season") != 2026 or row.get("season_type") != "REG" for row in game_rows)
    ):
        raise Entering2026ProductStateError("Week 10 selector gap has mismatched settled evidence")
    excluded, = (row for row in game_rows if row["game_id"] == _WEEK10_EXCLUDED_GAME)
    if (excluded.get("away_score"), excluded.get("home_score")) != (24, 21):
        raise Entering2026ProductStateError("Week 10 selector gap has mismatched WAS–NYG settlement")
    accepted_ids = settled_ids - {_WEEK10_EXCLUDED_GAME}

    for status_path in sorted(run_root.glob("*/run-status.json")):
        if status_path.parent.name not in _WEEK10_RUN_HASHES:
            status = json.loads(status_path.read_bytes())
            if str(status.get("week")) == "10":
                raise Entering2026ProductStateError(
                    f"unreviewed Week 10 selector status requires review: {status_path.parent.name}"
                )
    for proof_path in sorted(run_root.glob("*/product/deterministic-proof.json")):
        run_id = proof_path.parents[1].name
        if run_id not in _WEEK10_RUN_HASHES:
            selector = json.loads(proof_path.read_bytes()).get("selector_evidence")
            if isinstance(selector, Mapping) and (
                str(selector.get("week")) == "10" or "2026_10_" in json.dumps(selector)
            ):
                raise Entering2026ProductStateError(
                    f"unreviewed Week 10 selector proof requires review: {run_id}"
                )

    proofs = []
    reviewed_runs = {}
    for run_id, (status_sha, proof_sha) in sorted(_WEEK10_RUN_HASHES.items()):
        run = run_root / run_id
        status_path = run / "run-status.json"
        proof_path = run / "product/deterministic-proof.json"
        status_bytes = status_path.read_bytes() if status_path.is_file() else b""
        if hashlib.sha256(status_bytes).hexdigest() != status_sha:
            raise Entering2026ProductStateError(f"Week 10 selector status missing or changed: {run_id}")
        status = json.loads(status_bytes)
        expected_outcome = "SUCCESS" if proof_sha else "FOOTBALL_STATE_NOT_READY"
        if status.get("week") != 10 or status.get("outcome") != expected_outcome:
            raise Entering2026ProductStateError(f"Week 10 selector status conflicts with inventory: {run_id}")
        reviewed_runs[run_id] = {"status_sha256": status_sha, "proof_sha256": proof_sha}
        if proof_sha is None:
            if proof_path.exists():
                raise Entering2026ProductStateError(f"Week 10 unexpected selector proof requires review: {run_id}")
            continue
        if not proof_path.is_file():
            raise Entering2026ProductStateError(f"Week 10 selector proof missing: {run_id}")
        proof_bytes = proof_path.read_bytes()
        if hashlib.sha256(proof_bytes).hexdigest() != proof_sha:
            raise Entering2026ProductStateError(f"Week 10 selector proof changed: {run_id}")
        proof = json.loads(proof_bytes)
        selector = proof["selector_evidence"]
        kickoffs = {game["game_id"]: game["kickoff_at_utc"] for game in selector["games"]}
        if (
            selector.get("season") != 2026
            or selector.get("week") != 10
            or len(selector["games"]) != len(_WEEK10_KICKOFFS)
            or kickoffs != _WEEK10_KICKOFFS
            or _parse_utc(selector["captured_at_utc"]) < _parse_utc(kickoffs[_WEEK10_EXCLUDED_GAME])
            or any(row["game_id"] not in accepted_ids for row in selector["rows"])
        ):
            raise Entering2026ProductStateError(f"Week 10 selector identity or timing requires review: {run_id}")
        reviewed_runs[run_id]["captured_at_utc"] = selector["captured_at_utc"]
        proofs.append((proof_path, proof))

    selected_runs: dict[str, str] = {}
    rows = _final_pregame_selector_rows(
        run_root=run_root,
        week=10,
        required_game_ids=accepted_ids,
        successful_proofs=proofs,
        selected_runs=selected_runs,
    )
    if rows is None or Counter(str(row["game_id"]) for row in rows) != dict.fromkeys(accepted_ids, 6):
        raise Entering2026ProductStateError("Week 10 selector gap requires six authentic evaluator rows per covered game")
    return rows, {
        "reason": "DOCUMENTED_PARTIAL_PREGAME_MARKET_OBSERVATION",
        "season": 2026,
        "season_type": "REG",
        "week": 10,
        "settled_game_ids": sorted(settled_ids),
        "football_settlement_complete": True,
        "excluded_market_observation_game_id": _WEEK10_EXCLUDED_GAME,
        "excluded_game_kickoff_at_utc": _WEEK10_KICKOFFS[_WEEK10_EXCLUDED_GAME],
        "schedule_checkpoint_sha256": _WEEK10_CHECKPOINT,
        "accepted_pregame_game_ids": sorted(accepted_ids),
        "accepted_evaluator_rows": len(rows),
        "reviewed_runs": reviewed_runs,
        "selected_run_by_game": selected_runs,
        "synthetic_market_observations": 0,
    }


def advance_live_value_state(
    *,
    entering: ValueSelectorState,
    evidence,
    run_root: Path,
    repository_root: Path | None = None,
    recovery_audit: list[dict[str, Any]] | None = None,
) -> ValueSelectorState:
    """Advance selector trust prospectively from Week 2 final pregame boards.

    Week 1 is deliberately excluded because the governed native selector-evidence
    contract did not yet exist. Football-model state still advances through Week 1
    independently; only selector-family trust starts RESET/COLD in Week 2.
    """
    del repository_root  # retained for caller compatibility; legacy replay is forbidden.
    state = entering
    settled_games = evidence.games.to_dicts()
    game_rows = {str(row["game_id"]): row for row in settled_games}

    by_week: dict[int, set[str]] = {}
    for gid, row in game_rows.items():
        week = _game_week(row)
        by_week.setdefault(week, set()).add(gid)

    week10_checkpoint = getattr(evidence, "manifest", {}).get("schedule_checkpoints", {}).get("10")
    for week in range(SELECTOR_TRUST_START_WEEK, int(evidence.through_week) + 1):
        required_game_ids = by_week.get(week, set())
        if not required_game_ids:
            raise Entering2026ProductStateError(
                f"settled evidence has no games for selector trust Week {week}"
            )
        week10_audit = None
        if week == 10 and (week10_checkpoint == _WEEK10_CHECKPOINT or required_game_ids & _WEEK10_KICKOFFS.keys()):
            rows, week10_audit = _week10_gap_board(
                evidence=evidence, run_root=run_root,
                game_rows=[row for row in settled_games if _game_week(row) == 10],
            )
        else:
            rows = _final_pregame_selector_rows(
                run_root=run_root,
                week=week,
                required_game_ids=required_game_ids,
            )
        if rows is None:
            audit = _week9_gap_audit(
                state=state, evidence=evidence, run_root=run_root,
                game_rows=[row for row in settled_games if _game_week(row) == 9],
            )
            if recovery_audit is not None:
                recovery_audit.append(audit)
            continue
        settled_rows = []
        for source in rows:
            row = dict(source)
            game = game_rows.get(str(row.get("game_id")))
            if game is None:
                raise Entering2026ProductStateError("selector evidence references non-settled game")
            side = str(row.get("selected_side"))
            market = str(row.get("market_type"))
            home_margin = int(game["home_score"]) - int(game["away_score"])
            if market == "moneyline":
                result = home_margin if side == "home" else -home_margin
            elif market == "spread":
                selected_line = float(row.get("line") or 0.0)
                result = home_margin + selected_line if side == "home" else -home_margin + selected_line
            else:
                continue
            row["settlement"] = "WIN" if result > 0 else "LOSS" if result < 0 else "PUSH"
            settled_rows.append(row)
        previous_state = state
        state = advance_value_state(state, settled_rows)
        if week10_audit is not None:
            before = {
                "moneyline": len(previous_state.ml_observations),
                "spread": len(previous_state.spread_observations),
            }
            after = {"moneyline": len(state.ml_observations), "spread": len(state.spread_observations)}
            if len(settled_rows) != 52 or before != {"moneyline": 1, "spread": 7} or after != {"moneyline": 2, "spread": 8}:
                raise Entering2026ProductStateError("Week 10 selector gap has mismatched selector advancement")
            if recovery_audit is not None:
                week10_audit.update(
                    accepted_market_settlement_rows=len(settled_rows),
                    entering_observations=before,
                    exiting_observations=after,
                    observations_appended={"moneyline": 1, "spread": 1},
                    selector_state_before_sha256=_selector_state_sha256(previous_state),
                    selector_state_after_sha256=_selector_state_sha256(state),
                )
                recovery_audit.append(week10_audit)
    return state
