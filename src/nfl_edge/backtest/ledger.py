"""Development-only prediction and state ledger management.

Ledgers are append-only at the run level: the contract is that a single
walk-forward run produces exactly one ledger file per ledger type. The
default mode is overwrite-refusal on duplicate ``prediction_id`` so a
re-run cannot accidentally merge two executions. The schema is fixed so
downstream Task 03B (stacker) and the scorecard can rely on column order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

import polars as pl

from ..common.errors import WalkForwardError
from ..common.polars_utils import (
    assert_no_market_columns,
    write_parquet_deterministic,
)

# Required columns of the prediction ledger. The schema is frozen so
# downstream consumers (stacker, scorecard) can rely on order.
PREDICTION_LEDGER_COLUMNS: tuple[str, ...] = (
    "prediction_id",
    "run_id",
    "game_id",
    "season",
    "season_type",
    "week",
    "as_of_utc",
    "model_name",
    "model_version",
    "training_season_min",
    "training_season_max",
    "training_rows",
    "prediction_block_id",
    "home_team",
    "away_team",
    "home_elo_before",
    "away_elo_before",
    "home_field_adjustment",
    "home_qb_adjustment",
    "away_qb_adjustment",
    "qb_adjustment_net",
    "qb_certainty_state",
    "predicted_home_win_probability",
    "actual_home_win",
    "actual_tie",
    "target_available",
    "is_scored",
    "created_at_utc",
)

STATE_LEDGER_COLUMNS: tuple[str, ...] = (
    "run_id",
    "game_id",
    "season",
    "season_type",
    "week",
    "team",
    "side",
    "opponent",
    "elo_before",
    "expected_result",
    "actual_result",
    "margin",
    "update_multiplier",
    "k_factor",
    "home_field_adjustment",
    "probability_before_update",
    "elo_change",
    "elo_after",
    "state_update_order",
    "prediction_block_id",
)


def new_run_id(model_name: str, model_version: str, created_at: datetime) -> str:
    """Deterministic run identifier derived from the model, version, and
    UTC timestamp. UUIDs are intentionally avoided so the identifier is
    reproducible across runs that share the same logical inputs."""

    if created_at.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")
    stamp = created_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{model_name}-{model_version}-{stamp}"


def new_prediction_id(run_id: str, game_id: str) -> str:
    """Deterministic prediction_id for a single row. Unique by construction
    because ``game_id`` is unique inside a single run."""

    return f"{run_id}:{game_id}"


@dataclass(frozen=True)
class RunContext:
    """Shared run context passed to every block during a walk-forward run.

    The context is frozen so call sites cannot accidentally mutate the
    run identifier or the model fingerprints across blocks."""

    run_id: str
    model_name: str
    model_version: str
    model_config_sha256: str
    feature_version: str
    data_version: str
    feature_manifest_sha256: str
    feature_code_fingerprint: str
    backtest_config_sha256: str
    model_code_fingerprint: str
    random_seed: int
    training_season_min: int
    training_season_max: int
    training_rows: int
    created_at_utc: datetime
    warm_up_policy: str
    scored_row_policy: str


def build_prediction_ledger(
    rows: Iterable[Mapping[str, Any]],
    *,
    columns: tuple[str, ...] = PREDICTION_LEDGER_COLUMNS,
) -> pl.DataFrame:
    """Convert an iterable of prediction rows into a deterministic
    ``pl.DataFrame`` with the locked column order. Market columns are
    rejected at this boundary. Duplicate ``prediction_id`` is fatal."""

    rows_list = list(rows)
    if not rows_list:
        raise WalkForwardError("build_prediction_ledger", "no rows provided")
    extra = [c for c in rows_list[0].keys() if c not in columns]
    if extra:
        raise WalkForwardError("build_prediction_ledger", f"unexpected columns: {extra}")
    missing = [c for c in columns if c not in rows_list[0]]
    if missing:
        raise WalkForwardError("build_prediction_ledger", f"missing columns: {missing}")
    assert_no_market_columns(rows_list[0].keys())
    frame = pl.DataFrame(rows_list).select(list(columns))
    ids = frame["prediction_id"]
    if ids.is_duplicated().any():
        dupes = ids.filter(ids.is_duplicated()).unique().to_list()
        raise WalkForwardError("build_prediction_ledger", f"duplicate prediction_id: {dupes[:5]}")
    return frame.sort(["season", "week", "game_id"])


def build_state_ledger(
    rows: Iterable[Mapping[str, Any]],
    *,
    columns: tuple[str, ...] = STATE_LEDGER_COLUMNS,
) -> pl.DataFrame:
    """Convert an iterable of state transitions into a deterministic frame.
    Sorts by ``state_update_order`` to preserve the engine execution order.
    Duplicate ``(game_id, team)`` is fatal because every team-game has
    exactly one Elo update."""

    rows_list = list(rows)
    if not rows_list:
        raise WalkForwardError("build_state_ledger", "no rows provided")
    extra = [c for c in rows_list[0].keys() if c not in columns]
    if extra:
        raise WalkForwardError("build_state_ledger", f"unexpected columns: {extra}")
    missing = [c for c in columns if c not in rows_list[0]]
    if missing:
        raise WalkForwardError("build_state_ledger", f"missing columns: {missing}")
    assert_no_market_columns(rows_list[0].keys())
    frame = pl.DataFrame(rows_list).select(list(columns))
    keys = frame.select("game_id", "team")
    if keys.is_duplicated().any():
        dupes = keys.filter(keys.is_duplicated()).unique().to_dicts()
        raise WalkForwardError(
            "build_state_ledger", f"duplicate (game_id, team) state rows: {dupes[:5]}"
        )
    return frame.sort(["state_update_order", "game_id", "side"])


def write_ledger(frame: pl.DataFrame, path: str) -> None:
    """Persist a ledger to disk with the development-only default settings.

    The function is the only approved writer for prediction and state
    ledgers. Callers must not write through ``pl.write_parquet`` directly so
    the on-disk schema is uniform across runs."""

    write_parquet_deterministic(frame, path)


def ledger_unique_row_check(frame: pl.DataFrame, key: str) -> None:
    """Sanity check that the ledger has unique ``key`` rows. Raises
    ``WalkForwardError`` on duplicates."""

    if frame[key].is_duplicated().any():
        dupes = frame.filter(frame[key].is_duplicated())[key].unique().to_list()
        raise WalkForwardError("ledger_unique_row_check", f"duplicate {key}: {dupes[:5]}")


def assert_season_filter(frame: pl.DataFrame, allowed_max: int, where: str) -> None:
    """Hard-fail if a ledger row carries a season greater than ``allowed_max``.
    Used by every downstream auditable artifact."""

    if frame.height == 0:
        return
    max_season = int(frame["season"].max())
    if max_season > allowed_max:
        raise WalkForwardError(
            where,
            f"detected season {max_season} > allowed_max {allowed_max}",
        )
