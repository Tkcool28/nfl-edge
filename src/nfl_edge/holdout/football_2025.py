"""Authorization-only 2025 football-model block primitives.

This module is deliberately separate from the frozen development walk-forward
engines.  It does not read any files and does not authorize the holdout.  Its
job is to make the eventual one-shot executor mechanically safe once an
already-authorized caller supplies 2025 frames.

The first supported model surface is the accepted historical QB-Elo oracle
walk-through.  "Oracle" is narrow: the actual starter identity may be supplied
for the historical game, exactly as in Task04C, but the current block's score,
margin, winner, tie, and other post-kickoff outcome fields must still be absent
until the block has been predicted and frozen.

The canonical development functions are reused for Elo prediction and update;
no Elo math is reimplemented here.  The development season guards remain
untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import polars as pl

from nfl_edge.backtest.walk_forward import (
    _build_exposure_for_block,
    _predict_block,
    _require_resolver_identity,
    _update_block,
)
from nfl_edge.models.qb_elo import EloConfig, EloState, apply_season_carryover, ensure_team

HOLDOUT_SEASON = 2025
_ST_PRIORITY: dict[str, int] = {"REG": 0, "WC": 1, "DIV": 2, "CON": 3, "SB": 4}
_BLOCK_COLUMNS = {
    "game_id",
    "season",
    "season_type",
    "week",
    "prediction_as_of_utc",
    "home_team",
    "away_team",
    "neutral_site",
}
_OUTCOME_COLUMNS = (
    "target_margin",
    "target_home_win",
    "home_score",
    "away_score",
)


class HoldoutFootballContractError(RuntimeError):
    """Raised before prediction when a sealed-block invariant is violated."""


@dataclass(frozen=True)
class HoldoutBlock:
    """2025-only prediction block that does not weaken development guards."""

    block_id: str
    season: int
    season_type: str
    week: int
    as_of_utc: datetime
    game_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if int(self.season) != HOLDOUT_SEASON:
            raise HoldoutFootballContractError(
                f"holdout block season must be exactly {HOLDOUT_SEASON}: {self.season}"
            )
        if str(self.season_type).upper() not in _ST_PRIORITY:
            raise HoldoutFootballContractError(
                f"unsupported season_type: {self.season_type!r}"
            )
        if not self.game_ids:
            raise HoldoutFootballContractError("holdout block cannot be empty")
        if self.as_of_utc.tzinfo is None or self.as_of_utc.utcoffset() is None:
            raise HoldoutFootballContractError("holdout block as_of_utc must be timezone-aware")

    @property
    def order_key(self) -> tuple[int, int, int]:
        return (
            int(self.season),
            _ST_PRIORITY[str(self.season_type).upper()],
            int(self.week),
        )


def _coerce_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HoldoutFootballContractError(f"naive prediction_as_of_utc: {value!r}")
    return parsed.astimezone(timezone.utc)


def _order_key(season: int, season_type: str, week: int) -> tuple[int, int, int]:
    st = str(season_type).upper()
    if st not in _ST_PRIORITY:
        raise HoldoutFootballContractError(f"unsupported season_type: {season_type!r}")
    return (int(season), _ST_PRIORITY[st], int(week))


def build_holdout_blocks(frame: pl.DataFrame) -> list[HoldoutBlock]:
    """Build deterministic 2025 blocks without reading or revealing outcomes."""
    missing = sorted(_BLOCK_COLUMNS - set(frame.columns))
    if missing:
        raise HoldoutFootballContractError(f"holdout frame missing columns: {missing}")
    if frame.height == 0:
        raise HoldoutFootballContractError("holdout frame is empty")
    seasons = sorted({int(x) for x in frame["season"].unique().to_list()})
    if seasons != [HOLDOUT_SEASON]:
        raise HoldoutFootballContractError(
            f"holdout frame seasons {seasons} != [{HOLDOUT_SEASON}]"
        )
    if frame["game_id"].null_count() or frame["game_id"].n_unique() != frame.height:
        raise HoldoutFootballContractError("holdout game_id must be non-null and unique")

    by_key: dict[tuple[int, str, int], list[dict[str, Any]]] = {}
    for row in frame.select(
        "game_id", "season", "season_type", "week", "prediction_as_of_utc"
    ).to_dicts():
        key = (int(row["season"]), str(row["season_type"]).upper(), int(row["week"]))
        _order_key(*key)
        by_key.setdefault(key, []).append(row)

    blocks: list[HoldoutBlock] = []
    for key in sorted(by_key, key=lambda x: _order_key(*x)):
        rows = by_key[key]
        as_of_values = {_coerce_utc(r["prediction_as_of_utc"]) for r in rows}
        if len(as_of_values) != 1:
            raise HoldoutFootballContractError(f"heterogeneous cutoff inside block {key}")
        season, season_type, week = key
        blocks.append(
            HoldoutBlock(
                block_id=f"{season}_{season_type}_W{week:02d}",
                season=season,
                season_type=season_type,
                week=week,
                as_of_utc=next(iter(as_of_values)),
                game_ids=tuple(sorted(str(r["game_id"]) for r in rows)),
            )
        )
    return blocks


def assert_current_block_unrevealed(block_games: pl.DataFrame) -> None:
    """Reject any current-block post-kickoff outcome before prediction."""
    if block_games.height == 0:
        raise HoldoutFootballContractError("current holdout block is empty")
    seasons = sorted({int(x) for x in block_games["season"].unique().to_list()})
    if seasons != [HOLDOUT_SEASON]:
        raise HoldoutFootballContractError(f"current block seasons {seasons} are not 2025-only")
    if "target_available" in block_games.columns:
        available = block_games["target_available"].fill_null(False)
        if bool(available.any()):
            raise HoldoutFootballContractError(
                "current block outcome already marked available before prediction"
            )
    if "target_tie" in block_games.columns:
        tied = block_games["target_tie"].fill_null(False)
        if bool(tied.any()):
            raise HoldoutFootballContractError("current block tie outcome revealed before prediction")
    for col in _OUTCOME_COLUMNS:
        if col in block_games.columns and block_games[col].null_count() != block_games.height:
            raise HoldoutFootballContractError(
                f"current block post-kickoff field is non-null before prediction: {col}"
            )


def assert_history_strictly_prior(history: pl.DataFrame, block: HoldoutBlock) -> None:
    """Allow development history plus only already-revealed earlier 2025 blocks."""
    if history.height == 0:
        return
    required = {"season", "season_type", "week"}
    missing = sorted(required - set(history.columns))
    if missing:
        raise HoldoutFootballContractError(f"history missing chronology columns: {missing}")
    current_key = block.order_key
    for row in history.select("season", "season_type", "week").iter_rows(named=True):
        season = int(row["season"])
        key = _order_key(season, str(row["season_type"]), int(row["week"]))
        if season > HOLDOUT_SEASON or key >= current_key:
            raise HoldoutFootballContractError(
                f"history contains current/future block {key} for cutoff {current_key}"
            )
    holdout_history = history.filter(pl.col("season") == HOLDOUT_SEASON)
    if holdout_history.height and "target_available" in holdout_history.columns:
        available = holdout_history["target_available"].fill_null(False)
        if not bool(available.all()):
            raise HoldoutFootballContractError(
                "prior 2025 history contains an unrevealed outcome"
            )


def _current_block_frame(frame: pl.DataFrame, block: HoldoutBlock) -> pl.DataFrame:
    selected = frame.filter(
        (pl.col("season") == block.season)
        & (pl.col("season_type").cast(pl.Utf8).str.to_uppercase() == block.season_type)
        & (pl.col("week") == block.week)
    ).sort("game_id")
    ids = tuple(sorted(str(x) for x in selected["game_id"].to_list()))
    if ids != block.game_ids:
        raise HoldoutFootballContractError(
            f"block game identity mismatch: frame={ids} block={block.game_ids}"
        )
    return selected


def prepare_qb_elo_state_for_block(
    *, state: EloState, block_games: pl.DataFrame, block: HoldoutBlock, config: EloConfig
) -> EloState:
    """Apply the frozen season carryover once and ensure current teams exist."""
    prepared = state
    if prepared.current_season is not None and prepared.current_season < HOLDOUT_SEASON:
        prepared = apply_season_carryover(prepared, new_season=HOLDOUT_SEASON, config=config)
    elif prepared.current_season is not None and prepared.current_season > HOLDOUT_SEASON:
        raise HoldoutFootballContractError(
            f"QB-Elo state already beyond holdout season: {prepared.current_season}"
        )
    for team in sorted(
        set(str(x) for x in block_games["home_team"].to_list())
        | set(str(x) for x in block_games["away_team"].to_list())
    ):
        prepared = ensure_team(prepared, team, config)
    return prepared


def predict_oracle_qb_elo_block(
    *,
    history_games: pl.DataFrame,
    current_games: pl.DataFrame,
    block: HoldoutBlock,
    state: EloState,
    config: EloConfig,
    qb_adjustment_resolver: Callable[[str], tuple[float, float]],
    run_id: str,
    model_version: str = "v1.0.0",
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Predict one sealed 2025 block using the frozen Task04C Oracle-QB seam.

    The function fails before calling the canonical predictor if any current
    outcome is present.  Starter identity/adjustment is permitted via the
    reviewed Oracle resolver contract; outcome information is not.
    """
    assert_current_block_unrevealed(current_games)
    assert_history_strictly_prior(history_games, block)
    block_games = _current_block_frame(current_games, block)

    identity = _require_resolver_identity(qb_adjustment_resolver)
    qb_adjustment_resolver.assert_coverage(
        list(block.game_ids), where="holdout_2025.oracle_qb.coverage"
    )
    if identity.get("mode") != "ORACLE":
        raise HoldoutFootballContractError("QB resolver must preserve ORACLE mode")

    prepared_state = prepare_qb_elo_state_for_block(
        state=state, block_games=block_games, block=block, config=config
    )
    combined = pl.concat([history_games, current_games], how="diagonal_relaxed")
    exposure = _build_exposure_for_block(
        block_season=block.season,
        block_season_type=block.season_type,
        block_week=block.week,
        games=combined,
    )
    timestamp = created_at or datetime.now(timezone.utc)
    predictions, pregame_inputs = _predict_block(
        block_games=block_games,
        block_id=block.block_id,
        block_as_of_utc=block.as_of_utc,
        state=prepared_state,
        elo_config=config,
        run_id=run_id,
        model_version=model_version,
        exposure=exposure,
        created_at=timestamp,
        qb_adjustment_resolver=qb_adjustment_resolver,
    )
    if any(bool(row.get("target_available")) for row in predictions):
        raise HoldoutFootballContractError("canonical QB predictor observed a current outcome")
    return {
        "block": block,
        "predictions": predictions,
        "pregame_inputs": pregame_inputs,
        "block_start_state": prepared_state,
        "resolver_identity": identity,
        "outcomes_revealed": False,
    }


def reveal_and_update_qb_elo_block(
    *,
    frozen_prediction: dict[str, Any],
    revealed_games: pl.DataFrame,
    config: EloConfig,
    run_id: str,
    update_order_start: int = 0,
) -> dict[str, Any]:
    """Update Elo only after the already-frozen block receives its outcomes."""
    if bool(frozen_prediction.get("outcomes_revealed")):
        raise HoldoutFootballContractError("block outcomes already revealed")
    block = frozen_prediction.get("block")
    if not isinstance(block, HoldoutBlock):
        raise HoldoutFootballContractError("missing frozen HoldoutBlock identity")
    block_games = _current_block_frame(revealed_games, block)
    if "target_available" not in block_games.columns or not bool(
        block_games["target_available"].fill_null(False).all()
    ):
        raise HoldoutFootballContractError("revealed block is missing completed outcomes")
    if "target_margin" not in block_games.columns or block_games["target_margin"].null_count():
        raise HoldoutFootballContractError("revealed block is missing target_margin")

    outcomes = {str(r["game_id"]): r for r in block_games.to_dicts()}
    filled: list[dict[str, Any]] = []
    for prior in list(frozen_prediction.get("pregame_inputs") or []):
        gid = str(prior["game_id"])
        if gid not in outcomes:
            raise HoldoutFootballContractError(f"revealed outcome missing game_id {gid}")
        margin = int(outcomes[gid]["target_margin"])
        row = dict(prior)
        row["actual_margin"] = margin
        row["actual_tie"] = margin == 0
        row["actual_home_win"] = None if margin == 0 else margin > 0
        row["target_available"] = True
        filled.append(row)

    updates, new_state, next_order = _update_block(
        pregame_inputs=filled,
        state=frozen_prediction["block_start_state"],
        elo_config=config,
        block_id=block.block_id,
        run_id=run_id,
        update_order_start=update_order_start,
    )
    return {
        "block": block,
        "state_updates": updates,
        "new_state": new_state,
        "next_update_order": next_order,
        "outcomes_revealed": True,
    }
