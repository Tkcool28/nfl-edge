# Task05F Model-Confidence Coverage Audit V1

**Verdict:** `VALID_DETERMINISTIC_DIAGNOSTIC / CURRENT_HHR_CONFIDENCE_AXIS_MISMATCH_CONFIRMED`

**Result label:** `OBSERVATIONAL_ONLY_NOT_TUNED`

This report records the designated 2020–2024 diagnostic comparison between the frozen football-model signal and the current Task05F evaluator/Selector V3.1 filtering. It does not tune any model, evaluator, Play Through rule, selector threshold, staking rule, or market bucket. Sealed 2025 remains unopened.

## 1. Designated execution

- PR: `#20` — `feat/task05f-evaluator-rebuild-v1`
- Designated branch head: `7533cfca5821a3eb8c5bb70a1f10ccd35c579868`
- PR merge-test SHA executed by Actions: `0faeddb550610415d04a7ae1369810adc086860c`
- Clean pre-audit contract SHA: `18f456307102a74608da1ae6e65150d93e117c72`
- Actions run: `32573369004`
- Actions job: `97032033437`
- Conclusion: `success`
- Value-layer tests: **219 passed in 3.11s**
- Two complete audits were run and compared; outputs were identical.
- Hard audit contracts: `PASS`
- Evidence artifact ID: `9475983791`
- Evidence artifact ZIP digest: `sha256:125d7c53fa33885a05a1a4a3a11dd8d81054af6989fbac1d562dae894b95477d`

## 2. Prior model facts that matter

### QB-Elo

The frozen QB-Elo development scorecard (2018–2024) reported:

- descriptive accuracy: **63.51%**
- Brier: **0.2240**
- log loss: **0.6397**
- calibration slope: **0.9667**

Its confidence buckets were directionally coherent: 0.60–0.70 predictions won 62.62%, 0.70–0.80 predictions won 76.43%, 0.80–0.90 predictions won 78.57%, and 0.90–1.00 predictions won 90.91%.

### Expected Margin

The frozen Expected Margin V1 stable development scorecard reported **60.14% accuracy**, but that metric is straight-up game-winner accuracy, not against-the-spread cover accuracy. It may not be used as evidence that a spread with a strong Expected Margin output has a 60%+ cover rate.

### ML V4 evaluator architecture

The accepted ML V4 fair-value probability is intentionally market-dominant. Exact AVG football-model weight was zero in 91/98 supported calibration blocks and final weight was zero. The V4 report explicitly retained the raw exact-AVG football probability as a separate axis rather than forcing it into the universal fair-value probability.

Therefore Task05F already had two different concepts by design:

1. football-model confidence — who the football model thinks is likely to win;
2. evaluator fair probability — a calibrated price/valuation anchor.

The current HHR selector was incorrectly using the second concept as its primary hit-rate ranking axis.

## 3. Raw exact-AVG model still behaves like the original football models

On the exact same 2020–2024 candidate universe, taking the selected-side raw exact AVG favorite for every game where both frozen component models were available produced:

- n = **1,233**
- W-L-P = **781-449-3**
- hit rate excluding pushes = **63.50%**

Fixed confidence buckets inherited from pre-existing model reliability reporting:

| Raw exact-AVG probability | n | Mean model p | W-L-P | Hit rate ex-push |
|---|---:|---:|---:|---:|
| 0.50–0.60 | 572 | 55.01% | 307-264-1 | 53.77% |
| 0.60–0.70 | 416 | 64.41% | 282-133-1 | 67.95% |
| 0.70–0.80 | 197 | 74.39% | 154-42-1 | 78.57% |
| 0.80–0.90 | 47 | 83.42% | 37-10-0 | 78.72% |
| 0.90+ | 1 | 90.40% | 1-0-0 | 100% |

These are historical diagnostics, not new cutoffs. The important structural result is that model-native confidence remains strongly ordered and has not been erased by the Task05F rebuild.

## 4. Top raw football-model pick per weekly slate

Across the 109 season-week slates:

### Raw model available

- 89 slates had a raw exact-AVG moneyline output
- top raw model pick per available slate: **71-17-1**
- hit rate excluding push: **80.68%**
- mean raw model probability: **76.52%**

### Restricted to current evaluator HIGH/MEDIUM reliability

- n = **33**
- top raw football-model pick: **27-6**
- hit rate: **81.82%**
- mean raw model probability: **75.11%**

### Restricted further to current VALUE/PLAYABLE + HIGH/MEDIUM actionability

- n = **33**
- top raw football-model pick within the filtered universe: **16-17**
- hit rate: **48.48%**
- mean raw model probability: **62.12%**

This is the clearest diagnostic evidence of the architecture mismatch. Requiring the current evaluator price-status/reliability universe before choosing the HHR candidate switches away from the strongest model-native winner signal and collapses hit-rate performance in this development sample.

No historical threshold is created from this result.

## 5. Current High Hit Rate card

Current V3.1 HHR:

- n = **57**
- W-L = **31-26**
- hit rate = **54.39%**

### Moneyline portion

- n = **30**
- W-L = **18-12**
- hit rate = **60.00%**
- mean evaluator/actionable probability = **71.40%**
- mean raw exact-AVG football probability = **60.68%**

The realized 60% is much closer to the football-model confidence than to the 71.4% evaluator probability. The evaluator probability is not a valid replacement for football confidence in the HHR selector.

When the frozen football model agreed with the selected ML side:

- n = **27**
- W-L = **17-10**
- hit rate = **62.96%**

When the frozen football model opposed the selected side:

- n = **3**
- W-L = **1-2**
- hit rate = **33.33%**

### Spread portion

- n = **27**
- W-L = **13-14**
- hit rate = **48.15%**

Expected Margin cover-direction agreement improved only to 12-11 (52.17%) in this small diagnostic subset. Because Expected Margin's original ~60% score was straight-up winner accuracy rather than ATS cover accuracy, spread currently lacks a separately validated native cover-probability signal suitable for a true HHR ranking.

## 6. HHR no-play weeks are over-restricted relative to model confidence

Current HHR had **52 no-play slates**.

Primary reasons:

- evaluator reliability LOW: **28**
- evaluator unsupported: **9**
- no raw exact-AVG ML output: **15**

Raw top-model confidence among those no-play slates:

- 0.60–0.70: **8**
- 0.70–0.80: **14**
- 0.80–0.90: **15**
- no raw exact-AVG output: **15**

Thus:

- **37 / 52** no-play weeks had a raw top ML model probability at least 60%;
- **29 / 52** had a raw top ML model probability at least 70%.

For diagnosis only, those 37 model-available no-play picks went 29-7-1 (80.56% ex-push), and the 29 at 70%+ went 25-3-1 (89.29%). These figures are not permission to create 60% or 70% selector thresholds.

The structural conclusion is that evaluator reliability/support rules are currently suppressing many high-confidence football-model winner picks even though HHR is supposed to optimize hit probability rather than fair-price value.

## 7. Balanced has the same axis problem on moneyline

Current Balanced:

- n = **55**
- W-L = **30-25**
- hit rate = **54.55%**

Moneyline portion:

- n = **22**
- W-L = **9-13**
- hit rate = **40.91%**
- mean evaluator probability = **61.66%**
- mean raw football-model probability = **52.43%**

Spread portion:

- n = **33**
- W-L = **21-12**
- hit rate = **63.64%**

The moneyline Balanced ranking is therefore also using a fair-value/market probability where the product concept requires a football-confidence component.

## 8. Architectural conclusion

**`CURRENT_HHR_CONFIDENCE_AXIS_MISMATCH_CONFIRMED`**

Task05F should preserve the roles that were already explicit in the accepted ML V4 architecture:

- football-model probability answers winner confidence;
- evaluator fair probability answers price/value quality.

The current selector incorrectly lets evaluator probability/reliability dominate HHR and the hit-rate side of Balanced.

### Required architecture correction before backend freeze

1. **High Hit Rate** must rank on model-native football confidence, not evaluator fair probability.
2. **Balanced** must explicitly combine a model-native football-confidence axis with evaluator price-quality/value information rather than using evaluator probability for both roles.
3. **Value** remains strict evaluator `EV > 0`; no change is warranted from this audit.
4. Evaluator fair price, Play Through status, and price-quality warnings remain visible for HHR; they must not be relabeled as football confidence.
5. Spread must not inherit Expected Margin's 60% straight-up accuracy as an ATS hit-rate claim.
6. No 2020–2024 confidence cutoff or historical ROI bucket may be fitted from this audit.
7. Sealed 2025 remains the next clean outcome evidence after the corrected selector architecture and backend interfaces are independently reviewed/frozen.

## 9. Audit integrity

- candidate rows: **8,448**
- outcome fields in candidate inputs: **none**
- model-native and current-selector choices frozen before outcome join: **true**
- 2025 loaded: **false**
- audit executed twice: **deterministic**
- historical results may tune rules: **false**
