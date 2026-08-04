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
    "training_rows_available_before_block",
    "training_block_count",
    "prior_completed_games_count",
    "exposure_kind",
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
    "actual_margin",
    "actual_home_win",
    "actual_tie",
    "target_available",
    "is_binary_scored",
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
    "actual_margin",
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
    # Validate the SCHEMA on every row, not just the first. A row that
    # silently drops a field would be a contract violation.
    for idx, row in enumerate(rows_list):
        extra = [c for c in row.keys() if c not in columns]
        if extra:
            raise WalkForwardError(
                "build_prediction_ledger",
                f"row {idx} has unexpected columns: {extra}",
            )
        missing = [c for c in columns if c not in row]
        if missing:
            raise WalkForwardError(
                "build_prediction_ledger",
                f"row {idx} is missing columns: {missing}",
            )
        assert_no_market_columns(row.keys())
        _validate_prediction_row(row, where=f"build_prediction_ledger row {idx}")
    frame = pl.DataFrame(rows_list).select(list(columns))
    ids = frame["prediction_id"]
    if ids.is_duplicated().any():
        dupes = ids.filter(ids.is_duplicated()).unique().to_list()
        raise WalkForwardError("build_prediction_ledger", f"duplicate prediction_id: {dupes[:5]}")
    if frame["game_id"].is_duplicated().any():
        dupes = frame.filter(frame["game_id"].is_duplicated())["game_id"].unique().to_list()
        raise WalkForwardError("build_prediction_ledger", f"duplicate game_id: {dupes[:5]}")
    if int(frame["season"].max()) > 2024:
        raise WalkForwardError(
            "build_prediction_ledger",
            f"detected season {int(frame['season'].max())} > 2024",
        )
    return frame.sort(["season", "week", "game_id"])


def _validate_prediction_row(row: Mapping[str, Any], *, where: str) -> None:
    """Validate a single prediction row's invariants.

    This is intentionally strict: a row that violates any of these
    conditions must not be written to the canonical ledger.
    """
    season = int(row["season"])
    if season > 2024:
        raise WalkForwardError(where, f"season {season} > 2024")
    p = row.get("predicted_home_win_probability")
    if p is None or not (0.0 <= float(p) <= 1.0):
        raise WalkForwardError(where, f"invalid probability: {p}")
    target_available = bool(row.get("target_available"))
    actual_tie = bool(row.get("actual_tie"))
    actual_home_win = row.get("actual_home_win")
    actual_margin = row.get("actual_margin")
    is_binary_scored = bool(row.get("is_binary_scored"))

    # target_available consistency
    if target_available:
        if actual_margin is None:
            raise WalkForwardError(where, "target_available=True but actual_margin is null")
    else:
        if actual_margin is not None:
            raise WalkForwardError(where, "target_available=False but actual_margin is not null")
        if actual_tie:
            raise WalkForwardError(where, "target_available=False but actual_tie is true")
        if actual_home_win is not None:
            raise WalkForwardError(where, "target_available=False but actual_home_win is not null")

    # actual_margin consistency
    if target_available:
        m = int(actual_margin)
        if m > 0:
            if actual_home_win is not True or actual_tie:
                raise WalkForwardError(
                    where,
                    f"actual_margin={m} requires actual_home_win=True and actual_tie=False",
                )
        elif m < 0:
            if actual_home_win is not False or actual_tie:
                raise WalkForwardError(
                    where,
                    f"actual_margin={m} requires actual_home_win=False and actual_tie=False",
                )
        else:  # m == 0
            if actual_home_win is not None or not actual_tie:
                raise WalkForwardError(
                    where,
                    "actual_margin=0 requires actual_home_win=None and actual_tie=True",
                )

    # is_binary_scored consistency
    expected_binary = target_available and not actual_tie
    if is_binary_scored != expected_binary:
        raise WalkForwardError(
            where,
            f"is_binary_scored={is_binary_scored} but expected {expected_binary}",
        )


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
    for idx, row in enumerate(rows_list):
        extra = [c for c in row.keys() if c not in columns]
        if extra:
            raise WalkForwardError(
                "build_state_ledger",
                f"row {idx} has unexpected columns: {extra}",
            )
        missing = [c for c in columns if c not in row]
        if missing:
            raise WalkForwardError(
                "build_state_ledger",
                f"row {idx} is missing columns: {missing}",
            )
        assert_no_market_columns(row.keys())
    frame = pl.DataFrame(rows_list).select(list(columns))
    if frame.height > 0 and int(frame["season"].max()) > 2024:
        raise WalkForwardError(
            "build_state_ledger",
            f"detected season {int(frame['season'].max())} > 2024",
        )
    keys = frame.select("game_id", "team")
    if keys.is_duplicated().any():
        dupes = keys.filter(keys.is_duplicated()).unique().to_dicts()
        raise WalkForwardError(
            "build_state_ledger", f"duplicate (game_id, team) state rows: {dupes[:5]}"
        )
    # Exactly two state rows per completed game: {home, away}
    by_game = frame.group_by("game_id").agg(
        pl.col("side").alias("sides"),
        pl.col("team").alias("teams"),
    )
    bad = by_game.filter(
        (pl.col("sides").list.len() != 2)
        | ~(pl.col("sides").list.contains("home"))
        | ~(pl.col("sides").list.contains("away"))
    )
    if bad.height > 0:
        raise WalkForwardError(
            "build_state_ledger",
            f"games with bad side pairing: {bad.height}",
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
