# Task05G Spread Confidence V3 Validation Review

Verdict: `SPREAD_CONFIDENCE_V3_MECHANICALLY_VALIDATED_DIAGNOSTIC_ONLY`

V3 fixed the specific spread-confidence inflation diagnosed after V2, but it does not produce a promotable Task05G policy. 2023–2024 had already been outcome-exposed during V2 forensics and is therefore diagnostic only. 2025 remains sealed.

## Evidence identity

- V3 preregistration commit: `8124494085b1098105f6c40e257bc03a27188a35`
- V3 preregistration blob: `128d8d676986362261bdd7d2720dc8c7eacd0cb4`
- experiment workflow: `32808117762` — SUCCESS
- evidence artifact: `9548854345`
- artifact digest: `sha256:86a77227310990444ec44a0dbeb3aa34c9fd2a8784ac677b9b6fe5e62217cf57`
- deterministic double replay: PASS
- frozen-scope guard: PASS
- 2025 firewall: PASS

## 1. Spread probability inflation is fixed

V2's unconditional residual bootstrap routinely converted 8–12 point Expected Margin / offered-line disagreement into ~75–85% spread confidence even though those large-disagreement groups did not cover materially above 50%.

V3 replaces that bootstrap with strictly-prior direct logistic calibration of model cover margin to actual non-push cover outcome.

In the locked 2023–2024 diagnostic population:

- supported exact-shopped spread observations: 1,110
- average V3 predicted cover probability: **50.50%**
- realized non-push cover rate: **50.54%**
- aggregate calibration error: **+0.04 percentage points**
- Brier: 0.25053
- log loss: 0.69421

By model-cover-margin:

- 0–2: predicted 50.63%, actual 50.85%
- 2–4: predicted 50.97%, actual 51.90%
- 4–6: predicted 51.28%, actual 48.31%
- 6–8: predicted 51.53%, actual 53.03%
- >=8: predicted 51.85%, actual 38.00%

The direct calibrator no longer treats large disagreement as automatic high confidence.

No 2023–2024 supported spread proposition reached 55% V3 confidence. Thus the earlier 75–85% spread probabilities are eliminated rather than merely reduced.

## 2. Chronological slope guard behaved as intended

Season-entry spread calibration states:

- 2020: unsupported, no prior exact-offer calibration sample
- 2021: n=529, slope +0.1429, supported
- 2022: n=1,096, slope **-0.0154**, fail-closed / unsupported
- 2023: n=1,650, slope +0.0799, supported
- 2024: n=2,197, slope +0.0396, supported

The 2022 state is especially informative: strictly-prior offered-line evidence no longer showed a positive monotonic relation between Expected Margin cover margin and actual covers, so V3 correctly refused to manufacture spread confidence.

## 3. HHR V3 coverage survived, but development economics did not

2020–2022 HHR V1 comparator: 23 plays.

HHR V3 development:

- 46 plays / 65 blocks
- coverage: **70.77%**
- preregistered 75%-of-V1 play-count floor: PASS (46 >> 17.25)
- hit rate: **57.78%**
- ROI: **-10.97%**
- market mix: 43 ML / 3 spread
- spread subset: 3 plays, +92.43% ROI (tiny)
- ML subset: 43 plays, **-18.19% ROI**

Therefore the spread-confidence correction did not neuter HHR. Instead, once fake spread confidence was removed, HHR became overwhelmingly ML and exposed a separate development-period ML headline-selection problem.

Locked 2023–2024 HHR diagnostic:

- 35 plays / 44 blocks
- coverage: **79.55%**
- record: 24–11
- hit rate: **68.57%**
- ROI: **+5.34%**
- market mix: **35 ML / 0 spread**
- 2023: 11–7, -4.26% ROI
- 2024: 13–4, +15.50% ROI

This later diagnostic is much closer to the intended HHR product, but cannot be treated as pristine confirmation.

## 4. Balanced V3 price variants finally separate slightly, but development remains poor

All three variants retained 49 plays / 65 blocks (75.38% coverage), well above the preregistered minimum of 18 plays.

Development:

- B0: 25–24, 51.02% hit, **-9.36% ROI**
- B1: 25–24, 51.02%, -10.92%
- B2: 25–24, 51.02%, -10.92%

The frozen tie-break selects B0 because hit rate and coverage tied and B0 had the least-negative ROI.

B0 market mix:

- ML: 40 plays, **-17.67% ROI**
- spread: 9 plays, **+27.60% ROI**

Again the corrected spread component is not the development failure; ML dominates the losing headline stream.

Locked 2023–2024 B0 diagnostic:

- 37 plays / 44 blocks
- coverage: **84.09%**
- record 22–15
- hit rate: **59.46%**
- ROI: **+4.70%**
- ML: 35 plays, +5.23%
- spread: 2 plays, -4.55%

## 5. Interpretation

V3 successfully answers the spread-confidence question:

**The 75–85% spread confidence was a conversion artifact, not justified football-model certainty.**

The direct calibration is much more truthful and removes the pathological spread domination of HHR/Balanced without collapsing card frequency.

However, correcting spread confidence reveals that the remaining HHR/Balanced behavior is now primarily determined by the ML model-confidence/ranking path.

That creates a new, narrower question:

- general ML calibration previously looked stable overall;
- HHR/Balanced ML headline selections were poor in 2020–2022;
- the same ML-led selectors were materially healthier in the locked 2023–2024 diagnostic;
- therefore the next audit should examine **ML confidence specifically in the high-probability headline tail**, not refit the whole ML model or touch Task05F.

The required trace is:

1. ML model-confidence calibration by probability bucket and season;
2. selected-vs-not-selected ML rows within HHR/Balanced eligibility;
3. model confidence vs exact break-even/juice;
4. QB-Elo/XGB agreement and disagreement in the selected tail;
5. whether early chronology/cold-start calibration is overstating high probabilities;
6. whether the highest model-probability ML rows are genuinely better than the next-ranked rows.

No V3 selector threshold, calibration parameter, Task05F evaluator, football model, or 2025 data should be changed from this same outcome exposure.
