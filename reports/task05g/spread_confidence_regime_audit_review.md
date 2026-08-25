# Task05G Spread Model-Confidence Regime Audit Review

Verdict: `SPREAD_CONFIDENCE_HIGH_TAIL_STRUCTURALLY_MISCALIBRATED_2023_REGIME_WEAKNESS_AMPLIFIED_NOT_CAUSED_IT`

This is a read-only follow-up to the failed preregistered Model Confidence + Selector V2 confirmation. No Task05F evaluator, football model, selector, price tolerance, candidate region, or historical data was changed. 2025 remained sealed.

## Evidence identity

- Audit branch: `audit/task05g-spread-confidence-regime-v1`
- Tracking issue: #34
- Draft stacked PR: #35
- Workflow: `32792827817` — SUCCESS
- Evidence artifact: `9543753972`
- Artifact digest: `sha256:365c57e3573c47175a17e63c57347413d19db55fdb67748ec62d7aae9dbf2fe7`
- Deterministic replay: PASS
- Exact spread settlement/orientation rows checked: 2,816
- Settlement/orientation mismatches: **0**

## 1. Hypothesis tested

The hypothesis was that V2 spread confidence may have entered 2023 carrying a strong 2020-2022 residual history, then overstated confidence because the Expected Margin model entered a known weak 2023 betting regime.

That mechanism is possible in the implementation because V2 spread confidence uses an unweighted empirical pool of all strictly-prior Expected Margin residuals. For each offered spread, it adds each prior residual to today's Expected Margin projection and calculates the fraction of synthetic outcomes that would cover the offered line.

There is no season/regime weighting in that residual pool.

## 2. Broad residual-error regime did NOT break sharply in 2023

The strictly-prior residual distribution entering each season was compared with the residuals actually realized that season.

| Season | Prior residual SD | Realized SD | Ratio | Prior MAE | Realized MAE | Ratio |
|---|---:|---:|---:|---:|---:|---:|
| 2020 | 14.02 | 13.56 | 0.967 | 10.82 | 10.46 | 0.967 |
| 2021 | 13.84 | 14.79 | 1.069 | 10.68 | 11.71 | 1.096 |
| 2022 | 14.12 | 12.20 | 0.864 | 10.97 | 9.45 | 0.861 |
| **2023** | **13.72** | **14.17** | **1.033** | **10.64** | **10.92** | **1.027** |
| 2024 | 13.80 | 13.87 | 1.005 | 10.69 | 10.71 | 1.002 |

2023 residual SD was only 3.3% wider than the prior pool and MAE only 2.7% worse. 2024 was essentially identical to its prior history.

Therefore the failed 2023 spread betting regime was **not primarily a broad residual-variance shock** that the prior pool could not anticipate.

## 3. Entering 2024 did not materially change the confidence state

Spread residual state at season entry:

- 2023 Week 1: n=1,294, residual SD **13.718**
- 2024 Week 1: n=1,579, residual SD **13.800**

Because 2023's overall residual dispersion was not dramatically worse, ingesting 2023 into the historical pool widened the empirical uncertainty distribution by only about 0.6%.

Accordingly, selected spread confidence barely changed:

### HHR selected spreads
- 2023 average q: **76.83%**
- 2024 average q: **76.37%**

### Balanced selected spreads
- 2023 average q: **76.53%**
- 2024 average q: **76.14%**

Thus the method had no strong mechanism to become materially more conservative in 2024 after the bad 2023 betting season.

## 4. Aggregate spread calibration hides a severe tail problem

Across all exact-shopped supported spread offers, average V2 confidence remained close to 50% and realized hit rate also remained close to 50% each season:

- 2020: q 50.34%, hit 50.28%
- 2021: q 50.28%, hit 50.26%
- 2022: q 50.37%, hit 50.72%
- 2023: q 50.43%, hit 50.82%
- 2024: q 50.30%, hit 50.27%

At first glance that looks well calibrated.

It is misleading for headline selection because HHR/Balanced do not select average 50% rows. They select the extreme upper tail.

## 5. High-confidence tail was already badly miscalibrated before 2023

### Development 2020-2022 pooled probability buckets

| V2 spread q bucket | N | Avg q | Realized hit | Actual - q |
|---|---:|---:|---:|---:|
| <55% | 999 | 40.00% | 48.47% | +8.47pp |
| 55-60% | 200 | 57.70% | 59.09% | +1.39pp |
| 60-65% | 173 | 62.15% | 52.35% | **-9.80pp** |
| 65-70% | 122 | 67.74% | 42.15% | **-25.59pp** |
| 70-75% | 90 | 72.46% | 55.56% | **-16.91pp** |
| **75%+** | **92** | **79.29%** | **55.06%** | **-24.24pp** |

The high-confidence tail was therefore structurally overconfident even in the development years.

2022 happened to be the strongest high-tail season: 75%+ rows hit 69.23% versus 79.16% stated q. That strong season made the development headline products look much better, but it did not validate the probability scale.

## 6. 2023-2024 amplified the same structural defect

### Confirmation pooled probability buckets

| V2 spread q bucket | N | Avg q | Realized hit | Actual - q |
|---|---:|---:|---:|---:|
| <55% | 694 | 41.08% | 51.70% | +10.62pp |
| 55-60% | 134 | 57.52% | 48.85% | -8.66pp |
| 60-65% | 124 | 62.23% | 47.50% | -14.73pp |
| 65-70% | 88 | 67.59% | 54.55% | -13.05pp |
| 70-75% | 54 | 72.32% | 50.98% | -21.34pp |
| **75%+** | **46** | **78.47%** | **37.78%** | **-40.69pp** |

So 2023-2024 did not create a new calibration problem. They exposed and worsened an existing one.

## 7. HHR and Balanced live almost entirely in the broken tail

### HHR selected spreads

Development 2020-2022:
- 46 selections
- 45 non-push
- realized hit rate: **60.00%**
- average q: **78.07%**
- calibration gap: **-18.07pp**

Confirmation 2023-2024:
- 37 selections
- realized hit rate: **40.54%**
- average q: **76.62%**
- calibration gap: **-36.08pp**

### Balanced B0 selected spreads

Development:
- 51 selections
- 50 non-push
- realized hit rate: **60.00%**
- average q: **77.15%**
- calibration gap: **-17.15pp**

Confirmation:
- 41 selections
- realized hit rate: **41.46%**
- average q: **76.34%**
- calibration gap: **-34.88pp**

This explains why HHR/Balanced confirmation collapsed despite apparently enormous model-price gaps.

## 8. The selector is choosing extreme model-vs-line disagreements

The selected spreads had very large Expected Margin cushions versus the offered line.

HHR average model cushion:
- 2020: 9.99 points
- 2021: 10.12
- 2022: 10.15
- 2023: 9.40
- 2024: 9.14

Balanced:
- 2020: 10.08
- 2021: 9.37
- 2022: 9.92
- 2023: 9.27
- 2024: 9.04

The empirical residual-CDF method interprets a roughly 9-10 point Expected Margin advantage over the market line as approximately 76-79% cover probability.

But the historical outcomes do not support that probability scale.

This is especially important because the frozen Task05E Expected Margin betting evidence was validated in the **0-4 point disagreement region**. V2 HHR/Balanced were not restricted to that region and, when ranked by model confidence across the full board, migrated to much more extreme ~9-10 point disagreements.

This does **not** mean HHR must permanently be region-only. It means a full-board spread-confidence system needs a calibrated and supported way to handle large model-market disagreements rather than extrapolating unconditional residuals into extreme probabilities.

## 9. Why the unconditional residual method fails in the tail

The current calculation assumes that historical Expected Margin residuals are exchangeable with today's residual regardless of:

- size of model-market disagreement;
- which side the model disagrees toward;
- line magnitude;
- whether the model is operating inside or outside its historically validated betting region;
- season/regime;
- other conditional indicators of uncertainty.

That assumption can make the center of the full-board distribution look reasonable while badly overstating the upper tail.

A 10-point model cushion is treated as if the only uncertainty is the unconditional historical residual distribution. The data show that large disagreement itself contains information about model risk that this method ignores.

## 10. Answer to the 2023-regime hypothesis

**Partially, but not in the way initially suspected.**

Yes, the implementation carried prior residual history into 2023 without regime weighting, and the known weak 2023 spread season made the resulting high-confidence selections fail dramatically.

However:

- 2023 overall residual variance/MAE did not change enough to explain the collapse;
- the 65%+ and especially 75%+ confidence tails were already badly overconfident during 2020-2022;
- 2024 remained overconfident even after 2023 entered the history because 2023 did not materially widen the unconditional residual pool;
- HHR/Balanced systematically selected extreme ~9-10 point disagreements, well outside the 0-4 region where Expected Margin betting evidence had been validated.

Therefore the primary defect is **structural high-tail miscalibration in the spread probability conversion**, with 2023 model/market disagreement nonstationarity acting as an amplifier.

## 11. Next step — no selector tuning yet

Do not tune HHR, Balanced, B0/B1/B2, or Task05F around these results.

The next development task should build and preregister candidate methods for a **calibrated spread model-confidence probability**, using strictly-prior data and explicit out-of-support handling. Candidate approaches can include a directly calibrated cover-probability mapping from model cushion/disagreement rather than treating the unconditional residual CDF as ground truth.

Before any method is promoted it should demonstrate:

- monotonic probability buckets;
- calibration in the upper tail used by HHR/Balanced;
- development/confirmation separation;
- explicit behavior outside historically supported disagreement ranges;
- preserved play coverage;
- 2025 sealed.

No replacement mapping or threshold is selected by this audit.