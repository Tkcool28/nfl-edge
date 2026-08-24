# Task05G PLAYABLE + ML Suppression Audit Review

Verdict: `PLAYABLE_IS_CONTEXT_DEPENDENT_AND_ML_MODEL_SIGNAL_IS_EFFECTIVELY_ZEROED`

This is a read-only diagnostic follow-up to the stage-by-stage provenance audit. No selector threshold, Play Through corridor, evaluator parameter, football model, Task05E candidate region, or sealed 2025 data was changed.

Validated workflow: `32714050883` — SUCCESS
Evidence artifact: `9515233891`
Artifact digest: `sha256:41f6c71d25c16fe9f95649375c1e9cd9e52c60de78a4c849e77d61efd2dcf742`
Validated audit code head: `7d34a0f9187f3af1bd0de92c3bb7d375b2d761f0`

## 1. Why this audit was needed

The prior stage audit localized two likely mechanisms:

1. `PLAYABLE` / Play Through admission appeared to contaminate Balanced, especially spread.
2. ML V4 appeared to suppress the football-model signal that originally created profitable model candidates.

The purpose here was not to change either mechanism. It was to measure them directly and answer the coverage question: how many headline opportunities does PLAYABLE actually add beyond strict VALUE, and what happens to those incremental plays?

## 2. PLAYABLE was intentionally distinct from VALUE

The frozen Task05F contract is:

- `VALUE`: strict evaluator expected value > 0.
- `PLAYABLE`: a bounded Play Through concession below strict break-even, never relabeled as Value.
- Maximum frozen break-even concession: 1.5 percentage points.

Therefore PLAYABLE should be analyzed as a separate product/actionability state, not as weak VALUE.

## 3. Full HIGH/MEDIUM PLAYABLE population

Across exact-shopped DK/FD offers with HIGH/MEDIUM reliability:

| Market | N | Hit rate | ROI |
|---|---:|---:|---:|
| All PLAYABLE | 313 | 45.48% | **-11.59%** |
| Moneyline | 113 | 49.56% | **-1.74%** |
| Spread | 171 | 44.97% | **-13.77%** |
| Total | 29 | 32.14% | **-37.17%** |

Average estimated EV for the full PLAYABLE population was -0.79%, as expected for a below-break-even concession state. The realized loss was much larger than that estimate.

This immediately shows that PLAYABLE cannot safely be treated as one market-agnostic headline class.

## 4. The 1.5pp maximum is not the simple explanation

Most PLAYABLE rows were nowhere near the full 1.5pp maximum concession:

| Break-even concession | N | ROI |
|---|---:|---:|
| 0.50–0.75pp | 256 | **-12.80%** |
| 0.75–1.00pp | 46 | -4.16% |
| 1.00–1.25pp | 11 | -14.57% |

There were no material populations in the narrower <0.50pp or far 1.25–1.50pp bands in this board.

Therefore the problem is not simply that the corridor was allowed to extend to 1.5pp. The dominant losing PLAYABLE population was already only about 0.5–0.75pp below the frozen break-even boundary.

Likewise, realized ROI was not monotonic with evaluator estimated EV inside PLAYABLE:

- estimated EV -0.50% to 0%: 104 rows, **-26.83% ROI**
- -1.00% to -0.50%: 120, -7.53%
- -2.00% to -1.00%: 81, +1.55%

This is evidence of calibration/market-composition problems, not a clean "smaller negative EV = safer" relationship.

## 5. PLAYABLE adds very little headline coverage

### Hit Rate

- current VALUE-or-PLAYABLE eligible blocks: 59
- blocks with at least one strict VALUE under the same HHR constraints: 55
- blocks created only by PLAYABLE: **4**
- incremental coverage: **6.78%** of HHR play blocks

Those four PLAYABLE-only HHR selections:

- 2-2
- average odds -236.75
- **-25.38% ROI**

### Balanced

- current VALUE-or-PLAYABLE eligible blocks: 67
- blocks with at least one strict VALUE under the same Balanced constraints: 64
- blocks created only by PLAYABLE: **3**
- incremental coverage: **4.48%** of Balanced play blocks

Those three incremental selections:

- 1-2
- one ML win, one spread loss, one total loss
- **-45.02% ROI**

Thus PLAYABLE did not solve a large historical coverage shortage in either lane. It added only seven lane-blocks total across the full 2020-2024 chronology, and those incremental selections were negative.

## 6. HHR: PLAYABLE pool is useful, but HHR ranking anti-selected it

This is the most important nuance.

The 34 exact offers that were both PLAYABLE and HHR-eligible were:

- all moneyline
- 24-10
- 70.59% hit rate
- **+10.22% ROI**
- average actionable probability 64.53%
- average odds -194.44

So PLAYABLE is **not inherently bad for HHR**.

However, the original HHR selector actually selected 11 PLAYABLE headlines:

- 6-5
- 54.55% hit rate
- **-20.12% ROI**
- average actionable probability 69.07%
- average odds -236.36

The 48 HHR headlines that happened to be strict VALUE were:

- 35-13
- 72.92% hit rate
- **+12.35% ROI**

This localizes a second-order HHR issue: within the otherwise positive HHR-eligible PLAYABLE pool, pure highest-probability ordering selected a more heavily juiced subset that performed much worse.

That does **not** justify replacing HHR with strict-VALUE-only selection; HHR is intentionally not a Value selector. It does show that the generic PLAYABLE label is too coarse to serve as HHR's only price-sanity mechanism.

## 7. Balanced: PLAYABLE is harmful, but it is not the whole original failure

The 192 PLAYABLE offers satisfying Balanced's other eligibility constraints returned:

| Market | N | ROI |
|---|---:|---:|
| All Balanced-eligible PLAYABLE | 192 | **-13.46%** |
| Moneyline | 32 | **+8.13%** |
| Spread | 131 | **-13.48%** |
| Total | 29 | **-37.17%** |

So spread and totals are the major PLAYABLE contamination sources for Balanced, while the ML PLAYABLE subset was positive in this development evidence.

However, original Balanced selected only **3 PLAYABLE headlines** because its old ordering prioritized VALUE status first. Those three returned -45.02%, but the other **64 selected strict-VALUE headlines still returned -13.71% ROI**.

Therefore removing PLAYABLE alone does **not** fix original Balanced.

This also explains why the preregistered remediation became even more exposed to PLAYABLE: its probability-first Balanced ordering no longer privileged strict VALUE, so it promoted more PLAYABLE spreads, including the previously observed catastrophic remediation PLAYABLE spread subset.

## 8. ML V4 suppression: corrected calibrated-market trace

The ML diagnostic uses Task05F's actual calibrated market anchor (`staking_anchor_probability` for ML), not raw Pinnacle probability. This distinction matters because ML V4 first calibrates Pinnacle and then applies model weight.

### Frozen ML dog-value AVG region

- 232 exact-shopped candidates
- realized ROI: **+5.10%**
- raw football-model selected-side probability: **44.86%**
- calibrated market probability: **38.88%**
- final Task05F conditional probability: **38.89%**
- raw model minus calibrated market: **+5.98pp**
- final minus raw model: **-5.97pp**
- average retained model-vs-market probability displacement: approximately **0.21% of the original gap**

For the 184 rows in zero-model-weight blocks:

- calibrated market: 38.89%
- final evaluator probability: 38.89% — effectively exact identity
- retained model displacement: approximately zero
- 121/184 final probabilities were below exact-offer break-even
- realized ROI of that zero-weight subgroup: -1.57%

For the 23 positive-model-weight rows, the final probability still retained only about 1.88% of the model-vs-calibrated-market displacement on average.

### Frozen corroborated dog-value region

- 140 candidates
- realized ROI: **+4.53%**
- raw football-model probability: **45.78%**
- calibrated market probability: **37.78%**
- final Task05F conditional probability: **37.79%**
- raw model minus calibrated market: **+8.00pp**
- final minus raw model: **-7.99pp**
- average retained model displacement: approximately **0.23%**

In the 107 zero-model-weight rows, final evaluator probability was exactly the calibrated market probability to floating-point precision.

This confirms the architecture diagnosis: ML V4 is not meaningfully blending the model signal into the final probability in the historical blocks. It is overwhelmingly a calibrated-market probability evaluator.

## 9. Important counterpoint: model-first candidate gating lets the evaluator work as a price filter

Despite that suppression, Task05F performs well **inside the already-defined dog model regions** when it is used only to judge price/status:

### ML dog-value AVG

- full region: +5.10% ROI
- strict VALUE subset: 76 rows, **+16.87% ROI**
- PLAYABLE subset: 10 rows, +19.80%
- LEAN subset: 121 rows, -12.44%

### ML corroborated dog-value

- full region: +4.53%
- strict VALUE subset: 45 rows, **+12.33% ROI**
- PLAYABLE subset: 4 rows, +18.00%
- LEAN subset: 73 rows, -14.00%

This is critical. It means the evaluator does not need to replace candidate discovery with its own calibrated probability in order to be useful. The successful architecture is:

`model-derived candidate population -> evaluator exact-price/status filter`

Within the frozen dog regions, that combination materially improves ROI.

The failure occurs when generic evaluator output is asked to discover/rank the entire ML board as though its market-derived probability were the football-model signal.

## 10. Refined root-cause map

### PLAYABLE

- As a global market-agnostic class: poor (-11.59%).
- As Balanced eligibility: poor, especially spread and totals.
- As HHR eligibility: potentially useful (+10.22% pool), but the current highest-probability HHR ranking anti-selected the subset it actually promoted.
- Coverage benefit: small — only 4 extra HHR blocks and 3 extra Balanced blocks.
- 1.5pp maximum corridor width is not the sole problem; losses are concentrated even within the common 0.5–0.75pp concession band.

### ML evaluator

- ML V4 effectively collapses final probability to calibrated Pinnacle in most candidate rows.
- This makes it unsuitable as a replacement for model-derived candidate discovery/ranking.
- Yet as an exact-price/status filter **after** model candidate provenance is preserved, it successfully improves the frozen dog-region populations.

### Balanced

- Original Balanced is not rescued merely by removing PLAYABLE; 64 strict-VALUE selections were still -13.71%.
- PLAYABLE becomes a severe additional problem when probability-first ranking is allowed to promote it ahead of strict VALUE, as occurred in the remediation.
- Totals remain clearly harmful and have no validated upstream betting-edge family.

## 11. What should be investigated next — still no policy tuning

The evidence now argues against one universal fix such as "delete PLAYABLE" or "shrink the corridor from 1.5pp to X."

The next read-only diagnostic should isolate:

1. **HHR PLAYABLE ranking**
   - why the full HHR-eligible PLAYABLE pool is +10.22% while the 11 selected PLAYABLE headlines are -20.12%;
   - probability/price rank within those 34 rows;
   - whether the selected tail is simply the most heavily juiced/highest-probability tail.

2. **Balanced strict-VALUE anti-selection**
   - 64 original selected strict-VALUE headlines were still -13.71%;
   - decompose strict VALUE by market and candidate provenance;
   - determine why cross-market headline ranking turns positive spread strict VALUE evidence into a losing overall product.

3. **ML candidate-family provenance**
   - dog-region strict VALUE works;
   - generic/family-union ML strict VALUE does not;
   - locate which non-dog ML candidate populations invert the aggregate and why.

No replacement corridor, market-specific PLAYABLE rule, or selector threshold is adopted from these outcomes.