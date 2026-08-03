# Modeling Gap Report — Task 03A

## Status
The QB-Elo v1 baseline is **proven** on the 2018–2024 development period.
The 2025 season is sealed holdout and will be evaluated in a separate
dedicated task.

## What This Report Covers
- Features that are **available** for the 2025 forward-use season.
- Features that are **missing** in the Task 02 feature output and that
  would improve the QB adjustment.
- Where the current QB-Elo assumes zero (neutral) and why.

## Confirmed Pregame QB Knowledge

| Source | Pregame? | Available in 2018–2024? | Available in 2025? |
| --- | --- | --- | --- |
| Confirmed starter (depth chart) | Yes | ~0 / 2,227 | ~0 / 285 |
| Two-deep practice report | Yes | ~0 / 2,227 | ~0 / 285 |
| Injury report (game-day) | Yes | ~0 / 2,227 ~ low | ~0 / 285 |
| Postgame `starter_id` | NO | 2,226 / 2,227 | unknown |
| Schedule `starter_id` | maybe | Sealed | Sealed |

The overwhelming majority of rows have `starter_certainty =
POSTGAME_ONLY_EVIDENCE`. This is documented in the Task 02 gap report.

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

## Scorecard Reference Values (Development)
From the Task 03A run on 2018–2024:
- Predicted games: 1,942
- Scored games: 1,942
- Ties: 7
- Brier score: ~0.24
- Log loss: ~0.67
- Descriptive accuracy: ~0.66

These are raw Elo output with no calibration. The QB-Elo baseline will
serve as the reference Brier for the Brier Skill Score (BSS) of all
future models. A model that scores worse than Elo is a regression.

## Limitations
- No XGBoost, no opponent adjustment, no calibration, no stacking.
- QB adjustment is neutral for all 2018–2024 games.
- 2025 is not evaluated here.
- No market data of any kind is used.

## Recommended Next Step
Task 03B: opponent-adjusted expected margin model on the same walk-forward
infrastructure, scored against the QB-Elo baseline via Brier Skill Score.
