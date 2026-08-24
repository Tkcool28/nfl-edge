# Task05G Model Confidence + Selector V2 Validation Review

Verdict: `V2_MECHANICALLY_VALIDATED_BUT_CONFIRMATION_FAILED`

This report records the first valid deterministic result of the preregistered Model Confidence + Selector V2 experiment. It is report-only. No Task05F evaluator, football model, selector threshold, candidate region, price tolerance, or 2025 data was changed after outcome exposure.

## Evidence identity

- Preregistration commit: `a6a0fb5cb4d4f742ef6d2708f17c8aac7ba5bf44`
- Preregistration blob: `d06d64c4aa94d1c4d291f585af5e42003a86a49d`
- Valid experiment code head: `07b936b4daac00030782f7d907dbe6b74bfacb22`
- Workflow run: `32789498524` — SUCCESS
- Evidence artifact: `9542661616`
- Artifact digest: `sha256:3e66c74220bf3c34f6aeb28303b81908e4cfe1ad90de197c89aa982ec9896e4f`
- Scorecard SHA-256: `20ee8238e8922f6ded2ab36e867710a32343d89c612313774c48973c73b1daac`
- Candidate table SHA-256: `4def82069879e44cdaaf4aa8dda48814b399d2fb1090b856d0f253fb13e9391a`
- Model-confidence state SHA-256: `ee0ccf510035dc489981b293f4164e54695f24d30dd850935430261bfb55a980`
- 2025 remained sealed.

The CI label in the raw scorecard is `V2_EXPERIMENT_VALIDATED`; that means the preregistered experiment executed successfully and passed its mechanical/development gates. It must **not** be read as product promotion, because the untouched 2023–2024 confirmation failed materially.

## 1. Coverage did not collapse

The primary product concern before this experiment was that moving back toward model-led recommendations might again reduce action to a tiny number of plays. That did not happen.

### Development 2020–2022

| Lane | V1 plays | V2 plays | V1 coverage | V2 coverage |
|---|---:|---:|---:|---:|
| HHR | 23 | **54** | 35.4% | **83.1%** |
| Balanced | 24 | **55** | 36.9% | **84.6%** |
| Value | 25 | **50** | 38.5% | **76.9%** |

The preregistered HHR 75%-of-V1 coverage guard passed. Value V2 was exactly 2.0x V1 development play count, so the Value coverage warning also passed. Every Balanced candidate exceeded the preregistered coverage floor.

Thus the V2 architecture solved the historical **too-few-plays** problem in development; it did not solve out-of-sample quality.

## 2. Development looked encouraging

### HHR V2

- 54 plays
- 30 wins / 23 losses / 1 push
- non-push hit rate: **56.60%**
- ROI: **+5.63%**
- coverage: 83.08%
- average model confidence: 78.01%
- average odds: -125.80
- market mix: 8 ML / **46 spread** / 0 total

By season:
- 2020: 12 plays, 58.33% hit, +11.41% ROI
- 2021: 21, 47.62%, -11.08%
- 2022: 21, 65.00% non-push hit, +19.02%

HHR V1 over the same development period was much sparser: 23 plays, 73.91% hit, +12.99% ROI.

### Balanced development grid

All three preregistered tolerances produced the **same selected 55 wagers**:

| Variant | Model-vs-BE tolerance | Plays | Hit rate | ROI | Coverage |
|---|---:|---:|---:|---:|---:|
| B0 | 0pp | 55 | 59.26% | **+11.94%** | 84.62% |
| B1 | -1pp | 55 | 59.26% | **+11.94%** | 84.62% |
| B2 | -2pp | 55 | 59.26% | **+11.94%** | 84.62% |

All passed preregistered development gates. The frozen tie-break selected **B0 (0pp)** before confirmation was read.

B0 market mix was 4 ML / **51 spread** / 0 total. Average model confidence was 77.39%; average model-price gap was an extremely large **+24.23 percentage points**. Because the top-ranked candidates were so far above break-even under the new spread-confidence calculation, the 0/-1/-2pp price thresholds did not distinguish the selected headline stream at all.

### Value V2

- 50 plays
- 29-21
- 58.0% hit
- **+32.91% ROI**
- 76.92% coverage
- market mix: 40 ML / 10 spread / 0 total

By season:
- 2020: +14.64%
- 2021: +40.61%
- 2022: +35.39%

This was a dramatic development improvement over Value V1's 25 plays and -12.20% ROI, but it did not confirm later.

## 3. Untouched 2023–2024 confirmation failed

The preregistered development decision was frozen before confirmation. B0 was then applied untouched to 2023–2024.

| Lane | Plays | Coverage | Hit rate | ROI |
|---|---:|---:|---:|---:|
| HHR V2 | 44 | 100.0% | **45.45%** | **-18.78%** |
| Balanced V2 B0 | 44 | 100.0% | **45.45%** | **-15.92%** |
| Value V2 | 39 | 88.64% | **39.47%** | **-24.29%** |

This is a decisive non-promotion result. V2 fixed coverage but did not produce a stable recommendation product.

### HHR confirmation

- 7 ML, ROI +2.99%
- **37 spread, ROI -22.90%**
- 0 totals
- 2023: 22 plays, 36.36% hit, -31.66%
- 2024: 22, 54.55%, -5.90%

The HHR failure is overwhelmingly spread-driven.

### Balanced confirmation

- 3 ML, ROI +55.52%
- **41 spread, ROI -21.15%**
- 0 totals
- 2023: 22 plays, 45.45% hit, -15.88%
- 2024: 22, 45.45%, -15.96%

Again the failure is overwhelmingly spread-driven. The model-first price architecture did not make the card sparse; instead it admitted and prioritized a large number of spread candidates whose model-confidence probabilities were much too aggressive.

### Value confirmation

- 18 ML, ROI **-58.12%**
- 21 spread, ROI +4.71%
- 0 totals
- 2023: 19 plays, 22.22% non-push hit, -54.31%
- 2024: 20 plays, 55.0%, +4.23%

This result is different from HHR/Balanced. Value's spread component remained slightly positive in confirmation, while its ML component collapsed, consistent with the previously documented deterioration of the frozen ML dog families in later seasons.

## 4. HHR V2 does not meet the intended HHR product objective

Although HHR V2 passed its preregistered development coverage floor, its actual HHR behavior is wrong:

- development hit rate only 56.60% despite average stated model confidence of 78.01%;
- confirmation hit rate only 45.45% despite average stated model confidence of 77.20%;
- confirmation is 37/44 spread headlines.

The experiment successfully removed market juice as the source of HHR confidence, but the replacement spread-confidence conversion is not trustworthy enough for HHR. A reported ~77% model probability that realizes near 45% is a calibration failure, not an acceptable HHR tradeoff.

ML-only confirmation HHR was much smaller (7 plays) but approximately break-even/positive (+2.99%), so the immediate V2 HHR failure should not be generalized to the ML calibration without a separate trace.

## 5. Balanced price-threshold experiment was not informative

The intended B0/B1/B2 experiment asked whether Balanced should tolerate 0, 1, or 2 percentage points of model-vs-break-even concession. It did **not actually separate the selected wagers** in development:

- B0, B1, and B2 all selected the same 55 wagers;
- average selected model-price gap was +24.23pp;
- the three variants differed only in how many non-selected candidates were eligible, not the weekly headline stream.

Therefore this run does **not** provide evidence that 0pp is intrinsically the correct Balanced price tolerance. B0 won only because all three variants tied exactly and the preregistered tie-break favored B0.

Before another price-tolerance experiment, the spread model-confidence probabilities must be traced and corrected/validated independently. Otherwise any plausible 0/-1/-2pp threshold is dwarfed by the current probability gap.

## 6. Moneyline model-confidence calibration itself looks substantially more credible

The scorecard's model-only ML calibration diagnostics were stable between development and confirmation:

| Period | N | Brier | Log loss | Calibration intercept | Calibration slope |
|---|---:|---:|---:|---:|---:|
| 2020–2022 | 730 | 0.22059 | 0.63335 | 0.0463 | 0.9695 |
| 2023–2024 | 500 | 0.22189 | 0.63464 | 0.1246 | 0.9715 |

A calibration slope near 1 in both periods is encouraging. This does not prove the ML **bet-selection** families are stationary; Value's confirmation ML collapse shows they are not. It does indicate that the general ML model-confidence calibration is not showing the same obvious probability inflation seen in the selected spread headlines.

## 7. Root-cause interpretation after V2

The V2 experiment answers the play-frequency concern decisively: model-first selection can generate plenty of action.

It also reveals that there are now two distinct remaining problems:

1. **Spread confidence conversion / candidate ranking problem**
   - dominates HHR and Balanced;
   - produces implausibly high selected model probabilities (~77% average);
   - development appeared profitable but confirmation collapsed;
   - must be audited before any new HHR/Balanced threshold tuning.

2. **Later-period ML betting-edge decay**
   - dominates Value V2 confirmation, especially 2023;
   - general ML probability calibration remains stable, so this is more consistent with candidate/edge nonstationarity than a wholesale ML calibration failure.

This means the next step should **not** be a post-hoc selector threshold search. The correct next diagnostic is a read-only spread model-confidence audit:

- validate exact spread-line sign/orientation and settlement mapping;
- inspect empirical residual construction and non-finite/missing handling;
- measure spread probability calibration on all historical offered lines, independently of selector choice;
- break calibration by predicted-probability bucket, season, line magnitude, expected-margin disagreement, and chronology;
- compare model-confidence probability to realized cover rate before HHR/Balanced ranking;
- determine whether pooled residuals are producing overconfident tails and whether a calibrated spread-probability mapping is required.

No V2 selector/policy setting should be promoted from this failed confirmation.