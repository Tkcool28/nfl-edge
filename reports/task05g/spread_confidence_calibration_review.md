# Task05G Spread Confidence Calibration Review

Verdict: `SPREAD_CONFIDENCE_MONOTONICITY_INVALID_BEYOND_VALIDATED_DISAGREEMENT_RANGE`

This is a read-only diagnostic follow-up to the failed V2 confirmation. No football model, Task05F evaluator, selector rule, price tolerance, candidate region, or 2025 data was changed.

Evidence workflow: `32793620108` — SUCCESS
Artifact: `9544041315`
Artifact digest: `sha256:cb6abd0856e26557e41ead0758adc95b1f3be1c97422644bd5975c03232d73e2`

## 1. Orientation / settlement correctness

Spread sign/orientation and settlement reconstruction produced **0 mismatches**. The HHR/Balanced failure is not explained by a simple home/away or line-sign bug.

## 2. Entering-2023 stale residual-regime hypothesis is mostly rejected

The confidence layer entering 2023 had prior Expected Margin residual MAE 10.64 points and residual SD 13.72. Actual 2023 residual MAE was 10.92 and SD 14.17 — only 2.7% and 3.3% worse respectively. Entering 2024 versus realized 2024 was essentially identical.

Therefore the 2023 collapse cannot be explained primarily by the confidence layer carrying a much narrower 2020-2022 residual distribution into a suddenly much wider 2023 error regime.

## 3. The actual calibration defect: disagreement is treated as monotonically increasing edge

Across all exact-shopped supported spread offers, the V2 empirical-residual conversion maps larger model-vs-line cover margins into progressively higher cover probabilities:

| Model cover margin | N | Avg stated confidence | Actual non-push hit rate | Calibration error | ROI |
|---|---:|---:|---:|---:|---:|
| 0–2 pts | 420 | 53.51% | 54.13% | +0.61pp | +3.18% |
| 2–4 pts | 397 | 59.62% | 56.04% | -3.57pp | +6.78% |
| 4–6 pts | 286 | 65.60% | 44.88% | **-20.72pp** | **-14.31%** |
| 6–8 pts | 181 | 71.50% | 52.54% | **-18.96pp** | -0.02% |
| >=8 pts | 149 | 78.63% | 48.28% | **-30.35pp** | **-7.87%** |

This is the core failure. Historical performance is **not monotonic** with model-market disagreement. The conversion assumes that increasingly large disagreement is increasingly strong evidence; in reality, the useful region is concentrated around the previously validated 0–4 point range, and larger disagreement becomes unstable / suspicious rather than stronger.

The source architecture had already identified corrected Expected Margin 0–4 point disagreement as the promising historical region and explicitly called for frozen disagreement buckets as a spread benchmark. This diagnostic confirms why that matters.

## 4. Confidence buckets tell the same story

| Stated spread confidence | N | Actual hit rate | Overstatement | ROI |
|---|---:|---:|---:|---:|
| 55–60% | 334 | 55.02% | 2.62pp | +4.85% |
| 60–65% | 297 | 50.34% | **11.83pp** | -3.71% |
| 65–70% | 210 | 47.37% | **20.32pp** | -9.83% |
| 70–75% | 144 | 53.90% | **18.51pp** | +2.57% |
| 75–80% | 89 | 50.00% | **26.98pp** | -4.69% |
| >=80% | 49 | 47.92% | **34.76pp** | -8.50% |

The probability labels above ~60% are not trustworthy as literal cover probabilities. Most importantly, the highest-confidence tails are not the best-performing tails.

## 5. Why HHR/Balanced were dominated by bad spread confidence

### HHR selected spreads

- 83 total spread headlines across 2020–2024
- average stated confidence: 77.48%
- actual hit rate: 51.22%
- ROI: -2.47%
- **64/83** had model cover margin >=8 points

Those >=8-point HHR spread headlines:

- average stated confidence: 79.84%
- actual hit rate: 49.21%
- ROI: -6.11%

### Balanced B0 selected spreads

- 92 total spread headlines
- average stated confidence: 76.85%
- actual hit rate: 51.65%
- ROI: -1.51%
- **68/92** had model cover margin >=8 points

Those >=8-point Balanced spread headlines:

- average stated confidence: 79.79%
- actual hit rate: 49.25%
- ROI: -5.97%

Thus the selectors were doing what they were told: rank by model confidence. The bad behavior originated upstream in the V2 spread-confidence conversion, which rewarded extreme disagreement.

## 6. Season evidence

The same overconfidence remains visible in both 2023 and 2024, even though 2024's overall Expected Margin candidate region recovered historically:

### HHR spread headlines
- 2023: avg confidence 76.83%, hit 40.0%, ROI -24.83%
- 2024: avg confidence 76.37%, hit 41.18%, ROI -20.64%

### Balanced spread headlines
- 2023: avg confidence 76.53%, hit 42.86%, ROI -19.31%
- 2024: avg confidence 76.14%, hit 40.0%, ROI -23.08%

That strongly argues against treating this as only a one-season 2023 regime shock.

## 7. Design implication — no hard cap adopted yet

This audit does **not** adopt a permanent hard cutoff at 4 points. It establishes the more important principle:

> Extreme model-market disagreement must not automatically increase confidence.

A future spread-confidence method should be calibrated against observed cover behavior in disagreement buckets and should be capable of flattening, shrinking, or marking large disagreements as out-of-distribution / suspicious when historical support no longer justifies a higher probability.

Potential methods to preregister separately include:

- monotonicity-constrained only within the historically supported disagreement range, with shrinkage toward 50% outside it;
- bucketed / isotonic calibration using signed disagreement, where empirical evidence is allowed to flatten rather than increase indefinitely;
- explicit OOD/reliability penalty based on distance beyond the validated disagreement region;
- model-only cover confidence estimated from chronological calibration rows rather than direct empirical residual replay.

No one method is selected from this same outcome evidence.

## 8. Immediate conclusion

The V2 selector concept is not falsified by this result. HHR/Balanced ranked the signal they were given. The signal was malformed for spreads because the confidence layer encoded `more disagreement = more confidence` even where historical Expected Margin evidence did not support that relationship.

Before another HHR/Balanced test, spread confidence must be recalibrated so that large disagreement can mean **"something may be wrong"** rather than **"strongest play on the board."**