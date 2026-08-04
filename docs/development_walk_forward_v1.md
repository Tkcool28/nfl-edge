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


## Remediation Pass — 2026-08-03

The Task 03A contracts below were corrected in the PR #4 final remediation
pass. **All earlier calibration and replay claims are superseded.**

### Corrections implemented

- **Logistic calibration** is now a deterministic Newton-Raphson / IRLS fit
  on the binomial log-likelihood with explicit `max_iter=100`, `tol=1e-9`,
  probability clamp `[1e-9, 1-1e-9]`, finite-value checks, and no silent
  0/1 substitution. The earlier OLS-on-logits approach is retired.
  Calibration remains a diagnostic, not a production model input.
- **Actual-margin persistence.** The prediction ledger and the state
  ledger both persist `actual_margin` (signed home margin). The
  `signed_margin` field name and the ambiguous `is_scored` flag are
  retired; `is_binary_scored` excludes ties.
- **Clean independent replay.** `independent_replay_from_pregame` now
  reconstructs every persisted field from the pregame inputs and the
  persisted `actual_margin`. The replay validator
  (`detect_state_ledger_corruption`) checks `elo_before`,
  `expected_result`, `actual_result`, `update_multiplier`, `k_factor`,
  `elo_change`, `elo_after`, and the `actual_margin` consistency
  between the two side rows. Clean full 2018–2024 ledger produces
  zero mismatches.
- **Targeted corruption coverage.** Per-field corruption tests trip
  the validator with messages that name the game_id, side, field,
  and expected vs actual value for: home/away `elo_before`,
  `expected_result`, `actual_result`, `update_multiplier`, `k_factor`,
  `elo_change`, `elo_after`, `actual_margin`, missing home row,
  missing away row, duplicate home row, duplicate away row, orphan
  state row.
- **Repeated-team rejection.** A repeated team within a single
  prediction block raises `RepeatedTeamInPredictionBlockError` before
  any prediction row is written and before any state mutation. The
  error message names the block ID, the repeated team, and the
  affected game IDs. The real 2018–2024 dataset has zero
  repeated-team violations across 173 blocks.
- **Distinct training_block_count.** `training_block_count` counts
  distinct `(season, season_type, week)` keys; it is no longer a
  raw row count.
- **Canonical ledger writer.** The walk-forward engine is the only
  caller of `build_prediction_ledger`, `build_state_ledger`, and
  `write_ledger`; an alternate direct `pl.DataFrame.write_parquet`
  path is impossible. Per-row schema validation runs on every row,
  not just the first.
- **Full-range reliability buckets.** The reliability diagram now
  uses 10 buckets covering `[0.00, 1.00]` with the final bucket
  closed on the right. Probability 1.0 belongs in the final bucket.
  Empty buckets report `null` (not 0.0).
- **Deterministic artifacts.** Two independent runs in
  `/tmp/nfl-edge-pr4-run-a` and `/tmp/nfl-edge-pr4-run-b` produce
  byte-identical artifacts for all 7 output files.

### Corrected metrics and hashes

- Brier: 0.22395817969967416
- Log loss: 0.6396560960306621
- Descriptive accuracy: 0.635142118863049
- Calibration intercept: -0.08163555069431239
- Calibration slope: 0.9669825702467028
- Calibration fit status: converged (4 iterations)
- Predictions: 1942; transitions: 3884; ties: 7; binary-scored: 1935
- Prediction parquet SHA-256: `08ce867f32e5f44e9019ee1d1deaa4501e238d55ab8ecc948b9aca28384f0f26`
- State parquet SHA-256:    `a1bce06062cd6bd2a451f3a3b29fc2752adadbd64552cda9eccd3118c07c0927`
- Manifest SHA-256:         `cec593b071128c26c4889e67f812b9397acd26e46e521bfd2c0c136cbec09a62`
- Tuning ledger SHA-256:    `b46bced9d83abe7184519bf5f89f2cc3399749d54aedb10e9ebdafe4eb2320b0`
- Scorecard JSON SHA-256:   `1f6dad38426105268376d11d3e9a71bc4efbf413e0e755c4f60e3ae0dd77be2b`
- Scorecard MD SHA-256:     `d7b95a150bf92afc72c9a6600b4d4a84c1700864a9a0d436a58e1b05ea633363`
- Reliability CSV SHA-256:  `5ac82d5c5fa2e25d4ca4b30cb16f474b566d908d5864f8e7659541ae74e679b4`

The QB adjustment remains neutral because every development row
carries `qb_certainty_state=UNKNOWN`.
