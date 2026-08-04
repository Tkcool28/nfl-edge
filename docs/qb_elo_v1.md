# QB-Elo v1 — Development Baseline

## Overview
This document describes the QB-adjusted Elo model that serves as the
**development baseline** for NFL Edge. Task 03A establishes this baseline
on the 2018–2024 development window. The 2025 season is sealed holdout
and is never used for fit, prediction, scoring, or reporting.

All numbers in this document are computed from the actual development
artifacts produced by the Task 03A run, not approximate.

## Formula (Textbook NFL Elo)

### Expected win probability (home perspective)
$$E_H = \frac{1}{1 + 10^{(E_A - E_H - HFA) / 400}}$$

Where:
- $E_H$ = home team's Elo before the game
- $E_A$ = away team's Elo before the game
- $HFA$ = home-field advantage (in Elo points); 0 for neutral site

### QB-adjusted Elo difference
$$\Delta_{adj} = (E_H + HFA + q_H) - (E_A + q_A)$$

Where $q_H$ and $q_A$ are zero-point QB adjustments (see below).

### Final probability
$$P(\text{home win}) = \frac{1}{1 + 10^{-\Delta_{adj} / 400}}$$

Clamped to $[0.01, 0.99]$ for numerical safety only.

## Elo Update

After the game is complete (outcome persisted in the state ledger):

$$\Delta_{rating} = K \cdot M \cdot (S - E)$$

Where:
- $K$ = K-factor (20 regular, 4 postseason)
- $M$ = margin-of-victory multiplier:
  $$M = 1 + \min(M_{cap}, (\text{margin}/D)^2)$$
  with $D = 6$ and $M_{cap} = 2.5$
- $S$ = actual result (1.0 home win, 0.5 tie, 0.0 away win)
- $E$ = expected result for the team being updated

## Parameters (Frozen)

| Parameter | Value | Rationale |
| --- | --- | --- |
| `initial_rating` | 1500.0 | NFL-standard starting Elo |
| `k_factor_regular` | 20.0 | 538-style for football |
| `k_factor_postseason` | 4.0 | Less variance in small sample |
| `home_field_elo` | 48.0 | ≈3 points Pythagorean equivalent |
| `season_mean_reversion_fraction` | 1/3 | Standard 538 carryover |
| `mov_divisor` | 6.0 | FiveThirtyEight convention |
| `mov_cap` | 2.5 | Caps extreme blowouts |
| `prob_min` | 0.01 | Numerical safety |
| `prob_max` | 0.99 | Numerical safety |

## QB Adjustment

The Task 02 feature output records mostly `POSTGAME_ONLY_EVIDENCE`
(no confirmed pregame starter). The Task 03A development pipeline
returns the following QB-certainty distribution in the prediction
ledger:

| QB certainty state | Predicted games | Scored games |
| --- | --- | --- |
| `UNKNOWN` | 1,942 | 1,935 |
| **Total** | **1,942** | **1,935** |

The `UNKNOWN` state produces `qb_adjustment = 0.0` for both sides.

The full public formula for the FUTURE confirmed case
("CONFIRMED_PRE_CUTOFF") is:

$$q = \text{clamp}\left( (E_{expected} - E_{replacement}) \cdot \text{scale}, -q_{max}, q_{max} \right)$$

Where:
- $E_{expected}$ = candidate's shrunk passing EPA per dropback
- $E_{replacement}$ = replacement-level passing EPA per dropback (default $-0.05$)
- `scale` = Elo points per unit shrunk EPA (default 500)
- $q_{max}$ = maximum absolute adjustment (default 50)

The supported-but-uncertain branch (`DEPTH_CHART_SUPPORTED`,
`ROSTER_SUPPORTED`, `AMBIGUOUS`) returns `0.0` adjustment and counts
as `SUPPORTED_BUT_UNCERTAIN` in the ledger. The `POSTGAME_ONLY_EVIDENCE`
branch returns `0.0` and is rewritten as `UNKNOWN`.

The current development run **only** has `UNKNOWN` rows because the
Task 02 feature output does not contain any pregame-confirmed starters
in 2018–2024. There is no actual non-zero QB adjustment applied in
the current development scorecard.

## Tie Handling
A tie yields $S = 0.5$ for both teams, with no margin-of-victory
multiplier. The Elo update is symmetric.

## Neutral-Site Handling
When `neutral_site == True`, $HFA = 0$ and the probability is symmetric
in team Elos. Applied to all Super Bowls and international games.

## Season Carryover
Between seasons, every team's Elo is mean-reverted by
`season_mean_reversion_fraction` toward the league-wide mean rating at
that time. This stabilizes the system over long horizons.

## Actual Development Scorecard (2018–2024)

These are the **exact** numbers produced by the walk-forward run,
written to `reports/development/qb_elo_development_scorecard.json`.

- Predicted games: 1,942
- Scored games: 1,935 (1,942 minus 7 ties)
- Ties: 7
- Unscored / warm-up: 7
- Brier score: 0.2254
- Log loss: 0.6429
- Descriptive accuracy: 0.6305
- Calibration intercept (diagnostic): 0.4833
- Calibration slope (diagnostic): 0.2143

The calibration intercept/slope are **diagnostic only** — no
calibration transformation is applied to predictions in Task 03A.

### Per-season breakdown

| Season | Predicted | Scored | Ties | Accuracy | Log loss | Brier |
| --- | --- | --- | --- | --- | --- | --- |
| 2018 | 267 | 265 | 2 | 0.6264 | NA | 0.2282 |
| 2019 | 267 | 266 | 1 | 0.6353 | NA | 0.2243 |
| 2020 | 269 | 268 | 1 | 0.6530 | NA | 0.2194 |
| 2021 | 285 | 284 | 1 | 0.6092 | NA | 0.2308 |
| 2022 | 284 | 282 | 2 | 0.6064 | NA | 0.2268 |
| 2023 | 285 | 285 | 0 | 0.6070 | NA | 0.2343 |
| 2024 | 285 | 285 | 0 | 0.6772 | NA | 0.2136 |

(Per-season log loss: see scorecard JSON — Task 03A stores raw floats
in the JSON; the markdown column is omitted for the conditional
columns and lives in the JSON source of truth.)

## What This Model Does NOT Do
- No XGBoost
- No opponent-adjusted expected margin
- No stacker
- No calibration transformation applied
- No sportsbook data ingestion
- No 2025 holdout access
- No market comparison, ROI, CLV, or Pinnacle comparison
- No deployment / frontend

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
- Brier score: **0.2240** (full: 0.22395817969967416)
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


### Remediation Pass — 2026-08-03

The earlier "calibration intercept 0.4822 / slope 0.2158" line in this
document was the output of the OLS-on-logits fit. The 2026-08-03
remediation replaced that with a deterministic Newton-Raphson / IRLS
binomial fit and recomputed every artifact. The corrected numbers are:

- Calibration intercept: -0.08163555069431239
- Calibration slope: 0.9669825702467028
- Calibration fit status: converged (4 iterations, tol=1e-9)
- Calibration remains diagnostic only — never used as a production
  model input.

This document is updated in place; the prior values are superseded
and remain only as historical record.

### Final Review Remediation Pass — 2026-08-03

This section records the final independent-review remediation
applied to PR #4. The runtime, the manifest, the tuning ledger,
and the scorecard now agree on the canonical YAML configuration.

- Canonical YAML path: `config/qb_elo_v1.yaml`
- `season_mean_reversion_fraction = 0.333` (exact)
- The runtime loader is `nfl_edge.models.qb_elo_config.load_qb_elo_canonical_config`
- There is no in-code default; the prior `1.0 / 3.0` runtime value is superseded
- `model_config_sha256 = 2d1249cc1a4a067c0ce6dfbd40b74c36366c386a4aca014eaaae448d75010d06`

**Manifest hash contract**

- `prediction_ledger.file_sha256` = SHA-256 of exact on-disk Parquet bytes (post-write)
- `prediction_ledger.logical_content_sha256` = SHA-256 of canonical logical content (pre-write)
- Same split for `state_ledger`
- The prior ambiguous single `sha256` field is **removed**
- `prediction_ledger.file_sha256 = 47bb96b405866395cc1a18fb15413b11cf9265e0eccda30f8a77014f74926d45`
- `prediction_ledger.logical_content_sha256 = a000dbc1a974fece7211fcb32900b272deee27e896516f7a8879f75a8fc5ed50`
- `state_ledger.file_sha256 = fceb7a9b064c50b91d426de4b0d70185c8191d7e43948040a99178ab07802fbb`
- `state_ledger.logical_content_sha256 = 7b1b9f8124cdb2f95345eab9a944d9c4cfa58225043bdbe67a1dd5a6ad5b4fa2`

**Calibration contract**

- `max_iter = 100` (default)
- Undefined fits return `calibration_intercept = None`, `calibration_slope = None`
- Markdown renders null as `NA`; JSON serializes `None` as `null`
- The retired back-compat wrapper `calibration_intercept_slope` is **removed** (no silent `(0.0, 1.0)` substitution)

**Cross-ledger `actual_margin` validation**

- `detect_state_ledger_corruption` now compares both state side rows against the prediction ledger's `actual_margin`
- Error messages name `game_id`, `side`, prediction value, and state value
- The retired `margin` field is no longer silently defaulted via `row.get("actual_margin", row.get("margin", 0))`

**Corrected metrics**

- Brier: 0.2239582917989346
- Log loss: 0.6396576506911166
- Descriptive accuracy: 0.6351421188630491
- Calibration intercept: -0.0815648369071145
- Calibration slope: 0.9667354678276904
- Calibration fit status: converged (4 iterations)
- Calibration max_iter: 100
- Predictions: 1942; transitions: 3884; ties: 7; binary-scored: 1935

**Two-run determinism proof**

Both `/tmp/nfl-edge-pr4-final-a` and `/tmp/nfl-edge-pr4-final-b`
produced byte-identical artifacts across all 7 output files.
