# Task05G HHR Model-Market Corroboration V1 Review

Verdict: `HALF_SHRINK_NOT_DIRECTIONALLY_SUCCESSFUL`

This report records the preregistered ranking-only HHR corroboration experiment. It does **not** authorize production promotion. 2025 remained sealed.

## Evidence identity

- preregistration commit: `ae9a58bf83bf64fad1b57c5016b325aecc90458a`
- validated workflow head: `e9af1ab420d7153dae9135a35fa1568c2dc4e93c`
- workflow run: `32880347983` — SUCCESS
- artifact: `9575567404`
- artifact digest: `sha256:836f40af464352f42344d689492b228ef812dd54c809f32988cac1d7e790241e`
- deterministic double replay: PASS
- experiment-only scope: PASS
- focused upstream tests: PASS
- Task05F board reproduction: PASS
- Model Confidence V2 reproduction: PASS
- Spread Confidence V3 reproduction: PASS
- exact coverage parity: PASS
- 2025 firewall: PASS

## 1. Frozen primary rule

The primary rule was committed before outcome output:

```text
excess_model_over_market = max(model_confidence_probability - pinnacle_anchor_probability, 0)
headline_trust_score = model_confidence_probability - 0.50 * excess_model_over_market
```

This is `HALF_SHRINK`.

If the football-model confidence is at or below Pinnacle no-vig, it is left unchanged. If the model outruns Pinnacle, only the excess is pulled halfway back toward the market. Spread candidates retain Spread Confidence V3 unchanged.

The rule is ranking-only. Eligibility, HHR thresholds, exact DK/FD shopping, units, bankroll policy, and Play Through remain frozen.

The preregistered secondary comparator `MIN_CAP = min(model_confidence, Pinnacle no-vig)` is diagnostic only and cannot replace the primary after results.

## 2. Development 2020-2022

### V3 baseline

- 46 play blocks / 65 = 70.77% coverage
- 26 wins, 19 losses, 1 push
- 57.78% non-push hit rate
- -10.97% ROI
- average odds -194
- 43 ML / 3 spread
- average selected ML model confidence 70.83%
- average selected ML Pinnacle no-vig 64.28%
- average model-minus-Pinnacle +6.55pp
- average QB-Elo/XGB disagreement 13.61pp

### Primary HALF_SHRINK

- 46 / 65 = 70.77% coverage — exact parity
- 28 wins, 17 losses, 1 push
- 62.22% hit rate
- -7.13% ROI
- average odds -219
- 43 ML / 3 spread
- average selected ML model confidence 70.43%
- average selected ML Pinnacle no-vig 66.79%
- average model-minus-Pinnacle +3.64pp
- average QB-Elo/XGB disagreement 12.65pp

Delta versus baseline:

- hit rate: **+4.44pp**
- ROI: **+3.85pp**
- coverage: **unchanged**
- 10 of 46 blocks changed = 21.74%
- paired non-push outcomes: 23 both win, 14 both lose, 5 new-only wins, 3 old-only wins

The frozen development gate required at least +5.0pp hit-rate improvement and non-worse ROI. ROI passed, but hit rate missed the gate by 0.56pp. Therefore the frozen verdict is `HALF_SHRINK_NOT_DIRECTIONALLY_SUCCESSFUL` even though the observed direction is favorable.

## 3. Model agency was preserved

The user's concern was that market corroboration might silently turn HHR back into a Pinnacle selector. It did not.

Among the 43 development ML-selected blocks:

- HALF_SHRINK matched the pure model-confidence rank-1 in **33/43 = 76.74%**;
- HALF_SHRINK matched pure Pinnacle-no-vig rank-1 in **17/43 = 39.53%**;
- in 6 blocks, HALF_SHRINK selected a candidate that was neither pure-model rank-1 nor pure-Pinnacle rank-1;
- pure model rank-1 and pure Pinnacle rank-1 were themselves the same candidate in only 13 of 43 blocks.

Thus HALF_SHRINK remains materially model-led. Pinnacle acts as a corroboration/tempering signal rather than replacing the models.

## 4. Locked 2023-2024 diagnostic

### V3 baseline

- 35 / 44 = 79.55% coverage
- 24-11
- 68.57% hit rate
- +5.34% ROI
- average odds -184

### HALF_SHRINK

- identical 35 / 44 coverage
- 25-10
- 71.43% hit rate
- +3.01% ROI
- average odds -234

Delta:

- hit rate: **+2.86pp**
- ROI: **-2.33pp**
- 9 of 35 blocks changed
- paired outcomes: 22 both win, 8 both lose, 3 new-only wins, 2 old-only wins

Model agency again remained strong:

- pure model rank-1 overlap: **26/35 = 74.29%**
- pure Pinnacle rank-1 overlap: **11/35 = 31.43%**
- 7 selections differed from both pure rankings.

The later exposed period therefore supports the hit-rate direction descriptively, but does not satisfy a robustness claim because ROI declined and these outcomes were already exposed before this experiment.

## 5. Secondary MIN_CAP comparator

MIN_CAP is reported only because it was preregistered before output.

Development:

- exact 46/65 coverage
- 31 wins, 14 losses, 1 push
- **68.89% hit rate**
- **+1.54% ROI**
- average odds -228
- pure-model rank-1 overlap 60.47%
- pure-Pinnacle rank-1 overlap 46.51%

Locked 2023-2024:

- exact 35/44 coverage
- 68.57% hit rate — no improvement from baseline
- -1.91% ROI
- pure-model rank-1 overlap 54.29%
- pure-Pinnacle rank-1 overlap 48.57%

The attractive development MIN_CAP result cannot be promoted or substituted post hoc. It also shifts materially more agency away from the football-model ranking, matching the user's concern.

## 6. Interpretation

What this experiment establishes:

1. **Coverage does not need to be sacrificed.** A ranking-only corroboration layer retained every baseline HHR play block.
2. **Model agency can be preserved.** HALF_SHRINK still followed the pure model rank-1 about three-quarters of the time in both periods, while Pinnacle rank-1 overlap remained much lower.
3. **Tempering only unsupported model excess is directionally useful.** HHR hit rate improved in both periods: +4.44pp in development and +2.86pp in the locked diagnostic.
4. **The preregistered success gate still failed.** Development missed the required +5pp improvement by 0.56pp, and locked-period ROI declined despite a better hit rate.
5. **MIN_CAP is too market-dominant to adopt from this exposed result.** Its development result is strong, but later robustness is absent and model agency falls substantially.

## 7. Next implication

The evidence is now much narrower than at the start of Task05G. HHR does not need a global ML recalibration, a higher confidence floor, a retail-juice ban, or a pure Pinnacle selector. The promising structure is a **model-led confidence rank with market corroboration only when the model becomes much more bullish than the sharp market**.

No coefficient may be retuned from this exposed experiment. In particular, the 0.50 coefficient must not be changed to 0.40/0.60 based on these outcomes. Any further refinement must come from a separately preregistered rule with a new principled signal or functional form, not coefficient fishing.

No production promotion is authorized. 2025 remains sealed.
