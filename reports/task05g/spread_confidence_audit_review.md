# Task05G Spread Model-Confidence Audit Review

Verdict: `SPREAD_CONFIDENCE_TAIL_OVERCALIBRATION_CONFIRMED_NOT_JUST_2023_STALENESS`

This is a read-only diagnostic of the failed-confirmation V2 spread-confidence layer. No Expected Margin model, Task05F evaluator, V2 selector, price threshold, preregistration, or 2025 data was changed.

## Evidence

- Workflow: `32793620108` — SUCCESS
- Artifact: `9544041315`
- Artifact digest: `sha256:cb6abd0856e26557e41ead0758adc95b1f3be1c97422644bd5975c03232d73e2`
- Audit head: `71cffb7625d1439449487c1c4c68559a131e4f3e`
- 2025 remained sealed.
- Spread side/line settlement parity mismatches: **0**.

The spread-confidence construction is therefore not failing because of a simple home/away sign or settlement-orientation bug.

## 1. The user hypothesis is partly correct: 2022 made the entering-2023 error distribution look unusually favorable

The V2 spread-confidence layer converts Expected Margin to exact-line cover probability by applying the **strictly prior pooled empirical residual distribution**:

`historical residual = actual home margin - Expected Margin`

For a current line it asks how often those historical residuals would allow the current Expected Margin prediction to cover.

Entering-season residual diagnostics:

| Season | Prior residual SD entering season | Actual season residual SD | Actual/prior | Prior MAE | Actual MAE |
|---|---:|---:|---:|---:|---:|
| 2020 | 14.02 | 13.56 | 0.967 | 10.82 | 10.46 |
| 2021 | 13.84 | 14.79 | 1.069 | 10.68 | 11.71 |
| 2022 | 14.12 | **12.20** | **0.864** | 10.97 | **9.45** |
| 2023 | **13.72** | **14.17** | **1.033** | 10.64 | 10.92 |
| 2024 | 13.80 | 13.87 | 1.005 | 10.69 | 10.71 |

2022 was indeed an unusually accurate Expected Margin season by residual dispersion. Because the V2 confidence layer pools all prior residuals, that strong 2022 season tightened the entering-2023 empirical error distribution: pooled SD fell from about 14.12 entering 2022 to 13.72 entering 2023.

Then 2023 actual errors widened back to 14.17.

Thus entering 2023 the confidence mapping was modestly too optimistic about Expected Margin error dispersion.

However, the difference is only about 3.3% in overall residual SD and 2.7% in MAE. It cannot by itself explain selected probabilities around 76-78% realizing near 40-45%.

## 2. Pooled residual confidence adapts too slowly, but 2024 proves staleness is not the whole problem

The confidence layer uses **all prior residuals with equal weight**. Therefore one bad season is diluted by a much larger historical pool.

- entering 2023: n=1,294 prior residuals, SD 13.72
- after 2023 / entering 2024: n=1,579, SD only 13.80
- actual 2024 residual SD: 13.87

So the 2023 deterioration barely moved the pooled uncertainty estimate.

Nevertheless, 2024 still showed severe high-confidence failure after 2023 had entered the prior history. That rules out a pure "2020-22 confidence carried blindly into 2023" explanation.

## 3. Full spread board is calibrated near 50%; the high-confidence tails are not

Across all exact-shopped supported spreads, average model confidence stayed near 50% and realized cover rate also stayed near 50% each year. The gross orientation of the board is not broken.

The failure appears when Expected Margin and the offered spread disagree enough to create high modeled confidence.

### Calibration by model-confidence bucket, 2020-2024 pooled

| Claimed confidence bucket | N | Avg claimed q | Realized non-push hit | Calibration error | ROI |
|---|---:|---:|---:|---:|---:|
| 55-60% | 334 | 57.64% | **55.02%** | -2.62pp | +4.85% |
| 60-65% | 297 | 62.18% | **50.34%** | -11.83pp | -3.71% |
| 65-70% | 210 | 67.68% | **47.37%** | -20.32pp | -9.83% |
| 70-75% | 144 | 72.41% | **53.90%** | -18.51pp | +2.57% |
| 75-80% | 89 | 76.98% | **50.00%** | -26.98pp | -4.69% |
| >=80% | 49 | 82.68% | **47.92%** | -34.76pp | -8.50% |

The empirical-residual conversion is therefore **not calibrated as a probability mapping in the high-confidence tails**.

## 4. The cleanest root cause is model-vs-line disagreement magnitude

The V2 mapping treats a larger Expected Margin advantage over the exact offered line as mechanically stronger cover probability.

That assumption is not supported by realized outcomes.

### Exact-shopped spreads by Expected Margin modeled cover margin

| Model says it should cover by | N | Avg q | Realized hit | Calibration error | ROI |
|---|---:|---:|---:|---:|---:|
| 0-2 pts | 420 | 53.5% | **54.1%** | +0.6pp | +3.2% |
| 2-4 pts | 397 | 59.6% | **56.0%** | -3.6pp | +6.8% |
| 4-6 pts | 286 | 65.6% | **44.9%** | -20.7pp | -14.3% |
| 6-8 pts | 181 | 71.5% | **52.5%** | -19.0pp | ~0.0% |
| >=8 pts | 149 | 78.6% | **48.3%** | -30.4pp | -7.9% |

This is decisive.

The confidence conversion behaves reasonably in the **0-4 point disagreement range**, then breaks sharply. Larger disagreement does **not** imply larger realized cover probability.

This independently matches the earlier Task05E discovery that the validated Expected Margin spread betting region was the **0-4 disagreement family**. V2 incorrectly extrapolated the pooled residual model to the entire spread board and assumed extreme disagreement was stronger evidence.

## 5. HHR and Balanced selected almost exactly the broken tail

### HHR selected spreads, all 2020-2024

- 83 spread selections
- average claimed confidence: **77.48%**
- average modeled cover margin: **+9.75 points**
- realized hit rate: **51.22%**
- ROI: -2.47%

64 of 83 HHR spread selections were in the `>=8 point` modeled-cover-margin bucket:

- claimed q: **79.84%**
- realized hit: **49.21%**
- calibration error: **-30.63pp**
- ROI: -6.11%

By season HHR spread selection:

| Season | N | Avg q | Hit | ROI |
|---|---:|---:|---:|---:|
| 2020 | 11 | 78.63% | 63.64% | +21.54% |
| 2021 | 17 | 77.86% | 52.94% | +0.96% |
| 2022 | 18 | 78.16% | 64.71% | +21.59% |
| 2023 | 20 | 76.83% | **40.00%** | **-24.83%** |
| 2024 | 17 | 76.37% | **41.18%** | **-20.64%** |

Even in profitable development years, the stated probabilities were materially too high. 2023-2024 turned that pre-existing overconfidence into outright losses.

### Balanced B0 selected spreads

- 92 spread selections
- average q: **76.85%**
- average modeled cover margin: **+9.50 points**
- realized hit: **51.65%**
- ROI: -1.51%

68 of 92 were in the `>=8 point` bucket:

- q: 79.79%
- realized hit: 49.25%
- ROI: -5.97%

Thus HHR/Balanced were not merely exposed to a bad 2023 season. Their probability-first ordering systematically drove them toward the **least calibrated part of the spread-confidence mapping**.

## 6. 2023 chronology does not show broad confidence correction during the season

On the full exact-shopped spread board:

- weeks 1-9: avg q 50.48%, realized 50.97%
- weeks 10+: avg q 50.33%, realized 50.69%

So the full board remained globally centered and well behaved.

The issue was not broad board probability drift. It was the high-disagreement tail that HHR/Balanced preferentially selected.

Because pooled residual history is dominated by all prior games, adding 2023 outcomes during the season barely changes the tail mapping.

## 7. No simple residual-variance regime shift explains the tail

Residual dispersion conditional on the Expected Margin prediction magnitude is broadly similar across ordinary prediction ranges. There is no evidence that a single gross increase in residual SD is sufficient to explain the ~25-35pp probability overstatement in selected spreads.

The problem is more structural:

> V2 assumes that the unconditional historical residual distribution can be centered on the current Expected Margin prediction and used as an exact cover-probability distribution for any sportsbook line.

That requires Expected Margin to behave like a well-calibrated conditional mean across **model-market disagreement magnitude**.

The data show it does not. In particular, extreme Expected Margin-vs-line disagreement regresses sharply rather than becoming increasingly predictive.

## 8. Refined interpretation of the user's 2023 hypothesis

The hypothesis is directionally correct:

1. 2022 was unusually strong and had materially smaller residual errors.
2. That tightened the pooled error distribution entering 2023.
3. 2023 then reverted to larger errors, while all-history pooling adapted slowly.

But this is an **amplifier**, not the root cause.

The root cause was already present before 2023: high spread-confidence tails were systematically overconfident. 2022 happened to reward some extreme selections strongly enough that development performance looked good. 2023 exposed the fragility, and 2024 confirmed it even after 2023 had entered the residual history.

## 9. What this means for the next design

Do **not** tune HHR/Balanced thresholds around the current spread q.

Do **not** infer exact cover probability from the unconditional Expected Margin residual CDF across the full board.

The next spread-confidence design should be preregistered separately and should calibrate/validate the mapping from **Expected Margin versus exact offered line disagreement** to realized cover probability.

The earlier 0-4 region is now supported by two independent pieces of evidence:

1. Task05E betting-region discovery found positive spread evidence in 0-4 disagreement.
2. This probability audit finds 0-4 is the only range where modeled spread confidence is approximately directionally credible; >4 becomes severely overconfident.

That does not automatically make 0-4 a permanent HHR/Balanced hard gate. It means any future spread-confidence layer must learn or constrain the probability curve so it does not treat extreme disagreement as near-certain cover evidence.
