# Development Walk-Forward v1

## Purpose
This document describes the reusable expanding weekly walk-forward engine
that underlies Task 03A and will be reused by all subsequent development
models.

## Contract
At each step:
1. Select one chronological `(season, season_type, week)` prediction block.
2. Snapshot its deterministic `as_of_utc` (from `prediction_as_of_utc`).
3. Build the eligible training set using *only* earlier prediction blocks.
4. Predict the complete current block before any state update.
5. Persist prediction records to the ledger.
6. Apply state updates from completed games in the block.
7. Advance chronologically.

## Guarantees
- **No shuffled split.** Ordered by `season → season_type priority → week`.
- **No random train/test split.** Fully deterministic block ordering.
- **No ordinary cross-validation.** Each block is predicted exactly once.
- **No same-week partial reveal.** The entire block is predicted before
  any update. This is the key invariant: once a game is chosen for a
  block, its `home_elo_before`, `away_elo_before`, and `predicted_home_win_probability`
  are immutable in the ledger.
- **One frozen prediction per game.** Duplicate `prediction_id` is fatal.
- **Duplicate block rejection.** The same `(season, season_type, week)`
  cannot appear twice.
- **Overwrite refusal by default.** `assert_no_market_columns` rejects
  any market column at the ledger boundary.

## Block Ordering
`season_type priority = REG (0) < WC (1) < DIV (2) < CON (3) < SB (4)`.
This matches the actual NFL bracket order.

## Warm-Up Policy
The engine produces predictions for every development game (2018–2024).
Because Elo has no fitted parameters, there is no "insufficient training
history" condition — the state always exists and always advances. All
1,942 predictions are scored in the scorecard.

## Season 2025 Tripwire
The engine **never** loads, fits, predicts, scores, or reports on 2025.
Guards:
- `_load_games` filters to `season <= 2024`.
- `build_development_blocks` filters to `season <= 2024`.
- `assert_development_seasons_only` raises `SealedHoldoutAccessError` if
  a 2025+ row is supplied.
- All evaluation metrics and the scorecard raise `SealedHoldoutAccessError`
  on 2025+ input.

## File Outputs
- `data/modeling/development_v1/qb_elo_predictions_2018_2024.parquet`
- `data/modeling/development_v1/qb_elo_state_transitions_2018_2024.parquet`
- `data/modeling/development_v1/qb_elo_run_manifest_v1.json`
- `data/modeling/development_v1/qb_elo_tuning_ledger_v1.json`
- `reports/development/qb_elo_development_scorecard.md`
- `reports/development/qb_elo_development_scorecard.json`
- `reports/development/qb_elo_reliability_table.csv`

## Reproducibility
- All inputs are deterministic: parquet files, config YAML, run manifest.
- No randomness is used (random_seed = 20260802 is preserved for audit).
- The state ledger fully reproduces the final team Elo ratings.
- Replaying the engine with the same `created_at` produces a
  bit-identical prediction ledger.

## Future Models
The engine is model-agnostic. Task 03B (opponent-adjusted expected
margin) and Task 03C (XGBoost) will replace the `qb_elo` model logic
while preserving the walk-forward skeleton, ledger format, and tripwires.
