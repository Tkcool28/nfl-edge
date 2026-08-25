# Task05G ML Headline Trust V1 Review

Verdict: `PRIMARY_TRUST_CORRECTION_MIXED`

This report records the preregistered ranking-only ML headline trust experiment stacked on the validated ML confidence-tail audit. It does **not** authorize production promotion. 2025 remained sealed.

## Evidence identity

- preregistration commit: `462f4285fb8746c4be446a2f5c05d32a5463cf15`
- implementation/workflow head for validated run: `60a6366d7dd9897c02f3edb9e320eea856159bf5`
- workflow run: `32874952240` — SUCCESS
- artifact: `9573555661`
- artifact digest: `sha256:545347c17d1ee180366ebbf36b502702388c89e139499620e35550b0ca3f688e`
- deterministic double replay: PASS
- experiment-only scope: PASS
- focused upstream tests: PASS
- Task05F board reproduction: PASS
- Model Confidence V2 reproduction: PASS
- Spread Confidence V3 reproduction: PASS
- primary HHR/Balanced coverage parity: PASS
- 2025 firewall: PASS

## 1. Frozen primary rule

The primary rule was committed before experiment output:

```text
headline_trust_score = model_confidence_probability
                       - 0.50 * abs(QB-Elo selected probability - XGBoost selected probability)
```

for moneyline candidates. Spread candidates retained their existing Spread V3 confidence as the ranking score.

The trust score was ranking-only. It did not overwrite ML confidence, change candidate eligibility, add a confidence floor, impose a disagreement cutoff, or fail closed.

The frozen development success gate required:

- exact coverage parity for HHR and Balanced B0;
- at least +5 percentage points hit-rate improvement in HHR;
- at least +5 percentage points hit-rate improvement in Balanced B0;
- no ROI decline in either lane.

The primary rule failed that full gate.

## 2. Development 2020-2022

### HHR

V3 baseline:

- 46 play blocks / 65 = 70.77% coverage
- 26 wins, 19 losses, 1 push
- 57.78% non-push hit rate
- -10.97% ROI
- average odds -194
- 43 moneylines / 3 spreads
- selected-ML confidence 70.83%
- selected-ML QB-Elo/XGBoost disagreement 13.61pp

Primary T050:

- 46 / 65 = 70.77% coverage — exact parity
- 25 wins, 21 losses, 0 pushes
- 54.35% hit rate
- -11.21% ROI
- average odds -170
- 42 moneylines / 4 spreads
- selected-ML confidence 69.66%
- selected-ML disagreement 8.38pp

Delta versus baseline:

- hit rate: **-3.43pp**
- ROI: **-0.24pp**
- changed 19 of 46 selected blocks = 41.30%
- paired non-push outcomes: 21 both win, 15 both lose, 4 new-only wins, 5 old-only wins

The primary rule successfully reduced selected disagreement but did **not** improve HHR outcomes. Disagreement reduction alone therefore does not explain or repair HHR max-selection behavior.

### Balanced B0

V3 baseline:

- 49 / 65 = 75.38% coverage
- 25 wins, 24 losses
- 51.02% hit rate
- -9.36% ROI
- average odds -107
- 40 moneylines / 9 spreads
- selected-ML confidence 68.22%
- selected-ML disagreement 11.86pp

Primary T050:

- 49 / 65 = 75.38% coverage — exact parity
- 28 wins, 21 losses
- 57.14% hit rate
- +3.28% ROI
- average odds -107
- 39 moneylines / 10 spreads
- selected-ML confidence 67.29%
- selected-ML disagreement 7.70pp

Delta versus baseline:

- hit rate: **+6.12pp**
- ROI: **+12.64pp**
- changed 12 of 49 selected blocks = 24.49%
- paired outcomes: 23 both win, 19 both lose, 5 new-only wins, 2 old-only wins

Balanced therefore passed its lane-specific development direction: the ranking-only trust score improved hit rate beyond the preregistered +5pp requirement, turned ROI positive, and did so with identical block coverage.

## 3. Locked 2023-2024 diagnostic

The later period does not validate a universal fixed disagreement penalty.

### HHR

V3 baseline:

- 35 / 44 = 79.55% coverage
- 68.57% hit rate
- +5.34% ROI

Primary T050:

- identical 35 / 44 coverage
- 68.57% hit rate — no change
- -0.13% ROI
- changed 8 of 35 blocks
- paired outcomes: 2 new-only wins and 2 old-only wins

Hit rate was unchanged while ROI deteriorated by 5.47pp.

### Balanced B0

V3 baseline:

- 37 / 44 = 84.09% coverage
- 59.46% hit rate
- +4.70% ROI

Primary T050:

- identical 37 / 44 coverage
- 54.05% hit rate
- -5.71% ROI
- changed 9 of 37 blocks
- paired outcomes: 1 new-only win and 3 old-only wins

Hit rate deteriorated by 5.41pp and ROI by 10.41pp.

The locked-diagnostic robustness condition therefore failed.

## 4. Frozen sensitivity analysis does not identify a universal coefficient

The preregistration allowed T025 and T100 only as descriptive sensitivity checks. They cannot replace the primary rule after results are seen.

The sensitivity results are not monotonic and differ by lane/period:

- development HHR: neither T025 nor T100 beat the V3 baseline hit rate;
- development Balanced: T050 was materially better than baseline, while T025 was flat on hit rate and T100 only modestly better;
- locked HHR: stronger penalties degraded hit rate;
- locked Balanced: T025 happened to improve the exposed period, while T050 and T100 degraded it.

Because these outcomes are exposed, the attractive locked Balanced T025 result cannot be selected post hoc.

## 5. What this experiment establishes

### Supported

1. **Global ML calibration still should not be replaced.** The prior audit's broad calibration finding is not contradicted.
2. **A ranking-only trust layer can change selection without sacrificing card coverage.** Exact HHR/Balanced coverage parity was maintained.
3. **Constituent disagreement contains useful information in Balanced development.** T050 reduced selected disagreement from 11.86pp to 7.70pp while improving Balanced hit rate from 51.02% to 57.14% and ROI from -9.36% to +3.28%.
4. **Constituent disagreement alone is insufficient for HHR.** T050 reduced HHR selected disagreement from 13.61pp to 8.38pp but hit rate fell from 57.78% to 54.35%.
5. **One fixed disagreement coefficient is not stable across lanes and periods.** No universal penalty may be promoted from this experiment.

### Not supported

- promoting T050 as production policy;
- selecting T025 or T100 from exposed sensitivity results;
- adding a disagreement cutoff post hoc;
- changing ML confidence itself;
- opening 2025 to choose a better coefficient;
- assuming that lower constituent disagreement automatically means a safer HHR favorite.

## 6. Next diagnostic direction

The remaining HHR weakness should be treated separately from Balanced.

HHR is structurally different: it is concentrated in much heavier prices and is explicitly trying to identify a high-hit-rate floor. The next preregistered diagnostic should therefore test whether the HHR max-selection problem is better explained by **confidence + market-price corroboration / heavy-favorite extremity**, rather than by constituent-model disagreement alone.

Balanced may retain constituent disagreement as a plausible trust feature for a later preregistered multi-signal rule, but this experiment is not sufficient to promote it.

Any next rule must remain ranking-only first, preserve existing eligibility/coverage as a hard invariant, and keep 2025 sealed until a genuinely frozen final validation is ready.
