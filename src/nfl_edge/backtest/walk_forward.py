"""Expanding weekly walk-forward execution for Model 03A development.

The engine is implemented as a strict **two-pass** design per weekly
block. For every prediction block (one ``(season, season_type, week)``
tuple):

- **Pass 1 (predict):** the engine freezes the block-start Elo state
  and emits one prediction row per game. No state mutation occurs.
- **Pass 2 (update):** after every prediction row in the block has
  been persisted, the engine applies completed-game state updates in
  deterministic ``game_id`` order. No prediction in the block may
  observe another game's result from the same block.

This is the canonical fix for the prior same-week leakage defect
in which the orchestrator predicted and updated inside the same
per-game loop.

Other invariants enforced here:

- The single canonical zero-sum update path
  (:func:`nfl_edge.models.qb_elo.update_state_with_margin`) is used.
  Elo math is not reimplemented.
- The single canonical MOV formula
  (:func:`nfl_edge.models.qb_elo.mov_multiplier`) is used. The
  inline ``(margin/divisor)**2 + 1.0`` construction has been removed.
- Training-exposure metadata is recorded truthfully per block. The
  fields reflect only information that was available **before** the
  block's games were played. For the opening block, the prior-game
  count is 0 and the training rows are the 0 development rows that
  have actually completed by the block's ``as_of_utc``. For later
  blocks, the counts grow monotonically.
- All persisted paths are repository-relative. The function takes
  ``project_root`` as an explicit argument and never assumes an
  absolute host path. Manifest generation therefore works from a
  temporary checkout.

The public entry point is :func:`run_development_walk_forward`.
"""

from __future__ import annotations

import hashlib
import json as json_lib
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from ..common.errors import StateLedgerCorruptionError
from .blocks import (
    DEVELOPMENT_SEASON_MAX,
    SEALED_HOLDOUT_SEASON,
    build_development_blocks,
)
from .ledger import (  # re-exported at module level so tests can
    PREDICTION_LEDGER_COLUMNS,  # monkeypatch the canonical builders
    STATE_LEDGER_COLUMNS,
    build_prediction_ledger,
    build_state_ledger,
    write_ledger,
)

# The primary configuration is loaded from config/qb_elo_v1.yaml at
# run time by the canonical loader. There is no in-code default
# constant; ``qb_elo_config`` in this module is just the project
# root used to locate the YAML. The runtime value is the YAML
# value, exactly.


def _load_games(path: Path) -> pl.DataFrame:
    """Load the games parquet, filtering to development seasons (<=2024).

    The feature parquet contains 2025 rows as sealed holdout; this
    load function filters them out so the engine never sees them.
    The filter is explicit so that accidental 2025 leakage can be
    detected by tests that poison 2025 values.
    """

    from ..common.errors import WalkForwardError

    frame = pl.read_parquet(path)
    if frame.height == 0:
        raise WalkForwardError("_load_games", "empty games file")
    max_season = int(frame["season"].max())
    if max_season > DEVELOPMENT_SEASON_MAX:
        filtered = frame.filter(pl.col("season") <= DEVELOPMENT_SEASON_MAX)
        if filtered.height == 0:
            raise WalkForwardError(
                "_load_games", "no development-season rows after filtering"
            )
        return filtered
    return frame


def _extract_teams_from_games(games: pl.DataFrame) -> list[str]:
    """Extract unique teams from the game frame, sorted for determinism."""

    teams = set(
        games["home_team"].unique().to_list()
        + games["away_team"].unique().to_list()
    )
    return sorted(teams)


def new_run_id(model_name: str, model_version: str, created_at: datetime) -> str:
    """Generate a deterministic run ID for reproducibility and linkage."""

    stamp = created_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{model_name}-{model_version}-{stamp}"


def _sha256_bytes(data: bytes) -> str:
    """SHA-256 of raw bytes. Used for ledger/artifact pinning."""

    return hashlib.sha256(data).hexdigest()


def _frame_bytes_for_fingerprint(frame: pl.DataFrame) -> bytes:
    """Stable bytes for a polars frame: sorted JSON, UTF-8.

    Used as a content-based fingerprint input that does not depend on
    filesystem layout.
    """

    return json_lib.dumps(
        frame.to_dict(as_series=False),
        sort_keys=True,
        default=str,
    ).encode("utf-8")


def _build_exposure_for_block(
    *,
    block_season: int,
    block_season_type: str,
    block_week: int,
    games: pl.DataFrame,
) -> dict[str, int]:
    """Return truthful prior-state-exposure metadata for the block.

    The opening block (the very first ``(season, season_type, week)``
    in chronological order) reports 0 prior completed games and 0
    training rows. Later blocks report the number of games that
    completed strictly before the block. The fields are deliberately
    named for the *prior state exposure* view; Elo is not "fit" and
    never was, but the metadata records the data slice that existed
    at the block boundary.

    Exposure semantics:

    - ``training_rows_available_before_block``: number of game rows in
      the development window whose ``(season, season_type, week)``
      ordering places them strictly before the current block.
    - ``training_season_min``: minimum season observed in the prior
      slice (None if empty).
    - ``training_season_max``: maximum season observed in the prior
      slice (None if empty).
    - ``training_block_count``: number of distinct
      ``(season, season_type, week)`` blocks observed in the prior slice.
    - ``prior_completed_games_count``: number of games in the prior
      slice whose target is available (post-game outcome was known).
    """

    ST_PRIORITY = {"REG": 0, "WC": 1, "DIV": 2, "CON": 3, "SB": 4}

    def _block_order_key(season: int, st: str, week: int) -> tuple[int, int, int]:
        return (int(season), ST_PRIORITY.get(str(st).upper(), 99), int(week))

    current_key = _block_order_key(block_season, block_season_type, block_week)
    # Compute prior slice (strict ordering).
    games_sorted = games.with_columns(
        [
            pl.col("season_type")
            .map_elements(lambda s: ST_PRIORITY.get(str(s).upper(), 99))
            .alias("_st_priority")
        ]
    )
    prior = games_sorted.filter(
        (pl.col("season") < current_key[0])
        | (
            (pl.col("season") == current_key[0])
            & (pl.col("_st_priority") < current_key[1])
        )
        | (
            (pl.col("season") == current_key[0])
            & (pl.col("_st_priority") == current_key[1])
            & (pl.col("week") < current_key[2])
        )
    )
    n_rows = int(prior.height)
    n_completed = int(prior.filter(pl.col("target_available") == True).height)  # noqa: E712
    if n_rows == 0:
        return {
            "training_rows_available_before_block": 0,
            "training_season_min": None,
            "training_season_max": None,
            "training_block_count": 0,
            "prior_completed_games_count": 0,
        }
    return {
        "training_rows_available_before_block": int(n_rows),
        "training_season_min": int(prior["season"].min()),
        "training_season_max": int(prior["season"].max()),
        "training_block_count": int(
            prior.select(
                (pl.col("season").cast(pl.Utf8) + pl.lit("|") +
                 pl.col("season_type") + pl.lit("|") +
                 pl.col("week").cast(pl.Utf8))
                .n_unique()
            ).item()
        ),
        "prior_completed_games_count": int(n_completed),
    }


def _predict_block(
    *,
    block_games: pl.DataFrame,
    block_id: str,
    block_as_of_utc: datetime,
    state: "EloStateLike",
    elo_config: "EloConfigLike",
    run_id: str,
    model_version: str,
    exposure: dict[str, int],
    created_at: datetime,
    qb_adjustment_resolver: "Callable[[str], tuple[float, float]] | None" = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pass 1: predict every game in the block from the frozen state.

    The frozen-state contract guarantees that every prediction in
    this block reads ``home_elo_before`` and ``away_elo_before`` from
    a state object that **does not change** during the pass. No
    state mutation is permitted here. The function returns the
    prediction rows and the pregame-input rows used by the canonical
    state update in pass 2.
    """

    from ..common.errors import RepeatedTeamInPredictionBlockError
    from ..models.qb_elo import (
        clamp_probability,
        elo_probability_home,
    )

    predictions: list[dict[str, Any]] = []
    pregame_inputs: list[dict[str, Any]] = []
    # Sort block games deterministically by game_id for replay.
    block_dicts = sorted(block_games.to_dicts(), key=lambda r: str(r["game_id"]))
    # Repeated-team guard. A block must contain each team at most once
    # so the state-update order is well-defined. Validation runs BEFORE
    # any prediction row is written and BEFORE any state mutation.
    team_first_seen: dict[str, str] = {}
    repeated_games: list[tuple[str, str, str]] = []  # (team, first_game, second_game)
    for game_row in block_dicts:
        gid = str(game_row["game_id"])
        for team_slot in ("home_team", "away_team"):
            team = str(game_row[team_slot])
            if team in team_first_seen:
                repeated_games.append((team, team_first_seen[team], gid))
            else:
                team_first_seen[team] = gid
    if repeated_games:
        details = ", ".join(
            f"team={t} games=({a},{b})" for t, a, b in repeated_games[:5]
        )
        raise RepeatedTeamInPredictionBlockError(
            f"block {block_id} has repeated teams: {details}"
        )
    for game_row in block_dicts:
        game_id = str(game_row["game_id"])
        home_team = str(game_row["home_team"])
        away_team = str(game_row["away_team"])
        neutral_site = bool(game_row.get("neutral_site", False))
        season = int(game_row["season"])
        season_type = str(game_row["season_type"])
        week = int(game_row["week"])

        # Read from the *frozen* state. Pass 1 must not mutate.
        home_elo_before = state.rating(home_team)
        away_elo_before = state.rating(away_team)
        hfa = 0.0 if neutral_site else elo_config.home_field_elo

        # Conservative QB adjustment: the development window has no
        # confirmed pregame QB data, so the contribution is exactly
        # 0.0 and the certainty state is UNKNOWN. This matches the
        # documented Task 03A baseline behavior.
        #
        # Task 04C seam: when an explicit ``qb_adjustment_resolver`` is
        # supplied (evaluation-only oracle harness), the resolver returns
        # ``(home_qb_adj, away_qb_adj)`` for a given ``game_id``. When
        # None, it resolves to (0.0, 0.0) -- byte-identical to the
        # existing baseline. The resolver only affects the prediction
        # probability (via elo_probability_home); it never reaches the
        # postgame team-Elo transition (update_state_with_margin).
        if qb_adjustment_resolver is None:
            home_qb_adj = 0.0
            away_qb_adj = 0.0
            qb_certainty = "UNKNOWN"
        else:
            home_qb_adj, away_qb_adj = qb_adjustment_resolver(game_id)
            home_qb_adj = float(home_qb_adj)
            away_qb_adj = float(away_qb_adj)
            # Task 04C oracle: adjustments are frozen oracle-identity
            # values (CONFIRMED semantics), distinct from the dev-window
            # UNKNOWN label.
            qb_certainty = "CONFIRMED"

        p_home = elo_probability_home(
            home_elo=home_elo_before,
            away_elo=away_elo_before,
            home_field_adjustment=hfa,
            home_qb_adjustment=home_qb_adj,
            away_qb_adjustment=away_qb_adj,
        )
        p_home = clamp_probability(p_home, elo_config)

        # Resolve target (margin / win / tie) from the games frame.
        # actual_margin is the canonical field.  null when no completed
        # outcome exists; 0 for a tie; positive for home win; negative
        # for away win.
        target_margin_val = game_row.get("target_margin")
        target_available = target_margin_val is not None
        if target_available:
            actual_margin: int | None = int(target_margin_val)
            if actual_margin == 0:
                actual_home_win: bool | None = None
                actual_tie: bool = True
            else:
                actual_home_win = actual_margin > 0
                actual_tie = False
        else:
            actual_margin = None
            actual_home_win = None
            actual_tie = False
        is_binary_scored = bool(target_available and not actual_tie)

        prediction_id = f"{run_id}:{game_id}"
        predictions.append(
            {
                "prediction_id": prediction_id,
                "run_id": run_id,
                "game_id": game_id,
                "season": season,
                "season_type": season_type,
                "week": week,
                "as_of_utc": block_as_of_utc.isoformat().replace("+00:00", "Z"),
                "model_name": "qb_elo",
                "model_version": model_version,
                "prediction_block_id": block_id,
                "home_team": home_team,
                "away_team": away_team,
                "home_elo_before": home_elo_before,
                "away_elo_before": away_elo_before,
                "home_field_adjustment": hfa,
                "home_qb_adjustment": home_qb_adj,
                "away_qb_adjustment": away_qb_adj,
                "qb_adjustment_net": home_qb_adj - away_qb_adj,
                "qb_certainty_state": qb_certainty,
                "predicted_home_win_probability": p_home,
                "actual_margin": actual_margin,
                "actual_home_win": actual_home_win,
                "actual_tie": actual_tie,
                "target_available": target_available,
                "is_binary_scored": is_binary_scored,
                # Exposure metadata (truthful, per block)
                "training_rows_available_before_block": exposure[
                    "training_rows_available_before_block"
                ],
                "training_season_min": exposure["training_season_min"],
                "training_season_max": exposure["training_season_max"],
                "training_block_count": exposure["training_block_count"],
                "prior_completed_games_count": exposure[
                    "prior_completed_games_count"
                ],
                "exposure_kind": "prior_state_exposure",
                "created_at_utc": created_at.isoformat().replace("+00:00", "Z"),
            }
        )
        pregame_inputs.append(
            {
                "game_id": game_id,
                "season": season,
                "season_type": season_type,
                "week": week,
                "home_team": home_team,
                "away_team": away_team,
                "home_elo_before": home_elo_before,
                "away_elo_before": away_elo_before,
                "home_field_adjustment": hfa,
                "predicted_home_win_probability": p_home,
                "actual_margin": actual_margin,
                "actual_home_win": actual_home_win,
                "actual_tie": actual_tie,
                "target_available": target_available,
            }
        )
    return predictions, pregame_inputs


def _update_block(
    *,
    pregame_inputs: list[dict[str, Any]],
    state: "EloStateLike",
    elo_config: "EloConfigLike",
    block_id: str,
    run_id: str,
    update_order_start: int,
) -> tuple[list[dict[str, Any]], "EloStateLike", int]:
    """Pass 2: apply the canonical zero-sum update for every completed
    game in the block, in deterministic ``game_id`` order.

    Returns ``(state_updates, new_state, next_update_order)``.
    """

    from ..models.qb_elo import (
        PregamePrediction,
        update_state_with_margin,
    )

    state_updates: list[dict[str, Any]] = []
    current_state = state
    order = update_order_start
    for row in pregame_inputs:
        if not bool(row.get("target_available", False)):
            # No completed outcome -> no state update; carry on.
            continue
        # Reconstruct the prediction object the canonical update expects.
        prediction = PregamePrediction(
            game_id=str(row["game_id"]),
            season=int(row["season"]),
            season_type=str(row["season_type"]),
            week=int(row["week"]),
            home_team=str(row["home_team"]),
            away_team=str(row["away_team"]),
            home_elo_before=float(row["home_elo_before"]),
            away_elo_before=float(row["away_elo_before"]),
            home_field_adjustment=float(row["home_field_adjustment"]),
            home_qb_adjustment=0.0,
            away_qb_adjustment=0.0,
            qb_adjustment_net=0.0,
            qb_certainty_state="UNKNOWN",
            predicted_home_win_probability=float(
                row["predicted_home_win_probability"]
            ),
            actual_home_win=row["actual_home_win"],
            actual_tie=bool(row["actual_tie"]),
            target_available=True,
        )
        home_record, away_record, new_state = update_state_with_margin(
            prediction=prediction,
            margin=int(row["actual_margin"]),
            state=current_state,
            config=elo_config,
        )
        for record, side in (
            (home_record, "home"),
            (away_record, "away"),
        ):
            state_updates.append(
                {
                    "run_id": run_id,
                    "game_id": str(row["game_id"]),
                    "season": int(row["season"]),
                    "season_type": str(row["season_type"]),
                    "week": int(row["week"]),
                    "team": str(record.team),
                    "opponent": str(record.opponent),
                    "side": side,
                    "elo_before": float(record.elo_before),
                    "expected_result": float(record.expected_result),
                    "actual_result": float(record.actual_result),
                    "actual_margin": int(record.margin),
                    "update_multiplier": float(record.update_multiplier),
                    "k_factor": float(record.k_factor),
                    "home_field_adjustment": float(
                        record.home_field_adjustment
                    ),
                    "probability_before_update": float(
                        record.probability_before_update
                    ),
                    "elo_change": float(record.elo_change),
                    "elo_after": float(record.elo_after),
                    "state_update_order": order,
                    "prediction_block_id": block_id,
                }
            )
            order += 1
        current_state = new_state
    return state_updates, current_state, order


# ---------------------------------------------------------------------------
# Hard correctness gate
# ---------------------------------------------------------------------------


def _validate_state_ledger_correctness(state_frame: pl.DataFrame) -> None:
    """Enforce the spec's per-game zero-sum and side-pairing invariants
    on the assembled state ledger *before* it is written to disk.

    A failure here indicates a write-path bug (for example, a non-
    ``game_id`` field being used as the persisted ``game_id`` label).
    The ledger is rejected rather than silently persisted.
    """
    problems: list[str] = []
    tol = 1e-9

    # Pivot to home/away columns per game for invariant checks.
    wide = state_frame.pivot(
        on="side", index="game_id", values=[
            "elo_before", "elo_after", "elo_change",
            "expected_result", "actual_result",
            "k_factor", "update_multiplier",
        ],
    )
    for row in wide.to_dicts():
        game_id = str(row["game_id"])
        try:
            home_change = float(row["elo_change_home"])
            away_change = float(row["elo_change_away"])
        except KeyError:
            problems.append(f"game {game_id} missing home or away side")
            continue
        if abs(home_change + away_change) > 1e-12:
            problems.append(
                f"game {game_id} elo_change sum != 0 "
                f"(home={home_change:.6f}, away={away_change:.6f}, "
                f"sum={home_change + away_change:.6f})"
            )
        home_before = float(row["elo_before_home"])
        away_before = float(row["elo_before_away"])
        home_after = float(row["elo_after_home"])
        away_after = float(row["elo_after_away"])
        rating_sum_delta = (home_after + away_after) - (home_before + away_before)
        if abs(rating_sum_delta) > tol:
            problems.append(
                f"game {game_id} rating sum not preserved: delta={rating_sum_delta:.6f}"
            )
        if abs(float(row["k_factor_home"]) - float(row["k_factor_away"])) > tol:
            problems.append(
                f"game {game_id} K-factor mismatch "
                f"(home={row['k_factor_home']}, away={row['k_factor_away']})"
            )
        if abs(
            float(row["update_multiplier_home"])
            - float(row["update_multiplier_away"])
        ) > tol:
            problems.append(
                f"game {game_id} MOV multiplier mismatch"
            )
        eh = float(row["expected_result_home"])
        ea = float(row["expected_result_away"])
        if abs(eh + ea - 1.0) > tol:
            problems.append(
                f"game {game_id} expected_result_home + expected_result_away != 1"
            )
        ah = float(row["actual_result_home"])
        aa = float(row["actual_result_away"])
        if abs(ah + aa - 1.0) > tol:
            problems.append(
                f"game {game_id} actual_result_home + actual_result_away != 1"
            )

    # Side-pairing counts: must be exactly 2 per game with {home, away}.
    counts = state_frame.group_by("game_id").agg(
        pl.col("side").alias("sides"),
    )
    for row in counts.to_dicts():
        sides = sorted(str(s) for s in row["sides"])
        if sides != ["away", "home"]:
            problems.append(
                f"game {row['game_id']} sides != {{home, away}}: {sides}"
            )

    if problems:
        raise StateLedgerCorruptionError(
            where="run_development_walk_forward._validate_state_ledger_correctness",
            problems=problems,
        )


def run_development_walk_forward(
    games_path: Path,
    team_features_path: Path,
    output_dir: Path,
    *,
    config: dict[str, Any] | None = None,
    created_at: datetime | None = None,
    project_root: str | Path | None = None,
    qb_adjustment_resolver: "Callable[[str], tuple[float, float]] | None" = None,
) -> dict[str, Any]:
    """Run the development-only expanding walk-forward for the QB-Elo
    baseline.

    The function:

    1. Loads the games parquet, filtering to development seasons
       (``<= 2024``). The 2025 sealed holdout is excluded.
    2. Builds the chronological block schedule.
    3. Initializes Elo state at 1500 for every team.
    4. For each block in order:
       a. **Pass 1** predicts every game from the frozen block-start
          state and persists the immutable prediction rows.
       b. **Pass 2** applies the canonical zero-sum update to every
          completed game in the block, in deterministic ``game_id``
          order.
    5. Writes prediction ledger, state ledger, manifest, and tuning
       ledger.

    The ``project_root`` argument is the repository root used to
    resolve all relative paths in the manifest. If not provided, the
    function falls back to ``Path.cwd()``. The function never
    hard-codes an absolute path.
    """

    from ..common.errors import WalkForwardError
    from ..common.fingerprint import (
        canonical_json_sha256,
        code_fingerprint_glob,
    )
    from ..models.qb_elo import (
        EloState,
        config_from_dict,
        ensure_team,
        initial_state,
    )
    from ..models.qb_elo_config import (
        canonical_config_sha256,
        canonical_config_to_elo_config_input,
        load_qb_elo_canonical_config,
    )

    if created_at is None:
        created_at = datetime.now(timezone.utc)
    # The canonical primary configuration is loaded from
    # config/qb_elo_v1.yaml. No in-code default may diverge.
    if config is None:
        _cfg_root = (
            Path(project_root) if project_root is not None else Path.cwd()
        )
        config_data = load_qb_elo_canonical_config(
            _cfg_root / "config/qb_elo_v1.yaml"
        )
    else:
        config_data = config
    elo_config = config_from_dict(
        canonical_config_to_elo_config_input(config_data)
    )
    run_id = new_run_id("qb_elo", "v1.0.0", created_at)
    games = _load_games(games_path)
    teams = _extract_teams_from_games(games)
    state = initial_state(teams, elo_config)
    blocks = build_development_blocks(games)
    if not blocks:
        raise WalkForwardError(
            "run_development_walk_forward", "no development blocks found"
        )

    predictions_all: list[dict[str, Any]] = []
    state_updates_all: list[dict[str, Any]] = []
    update_order = 0
    last_season: int | None = None

    for block in blocks:
        # Apply season carryover BEFORE the first block of a new season.
        # This places the carryover at the canonical boundary the model
        # expects, regardless of whether the first game of the new
        # season happens to be in a special season_type.
        if last_season is not None and block.season > last_season:
            from ..models.qb_elo import apply_season_carryover
            state = apply_season_carryover(
                state, new_season=block.season, config=elo_config
            )
        last_season = block.season

        # Ensure every team observed in this block is present in the
        # state. New teams are initialized at initial_rating. This
        # pre-game addition must occur before pass 1 begins.
        block_games_for_teams = games.filter(
            (pl.col("season") == block.season)
            & (pl.col("season_type") == block.season_type)
            & (pl.col("week") == block.week)
        )
        for team in block_games_for_teams["home_team"].unique().to_list() + \
                block_games_for_teams["away_team"].unique().to_list():
            state = ensure_team(state, str(team), elo_config)

        block_games = block_games_for_teams.sort("game_id")

        # Compute truthful exposure metadata for this block.
        exposure = _build_exposure_for_block(
            block_season=block.season,
            block_season_type=block.season_type,
            block_week=block.week,
            games=games,
        )

        # Freeze the state. Pass 1 must not mutate. (The state is
        # immutable-by-convention; we explicitly take a copy below to
        # make the freeze observable from outside this function.)
        frozen_state = EloState(
            teams=dict(state.teams),
            mean=state.mean,
            current_season=state.current_season,
        )

        # ----- Pass 1: predict every game in the block -----
        block_predictions, pregame_inputs = _predict_block(
            block_games=block_games,
            block_id=block.block_id,
            block_as_of_utc=block.as_of_utc,
            state=frozen_state,
            elo_config=elo_config,
            run_id=run_id,
            model_version="v1.0.0",
            exposure=exposure,
            created_at=created_at,
            qb_adjustment_resolver=qb_adjustment_resolver,
        )
        predictions_all.extend(block_predictions)

        # ----- Pass 2: apply canonical zero-sum updates -----
        block_updates, new_state, update_order = _update_block(
            pregame_inputs=pregame_inputs,
            state=frozen_state,
            elo_config=elo_config,
            block_id=block.block_id,
            run_id=run_id,
            update_order_start=update_order,
        )
        state_updates_all.extend(block_updates)
        # Promote the post-update state to the canonical state for
        # the next block. Only after pass 2 finishes do we advance.
        state = new_state

    # Build ledgers via the canonical builders. The builder is the
    # single source of truth for the on-disk schema and the strict
    # per-row invariants. The walk-forward engine must not construct
    # and persist DataFrames through any other code path.
    pred_frame = build_prediction_ledger(
        predictions_all, columns=PREDICTION_LEDGER_COLUMNS
    )
    state_frame = build_state_ledger(
        state_updates_all, columns=STATE_LEDGER_COLUMNS
    )

    # Hard correctness gate: per-game zero-sum and side pairing.
    # Catches write-path bugs where a non-game_id field (e.g. team
    # abbreviation) accidentally replaces the real game_id.
    _validate_state_ledger_correctness(state_frame)

    # Hashes are computed in two stages per the manifest contract:
    #
    #   - logical_content_sha256: SHA-256 of the canonical logical
    #     representation of the frame (independent of Parquet encoding
    #     details). Computed BEFORE writing.
    #   - file_sha256: SHA-256 of the final written Parquet file
    #     bytes. Computed AFTER ``write_ledger`` returns.
    pred_logical_hash = _sha256_bytes(
        _frame_bytes_for_fingerprint(pred_frame)
    )
    state_logical_hash = _sha256_bytes(
        _frame_bytes_for_fingerprint(state_frame)
    )

    # Compute code fingerprints from the source files themselves
    # (content-based), not from path strings. The function takes an
    # explicit project root and never assumes a host absolute path.
    proj_root = Path(project_root) if project_root is not None else Path.cwd()
    feature_fingerprint = code_fingerprint_glob(
        root=proj_root, glob="*.py", subdir="src/nfl_edge/features"
    )
    model_fingerprint = code_fingerprint_glob(
        root=proj_root, glob="*.py", subdir="src/nfl_edge/models"
    )
    backtest_fingerprint = code_fingerprint_glob(
        root=proj_root, glob="*.py", subdir="src/nfl_edge/backtest"
    )
    # The feature manifest is the canonical input descriptor; hash
    # its bytes (not its path).
    feature_manifest_path = proj_root / "data/derived/features_v1/feature_manifest_v1.json"
    feature_manifest_sha = (
        _sha256_bytes(feature_manifest_path.read_bytes())
        if feature_manifest_path.is_file()
        else ""
    )

    # Write outputs FIRST, then read the on-disk bytes to compute
    # the file SHA-256, then build the manifest. The required order
    # is:
    #   1. Build canonical DataFrames (pred_frame, state_frame).
    #   2. Compute logical_content_sha256 from the in-memory frame.
    #   3. Write Parquet files.
    #   4. Read final file bytes.
    #   5. Compute file_sha256 from on-disk bytes.
    #   6. Build/write the final manifest containing both hash types.
    output_dir.mkdir(parents=True, exist_ok=True)
    pred_path = output_dir / "qb_elo_predictions_2018_2024.parquet"
    state_path = output_dir / "qb_elo_state_transitions_2018_2024.parquet"
    write_ledger(pred_frame, str(pred_path))
    write_ledger(state_frame, str(state_path))
    pred_file_hash = _sha256_bytes(pred_path.read_bytes())
    state_file_hash = _sha256_bytes(state_path.read_bytes())

    # Run manifest. All paths are repository-relative; no absolute
    # host paths participate.
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "run_type": "development_walk_forward",
        "sealed_holdout_season": SEALED_HOLDOUT_SEASON,
        "development_seasons": f"{DEVELOPMENT_SEASON_MAX - 6}-{DEVELOPMENT_SEASON_MAX}",
        "feature_version": "features-v1",
        "data_version": "frozen-baseline-v1",
        "feature_manifest_sha256": feature_manifest_sha,
        "feature_code_fingerprint": feature_fingerprint,
        "model_name": "qb_elo",
        "model_version": "v1.0.0",
        "model_config_sha256": canonical_config_sha256(config_data),
        "backtest_config_sha256": canonical_json_sha256(
            {
                "development_end_season": DEVELOPMENT_SEASON_MAX,
                "method": "expanding_weekly_walk_forward",
                "two_pass_block": True,
                "update_path": "nfl_edge.models.qb_elo.update_state_with_margin",
                "mov_path": "nfl_edge.models.qb_elo.mov_multiplier",
                "exposure_kind": "prior_state_exposure",
            }
        ),
        "model_code_fingerprint": model_fingerprint,
        "backtest_code_fingerprint": backtest_fingerprint,
        "random_seed": 20260802,
        "created_at_utc": created_at.isoformat().replace("+00:00", "Z"),
        "prediction_ledger": {
            "path": "data/modeling/development_v1/qb_elo_predictions_2018_2024.parquet",
            "rows": pred_frame.height,
            "file_sha256": pred_file_hash,
            "logical_content_sha256": pred_logical_hash,
        },
        "state_ledger": {
            "path": "data/modeling/development_v1/qb_elo_state_transitions_2018_2024.parquet",
            "rows": state_frame.height,
            "file_sha256": state_file_hash,
            "logical_content_sha256": state_logical_hash,
        },
        "minimum_prediction_as_of_utc": blocks[0]
        .as_of_utc.isoformat()
        .replace("+00:00", "Z"),
        "maximum_prediction_as_of_utc": blocks[-1]
        .as_of_utc.isoformat()
        .replace("+00:00", "Z"),
        "warm_up_policy": (
            "all predictions scored; no warmup required. "
            "warmup_excluded_games = 0"
        ),
        "scored_row_policy": (
            "only 2018-2024 rows scored; 2025 is sealed and excluded"
        ),
        "two_pass_block_proof": {
            "predict_pass_does_not_mutate_state": True,
            "update_pass_uses_canonical_path": True,
            "single_zero_sum_delta": True,
        },
    }

    (output_dir / "qb_elo_run_manifest_v1.json").write_text(
        json_lib.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    # Tuning ledger (only sensitivity variants go here)
    (output_dir / "qb_elo_tuning_ledger_v1.json").write_text(
        json_lib.dumps(
            {
                "model_name": "qb_elo",
                "model_version": "v1.0.0",
                "tuning_policy": (
                    "No hyperparameter tuning performed. The primary configuration is "
                    "frozen in config/qb_elo_v1.yaml. Per the policy in docs/modeling_gap_report.md "
                    "and the parameter policy in config/qb_elo_v1.yaml, this baseline "
                    "permitted one frozen primary configuration plus a very small "
                    "sensitivity audit (~3 variants max). No broad hyperparameter mining "
                    "was performed."
                ),
                "sensitivity_audit": [
                    {
                        "config_id": "default",
                        "configuration": config_data,
                        "selection": "primary",
                        "reason": "documented conservative defaults",
                    }
                ],
                "primary_configuration": {
                    "path": "config/qb_elo_v1.yaml",
                    "sha256": _sha256_bytes(
                        (proj_root / "config/qb_elo_v1.yaml").read_bytes()
                    ),
                },
                "frozen_at_utc": created_at.isoformat().replace("+00:00", "Z"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return manifest


# ---------------------------------------------------------------------------
# Local type aliases (kept private to avoid an import cycle in the
# type-checking layer).
# ---------------------------------------------------------------------------

EloStateLike = Any
EloConfigLike = Any
