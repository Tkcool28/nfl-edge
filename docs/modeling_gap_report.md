# Modeling Gap Report — Task 03A

## Status
The QB-Elo v1 baseline has been **executed** on the 2018–2024
development period. The 2025 season is sealed holdout and is not
evaluated in this report. The scorecard numbers below are the
**actual** ledger values, not approximate.

## What This Report Covers
- Features that are **available** for the 2025 forward-use season.
- Features that are **missing** in the Task 02 feature output and that
  would improve the QB adjustment.
- Where the current QB-Elo assumes zero (neutral) and why.

## Confirmed Pregame QB Knowledge

| Source | Pregame? | Available in 2018–2024? | Available in 2025? |
| --- | --- | --- | --- |
| Confirmed starter (depth chart) | Yes | 0 / 1,942 | not consulted |
| Two-deep practice report | Yes | 0 / 1,942 | not consulted |
| Injury report (game-day) | Yes | 0 / 1,942 | not consulted |
| Postgame `starter_id` | NO | 1,942 / 1,942 | not consulted |
| Schedule `starter_id` | maybe | not consulted | not consulted |

The entire 2018–2024 development prediction ledger has `qb_certainty_state = UNKNOWN`.
No pregame starter is confirmed in the development data.

## Why QB-Elo Uses Neutral Adjustment
Because no pregame starter is confirmed in the development data, the
model applies `qb_adjustment = 0.0` for every prediction. This is
documented conservative behavior and matches the Task 03A spec.

## What Would Close the Gap
1. **Pregame depth chart ingestion.** A reliable source of who is
   starting (e.g., the team's own injury report on Fridays) would
   unlock real QB adjustments.
2. **Historical QB-EPA recomputation.** With confirmed starters, we
   could compute `n_games`, `expected_epa`, and `prior_epa` per team
   and feed the QB adjustment formula.
3. **Opponent-adjusted expected margin.** This is Task 03B and will
   use the same walk-forward engine.
4. **XGBoost base model.** Task 03C.

## Deferred Historical QB-Retraining Milestone

After the live Sleeper source has been proven end to end, perform a
separate historical QB-evidence reconstruction audit before changing
the baseline model. The audit should determine whether nflverse depth
charts, historical injury reports, stable player IDs, and only evidence
available before each game can defensibly identify the expected starter
for 2018–2024.

Only if that audit proves adequate point-in-time coverage should the
project:

1. rebuild historical starter-certainty states;
2. join each expected starter to prior-game QB metrics;
3. rerun QB-adjusted Elo across the 2018–2024 development walk-forward;
4. compare the reconstructed QB-adjusted version against the current
   neutral-QB Elo baseline using Brier score, log loss, calibration, and
   retained prediction ledgers;
5. preserve 2025 as sealed holdout throughout the audit and retraining.

This milestone is intentionally deferred until the Sleeper live source
probe is complete. Sleeper's current-state API must not be assumed to
provide historical injury snapshots.

## Exact Scorecard (Development)

From the Task 03A run on 2018–2024 (source-of-truth:
`reports/development/qb_elo_development_scorecard.json`):

- Predicted games: 1,942
- Scored games: 1,935
- Ties: 7
- Brier score: 0.2254
- Log loss: 0.6429
- Descriptive accuracy: 0.6305
- Calibration intercept: 0.4833
- Calibration slope: 0.2143

These are raw Elo output with no calibration transformation applied.
The QB-Elo baseline will serve as the reference Brier for the Brier
Skill Score (BSS) of all future models. A model that scores worse than
Elo is a regression.

## Per-Season Numbers

| Season | Predicted | Scored | Ties | Accuracy | Brier |
| --- | --- | --- | --- | --- | --- |
| 2018 | 267 | 265 | 2 | 0.6264 | 0.2282 |
| 2019 | 267 | 266 | 1 | 0.6353 | 0.2243 |
| 2020 | 269 | 268 | 1 | 0.6530 | 0.2194 |
| 2021 | 285 | 284 | 1 | 0.6092 | 0.2308 |
| 2022 | 284 | 282 | 2 | 0.6064 | 0.2268 |
| 2023 | 285 | 285 | 0 | 0.6070 | 0.2343 |
| 2024 | 285 | 285 | 0 | 0.6772 | 0.2136 |

## QB-Certainty Coverage

| Certainty | Predicted | Scored |
| --- | --- | --- |
| `UNKNOWN` | 1,942 | 1,935 |

The entire 2018–2024 prediction ledger is `UNKNOWN`. This is the
documented behavior of the current Task 02 feature output.

## Limitations
- No XGBoost, no opponent adjustment, no calibration transformation, no stacking.
- QB adjustment is neutral for all 1,942 game predictions.
- 2025 is sealed holdout and is not evaluated in this report.
- No market data of any kind is used.
- No market comparison, ROI, CLV, or sportsbook comparison is produced.

## Recommended Next Step
Complete the bounded Sleeper live-source audit and prove that current QB
injury, practice, roster, and depth evidence can be collected reliably
before wiring it into model scoring. After the live source is proven,
return to the deferred historical QB-retraining milestone above.

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
- Log loss: **0.6397** (full: 0.6396560960306621)
- Descriptive accuracy: **0.6351** (full: 0.635142118863049)
- Calibration intercept: **-0.0816** (full: -0.08163555069431239)
- Calibration slope: **0.9670** (full: 0.9669825702467028)
- Calibration fit status: **converged** in 4 iterations

The earlier "calibration intercept 0.4822 / slope 0.2158" was the
output of an OLS-on-logits fit. The 2026-08-03 remediation replaced
that with a deterministic Newton-Raphson / IRLS binomial fit; the
earlier numbers are **superseded**.

Manifest fingerprints:

- `model_code_fingerprint`: `91773cfd4361d7184673f969add48b632533fceca056fb90a4cd609b7286bf7c`
- `feature_code_fingerprint`: `1ee67408974b9183be61ad54963ddae5e7aa093d8518edef8948b07ce2c9a921`
- `backtest_code_fingerprint`: `37ae010aab76a75923ad34f2dd56a8536df9e305889e470fbf9c61642563aa78`

The 2025 holdout was not fit, predicted, scored, calibrated, or
reported. The poison test (corrupting every 2025 row) is preserved
in `tests/holdout/test_2025_sealed.py` and continues to pass.


## Remediation Pass — 2026-08-03

The independent-review findings on PR #4 are resolved in the final
remediation commit. Earlier calibration and replay claims are
superseded by the corrected contracts.

### Resolved

- **Calibration is now a deterministic Newton-Raphson / IRLS
  binomial fit** (converged in 4 iterations; status `converged`).
  The earlier OLS-on-logits fit is retired.
- **`actual_margin` is persisted** in both the prediction and state
  ledgers. `signed_margin` and the ambiguous `is_scored` flag are
  retired; `is_binary_scored` excludes ties.
- **Clean independent replay succeeds** before any targeted
  corruption. The replay validator checks `elo_before`,
  `expected_result`, `actual_result`, `update_multiplier`, `k_factor`,
  `elo_change`, `elo_after`, and the `actual_margin` consistency
  between the two side rows. Clean full 2018–2024 ledger produces
  zero mismatches.
- **Targeted corruption coverage**: per-field corruption trips the
  validator with messages that name the game_id, side, field, and
  expected vs actual value (tests in
  `tests/models/test_targeted_corruption.py`).
- **Repeated-team rejection** is enforced before any prediction row
  is written and before any state mutation. Real 2018–2024 data has
  zero violations across 173 blocks.
- **Distinct `training_block_count`** counts distinct
  `(season, season_type, week)` keys, not raw rows.
- **Canonical ledger writer contract** is the only path: the engine
  calls `build_prediction_ledger` / `build_state_ledger` /
  `write_ledger`; per-row schema validation runs on every row.
- **Full-range reliability buckets**: 10 buckets covering
  `[0.00, 1.00]` with the final bucket closed on the right; empty
  buckets report `null`.

### Corrected metrics and hashes

- Predictions: 1942; transitions: 3884; ties: 7; binary-scored: 1935
- Brier: 0.22395817969967416
- Log loss: 0.6396560960306621
- Accuracy: 0.635142118863049
- Calibration: intercept -0.08163555069431239, slope 0.9669825702467028,
  fit status `converged` (4 iterations)
- Prediction parquet SHA-256: `08ce867f32e5f44e9019ee1d1deaa4501e238d55ab8ecc948b9aca28384f0f26`
- State parquet SHA-256:    `a1bce06062cd6bd2a451f3a3b29fc2752adadbd64552cda9eccd3118c07c0927`
- Manifest SHA-256:         `cec593b071128c26c4889e67f812b9397acd26e46e521bfd2c0c136cbec09a62`
- Scorecard JSON SHA-256:   `1f6dad38426105268376d11d3e9a71bc4efbf413e0e755c4f60e3ae0dd77be2b`
- Scorecard MD SHA-256:     `d7b95a150bf92afc72c9a6600b4d4a84c1700864a9a0d436a58e1b05ea633363`
- Reliability CSV SHA-256:  `5ac82d5c5fa2e25d4ca4b30cb16f474b566d908d5864f8e7659541ae74e679b4`

The QB adjustment remains neutral because every development row
carries `qb_certainty_state=UNKNOWN`.

The 2025 holdout remains sealed: no fit, predict, score, calibrate,
tune, or report on 2025. The poison test in
`tests/holdout/test_2025_sealed.py` continues to pass.
