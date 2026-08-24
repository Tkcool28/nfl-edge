# Task05G Stage-by-Stage Provenance Audit Review

Verdict: `DOWNSTREAM_FAILURE_POINTS_LOCALIZED`

This is a read-only diagnostic. No football model, Task05F evaluator, selector policy, remediation policy, Task05E candidate region, threshold, or sealed 2025 data was changed.

Validation workflow: `32710883710` — SUCCESS
Evidence artifact: `9514056318`
Artifact digest: `sha256:12c337a72a699a3607ccfacf4a3dfb1db97d1cf3d504b393b33775ef72f40391`

> Follow-up refinement: `reports/task05g/playable_ml_suppression_audit_review.md` supersedes any broad reading that PLAYABLE alone explains original Balanced. It shows original Balanced selected only three PLAYABLE headlines; its 64 strict-VALUE headlines were still negative. It also corrects the ML signal trace to compare against Task05F's calibrated market anchor rather than raw Pinnacle probability.

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

This localizes a major failure: a positive raw model-candidate population becomes negative as Task05F reliability/status gates are applied when candidate families are pooled.

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

Task05F strict VALUE improves the frozen Expected Margin spread population from +5.54% to +11.10%.

The 132 VALUE-or-PLAYABLE rows contain 75 strict VALUE rows at +11.10% and 57 implied PLAYABLE-only rows at approximately -22.14%. This proves PLAYABLE can contaminate the **eligible spread pool**, especially under policies that allow PLAYABLE to outrank strict VALUE. The follow-up audit clarifies that original Balanced itself selected only three PLAYABLE headlines because its old ordering prioritized VALUE first.

## 6. Moneyline: candidate provenance remains essential

The pooled frozen ML-region union is weaker and can become negative under generic Task05F filtering, but the dog-value families behave materially better when kept distinct.

The follow-up corrected ML audit shows ML V4's final probability is overwhelmingly the calibrated market probability, with almost none of the football-model probability displacement retained. However, when model-region provenance is preserved externally and Task05F is used only as an exact-price/status filter, the dog-value VALUE subsets are strongly positive:

- ML dog-value AVG strict VALUE: +16.87% ROI
- ML corroborated dog-value strict VALUE: +12.33% ROI

Therefore the core failure is not that Task05F can never filter ML price. It is that generic evaluator probability/value is not a substitute for the model-derived candidate definition that created the useful ML population.

See `reports/task05g/playable_ml_suppression_audit_review.md` for the corrected calibrated-market trace.

## 7. Expected Margin model influence is not the main spread failure

For the 800 frozen spread candidates:

- spread-beta zero-influence rows: 525, **+5.88% ROI**
- positive-influence rows: 198, **+5.05% ROI**
- early/missing-state rows: 77, **+4.42% ROI**

The underlying Expected Margin candidate population remains positive regardless of whether Task05F fitted beta is zero or positive.

Therefore severe Balanced spread failure is not explained simply by `spread_beta == 0`.

## 8. Actionable-probability ranking is not universally broken for spread

Among all frozen Expected Margin spread candidates, rank by Task05F actionable probability within each chronological block produced:

- rank 1: 96 rows, **+10.92% ROI**
- rank 2: 92, +2.49%
- rank 3: 85, +4.01%
- rank 4+: 450, +5.49%

Thus actionable-probability ranking itself can identify a strong top spread candidate before admission/status policy distorts the candidate pool.

Ranking the same candidates by raw model-market disagreement did not improve monotonically:

- raw-disagreement rank 1: +3.05%
- rank 2: +0.97%
- rank 3: +3.44%
- rank 4+: +7.59%

No replacement ranking is adopted.

## 9. What this says about HHR

HHR should return to its intended conceptual role:

> highest-probability validated/actionable wager from the common evaluated-wager table, with sane price/reliability/product guardrails.

It should **not** be permanently restricted to frozen Task05E +ROI/model-edge regions.

The follow-up audit adds an important nuance: the broad HHR-eligible PLAYABLE pool is positive, but the specific PLAYABLE subset selected by pure highest-probability HHR ordering is negative and more heavily juiced. Therefore HHR needs a more precise price-sanity mechanism than simply accepting the generic PLAYABLE label.

## 10. What this says about Balanced

Balanced currently combines concepts that do not behave compatibly:

- win probability;
- strict evaluated Value;
- bounded Play Through / PLAYABLE;
- cross-market comparability;
- evaluator reliability;
- one headline ranking.

At least three failures are localized:

1. the full Balanced eligible population is negative despite positive estimated EV;
2. totals are strongly harmful;
3. spread strict VALUE is good, while spread PLAYABLE is poor as an eligible population.

But the follow-up audit proves removing PLAYABLE alone cannot fix original Balanced: 64 original selected strict-VALUE headlines were still -13.71% ROI.

## 11. Current root-cause map

### HHR

- Intended full-board universe: supported by evidence.
- Remediation region restriction: diagnostic over-constraint, not permanent architecture.
- Full eligible pool: positive.
- Final selection: positive.
- PLAYABLE: context-dependent; broad HHR-eligible pool positive, selected high-probability/juiced tail negative.

### Balanced

- Admission pool: already negative.
- Totals: clearly harmful.
- Spread strict VALUE: strong positive evidence.
- Spread PLAYABLE: negative eligible population and especially dangerous when allowed to outrank VALUE.
- ML/totals strict-VALUE selection remains a major failure independent of PLAYABLE.

### Value

- Full-board generic strict Value remains negative overall, especially when candidate provenance is discarded.
- Model-provenance remediation materially improved selected Value.
- Spread frozen-region strict Value and ML dog-region strict Value are the cleanest evidence that Task05F can perform useful exact-price filtering when model candidate provenance is preserved.

## 12. Next diagnostic — no policy tuning yet

The next read-only work should focus on:

1. HHR PLAYABLE ranking: why 34 HHR-eligible PLAYABLE offers are +10.22% while 11 selected PLAYABLE headlines are -20.12%.
2. Balanced strict-VALUE anti-selection: why 64 selected strict-VALUE headlines are still -13.71%, especially by market/provenance family.
3. ML candidate-family provenance: identify which non-dog ML candidate populations invert pooled ML strict VALUE.

No replacement threshold, corridor, selector, evaluator weight, or market-specific rule is selected from these same outcomes.
