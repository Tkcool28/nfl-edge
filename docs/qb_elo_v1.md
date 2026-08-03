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
