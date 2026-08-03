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

## Correction History (PR #4 remediation)

On 2026-08-03, an independent review identified several defects in the
prior walk-forward and Elo implementation. All defects have been
corrected and the development baseline has been re-executed. The
prior published metrics are **superseded** and must not be cited.

Defects fixed:

- **A. Same-week leakage.** The orchestrator previously predicted
  and updated state inside the same per-game loop. The corrected
  engine implements a strict two-pass block design (Pass 1 freezes
  the block-start state and predicts every game; Pass 2 applies all
  updates in deterministic ``game_id`` order).
- **B. Non-zero-sum updates.** The corrected ``update_state_with_margin``
  uses a single ``delta = K * MOV * (actual - expected)`` and sets
  ``away_change = -home_change`` exactly.
- **C. MOV formula.** The corrected ``mov_multiplier`` matches the
  spec (``min(mov_cap, 1 + (abs(margin)/divisor)**2)``); the inline
  reimplementation was removed.
- **D. Two paths.** The orchestrator now uses the canonical
  ``update_state_with_margin`` and ``mov_multiplier`` helpers; no
  duplicate Elo math remains.
- **E. Exposure metadata.** Prediction rows now record
  ``training_rows_available_before_block``,
  ``training_season_min/max``, ``training_block_count``,
  ``prior_completed_games_count`` for the *prior* state only.
- **F. Content fingerprint.** ``code_fingerprint`` now hashes file
  bytes (not paths) and is independent of the absolute checkout
  location.
- **G. No hard-coded paths.** ``run_development_walk_forward`` takes
  a ``project_root`` argument.
- **H. Independent replay.** ``independent_replay_from_pregame``
  recalculates ``elo_after`` from pregame inputs and raises
  ``StateLedgerCorruptionError`` on mismatch.
- **J. Tie / warm-up terminology.** The scorecard reports
  ``predicted_games``, ``target_unavailable_games``,
  ``binary_scored_games``, ``ties_excluded_from_binary_metrics``,
  ``warmup_excluded_games`` (warmup = 0).

Additionally a hard correctness gate
(``_validate_state_ledger_correctness``) runs immediately before the
state ledger is persisted; a violation raises
``StateLedgerCorruptionError`` and prevents the ledger from being
written.

### Corrected development metrics (2018–2024)

- Predicted games: **1942**
- Binary-scored games: **1935**
- Ties (excluded from binary metrics): **7**
- Target-unavailable games: **0**
- Warm-up excluded games: **0**
- Brier score: **0.2240**
- Log loss: **0.6397**
- Descriptive accuracy: **0.6351**
- Calibration intercept: **0.4822**
- Calibration slope: **0.2158**

Manifest fingerprints:

- `model_code_fingerprint`: `91773cfd4361d7184673f969add48b632533fceca056fb90a4cd609b7286bf7c`
- `feature_code_fingerprint`: `1ee67408974b9183be61ad54963ddae5e7aa093d8518edef8948b07ce2c9a921`
- `backtest_code_fingerprint`: `37ae010aab76a75923ad34f2dd56a8536df9e305889e470fbf9c61642563aa78`

The 2025 holdout was not fit, predicted, scored, calibrated, or
reported. The poison test (corrupting every 2025 row) is preserved
in `tests/holdout/test_2025_sealed.py` and continues to pass.
