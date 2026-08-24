# Task05G Stage-by-Stage Provenance Audit Review

Verdict: `DOWNSTREAM_FAILURE_POINTS_LOCALIZED`

This is a read-only diagnostic. No football model, Task05F evaluator, selector policy, remediation policy, Task05E candidate region, threshold, or sealed 2025 data was changed.

Validation workflow: `32710883710` — SUCCESS
Evidence artifact: `9514056318`
Artifact digest: `sha256:12c337a72a699a3607ccfacf4a3dfb1db97d1cf3d504b393b33775ef72f40391`

## 1. Architecture correction: frozen Task05E regions are not the intended HHR universe

The Task05G remediation intentionally forced all three headline lanes through four frozen Task05E model-candidate regions to test whether restoring football-model provenance corrected the prior pathology.

That was a diagnostic experiment, not the intended permanent Hit Rate architecture.

The updated Market Evaluation Layer plan defines one common evaluated-wager table consumed by Hit Rate, Balanced, and Value. Hit Rate's primary objective is actionable win probability, subject to reliability, price sanity, historical support, and product constraints.

Therefore the remediation region gate must not silently become permanent HHR/Balanced eligibility.

## 2. Hit Rate: full-board architecture is materially healthier

### Full intended HHR eligibility pool

- 201 eligible exact shopped offers
- 135 wins / 66 losses
- non-push hit rate: 67.16%
- ROI: **+8.94%**
- average actionable probability: 62.88%
- average expected EV: +2.40%

By market:

- ML: 171 offers, 68.42% hit rate, **+8.35% ROI**
- spread: 15 offers, 73.33% hit rate, **+36.96% ROI**
- total: 15 offers, 46.67% hit rate, **-12.28% ROI**

### Original full-board HHR selections

- 59 selections
- 41-18
- hit rate: 69.49%
- ROI: **+6.30%**

Crucially, frozen Task05E region membership was rare:

- inside frozen regions: **4 / 59**, ROI +18.46%
- outside frozen regions: **55 / 59**, ROI **+5.42%**, 69.09% hit rate

Thus the original HHR was overwhelmingly a full-board probability-oriented product. Restricting HHR to the frozen +ROI/model-edge regions is not justified by either the architecture or the evidence.

The remediation's 15-play +20.47% HHR result is useful diagnostic evidence but is too sparse and over-constrained to redefine HHR.

## 3. Balanced: failure begins before the weekly selector

The full-board Balanced eligibility pool was already economically wrong before one wager per week was selected:

- 608 eligible offers
- average evaluator EV: **+1.52%**
- realized ROI: **-5.25%**
- non-push hit rate: 51.57%

This is a direct evaluator/eligibility calibration failure: the population called eligible had positive estimated economics and negative realized economics.

By market:

- ML: 165 eligible, **+4.12% ROI**
- spread: 320 eligible, **-3.84% ROI**
- total: 123 eligible, **-21.48% ROI**

The final original Balanced selector then worsened the population:

- all: 67 selections, **-15.12% ROI**
- ML: 26, **-25.15% ROI**
- spread: 28, **+13.12% ROI**
- total: 13, **-55.86% ROI**

Interpretation:

1. Balanced's problem is not solely a weekly ranking bug; its admission pool is already negative.
2. The weekly ranking actually improved spread performance but severely anti-selected ML and totals.
3. Totals remain an obvious unsupported headline source.

## 4. What happens to the frozen model-candidate regions through Task05F

The frozen-region registry contained 1,202 unique model-candidate sides represented on the Task05F board.

Stage-by-stage:

| Stage | N | ROI |
|---|---:|---:|
| Exact shopped model candidates | 1,202 | **+4.25%** |
| Task05F supported | 1,086 | **+2.87%** |
| HIGH/MEDIUM reliability | 711 | **-0.70%** |
| VALUE or PLAYABLE | 223 | **-4.97%** |
| Strict VALUE | 151 | **-1.23%** |
| Balanced eligible | 125 | **-4.81%** |
| HHR eligible | 19 | **+23.17%** |

This localizes a major failure: a positive raw model-candidate population becomes negative as Task05F reliability/status gates are applied.

## 5. Spread: strict Value works; VALUE + PLAYABLE does not

The frozen Expected Margin 0-4 spread region behaves very differently from the global Balanced result.

| Stage | N | ROI |
|---|---:|---:|
| Exact shopped | 800 | **+5.54%** |
| Supported | 723 | **+5.66%** |
| HIGH/MEDIUM | 481 | **+3.67%** |
| Strict VALUE | 75 | **+11.10%** |
| VALUE or PLAYABLE | 132 | **-3.25%** |
| Balanced eligible | 112 | **-5.14%** |
| HHR eligible | 6 | **+55.34%** |

This is important: Task05F strict VALUE actually **improves** the frozen Expected Margin spread population from +5.54% to +11.10%.

The collapse occurs when `PLAYABLE` is combined with strict `VALUE` for headline eligibility.

The 132 VALUE-or-PLAYABLE spread rows consist of:

- 75 strict VALUE rows at +11.10% ROI
- 57 implied PLAYABLE-only rows

Because flat-unit ROI is additive, the implied 57 PLAYABLE-only rows returned approximately **-22.14% ROI**.

This identifies `PLAYABLE` headline admission as a major Balanced contamination path in spread.

The remediation selections reinforce this diagnosis: its 12 Balanced spread selections with `PLAYABLE` status returned approximately **-84.42% ROI**.

`PLAYABLE` was designed as a bounded Play Through concession, especially useful for exact alternate/manual/full-board price handling. The architecture does not require it to be treated as equivalent to strict Value for top headline eligibility.

## 6. Moneyline: Task05F is suppressing rather than recovering model-region edge

The frozen ML region union is weaker than spread but shows a different failure mode.

ML model-candidate stages:

- exact shopped: 402 rows, **+1.70% ROI**
- supported: 363, **-2.69%**
- HIGH/MEDIUM: 230, **-9.85%**
- strict VALUE: 76, **-13.39%**
- VALUE or PLAYABLE: 91, **-7.46%**

The individual frozen dog regions are especially revealing:

### ML dog-value AVG

- 232 exact shopped rows
- realized ROI: **+5.10%**
- evaluator average expected EV: **-3.77%**
- evaluator average actionable probability: 38.70%

### ML corroborated dog-value

- 140 exact shopped rows
- realized ROI: **+4.53%**
- evaluator average expected EV: **-4.31%**
- evaluator average actionable probability: 37.60%

The evaluator is therefore systematically assigning negative economics to two model-defined populations that were positive over the full 2020-2024 development sample. This is consistent with the earlier forensic finding that ML V4 usually gives the football model zero incremental weight and largely follows the market anchor.

In other words, for these ML candidates the evaluator is often not "cherry-picking the good model picks" because it has largely discarded the signal that made them model candidates in the first place.

## 7. Expected Margin model influence is not the main spread failure

For the 800 frozen spread candidates:

- spread-beta zero-influence rows: 525, **+5.88% ROI**
- positive-influence rows: 198, **+5.05% ROI**
- early/missing-state rows: 77, **+4.42% ROI**

The underlying Expected Margin candidate population remains positive regardless of whether Task05F fitted beta is zero or positive.

Therefore the severe Balanced spread failure is not explained simply by `spread_beta == 0`.

The stronger localization is the subsequent status/eligibility path, especially PLAYABLE admission.

## 8. Actionable-probability ranking is not universally broken for spread

Among all frozen Expected Margin spread candidates, rank by Task05F actionable probability within each chronological block produced:

- rank 1: 96 rows, **+10.92% ROI**
- rank 2: 92, +2.49%
- rank 3: 85, +4.01%
- rank 4+: 450, +5.49%

Thus actionable-probability ranking itself can identify a strong top spread candidate **before** the Balanced VALUE/PLAYABLE admission path distorts the population.

For comparison, ranking the same candidates by raw model-market disagreement magnitude did not improve monotonically:

- raw-disagreement rank 1: +3.05%
- rank 2: +0.97%
- rank 3: +3.44%
- rank 4+: +7.59%

This is evidence against simply replacing evaluator probability with "largest raw model disagreement." No replacement rule is adopted here.

## 9. What this says about HHR

HHR should return to its intended conceptual role:

> highest-probability validated/actionable wager from the common evaluated-wager table, with sane price/reliability/product guardrails.

It should **not** be permanently restricted to the frozen Task05E +ROI/model-edge regions.

The full-board evidence already demonstrates that most successful HHR selections came from outside those regions.

This does not mean HHR should ignore price completely. The product has always intended to avoid obviously overpriced favorites. It means historical +ROI-region membership is not an HHR prerequisite.

## 10. What this says about Balanced

Balanced currently combines several concepts that are not behaving compatibly:

- positive/high win probability;
- strict evaluated Value;
- bounded Play Through / PLAYABLE status;
- cross-market comparability;
- evaluator reliability;
- one headline ranking.

The audit shows at least three distinct failures:

1. the full Balanced eligible population is negative despite positive estimated EV;
2. totals are strongly harmful;
3. spread strict VALUE is good, while spread PLAYABLE is strongly bad.

For ML, the evaluator itself appears to be suppressing the model-defined edge before Balanced ever ranks it.

Therefore "fix Balanced's sort order" is insufficient.

## 11. Current root-cause map

### HHR

- Intended full-board universe: supported by evidence.
- Remediation frozen-region restriction: diagnostic over-constraint, not permanent architecture.
- Full eligible pool: positive.
- Final selection: positive.
- Primary unresolved question: whether PLAYABLE should be allowed in HHR headlines at all, since the original selected PLAYABLE ML subset was weaker than strict Value selections.

### Balanced

- Admission pool: already negative.
- Totals: clearly harmful.
- Spread strict VALUE: strong positive evidence.
- Spread PLAYABLE: severe negative contamination.
- ML: Task05F reliability/value filtering anti-selects frozen model candidates.
- Weekly ranking: additionally worsens ML/totals.

### Value

- Full-board generic strict Value remains negative overall, especially ML/totals.
- Model-provenance remediation materially improved the selected Value lane.
- Spread frozen-region strict Value remains the cleanest evidence that Task05F can perform useful price filtering when candidate provenance is preserved.

## 12. Next diagnostic — no policy tuning yet

Before changing selector rules, the next read-only work should focus on two exact mechanisms:

1. **PLAYABLE / Play Through audit**
   - why rows inside a maximum 1.5pp break-even concession are so negative;
   - whether the issue is probability miscalibration, price distribution, market mix, or use of PLAYABLE as headline eligibility rather than display/actionability information;
   - HHR and Balanced separately.

2. **ML evaluator suppression audit**
   - trace raw QB-Elo/XGB/AVG probability, Pinnacle anchor, fitted ML model weight, actionable probability, break-even, status, and realized outcome for the frozen ML dog regions;
   - quantify exactly how often Task05F changes a historically profitable model candidate into PASS/LEAN versus VALUE/PLAYABLE;
   - identify whether shrinkage-to-market is systematically over-aggressive in the candidate tail.

No replacement threshold, selector, evaluator weight, or market-specific rule should be chosen until those mechanisms are understood.
