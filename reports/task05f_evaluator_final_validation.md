# Task05F Evaluator Final Validation

Verdict: `MARKET_EVALUATION_LAYER_V1_READY_FOR_REVIEW`

Validated branch: `feat/task05f-evaluator-freeze-v1`
Validated head before this evidence-only commit: `d441d3bb89d085b4526b9ce6e6a8ec83bca9dcbe`
Base main: `eab5f719d8695df484f10cade39ee0322d2841fa`
Validation workflow run: `32589445431`
Validation result: PASS

## Frozen evaluator families

- Moneyline: `ml_v4`
- Spread: `spread_v3`
- Total: `total_v3`

No football-model family was changed or retuned in this task.

## Scope and chronology gates

- Development seasons only: 2020, 2021, 2022, 2023, 2024.
- 2025 remained sealed and was not loaded for evaluator validation.
- Expanding strictly-prior season-week blocks only.
- Scope enforcement passed: no frozen football-model, frozen data/evidence, selector, staking-profile, user-staking, product-simulation, or selector-board files entered the implementation diff.

## Runtime contract

- Production arbitrary-offer entry point: `evaluate_offer(...)`.
- Stored and manual exact offers use the same runtime path.
- Manual/stored parity checks: 7,594.
- Complete replayable evaluator state is serialized, including point-market residual distributions.
- Integer Pinnacle spread/total lines use conditional-nonpush inversion with explicit push-cell semantics; half-point lines retain the closed-form no-push inversion.
- Exact actionable/manual point-market line participates in support/OOD checks.

## Reliability contract

Reliability is assigned once from accepted-family evidence:

1. accepted-family fit support/OOD,
2. accepted-family strictly-prior OOS uncertainty,
3. constituent disagreement where applicable.

No inherited `exact_avg` or `normal_cdf` reliability tier is combined with a second Phase-F tier.

Cold-start rows that are otherwise structurally supported remain supported at LOW reliability until enough accepted-family OOS evidence exists; reliability OOS evidence therefore accumulates without self-blocking.

Final supported reliability counts:

| Market | HIGH | MEDIUM | LOW | UNSUPPORTED |
|---|---:|---:|---:|---:|
| Moneyline | 0 | 1,314 | 888 | 614 |
| Spread | 32 | 1,618 | 898 | 268 |
| Total | 0 | 386 | 2,156 | 274 |

Final accepted-family OOS uncertainty state:

- Moneyline: radius 0.03714097, 80 blocks, 1,099 prior OOS observations, stable.
- Spread: radius 0.03078308, 100 blocks, 1,249 prior OOS observations, stable.
- Total: radius 0.02794131, 100 blocks, 1,260 prior OOS observations, stable.

## Probability scorecard

### Moneyline V4

Accepted probability:

- n = 2,198 scored non-ties
- Brier = 0.20649816
- log loss = 0.60172354
- AUC = 0.74293530
- calibration intercept ~= 0
- calibration slope = 1.06096605

Pinnacle market anchor on the same scored rows:

- Brier = 0.20650221
- log loss = 0.60175917
- AUC = 0.74291957

ML V4 remains the accepted moneyline fair-value base. It marginally improves Brier/log loss/AUC over the market anchor on this OOS board. It does not demonstrate a universal full-board +EV betting edge.

### Spread V3

Accepted probability:

- n = 2,499 non-push scored rows
- Brier = 0.25054670
- log loss = 0.69424259
- AUC = 0.49610856
- calibration slope = -0.05897242

Pinnacle-derived market anchor:

- Brier = 0.24982014
- log loss = 0.69278390
- AUC = 0.51088515

Spread V3 is not claimed to be a strong universal ATS probability model. It is retained as the accepted exact-offer evaluation/filter layer because it no longer reverses the previously frozen spread-model evidence and preserves useful value separation there.

Frozen `SPREAD_0_4_DISCOVERY_UNION` evidence after corrected integer-line semantics:

- baseline: n=800, ROI +5.54%
- supported: n=722, ROI +5.80%
- strict +EV kept: n=143, ROI +11.16%
- nonpositive-EV rejected: n=579, ROI +4.48%

Read-only contribution diagnostic:

- 71/100 supported blocks had spread beta exactly 0.
- 29/100 had positive spread beta.
- strict +EV kept in zero-beta blocks: 74 bets, ROI +9.84%.
- strict +EV kept in positive-beta blocks: 69 bets, ROI +12.58%.
- Expected Margin favored the evaluated frozen-region wager side on 134/143 strict +EV kept rows.

Interpretation: Expected Margin remains a separate football signal; Spread V3 remains an exact-offer evaluator/filter. The diagnostic was observational only and did not change beta, thresholds, buckets, or evaluator selection.

### Total V3

Accepted probability:

- n = 2,518 non-push scored rows
- Brier = 0.25045532
- log loss = 0.69406891
- AUC = 0.51034489
- calibration slope = 0.16330678

Total V3 remains accepted as the totals probability architecture but retains the label `TOTALS_VALUE_WEAK_NO_DEMONSTRATED_EDGE`. No EV threshold or historical bucket was added to manufacture a totals edge.

## Candidate and economics contract

- Candidate rows: 8,448.
- Candidate table is account-independent.
- DK/FD/Pinnacle offer identity and provenance are retained.
- Outcome columns are excluded from the production candidate table.
- Strict Value remains `expected_value > 0`.
- Pushes are refunds in spread/total EV.
- Frozen Play Through maximum break-even concession remains 0.015 probability points (1.5 percentage points).
- Play Through does not alter evaluator probabilities or strict Value semantics.

## Test and reproducibility evidence

Final workflow run `32589445431`:

- scope enforcement: PASS
- evaluator contract tests: 21 passed
- runtime compile: PASS
- chronological evaluator run A: PASS
- chronological evaluator run B: PASS
- byte/dataframe deterministic reproduction: PASS
- candidate outcome firewall: PASS
- read-only spread contribution diagnostic: PASS
- evidence artifact upload: PASS

Artifact ID: `9479923463`
Artifact ZIP SHA-256: `e3fb1ba38c4d1d88fbcbbb32fa4648f44e33343130d46b4b9eeb1f6024524620`

## Final Task05F boundary

This task stops at the evaluator/common-candidate boundary.

Not included here:

- HHR/Balanced/Value selector policy,
- headline-pick eligibility,
- recommendation strength/units,
- user risk profiles,
- bankroll-to-dollar conversion,
- product simulations,
- 2025 evaluation.

Those are downstream tasks and must not be inferred from this evaluator freeze.
