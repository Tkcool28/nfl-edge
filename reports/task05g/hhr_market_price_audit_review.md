# Task05G HHR Market-Price Corroboration Audit Review

Verdict: `RETAIL_OVERJUICE_NOT_PRIMARY_HHR_FAILURE_MARKET_CORROBORATION_MORE_RELEVANT`

This report records the frozen diagnostic audit of HHR moneyline price corroboration. It does **not** authorize a production selector change. 2025 remained sealed.

## Evidence identity

- frozen audit-plan commit: `8c11ee5fe06d6d3d8d7e6d75cccea22ba078d21e`
- validated workflow head: `12e13aa4bc67f03cfc760d7dc6b5992b0c175765`
- workflow run: `32876373512` — SUCCESS
- artifact: `9574082382`
- artifact digest: `sha256:c46bb32ca20d76a6e6fec53cfd1a1c365d815b7022842e15bcecace0b5969365`
- deterministic double replay: PASS
- focused tests: PASS
- Task05F -> Model Confidence V2 -> Spread Confidence V3 reproduction: PASS
- audit-only scope: PASS
- 2025 firewall: PASS

## 1. Frozen definitions

The audit separated two concepts that had previously been easy to conflate:

1. **sharp-market favorite strength** = selected-side Pinnacle two-sided proportional no-vig probability;
2. **retail juice premium** = best actionable DK/FD break-even probability minus Pinnacle no-vig probability.

Frozen descriptive labels:

- genuine heavy favorite: Pinnacle no-vig >= 65%;
- material retail overjuice: retail premium >= 2.5 percentage points.

These are audit labels only. They are not authorized selector thresholds.

## 2. Development HHR headlines: retail overjuice is not the main problem

Current HHR ML headlines in 2020-2022:

- n = 43
- 23 wins, 19 losses, 1 push
- 54.76% non-push hit rate
- -18.19% ROI
- average model confidence = 70.83%
- average Pinnacle no-vig probability = 64.28%
- average best DK/FD break-even = 66.43%
- average retail juice premium = only +2.15pp
- average model-minus-Pinnacle gap = +6.55pp
- average QB-Elo/XGB disagreement = 13.61pp
- average actionable price = -200

The retail premium itself did not isolate the losing stream:

- materially overjuiced: 16 headlines, 56.25% hit, -21.73% ROI
- not materially overjuiced: 27 headlines, 53.85% hit, -16.09% ROI

The difference is small and in the wrong direction for a clean "overjuice causes HHR failure" explanation.

In the already-exposed 2023-2024 diagnostic, materially overjuiced HHR headlines actually went 7-1 (87.5%) with +25.00% ROI, again inconsistent with a stable retail-overjuice failure mechanism.

## 3. Genuine sharp-market favorite status is materially more informative

Development HHR headlines split by the frozen Pinnacle >=65% label:

### Genuine heavy favorites

- 22 headlines
- 14 wins, 7 losses, 1 push
- 66.67% non-push hit rate
- -7.52% ROI

### Not genuine heavy favorites

- 21 headlines
- 9 wins, 12 losses
- 42.86% hit rate
- -29.36% ROI

Thus the development HHR weakness is concentrated much more heavily in candidates the model-confidence layer elevated into HHR even though Pinnacle did **not** price them as strong favorites.

The same direction persists descriptively in the already-exposed 2023-2024 period:

- genuine heavy: 16-5, 76.19% hit, +6.81% ROI
- not genuine heavy: 8-6, 57.14% hit, +3.13% ROI

This does not authorize a 65% production cutoff, but it strongly supports market corroboration as a meaningful HHR trust dimension.

## 4. The worst development quadrant is model-HHR without sharp-market confirmation plus retail overjuice

Frozen development quadrants:

- genuine heavy + not overjuiced: n=11, 60.0% hit, -14.61% ROI
- genuine heavy + overjuiced: n=11, 72.73% hit, -0.44% ROI
- not genuine heavy + not overjuiced: n=16, 50.0% hit, -17.11% ROI
- not genuine heavy + overjuiced: n=5, 20.0% hit, -68.57% ROI

The final cell is small and cannot become a post-hoc rule, but it is consistent with the broader result: retail premium becomes dangerous mainly when the sharp market itself is **not** corroborating the model's high-confidence favorite claim.

## 5. Rank 1 versus rank 2 shows why retail juice alone cannot explain the max-selection problem

Development ML-only frozen HHR ordering:

### Rank 1

- n=43
- 54.76% hit
- -18.19% ROI
- Pinnacle no-vig 64.28%
- retail break-even 66.43%
- retail premium +2.15pp
- model-minus-Pinnacle +6.55pp
- QB-Elo/XGB disagreement 13.61pp
- average odds -200

### Rank 2

- n=41
- 75.61% hit
- +19.76% ROI
- Pinnacle no-vig 61.56%
- retail break-even 63.57%
- retail premium +2.01pp
- model-minus-Pinnacle +4.94pp
- QB-Elo/XGB disagreement 8.97pp
- average odds -172

Rank 1 was actually a **stronger market favorite** than rank 2 by +2.72pp Pinnacle probability, while retail premium differed by only +0.14pp.

The bigger differences were:

- rank 1 model-minus-Pinnacle gap: +1.61pp larger;
- rank 1 QB-Elo/XGB disagreement: +4.64pp larger.

So the max-selection failure is not explained by "rank 1 simply paid much worse retail juice." It is more consistent with an extreme model-confidence candidate whose evidence is less internally and externally corroborated.

## 6. Model confidence outrunning Pinnacle is the more concerning tail

Development HHR headline results by frozen model-minus-Pinnacle gap:

- <=0pp: n=11, 63.64% hit, -13.36% ROI
- 0-5pp: n=11, 70.0% hit, +3.60% ROI
- 5-10pp: n=6, 83.33% hit, +27.18% ROI
- 10-15pp: n=6, 50.0% hit, -19.10% ROI
- >15pp: n=9, **11.11% hit, -80.34% ROI**

The >15pp development tail is an extreme warning signal: average model confidence was 76.49% while Pinnacle no-vig averaged only 57.48%.

However, this exact bucket did not reproduce as catastrophically in the already-exposed 2023-2024 period (4-3, +14.99% ROI), so no cutoff may be selected from it. The appropriate inference is qualitative: **large model-vs-sharp-market divergence is a plausible HHR trust variable, not a validated threshold.**

## 7. Interpretation

Supported:

1. Retail overjuice by itself is **not** the primary HHR failure mechanism.
2. Genuine sharp-market favorite strength is much more informative than retail juice premium in the development HHR stream.
3. The current HHR max-confidence selector often elevates candidates whose model confidence materially exceeds Pinnacle's no-vig probability.
4. Rank 1's poor development results occur despite only a trivial retail-premium difference from rank 2.
5. HHR should be treated differently from Balanced: HHR needs a form of **external market corroboration of favorite strength**, not simply a universal constituent-disagreement penalty.

Not supported:

- banning prices above an arbitrary juice level;
- selecting the 65% Pinnacle label as a production eligibility threshold;
- selecting 2.5pp retail premium as a production cutoff;
- selecting a 10pp or 15pp model-market cutoff post hoc;
- changing ML calibration or Task05F;
- opening 2025.

## 8. Recommended next experiment

The cleanest next ranking-only HHR experiment is a separately preregistered **conservative model/market corroboration score** that requires both signals to support the headline without introducing a fitted coefficient.

A principled candidate is:

```text
hhr_corroborated_trust = min(
    model_confidence_probability,
    pinnacle_anchor_probability,
)
```

Rationale:

- if the model says 76% but Pinnacle says 57%, the headline is ranked as 57%-quality evidence rather than 76%-quality evidence;
- if model and sharp market both say roughly 70%, the candidate retains roughly 70% trust;
- if Pinnacle is stronger than the model, the model remains the conservative side;
- no new eligibility gate is needed;
- block coverage can remain exactly unchanged;
- no arbitrary penalty coefficient is required.

This rule has **not** been tested in this audit and is not authorized until separately preregistered before outcome output.
