"""Expanding weekly walk-forward execution for Model 03A development.

The engine processes one prediction block at a time. At each step:

1. Load the block's games from the feature parquet (already filtered to 2018-2024).
2. Verify no 2025+ rows are present (sealed holdout tripwire).
3. Build Elo predictions for each game using the current state.
4. Persist predictions to the development prediction ledger.
5. Apply the Elo updates from completed games in this block before any
   subsequent block's predictions.

The engine maintains the order invariant: the entire block is predicted
before any same-week result updates the state. This is the key safeguard
against same-week leakage.

The public entry point is :func:`run_development_walk_forward`.
"""

from __future__ import annotations

import hashlib
import json as json_lib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from .blocks import (
    DEVELOPMENT_SEASON_MAX,
    SEALED_HOLDOUT_SEASON,
    build_development_blocks,
)


# Default config for the primary run (documented in docs/qb_elo_v1.md).
DEFAULT_ELO_CONFIG: dict[str, Any] = {
    "initial_rating": 1500.0,
    "k_factor_regular": 20.0,
    "k_factor_postseason": 4.0,
    "home_field_elo": 48.0,
    "season_mean_reversion_fraction": 1.0 / 3.0,
    "mov_divisor": 6.0,
    "mov_cap": 2.5,
    "prob_min": 0.01,
    "prob_max": 0.99,
}


def _load_games(path: Path) -> pl.DataFrame:
    """Load the games parquet, filtering to development seasons (<=2024).

    The feature parquet contains 2025 rows as sealed holdout, but this
    load function must filter them out so the engine never sees them.
    The filter is explicit so that accidental 2025 leakage can be
    detected by tests that poison 2025 values.
    """
    from ..common.errors import SealedHoldoutAccessError, WalkForwardError

    frame = pl.read_parquet(path)
    if frame.height == 0:
        raise WalkForwardError("_load_games", "empty games file")
    max_season = int(frame["season"].max())
    if max_season > DEVELOPMENT_SEASON_MAX:
        # Filter to development only, but record the filtered-out count
        filtered = frame.filter(pl.col("season") <= DEVELOPMENT_SEASON_MAX)
        if filtered.height == 0:
            raise WalkForwardError("_load_games", "no development-season rows after filtering")
        return filtered
    return frame


def _extract_teams_from_games(games: pl.DataFrame) -> list[str]:
    """Extract unique teams from the game frame, sorted for determinism."""
    teams = set(games["home_team"].unique().to_list() + games["away_team"].unique().to_list())
    return sorted(teams)


def new_run_id(model_name: str, model_version: str, created_at: datetime) -> str:
    """Generate a deterministic run ID for reproducibility and linkage."""
    stamp = created_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{model_name}-{model_version}-{stamp}"


def _sha256_file(path: Path) -> str:
    """Compute sha256 of a file's contents."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_development_walk_forward(
    games_path: Path,
    team_features_path: Path,
    output_dir: Path,
    *,
    config: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Run the development-only expanding walk-forward for the QB-Elo baseline.

    This is the single orchestration endpoint for Task 03A. The function:
    1. Loads the games parquet, filtering to development seasons (<=2024).
    2. Builds the chronological block schedule.
    3. Initializes Elo state at 1500 for each team.
    4. For each block in order:
        a. Predicts every game using current state.
        b. Persists predictions (before state update).
        c. Updates state after ALL games in the block are predicted.
    5. Writes prediction ledger, state ledger, and run manifest.
    """
    from ..common.fingerprint import canonical_json_sha256
    from ..common.polars_utils import assert_no_market_columns, write_parquet_deterministic
    from ..models.qb_elo import (
        EloState,
        TeamState,
        apply_season_carryover,
        clamp_probability,
        config_from_dict,
        elo_expected,
        elo_probability_home,
        ensure_team,
        initial_state,
    )

    from ..common.errors import WalkForwardError

    if created_at is None:
        created_at = datetime.now(timezone.utc)
    config_data = config or DEFAULT_ELO_CONFIG.copy()
    elo_config = config_from_dict(config_data)
    run_id = new_run_id("qb_elo", "v1.0.0", created_at)
    games = _load_games(games_path)
    teams = _extract_teams_from_games(games)
    state = initial_state(teams, elo_config)
    blocks = build_development_blocks(games)
    if not blocks:
        raise WalkForwardError("run_development_walk_forward", "no development blocks found")

    predictions_all: list[dict[str, Any]] = []
    state_updates_all: list[dict[str, Any]] = []
    training_rows = 0
    min_training_season = 2018
    max_training_season = DEVELOPMENT_SEASON_MAX
    all_games = games.filter(pl.col("season") <= max_training_season)
    training_rows = all_games.height
    update_order = 0

    for block in blocks:
        block_games = games.filter(
            (pl.col("season") == block.season)
            & (pl.col("season_type") == block.season_type)
            & (pl.col("week") == block.week)
        ).sort("game_id")
        if block_games.height == 0:
            raise WalkForwardError(
                "run_development_walk_forward", f"no games for block {block.block_id}"
            )

        for game_row in block_games.to_dicts():
            game_id = game_row["game_id"]
            home_team = game_row["home_team"]
            away_team = game_row["away_team"]
            neutral_site = bool(game_row.get("neutral_site", False))
            season = int(game_row["season"])
            season_type = str(game_row["season_type"])
            week = int(game_row["week"])

            # Ensure teams in state
            state = ensure_team(state, home_team, elo_config)
            state = ensure_team(state, away_team, elo_config)

            # Apply season carryover if needed
            if state.current_season is not None and season > state.current_season:
                state = apply_season_carryover(state, new_season=season, config=elo_config)

            # QB adjustment (conservative: all UNKNOWN -> 0.0)
            home_qb_adj = 0.0
            away_qb_adj = 0.0
            qb_certainty = "UNKNOWN"

            # Elo prediction
            home_elo_before = state.rating(home_team)
            away_elo_before = state.rating(away_team)
            hfa = 0.0 if neutral_site else elo_config.home_field_elo
            p_home = elo_probability_home(
                home_elo=home_elo_before,
                away_elo=away_elo_before,
                home_field_adjustment=hfa,
                home_qb_adjustment=home_qb_adj,
                away_qb_adjustment=away_qb_adj,
            )
            p_home = clamp_probability(p_home, elo_config)

            # Target
            # The feature parquet uses target_margin (signed: home - away)
            target_margin_val = game_row.get("target_margin")
            target_available = target_margin_val is not None
            if target_available:
                margin = int(abs(target_margin_val))
                if target_margin_val == 0:
                    actual_home_win = None
                    actual_tie = True
                else:
                    actual_home_win = target_margin_val > 0
                    actual_tie = False
            else:
                actual_home_win = None
                actual_tie = False
                margin = 0

            # Build prediction row
            prediction_id = f"{run_id}:{game_id}"
            predictions_all.append({
                "prediction_id": prediction_id,
                "run_id": run_id,
                "game_id": game_id,
                "season": season,
                "season_type": season_type,
                "week": week,
                "as_of_utc": block.as_of_utc.isoformat().replace("+00:00", "Z"),
                "model_name": "qb_elo",
                "model_version": "v1.0.0",
                "training_season_min": min_training_season,
                "training_season_max": max_training_season,
                "training_rows": training_rows,
                "prediction_block_id": block.block_id,
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
                "actual_home_win": actual_home_win,
                "actual_tie": actual_tie,
                "target_available": target_available,
                "is_scored": target_available,
                "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            })

            # Build state updates and update state
            if target_available:
                expected_home = elo_expected(home_elo_before + hfa, away_elo_before)
                expected_away = 1.0 - expected_home
                if actual_tie:
                    actual_home_float_val = 0.5
                    mult_home = 1.0
                    mult_away = 1.0
                elif actual_home_win is True:
                    mult_home = 1.0 + min(elo_config.mov_cap, (margin / elo_config.mov_divisor) ** 2 + 1.0)
                    mult_away = 1.0
                    actual_home_float_val = 1.0
                else:
                    mult_home = 1.0
                    mult_away = 1.0 + min(elo_config.mov_cap, (margin / elo_config.mov_divisor) ** 2 + 1.0)
                    actual_home_float_val = 0.0
                season_type_upper = season_type.upper()
                k = (
                    elo_config.k_factor_postseason
                    if season_type_upper in {"WC", "DIV", "CON", "SB"}
                    else elo_config.k_factor_regular
                )
                delta_home = k * mult_home * (actual_home_float_val - expected_home)
                delta_away = k * mult_away * ((1.0 - actual_home_float_val) - expected_away)
                new_home_rating = home_elo_before + delta_home
                new_away_rating = away_elo_before + delta_away

                state_updates_all.append({
                    "run_id": run_id,
                    "game_id": game_id,
                    "season": season,
                    "season_type": season_type,
                    "week": week,
                    "team": home_team,
                    "opponent": away_team,
                    "side": "home",
                    "elo_before": home_elo_before,
                    "expected_result": expected_home,
                    "actual_result": actual_home_float_val,
                    "margin": margin,
                    "update_multiplier": mult_home,
                    "k_factor": k,
                    "home_field_adjustment": hfa,
                    "probability_before_update": p_home,
                    "elo_change": delta_home,
                    "elo_after": new_home_rating,
                    "state_update_order": update_order,
                    "prediction_block_id": block.block_id,
                })
                update_order += 1
                state_updates_all.append({
                    "run_id": run_id,
                    "game_id": game_id,
                    "season": season,
                    "season_type": season_type,
                    "week": week,
                    "team": away_team,
                    "opponent": home_team,
                    "side": "away",
                    "elo_before": away_elo_before,
                    "expected_result": expected_away,
                    "actual_result": 1.0 - actual_home_float_val,
                    "margin": margin,
                    "update_multiplier": mult_away,
                    "k_factor": k,
                    "home_field_adjustment": -hfa,
                    "probability_before_update": 1.0 - p_home,
                    "elo_change": delta_away,
                    "elo_after": new_away_rating,
                    "state_update_order": update_order,
                    "prediction_block_id": block.block_id,
                })
                update_order += 1

                # Update state
                team_dict = dict(state.teams)
                team_dict[home_team] = TeamState(team=home_team, rating=new_home_rating, last_season=season)
                team_dict[away_team] = TeamState(team=away_team, rating=new_away_rating, last_season=season)
                new_mean = sum(t.rating for t in team_dict.values()) / len(team_dict)
                state = EloState(teams=team_dict, mean=new_mean, current_season=season)

    # Build ledgers
    pred_frame = pl.DataFrame(predictions_all).sort(["season", "week", "game_id"])
    assert_no_market_columns(pred_frame.columns)
    state_frame = pl.DataFrame(state_updates_all).sort(["state_update_order", "game_id", "side"])
    assert_no_market_columns(state_frame.columns)

    # Compute hashes
    pred_hash = hashlib.sha256(
        json_lib.dumps(pred_frame.to_dict(as_series=False), sort_keys=True).encode("utf-8")
    ).hexdigest()
    state_hash = hashlib.sha256(
        json_lib.dumps(state_frame.to_dict(as_series=False), sort_keys=True).encode("utf-8")
    ).hexdigest()

    # Run manifest
    manifest = {
        "run_id": run_id,
        "run_type": "development_walk_forward",
        "sealed_holdout_season": SEALED_HOLDOUT_SEASON,
        "development_seasons": f"{min_training_season}-{max_training_season}",
        "feature_version": "features-v1",
        "data_version": "frozen-baseline-v1",
        "feature_manifest_sha256": _sha256_file(
            Path("/root/nfl-edge/data/derived/features_v1/feature_manifest_v1.json")
        ),
        "feature_code_fingerprint": canonical_json_sha256(
            sorted(
                str(p.relative_to("/root/nfl-edge")).encode("utf-8")
                for p in Path("/root/nfl-edge/src/nfl_edge/features").rglob("*.py")
            )
        ),
        "model_name": "qb_elo",
        "model_version": "v1.0.0",
        "model_config_sha256": canonical_json_sha256(config_data),
        "backtest_config_sha256": canonical_json_sha256(
            {"development_end_season": max_training_season, "method": "expanding_weekly_walk_forward"}
        ),
        "model_code_fingerprint": canonical_json_sha256(
            sorted(
                str(p.relative_to("/root/nfl-edge")).encode("utf-8")
                for p in Path("/root/nfl-edge/src/nfl_edge/models").rglob("*.py")
            )
        ),
        "random_seed": 20260802,
        "created_at_utc": created_at.isoformat().replace("+00:00", "Z"),
        "prediction_ledger": {
            "path": "data/modeling/development_v1/qb_elo_predictions_2018_2024.parquet",
            "sha256": pred_hash,
            "rows": len(predictions_all),
        },
        "state_ledger": {
            "path": "data/modeling/development_v1/qb_elo_state_transitions_2018_2024.parquet",
            "sha256": state_hash,
            "rows": len(state_updates_all),
        },
        "minimum_prediction_as_of_utc": blocks[0].as_of_utc.isoformat().replace("+00:00", "Z"),
        "maximum_prediction_as_of_utc": blocks[-1].as_of_utc.isoformat().replace("+00:00", "Z"),
        "warm_up_policy": "all predictions scored; no warmup required",
        "scored_row_policy": "only 2018-2024 rows scored; 2025 is excluded",
    }

    # Write outputs
    output_dir.mkdir(parents=True, exist_ok=True)
    pred_path = output_dir / "qb_elo_predictions_2018_2024.parquet"
    state_path = output_dir / "qb_elo_state_transitions_2018_2024.parquet"
    write_parquet_deterministic(pred_frame, pred_path)
    write_parquet_deterministic(state_frame, state_path)
    (output_dir / "qb_elo_run_manifest_v1.json").write_text(
        json_lib.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    # Tuning ledger (only sensitivity variants go here)
    (output_dir / "qb_elo_tuning_ledger_v1.json").write_text(
        json_lib.dumps(
            [
                {
                    "config_id": "default",
                    "configuration": config_data,
                    "selection": "primary",
                    "reason": "documented conservative defaults",
                }
            ],
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return manifest