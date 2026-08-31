"""Authorized one-shot 2025 NFL EDGE runtime composition.

Nothing executes at import time.  The CLI authorization gate prepares all
2018-2024 state first, atomically consumes the one-spend marker, and only then
calls :func:`run_authorized_holdout` to open 2025.

This module composes frozen model/evaluator/product seams.  It does not change
football-model, evaluator, selector, staking, Play Through, or market
methodology.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping

import polars as pl

from nfl_edge.backtest.blocks import build_development_blocks
from nfl_edge.features.totals_v1.feature_table import (
    _normalize_pbp_teams_to_canonical,
    _split_pbp_by_game,
)
from nfl_edge.features.totals_v1.game_observations import build_game_observations_with_provenance
from nfl_edge.features.totals_v1.manifest import load_pbp_frames, resolve_artifact_root
from nfl_edge.features.totals_v1.mapping import map_pbp_to_canonical
from nfl_edge.holdout.expected_margin_2025 import predict_expected_margin_block
from nfl_edge.holdout.football_2025 import (
    HoldoutBlock,
    build_holdout_blocks,
    predict_oracle_qb_elo_block,
    reveal_and_update_qb_elo_block,
)
from nfl_edge.holdout.one_shot_2025 import (
    BankrollState,
    ReplayState,
    canonical_json_bytes,
    run_one_shot,
    sha256_json,
)
from nfl_edge.holdout.oracle_qb_game_resolver_2025 import FrozenOracleQBGameResolver2025
from nfl_edge.holdout.product_2025 import build_pre_result_product_block
from nfl_edge.holdout.totals_2025 import predict_ridge_totals_block
from nfl_edge.holdout.totals_features_2025 import (
    bootstrap_totals_state,
    materialize_totals_feature_block,
    reveal_and_commit_totals_block,
)
from nfl_edge.holdout.xgboost_2025 import predict_xgboost_block
from nfl_edge.holdout.xgboost_inputs_2025 import assemble_candidate1_xgboost_surface
from nfl_edge.models.expected_margin import load_all_candidates
from nfl_edge.models.qb_elo import EloState, TeamState, config_from_dict
from nfl_edge.models.qb_elo_config import (
    canonical_config_to_elo_config_input,
    load_qb_elo_canonical_config,
)
from nfl_edge.models.xgboost_contract import QB_FEATURE_COLUMNS
from nfl_edge.recommendation.final_selectors_v1 import ValueSelectorState, advance_value_state
from nfl_edge.recommendation.staking_v1 import cap_slate_stakes, dollar_stake
from nfl_edge.value.contracts import NormalizedOffer
from nfl_edge.value.market_math import american_to_decimal
from nfl_edge.value.wager_economics import (
    Settlement,
    moneyline_settlement,
    spread_settlement,
    total_settlement,
)

ROOT = Path(__file__).resolve().parents[3]
GAMES = ROOT / "data/frozen/games/games_2018_2025.parquet"
FEATURES = ROOT / "data/derived/features_v1/game_features_2018_2025.parquet"
QB_PREGAME = ROOT / "data/derived/features_v1/qb_pregame_features_2018_2025.parquet"
SCHEDULE = ROOT / "data/raw/source_snapshots/v1/schedules_2018_2025_frozen-baseline-v1.parquet"
XGB_DEV = ROOT / "data/derived/features_v1/xgboost_development_2018_2024.parquet"
XGB_CONTRACT = ROOT / "data/modeling/development_v1/xgboost_feature_contract_v1.json"
EXPECTED_MARGIN_PREDICTIONS = ROOT / "data/modeling/development_v1/expected_margin_predictions_2018_2024.parquet"
TOTALS_DEV_MODELING = ROOT / "data/derived/totals_v1_modeling_table_2018_2024.parquet"
ORACLE_GAME = ROOT / "data/derived/oracle_qb_entering_state_2025_v1/oracle_qb_pregame_adjustments_by_game_2025_v1.parquet"
ORACLE_SIDES = ROOT / "data/derived/oracle_qb_entering_state_2025_v1/oracle_qb_entering_state_game_sides_2025_v1.parquet"
OBSERVATIONS_2025 = ROOT / "data/derived/task05c_game_observations_2025_v1/game_observations_2025_v1.jsonl"
QB_ELO_MANIFEST = ROOT / "data/modeling/development_v1/qb_elo_run_manifest_v1.json"
QB_ELO_CONFIG = ROOT / "config/qb_elo_v1.yaml"
EXPECTED_MARGIN_CONFIG = ROOT / "config/expected_margin_v1.yaml"
TASK05F_CONFIG = ROOT / "config/task05f_evaluator_final_v1.yaml"

HISTORICAL_BOARD_SHA256 = "e28f0eb43275fc97c8e36744e032ef401d7659b72854dc5a3aa25236ce1e5dad"
MARKET_CANONICAL_SHA256 = "c8499262388fca13d6dfd0a7da2f891c1989ed601c75b6987067013ce8092a62"
MARKET_GAMES_SHA256 = "e9d4b9a5302a72d32f767a87b52f86e32044118bfb27900fb4c4217d6edd74ef"
MARKET_RUN_ID = 33288564115
MARKET_ARTIFACT_ID = 9725230097
MARKET_ARTIFACT_DIGEST = "sha256:de19ec99fbd65dd00e605beb60c0815eaab6d6a642e98b3c413064bb63b96307"
EXPECTED_GAMES = 285
PROFILES = ("Cautious", "Conservative", "Normal", "Aggressive", "Ultra")

_BASE_META = (
    "game_id", "season", "season_type", "week", "prediction_as_of_utc",
    "scheduled_start_utc", "home_team", "away_team", "neutral_site",
)
_EM_SCHEMA = (
    "game_id", "season", "season_type", "week", "prediction_as_of_utc",
    "home_team", "away_team", "neutral_site", "target_available",
    "home_score", "away_score", "target_margin", "target_home_win", "target_tie",
)


class AuthorizedHoldoutRuntimeError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AuthorizedHoldoutRuntimeError(f"unable to load frozen script: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _task05f():
    return _load_script("authorized_2025_task05f", ROOT / "scripts/task05f_evaluator_final_runner.py")


def _qb_config():
    normalized = load_qb_elo_canonical_config(QB_ELO_CONFIG)
    return config_from_dict(canonical_config_to_elo_config_input(normalized))


def _end_2024_elo_state() -> EloState:
    manifest = json.loads(QB_ELO_MANIFEST.read_text(encoding="utf-8"))
    state_info = dict(manifest.get("state_ledger") or {})
    rel, expected = state_info.get("path"), state_info.get("file_sha256")
    if not rel or not expected:
        raise AuthorizedHoldoutRuntimeError("QB-Elo manifest lacks state-ledger identity")
    path = ROOT / str(rel)
    if _sha256(path) != str(expected):
        raise AuthorizedHoldoutRuntimeError("end-2024 QB-Elo state-ledger hash drift")
    ledger = pl.read_parquet(path)
    required = {"team", "elo_after", "season", "state_update_order"}
    missing = sorted(required - set(ledger.columns))
    if missing:
        raise AuthorizedHoldoutRuntimeError(f"QB-Elo state ledger missing columns: {missing}")
    last = ledger.sort("state_update_order").group_by("team", maintain_order=True).last()
    teams = {
        str(row["team"]): TeamState(
            team=str(row["team"]), rating=float(row["elo_after"]), last_season=int(row["season"])
        )
        for row in last.select("team", "elo_after", "season").to_dicts()
    }
    if not teams:
        raise AuthorizedHoldoutRuntimeError("end-2024 QB-Elo state is empty")
    return EloState(
        teams=teams,
        mean=sum(v.rating for v in teams.values()) / len(teams),
        current_season=2024,
    )


def _development_expected_margin() -> pl.DataFrame:
    predictors = (
        pl.scan_parquet(FEATURES)
        .filter(pl.col("season") <= 2024)
        .select(
            "game_id", "season", "season_type", "week", "prediction_as_of_utc",
            "home_team", "away_team", "neutral_site", "target_available",
            "target_margin", "target_home_win", "target_tie",
        )
    )
    scores = (
        pl.scan_parquet(GAMES)
        .filter(pl.col("season") <= 2024)
        .select("game_id", "home_score", "away_score")
    )
    frame = predictors.join(scores, on="game_id", how="left").collect().sort(
        ["season", "week", "game_id"]
    )
    if frame["home_score"].null_count() or frame["away_score"].null_count():
        raise AuthorizedHoldoutRuntimeError("development score history incomplete")
    return frame.select(list(_EM_SCHEMA))


def _development_totals_state():
    pbp_root = resolve_artifact_root()
    pbp = load_pbp_frames(pbp_root)
    canonical = (
        pl.scan_parquet(GAMES)
        .filter(pl.col("season") <= 2024)
        .select("game_id", "season", "season_type", "week", "away_team", "home_team")
        .collect()
    )
    chronology = (
        pl.scan_parquet(FEATURES)
        .filter(pl.col("season") <= 2024)
        .select("game_id", "season", "season_type", "week", "prediction_as_of_utc")
        .collect()
    )
    blocks = build_development_blocks(chronology)
    mapped = pl.concat(
        [map_pbp_to_canonical(pbp[season], canonical) for season in sorted(pbp)],
        how="vertical_relaxed",
    )
    mapped = _normalize_pbp_teams_to_canonical(mapped)
    per_game = _split_pbp_by_game(mapped)
    game_to_teams = {
        str(row["game_id"]): (str(row["home_team"]), str(row["away_team"]))
        for row in canonical.to_dicts()
    }
    observations = {}
    for block in blocks:
        obs, _ = build_game_observations_with_provenance(
            block_id=block.block_id,
            pbp_frames={gid: per_game[gid] for gid in block.game_ids},
            game_to_teams=game_to_teams,
        )
        observations[block.block_id] = tuple(obs)
    return bootstrap_totals_state(blocks=blocks, observations_by_block=observations), str(pbp_root)


def _historical_board(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise AuthorizedHoldoutRuntimeError(f"historical Task05F board missing: {path}")
    got = _sha256(path)
    if got != HISTORICAL_BOARD_SHA256:
        raise AuthorizedHoldoutRuntimeError(
            f"historical Task05F board SHA {got} != frozen {HISTORICAL_BOARD_SHA256}"
        )
    frame = pl.read_parquet(path)
    if frame.height == 0 or int(frame["season"].max()) > 2024:
        raise AuthorizedHoldoutRuntimeError("historical Task05F board is not development-only")
    return frame.to_dicts()


def _expected_margin_config():
    shared, candidates, _ = load_all_candidates(EXPECTED_MARGIN_CONFIG)
    stable = [candidate for candidate in candidates if candidate.id == "stable"]
    if len(stable) != 1:
        raise AuthorizedHoldoutRuntimeError("Expected Margin stable candidate unavailable")
    return shared, stable[0]


def _xgb_contract() -> tuple[list[str], list[str]]:
    contract = json.loads(XGB_CONTRACT.read_text(encoding="utf-8"))
    features = list(contract["deterministic_ordering"]["feature_order"])
    qb = {f"{side}_qb_{name}" for side in ("home", "away") for name in QB_FEATURE_COLUMNS}
    if len(features) != 132:
        raise AuthorizedHoldoutRuntimeError("XGBoost feature-count drift")
    return features, [column for column in features if column not in qb]


def prepare_development_state(*, historical_board_path: Path) -> dict[str, Any]:
    """Read/bootstrap development-only state before the holdout is opened."""
    task05f = _task05f()
    product_games = task05f.build_inputs(ROOT)
    product_market = task05f.build_market(ROOT, product_games)
    totals_state, pbp_root = _development_totals_state()
    xgb_dev = pl.read_parquet(XGB_DEV)
    if xgb_dev.height == 0 or int(xgb_dev["season"].max()) > 2024:
        raise AuthorizedHoldoutRuntimeError("XGBoost development reference is not pre-2025")
    expected_shared, expected_candidate = _expected_margin_config()
    expected_oos = pl.read_parquet(EXPECTED_MARGIN_PREDICTIONS)
    if expected_oos.height == 0 or int(expected_oos["season"].max()) > 2024:
        raise AuthorizedHoldoutRuntimeError("Expected Margin OOS ledger is not pre-2025")
    qb_config = _qb_config()
    return {
        "task05f": task05f,
        "product_games": product_games,
        "market_index": product_market,
        "prior_board_rows": _historical_board(historical_board_path),
        "totals_state": totals_state,
        "totals_pbp_root": pbp_root,
        "totals_training": pl.read_parquet(TOTALS_DEV_MODELING),
        "xgb_dev": xgb_dev,
        "xgb_history": xgb_dev.clone(),
        "expected_history": _development_expected_margin(),
        "expected_oos": expected_oos.to_dicts(),
        "expected_shared": expected_shared,
        "expected_candidate": expected_candidate,
        "qb_config": qb_config,
        "qb_state": _end_2024_elo_state(),
        "qb_update_order": 0,
        "value_state": ValueSelectorState(),
        "task05f_config_sha": _sha256(TASK05F_CONFIG),
    }


def _market_pair(root: Path) -> tuple[Path, Path]:
    market = list(root.rglob("canonical_book_market_2025.parquet"))
    games = list(root.rglob("canonical_games_2025.parquet"))
    if len(market) != 1 or len(games) != 1:
        raise AuthorizedHoldoutRuntimeError(
            f"expected one canonical 2025 market pair under {root}: {len(market)}/{len(games)}"
        )
    if _sha256(market[0]) != MARKET_CANONICAL_SHA256:
        raise AuthorizedHoldoutRuntimeError("2025 canonical book-market SHA drift")
    if _sha256(games[0]) != MARKET_GAMES_SHA256:
        raise AuthorizedHoldoutRuntimeError("2025 canonical market-games SHA drift")
    return market[0], games[0]


def _market_index_2025(market_path: Path, games_path: Path):
    from nfl_edge.market_data.matching import _NAME_TO_ABBR

    games = pl.read_parquet(games_path)
    if games.height != EXPECTED_GAMES or games["game_id"].n_unique() != EXPECTED_GAMES:
        raise AuthorizedHoldoutRuntimeError("2025 canonical market-game coverage drift")
    sides = {
        str(row["game_id"]): (str(row["home_abbr"]), str(row["away_abbr"]))
        for row in games.select("game_id", "home_abbr", "away_abbr").to_dicts()
    }
    bm = pl.read_parquet(market_path)
    index: dict[Any, list[NormalizedOffer]] = {}
    for row in bm.to_dicts():
        book, key, gid = str(row.get("bookmaker_key") or ""), str(row.get("market_key") or ""), str(row.get("game_id") or "")
        if book not in {"draftkings", "fanduel", "pinnacle"} or key not in {"h2h", "spreads", "totals"}:
            continue
        if key == "totals":
            side = str(row.get("outcome_name") or "").strip().lower()
            if side not in {"over", "under"}:
                continue
        else:
            abbr = _NAME_TO_ABBR.get(str(row.get("outcome_name") or "").strip())
            home, away = sides.get(gid, (None, None))
            side = "home" if abbr == home else "away" if abbr == away else None
            if side is None:
                continue
        market_type = {"h2h": "moneyline", "spreads": "spread", "totals": "total"}[key]
        try:
            offer = NormalizedOffer(
                market_type=market_type,
                side=side,
                book=book,
                price_american=int(row["american_price"]),
                line=None if market_type == "moneyline" else float(row["point"]),
                snapshot_utc=str(row.get("actual_snapshot_timestamp_utc") or row.get("requested_snapshot_timestamp_utc") or ""),
            )
        except (TypeError, ValueError):
            continue
        index.setdefault((gid, market_type, side, book), []).append(offer)
    return index, bm


def _merge_index(target: dict[Any, list[Any]], source: Mapping[Any, list[Any]]) -> None:
    for key, values in source.items():
        target.setdefault(key, []).extend(values)


def _pre_result_frames(feature_cols: list[str], base_features: list[str]):
    # Result/target columns are deliberately not selected from mixed sources.
    selected = list(dict.fromkeys([*_BASE_META, *base_features]))
    game_features = (
        pl.scan_parquet(FEATURES)
        .filter(pl.col("season") == 2025)
        .select(selected)
        .collect()
        .sort("game_id")
    )
    qb = (
        pl.scan_parquet(QB_PREGAME)
        .filter((pl.col("season") == 2025) & (pl.col("candidate_rank") == 1))
        .select("game_id", "season", "side", "candidate_rank", *QB_FEATURE_COLUMNS)
        .collect()
    )
    xgb = assemble_candidate1_xgboost_surface(game_features, qb, season_min=2025, season_max=2025)
    xgb = xgb.with_columns(
        pl.lit(None, dtype=pl.Int8).alias("target_home_win"),
        pl.lit(False).alias("target_available"),
    )
    keep = [c for c in xgb.columns if c in set(feature_cols) | set(_BASE_META) | {"target_home_win", "target_available"}]
    xgb = xgb.select(keep)

    canonical = (
        pl.scan_parquet(GAMES)
        .filter(pl.col("season") == 2025)
        .select("game_id", "season", "season_type", "week", "home_team", "away_team", "roof_type")
        .collect()
    )
    schedule = (
        pl.scan_parquet(SCHEDULE)
        .filter(pl.col("season") == 2025)
        .select("game_id", "away_rest", "home_rest", "surface")
        .collect()
    )
    context = (
        game_features.select("game_id", "prediction_as_of_utc", "scheduled_start_utc", "neutral_site")
        .join(canonical, on="game_id", how="inner", validate="1:1")
        .join(schedule, on="game_id", how="inner", validate="1:1")
        .with_columns(
            pl.lit(False).alias("target_available"),
            pl.lit(None, dtype=pl.Int32).alias("home_score"),
            pl.lit(None, dtype=pl.Int32).alias("away_score"),
            pl.lit(None, dtype=pl.Int32).alias("target_margin"),
            pl.lit(None, dtype=pl.Boolean).alias("target_home_win"),
            pl.lit(None, dtype=pl.Boolean).alias("target_tie"),
            pl.lit(None, dtype=pl.Float64).alias("target_total_points"),
        )
        .sort("game_id")
    )
    if context.height != EXPECTED_GAMES:
        raise AuthorizedHoldoutRuntimeError(f"2025 pre-result context rows={context.height}")
    return context, xgb


def _oracle_sides() -> pl.DataFrame:
    from nfl_edge.features.totals_v1.feature_table import _ORACLE_QB_CONSUMED_COLUMNS
    frame = pl.read_parquet(ORACLE_SIDES, columns=["game_id", "side", *_ORACLE_QB_CONSUMED_COLUMNS])
    if frame.height != EXPECTED_GAMES * 2:
        raise AuthorizedHoldoutRuntimeError("2025 Oracle game-side coverage drift")
    return frame


class _ObservationCursor:
    """Read exactly one chronological block of postgame observations per reveal."""
    def __init__(self, path: Path) -> None:
        self._handle = path.open("r", encoding="utf-8")

    def take(self, block: HoldoutBlock):
        from nfl_edge.features.totals_v1.block_state import GameObservation
        out = []
        for _ in block.game_ids:
            line = self._handle.readline()
            if not line:
                raise AuthorizedHoldoutRuntimeError(f"GameObservation ledger ended inside {block.block_id}")
            row = json.loads(line)
            if str(row.get("block_id")) != block.block_id:
                raise AuthorizedHoldoutRuntimeError(f"GameObservation chronology drift in {block.block_id}")
            updates = {
                str(team): {
                    str(metric): (float(vals[0]), float(vals[1]), int(vals[2]))
                    for metric, vals in metrics.items()
                }
                for team, metrics in dict(row["team_updates"]).items()
            }
            out.append(GameObservation(block_id=block.block_id, game_id=str(row["game_id"]), team_updates=updates))
        if {obs.game_id for obs in out} != set(block.game_ids):
            raise AuthorizedHoldoutRuntimeError(f"GameObservation game identity drift in {block.block_id}")
        return out

    def assert_exhausted(self) -> None:
        if self._handle.readline():
            raise AuthorizedHoldoutRuntimeError("unused future GameObservation rows remain")
        self._handle.close()


def _revealed_block(block: HoldoutBlock, context: pl.DataFrame) -> pl.DataFrame:
    # Called only after run_one_shot has physically frozen the current block.
    scores = (
        pl.scan_parquet(GAMES)
        .filter(pl.col("game_id").is_in(list(block.game_ids)))
        .select("game_id", "home_score", "away_score")
        .collect()
    )
    current = context.filter(pl.col("game_id").is_in(list(block.game_ids)))
    return (
        current.drop("home_score", "away_score", "target_margin", "target_home_win", "target_tie", "target_total_points", "target_available")
        .join(scores, on="game_id", how="inner", validate="1:1")
        .with_columns(
            (pl.col("home_score") - pl.col("away_score")).alias("target_margin"),
            pl.when(pl.col("home_score") == pl.col("away_score")).then(None).otherwise(pl.col("home_score") > pl.col("away_score")).alias("target_home_win"),
            (pl.col("home_score") == pl.col("away_score")).alias("target_tie"),
            (pl.col("home_score") + pl.col("away_score")).cast(pl.Float64).alias("target_total_points"),
            pl.lit(True).alias("target_available"),
        )
        .sort("game_id")
    )


def _market_digest(book_market: pl.DataFrame, block: HoldoutBlock) -> str:
    columns = [c for c in ("game_id", "bookmaker_key", "market_key", "side", "point", "american_price") if c in book_market.columns]
    return sha256_json(book_market.filter(pl.col("game_id").is_in(list(block.game_ids))).sort(columns).to_dicts())


def _settlement(row: Mapping[str, Any], home: int, away: int) -> Settlement:
    market, side = str(row["market_type"]), str(row["selected_side"])
    if market == "moneyline":
        return moneyline_settlement(side, home, away)
    if market == "spread":
        return spread_settlement(side, float(row["line"]), home, away)
    if market == "total":
        return total_settlement(side, float(row["line"]), home, away)
    raise AuthorizedHoldoutRuntimeError(f"unknown market {market!r}")


def _unit_profit(settlement: Settlement, odds: int) -> float:
    if settlement is Settlement.PUSH:
        return 0.0
    if settlement is Settlement.LOSS:
        return -1.0
    return american_to_decimal(odds) - 1.0


def _settle_rows(rows: list[dict[str, Any]], revealed: pl.DataFrame) -> list[dict[str, Any]]:
    outcomes = {str(r["game_id"]): (int(r["home_score"]), int(r["away_score"])) for r in revealed.select("game_id", "home_score", "away_score").to_dicts()}
    out = []
    for source in rows:
        row = dict(source)
        home, away = outcomes[str(row["game_id"])]
        settled = _settlement(row, home, away)
        row["settlement"] = settled.value
        row["realized_profit"] = float(_unit_profit(settled, int(row["american_odds"])))
        out.append(row)
    return out


def _elo_digest(state: EloState) -> str:
    return sha256_json({
        "season": state.current_season,
        "teams": {team: float(value.rating) for team, value in sorted(state.teams.items())},
    })


def _totals_digest(state, block: HoldoutBlock) -> str:
    snap = state.snapshot_for_block(block)
    return sha256_json({
        team: {metric: [float(acc.numerator), float(acc.denominator), int(acc.sample_count)] for metric, acc in sorted(team_state.metrics.items())}
        for team, team_state in sorted(snap.teams.items())
    })


def _state_summary(raw: dict[str, Any], next_block: HoldoutBlock | None) -> dict[str, Any]:
    out = {
        "qb_elo_sha256": _elo_digest(raw["qb_state"]),
        "xgb_prior_rows": int(raw["xgb_history"].height),
        "expected_margin_prior_rows": int(raw["expected_history"].height),
        "expected_margin_oos_rows": len(raw["expected_oos"]),
        "totals_prior_rows": int(raw["totals_training"].height),
        "prior_product_games": len(raw["product_games"]),
        "prior_board_rows": len(raw["prior_board_rows"]),
    }
    if next_block is not None:
        out["totals_state_sha256"] = _totals_digest(raw["totals_state"], next_block)
    return out


def _advance_bankroll(bankroll: BankrollState, exposure: list[dict[str, Any]], revealed: pl.DataFrame, entering_streak: int):
    outcomes = {str(r["game_id"]): (int(r["home_score"]), int(r["away_score"])) for r in revealed.select("game_id", "home_score", "away_score").to_dicts()}
    settlements = {}
    for row in exposure:
        home, away = outcomes[str(row["game_id"])]
        settlements[str(row["offer_key"])] = _settlement(row, home, away)

    values, peaks, drawdowns = dict(bankroll.values), dict(bankroll.peaks), dict(bankroll.max_drawdowns)
    scenario_rows = []
    by_key = {str(row["offer_key"]): row for row in exposure}
    for profile in PROFILES:
        start = float(bankroll.values[profile])
        proposed = [(str(row["offer_key"]), dollar_stake(start, profile, float(row["current_units"]))) for row in exposure]
        stakes = cap_slate_stakes(start, proposed)
        pnl = 0.0
        for key, stake in sorted(stakes.items()):
            row, settled = by_key[key], settlements[key]
            profit = float(stake) * _unit_profit(settled, int(row["american_odds"]))
            pnl += profit
            scenario_rows.append({
                "profile": profile, "offer_key": key, "game_id": str(row["game_id"]),
                "market_type": str(row["market_type"]), "selected_side": str(row["selected_side"]),
                "american_odds": int(row["american_odds"]), "line": row.get("line"),
                "stake_dollars": float(stake), "settlement": settled.value,
                "profit_dollars": float(profit), "starting_bankroll": start,
            })
        end = start + pnl
        peak = max(float(bankroll.peaks[profile]), end)
        dd = 0.0 if peak <= 0 else max(0.0, (peak - end) / peak)
        values[profile], peaks[profile] = float(end), float(peak)
        drawdowns[profile] = max(float(bankroll.max_drawdowns[profile]), float(dd))

    record = {"wins": 0, "losses": 0, "pushes": 0}
    weighted, streak, longest = 0.0, int(entering_streak), int(entering_streak)
    labels = {Settlement.WIN: "wins", Settlement.LOSS: "losses", Settlement.PUSH: "pushes"}
    for row in sorted(exposure, key=lambda x: (str(x["game_id"]), str(x["offer_key"]))):
        settled = settlements[str(row["offer_key"])]
        record[labels[settled]] += 1
        weighted += float(row["current_units"]) * _unit_profit(settled, int(row["american_odds"]))
        if settled is Settlement.LOSS:
            streak += 1
            longest = max(longest, streak)
        elif settled is Settlement.WIN:
            streak = 0
    return BankrollState(values=values, peaks=peaks, max_drawdowns=drawdowns), scenario_rows, record, float(weighted), streak, longest


def _csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col) for col in columns})


def _final_outputs(output: Path, blocks: list[HoldoutBlock], raw: dict[str, Any], state: ReplayState, proof: list[dict[str, Any]], provenance: dict[str, Any]) -> None:
    headlines, weekly, scenarios = raw["headline_rows"], raw["weekly_rows"], raw["scenario_rows"]
    _csv(output / "holdout_headline_cards.csv", headlines, ["block_id", "season_type", "week", "lane", "headline_action", "published", "current_units", "game_id", "market_type", "selected_side", "sportsbook", "line", "american_odds", "value_at_price_american", "offer_key"])
    _csv(output / "holdout_weekly_summary.csv", weekly, ["block_id", "season_type", "week", "game_count", "unique_wagers", "wins", "losses", "pushes", "weighted_unit_profit"])
    lanes = []
    for lane in ("hit_rate", "balanced", "value"):
        rows = [r for r in headlines if r["lane"] == lane]
        lanes.append({"lane": lane, "weeks": len(rows), "published": sum(bool(r.get("published")) for r in rows), "no_play": sum(str(r.get("headline_action")) == "NO_PLAY" for r in rows)})
    _csv(output / "holdout_lane_summary.csv", lanes, ["lane", "weeks", "published", "no_play"])
    market_mix = []
    for market in ("moneyline", "spread", "total"):
        rows = [r for r in raw["settled_exposures"] if r["market_type"] == market]
        market_mix.append({"market_type": market, "wagers": len(rows), "wins": sum(r["settlement"] == "WIN" for r in rows), "losses": sum(r["settlement"] == "LOSS" for r in rows), "pushes": sum(r["settlement"] == "PUSH" for r in rows)})
    _csv(output / "holdout_market_mix.csv", market_mix, ["market_type", "wagers", "wins", "losses", "pushes"])
    bankroll = [{"profile": p, "starting_bankroll": 1000.0, "ending_bankroll": float(state.bankroll.values[p]), "return_pct": (float(state.bankroll.values[p]) / 1000.0 - 1.0) * 100.0, "maximum_drawdown_pct": float(state.bankroll.max_drawdowns[p]) * 100.0} for p in PROFILES]
    _csv(output / "holdout_bankroll_scenarios.csv", bankroll, ["profile", "starting_bankroll", "ending_bankroll", "return_pct", "maximum_drawdown_pct"])
    _csv(output / "holdout_scenario_ledger.csv", scenarios, ["block_id", "week", "profile", "offer_key", "game_id", "market_type", "selected_side", "american_odds", "line", "stake_dollars", "settlement", "profit_dollars", "starting_bankroll"])
    integrity = {
        "schema_version": "task05g_2025_product_integrity_v1", "blocks": len(blocks), "games": EXPECTED_GAMES,
        "dead_zero_dollar_headlines": sum(bool(r.get("published")) and float(r.get("current_units") or 0.0) <= 0.0 for r in headlines),
        "duplicate_wagers_not_additive": True, "full_board_output_preserved_per_week": True,
        "same_block_outcomes_available_to_predictions": False,
    }
    (output / "holdout_product_integrity.json").write_bytes(canonical_json_bytes(integrity))
    (output / "holdout_provenance.json").write_bytes(canonical_json_bytes(provenance))
    report = {
        "schema_version": "task05g_2025_acceptance_report_v1", "holdout_season": 2025,
        "blocks": len(blocks), "games": EXPECTED_GAMES, "record": dict(state.record),
        "weighted_unit_profit": float(state.weighted_units), "longest_losing_streak": int(state.longest_losing_streak),
        "bankroll": bankroll, "integrity": integrity, "weekly_state_hash_manifest_blocks": len(proof),
        "interpretation": {"every_lane_profitable_required": False, "positive_one_season_roi_proves_durable_edge": False, "negative_one_season_roi_proves_defect": False, "post_result_retuning": "prohibited"},
    }
    (output / "holdout_acceptance_report.json").write_bytes(canonical_json_bytes(report))


def run_authorized_holdout(*, output_root: Path, market_root: Path, development_state: dict[str, Any], opened_marker_identity: Mapping[str, Any]) -> ReplayState:
    """Run the already-authorized 2025 holdout exactly once."""
    raw = development_state
    market_path, market_games_path = _market_pair(Path(market_root))
    market_2025, book_market = _market_index_2025(market_path, market_games_path)
    _merge_index(raw["market_index"], market_2025)
    feature_cols, base_features = _xgb_contract()
    context, xgb_all = _pre_result_frames(feature_cols, base_features)
    blocks = build_holdout_blocks(context)
    if sum(len(block.game_ids) for block in blocks) != EXPECTED_GAMES:
        raise AuthorizedHoldoutRuntimeError("2025 block inventory does not cover 285 games")

    resolver = FrozenOracleQBGameResolver2025(ORACLE_GAME, repo_root=ROOT)
    resolver.assert_coverage([gid for block in blocks for gid in block.game_ids], where="authorized_2025_schedule")
    oracle_sides = _oracle_sides()
    observation_cursor = _ObservationCursor(OBSERVATIONS_2025)
    raw.update({"pending_models": {}, "pending_product": {}, "pending_revealed": {}, "headline_rows": [], "weekly_rows": [], "scenario_rows": [], "settled_exposures": []})
    initial = ReplayState(model_state=_state_summary(raw, blocks[0]), selector_state={"ml_observations": 0, "spread_observations": 0})

    def market_digest(block):
        return _market_digest(book_market, block)

    def predict(block, state):
        current = context.filter(pl.col("game_id").is_in(list(block.game_ids)))
        current_xgb = xgb_all.filter(pl.col("game_id").is_in(list(block.game_ids)))
        qb = predict_oracle_qb_elo_block(history_games=raw["expected_history"], current_games=current, block=block, state=raw["qb_state"], config=raw["qb_config"], qb_adjustment_resolver=resolver, run_id="task05g_2025_holdout_one_shot_v1")
        xgb = predict_xgboost_block(development_reference=raw["xgb_dev"], prior_history=raw["xgb_history"], current_games=current_xgb, block=block, feature_cols=feature_cols)
        expected = predict_expected_margin_block(history_games=raw["expected_history"], current_games=current.select(list(_EM_SCHEMA)), prior_oos_predictions=raw["expected_oos"], block=block, candidate=raw["expected_candidate"], shared=raw["expected_shared"], run_id="task05g_2025_holdout_one_shot_v1")
        frozen_totals = materialize_totals_feature_block(state=raw["totals_state"], current_games=current, oracle_qb=oracle_sides, block=block)
        totals = predict_ridge_totals_block(prior_history=raw["totals_training"], current_games=frozen_totals.model_frame, block=block)
        qb_by = {str(r["game_id"]): float(r["predicted_home_win_probability"]) for r in qb["predictions"]}
        xgb_by = {} if xgb.get("warmup") else {str(g): float(p) for g, p in zip(xgb["game_ids"], xgb["probabilities"], strict=True)}
        margin_by = {str(r["game_id"]): float(r["expected_home_margin"]) for r in expected["predictions"]}
        total_by = {str(g): float(p) for g, p in zip(totals["game_ids"], totals["predicted_totals"], strict=True)}
        models = {gid: {"qbelo_home": qb_by.get(gid), "xgb_home": xgb_by.get(gid), "expected_home_margin": margin_by.get(gid), "predicted_total": total_by.get(gid)} for gid in block.game_ids}
        raw["pending_models"][block.block_id] = {"qb": qb, "xgb": xgb, "expected": expected, "frozen_totals": frozen_totals, "current_xgb": current_xgb, "game_models": models}
        return {"block_id": block.block_id, "game_models": models, "diagnostics": {"qb_games": len(qb_by), "xgb_warmup": bool(xgb.get("warmup")), "xgb_games": len(xgb_by), "expected_margin_games": len(margin_by), "totals_games": len(total_by)}}

    def candidates(block, state, model):
        current_map = {}
        for row in context.filter(pl.col("game_id").is_in(list(block.game_ids))).select("game_id", "week").to_dicts():
            gid = str(row["game_id"])
            current_map[gid] = {"game_id": gid, "season": 2025, "week": int(row["week"]), **raw["pending_models"][block.block_id]["game_models"][gid], "home_score": None, "away_score": None, "target_margin": None, "target_home_win": None, "target_total_points": None, "target_available": False}
        material = build_pre_result_product_block(root=ROOT, config_sha=raw["task05f_config_sha"], prior_games=raw["product_games"], current_games=current_map, market_index=raw["market_index"], prior_board_rows=raw["prior_board_rows"], value_state=raw["value_state"])
        raw["pending_product"][block.block_id] = material
        return list(material["board_rows"])

    def product(block, state, rows):
        material = raw["pending_product"][block.block_id]
        headlines = [dict(row) for row in material["headlines"]]
        for row in headlines:
            raw["headline_rows"].append({"block_id": block.block_id, "season_type": block.season_type, "week": block.week, **row})
        return ({"block_id": block.block_id, "headlines": headlines}, {"block_id": block.block_id, "week": block.week, "headlines": headlines, "profile_total_risk_reference_1000": material["profile_total_risk"], "unique_exposure_count": len(material["unique_exposure"])})

    def reveal(block, state, bundle):
        revealed = _revealed_block(block, context)
        observations = observation_cursor.take(block)
        material = raw["pending_product"][block.block_id]
        settled_board = _settle_rows([dict(r) for r in material["board_rows"]], revealed)
        settled_exposure = _settle_rows([dict(r) for r in material["unique_exposure"]], revealed)
        raw["pending_revealed"][block.block_id] = {"frame": revealed, "observations": observations, "settled_board": settled_board, "settled_exposure": settled_exposure}
        return {"block_id": block.block_id, "scores": revealed.select("game_id", "home_score", "away_score", "target_margin", "target_total_points").to_dicts(), "settled_board_rows": settled_board, "settled_unique_exposure": settled_exposure}

    def advance(block, state, bundle, result):
        pending, revealed_material = raw["pending_models"][block.block_id], raw["pending_revealed"][block.block_id]
        revealed = revealed_material["frame"]
        qb_update = reveal_and_update_qb_elo_block(frozen_prediction=pending["qb"], revealed_games=revealed, config=raw["qb_config"], run_id="task05g_2025_holdout_one_shot_v1", update_order_start=int(raw["qb_update_order"]))
        raw["qb_state"], raw["qb_update_order"] = qb_update["new_state"], int(qb_update["next_update_order"])
        totals_update = reveal_and_commit_totals_block(frozen=pending["frozen_totals"], state=raw["totals_state"], revealed_games=revealed, observations=revealed_material["observations"])
        raw["totals_training"] = pl.concat([raw["totals_training"], totals_update["graded_model_rows"]], how="diagonal_relaxed")
        xgb_revealed = pending["current_xgb"].drop("target_home_win", "target_available").join(revealed.select("game_id", "target_home_win"), on="game_id", how="left", validate="1:1").with_columns(pl.lit(True).alias("target_available"))
        raw["xgb_history"] = pl.concat([raw["xgb_history"], xgb_revealed], how="diagonal_relaxed")
        raw["expected_history"] = pl.concat([raw["expected_history"], revealed.select(list(_EM_SCHEMA))], how="diagonal_relaxed")
        outcome = {str(r["game_id"]): r for r in revealed.select("game_id", "target_margin", "target_home_win", "target_tie").to_dicts()}
        for source in pending["expected"]["predictions"]:
            row, actual = dict(source), outcome[str(source["game_id"])]
            row.update({"actual_margin": int(actual["target_margin"]), "actual_home_win": actual["target_home_win"], "actual_tie": bool(actual["target_tie"]), "target_available": True})
            raw["expected_oos"].append(row)
        for row in revealed.select("game_id", "week", "home_score", "away_score").to_dicts():
            gid = str(row["game_id"])
            raw["product_games"][gid] = {"game_id": gid, "season": 2025, "week": int(row["week"]), "home_score": int(row["home_score"]), "away_score": int(row["away_score"]), **pending["game_models"][gid]}
        settled_board = list(revealed_material["settled_board"])
        raw["value_state"] = advance_value_state(raw["value_state"], settled_board)
        raw["prior_board_rows"].extend(settled_board)
        raw["settled_exposures"].extend(revealed_material["settled_exposure"])
        next_bankroll, scenario_rows, block_record, block_weighted, streak, longest = _advance_bankroll(state.bankroll, [dict(r) for r in raw["pending_product"][block.block_id]["unique_exposure"]], revealed, state.losing_streak)
        for row in scenario_rows:
            row.update({"block_id": block.block_id, "week": block.week})
        raw["scenario_rows"].extend(scenario_rows)
        total_record = {key: int(state.record[key]) + int(block_record[key]) for key in ("wins", "losses", "pushes")}
        raw["weekly_rows"].append({"block_id": block.block_id, "season_type": block.season_type, "week": block.week, "game_count": len(block.game_ids), "unique_wagers": sum(block_record.values()), **block_record, "weighted_unit_profit": float(block_weighted)})
        index = blocks.index(block)
        next_block = blocks[index + 1] if index + 1 < len(blocks) else None
        return ReplayState(completed_blocks=state.completed_blocks + (block.block_id,), model_state=_state_summary(raw, next_block), selector_state={"ml_observations": len(raw["value_state"].ml_observations), "spread_observations": len(raw["value_state"].spread_observations)}, bankroll=next_bankroll, record=total_record, weighted_units=float(state.weighted_units) + float(block_weighted), losing_streak=int(streak), longest_losing_streak=max(int(state.longest_losing_streak), int(longest)))

    final_state, proof = run_one_shot(blocks=blocks, output_root=output_root, initial_state=initial, market_digest=market_digest, predict=predict, candidates=candidates, product=product, reveal=reveal, advance=advance)
    observation_cursor.assert_exhausted()
    provenance = {
        "schema_version": "task05g_2025_holdout_provenance_v1",
        "market_artifact_run_id": MARKET_RUN_ID, "market_artifact_id": MARKET_ARTIFACT_ID,
        "market_artifact_digest": MARKET_ARTIFACT_DIGEST,
        "canonical_book_market_sha256": MARKET_CANONICAL_SHA256, "canonical_market_games_sha256": MARKET_GAMES_SHA256,
        "historical_task05f_board_sha256": HISTORICAL_BOARD_SHA256, "oracle_resolver": resolver.manifest_identity(),
        "development_pbp_root": raw["totals_pbp_root"], "opened_marker": dict(opened_marker_identity),
        "outcomes_opened_only_after_each_pre_result_freeze": True, "future_game_observations_streamed_before_reveal": False,
        "methodology_changed": False, "tuning_performed": False,
    }
    _final_outputs(output_root, blocks, raw, final_state, proof, provenance)
    return final_state
