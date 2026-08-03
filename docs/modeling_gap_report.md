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
Task 03B: opponent-adjusted expected margin model on the same walk-forward
infrastructure, scored against the QB-Elo baseline via Brier Skill Score.
