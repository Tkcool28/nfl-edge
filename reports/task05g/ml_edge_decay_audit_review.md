# Task05G ML Edge Decay Audit Review

Verdict: `ML_PROBABILITY_CALIBRATION_HEALTHY_BUT_VALUE_EDGE_NONSTATIONARY`

This is a read-only diagnostic follow-up to the failed Model Confidence + Selector V2 confirmation. No Task05F evaluator, football model, selector threshold, candidate region, price tolerance, or data was changed. 2025 remained sealed.

## Evidence identity

- Corrected workflow: `32810380687` — SUCCESS
- Evidence artifact: `9549603324`
- Artifact digest: `sha256:3c0dcea36f8ec0062d0668f05f5e79e3b1a144a765f820388d824796a3567d3d`
- Corrected audit head: `3a013486f6506633deca37ba9cbfe5fae71a3ff9`
- Actual Value-card ML selection parity asserted in CI:
  - development 2020-2022: 40 ML headlines
  - confirmation 2023-2024: 18 ML headlines

## 1. General model-only ML probability calibration is healthy

The model-confidence ML probability is not showing the spread-style overconfidence failure.

| Model-confidence bucket | Avg predicted | Actual win rate | Predicted - actual |
|---|---:|---:|---:|
| <45% | 33.15% | 32.17% | +0.97pp |
| 45-50% | 47.52% | 46.85% | +0.67pp |
| 50-55% | 52.48% | 53.15% | -0.67pp |
| 55-60% | 57.55% | 58.96% | -1.41pp |
| 60-65% | 62.48% | 63.46% | -0.98pp |
| 65-70% | 67.36% | 71.51% | -4.15pp |
| >=70% | 77.39% | 76.11% | +1.28pp |

This supports the prior V2 scorecard finding that the QB-Elo/XGB model-only ML calibration is broadly stable. There is no basis here to replace or globally shrink ML confidence merely because the Value betting stream failed.

## 2. The ML Value-eligible population is strongly nonstationary

The exact-shopped ML pool satisfying the V2 Value economic gates contained 260 wagers overall and returned +2.76% ROI, but the result varies sharply by season:

| Season | N | Hit rate | ROI | Avg model confidence | Avg break-even | Avg model-price gap | Avg evaluator EV |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2020 | 24 | 62.50% | **+40.07%** | 53.52% | 45.74% | +7.78pp | +9.03% |
| 2021 | 89 | 52.81% | **+26.29%** | 54.00% | 43.89% | +10.11pp | +8.73% |
| 2022 | 88 | 37.50% | **-13.96%** | 51.04% | 42.35% | +8.68pp | +5.66% |
| 2023 | 34 | 23.53% | **-46.67%** | 50.77% | 43.38% | +7.38pp | +1.93% |
| 2024 | 25 | 52.00% | **+9.20%** | 54.63% | 47.58% | +7.05pp | +1.10% |

The edge deterioration therefore begins before 2023: 2022's admitted ML Value population was already negative. 2023 was the extreme collapse, followed by a partial 2024 recovery.

This is not consistent with a globally broken win-probability model. It is consistent with nonstationarity in the conditional proposition: `model probability exceeds available price break-even by X -> profitable wager`.

## 3. The actual cross-market Value selector amplified the regime break

The corrected audit reproduces the real V2 Value selector across both ML and spread first, then isolates the weeks on which ML actually won the headline.

### Development 2020-2022

- 40 actual ML headlines
- aggregate ROI: **+41.86%**

By season:
- 2020: 6 ML headlines, 4-2, +45.97%
- 2021: 18, 11-7, +45.39%
- 2022: 16, 9-7, +36.35%

Notably, the selector rescued the otherwise-negative 2022 ML Value-eligible pool by choosing a profitable subset.

### Untouched confirmation 2023-2024

- 18 actual ML headlines
- aggregate ROI: **-58.12%**

By season:
- 2023: 12 ML headlines, **1-11, -85.00%**
- 2024: 6, 3-3, -4.37%

The 2023 selected ML headlines averaged:
- model confidence: 53.78%
- exact-offer break-even: 46.75%
- model-price gap: +7.03pp
- evaluator EV: only +2.15%
- average American odds: +66

This is important: unlike spread, the selected ML stream was **not** claiming 75-80% confidence. The probabilities themselves were moderate. The failure was that a historically profitable model-vs-price disagreement ceased translating into realized betting profit in 2023.

## 4. Frozen candidate-family evidence already warned about this decay

Across the full 2020-2024 sample, the evaluator can still identify profitable subsets inside the frozen model families:

- `ML_DOG_VALUE_ZONE_AVG` Value-eligible: 76 rows, +16.87% ROI
- `ML_DOG_VALUE_ZONE_CORROB`: 45, +12.33%
- `ML_AVG_DISAGREEMENT_AVG_0_2`: 50, approximately flat (-0.60%)

Among actual Value-selected ML headlines over all five seasons:

- dog AVG family: 24 rows, +30.29%
- corroborated dog family: 12, +41.92%
- AVG disagreement 0-2: 15, +7.84%

However, the previously frozen Task05E season evidence shows the dog families themselves deteriorated sharply later:

- ML dog AVG: 2023 -28.55%, 2024 -15.72%
- corroborated dog: 2023 -25.59%, 2024 -42.00%

Thus the all-period profitability of these families masks a substantial regime change. A selector trained on the aggregate historical edge can remain logically correct according to the old relationship while becoming economically wrong in later seasons.

## 5. Price-gap magnitude is informative historically but is not a post-hoc rule

Across all 260 V2 ML Value-eligible wagers:

- model-price gap 0-2pp: -28.06% ROI
- 2-5pp: -0.97%
- 5-8pp: +0.61%
- 8-12pp: -0.42%
- >=12pp: +24.31%

Across the 58 actual Value-selected ML headlines:

- 0-2pp: -5.78%
- 2-5pp: -5.83%
- 5-8pp: -19.06%
- 8-12pp: +31.10%
- >=12pp: +29.38%

This suggests stronger model-price disagreement may contain more durable signal, but no new minimum-gap threshold is adopted from these same outcomes. It requires a separately preregistered development/confirmation test if pursued.

## 6. Odds composition is not a single clean explanation

Across the full Value-eligible ML population:

- +101 to +150: +7.98% ROI
- +151 to +200: +10.52%
- >+200: -10.81%
- -200 to -151: approximately flat (+0.58%)
- -150 to -111: -9.62%

Across actual selected ML headlines:

- +101 to +150: +28.78%
- +151 to +200: -19.60%
- >+200: +40.00%
- -200 to -151: -4.25%
- -150 to -111: -23.51%

There is no defensible single odds cutoff that explains the 2023 collapse without further chronology-specific testing.

## 7. Root-cause interpretation

### What is healthy

- General model-only ML win-probability calibration.
- The conceptual separation of football-model confidence from sportsbook-implied probability.

### What is not stable

- The assumption that historical ML model-vs-price disagreement implies the same betting edge in later seasons.
- Frozen dog/value candidate families were highly profitable early and materially negative in 2023-2024.
- V2 Value selection inherited that nonstationarity and suffered a 1-11 ML collapse in 2023.

### What should not be done

- Do not globally shrink or replace ML probability calibration based on Value ROI.
- Do not retune Task05F evaluator weights from these outcomes.
- Do not select a post-hoc minimum model-price gap or odds cutoff from the same 2020-2024 sample.

## 8. Recommended next design question

The ML problem is now best framed as **edge persistence / regime validation**, not probability calibration.

A future preregistered Value experiment should test whether a candidate family's betting-edge authorization needs strictly prior evidence of current persistence before it can supply Value headlines. Examples of diagnostic inputs to preregister—not adopted here—include:

- recent strictly-prior candidate-family performance/calibration;
- minimum current model-price disagreement;
- agreement between independent football models;
- whether the candidate family is improving, stable, or deteriorating across chronological blocks.

The goal should be to preserve the healthy ML probability model while preventing historical 2020-2021 betting edges from being treated as permanently stationary.