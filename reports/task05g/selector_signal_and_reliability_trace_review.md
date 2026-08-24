# Task05G Selector Signal + ML Reliability Trace Review

Verdict: `SELECTOR_SIGNAL_CONFUSION_CONFIRMED_WITH_RELIABILITY_COLD_START_CONFOUND`

This is read-only diagnostic evidence. No football model, Task05F evaluator, selector policy, Play Through corridor, reliability thresholds, Task05E regions, or 2025 data was changed.

Validated workflow: `32763145455` — SUCCESS
Evidence artifact: `9533474744`
Artifact digest: `sha256:ec9fdb8769c8bc5f3f5470d92cf9de56bfdab93b5b4edc3b5db95cadf4e0b09d`
Validated audit code head: `4e3bc03e37815083a9c86f7c73ac03249afb8952`

## 1. HHR is using market-derived confidence as if it were football-model confidence

The prior audit found 34 HHR-eligible PLAYABLE ML offers at +10.22% ROI, but the 11 selected HHR PLAYABLE headlines were 6-5 and -20.12%.

The refined trace explains the selection difference:

| Population | N | Record | ROI | Evaluator q | Raw model q | Avg odds |
|---|---:|---:|---:|---:|---:|---:|
| HHR PLAYABLE selected | 11 | 6-5 | **-20.12%** | **69.07%** | 56.81% | **-236** |
| HHR PLAYABLE not selected | 23 | 18-5 | **+24.74%** | 62.36% | **57.20%** | -174 |

The selected subset had almost identical raw football-model probability to the unselected subset (56.81% versus 57.20%). The apparent +6.7pp confidence advantage existed only in Task05F actionable probability and came with materially worse juice.

For the selected 11 PLAYABLEs, Task05F actionable probability exceeded raw football-model probability by **12.26 percentage points on average**. Their exact-offer break-even probability averaged 69.72%, while raw model probability averaged only 56.81%.

This directly confirms the product-semantic problem: HHR is currently able to interpret an expensive market favorite as a high-confidence football pick even when the football models themselves are not materially more confident.

## 2. Raw model probability cannot simply replace Task05F actionable probability

The correction is not as simple as sorting by raw QB-Elo/XGB AVG probability.

Among all 171 HHR-eligible ML offers, ranking within block produced:

| Rank signal / band | N | Hit rate | ROI |
|---|---:|---:|---:|
| Actionable q rank 1 | 54 | 66.67% | -1.13% |
| Raw model q rank 1 | 54 | 62.96% | -4.32% |
| Raw model q rank 2 | 46 | 67.39% | +4.84% |
| Raw model q rank 3 | 34 | 79.41% | +29.42% |

These rank bands are diagnostic only and are not monotonic enough to justify a post-hoc replacement rule.

The important conclusion is narrower:

- current actionable probability is largely market-derived and therefore does not represent football-model confidence;
- raw model probabilities are not sufficiently calibrated/rank-stable to substitute blindly;
- HHR needs a **separate model-confidence probability or score**, calibrated independently of the market, with price used as a guardrail rather than as the source of confidence.

## 3. HHR model-support threshold alone does not solve selection

Using raw model probability 55% only as a diagnostic split:

- HHR-eligible ML with raw model q >=55%: 74 rows, 67.57% hit, +0.95% ROI
- raw model q <55%: 97 rows, 69.07% hit, +13.99% ROI

Among selected HHR ML:

- raw model q >=55%: 31 rows, 64.52% hit, -7.21% ROI
- raw model q <55%: 23 rows, 69.57% hit, +7.06% ROI

Thus the raw AVG probability itself is not yet a valid HHR admission threshold. The problem to fix is **signal identity/calibration**, not merely increasing the raw-model cutoff.

## 4. Balanced strict-VALUE pool is not uniformly bad; selection is destroying ML and totals

Under Balanced's other frozen constraints, the strict-VALUE pools were:

| Market | Pool N | Pool ROI | Selected N | Selected ROI |
|---|---:|---:|---:|---:|
| Moneyline | 133 | **+3.15%** | 25 | **-28.75%** |
| Spread | 189 | **+2.85%** | 27 | **+17.31%** |
| Total | 94 | **-16.64%** | 12 | **-52.18%** |

This materially refines the earlier diagnosis:

- the Balanced strict-VALUE ML pool is modestly positive before selection;
- the strict-VALUE spread pool is modestly positive and the selector improves it;
- totals are already bad before selection and become much worse;
- the current Balanced ranking is specifically anti-selecting ML and totals.

## 5. EV-first ranking is a major Balanced failure mechanism

Balanced currently gives strict VALUE status priority, then reliability, then estimated EV before actionable probability.

Inside the strict-VALUE pools, ranking by estimated EV is especially damaging:

### Moneyline

- EV rank 1: 48 rows, 21-27, **-24.60% ROI**
- EV rank 2: +12.64%
- EV rank 3: +43.46%

### Total

- EV rank 1: 15 rows, 3-12, **-61.75% ROI**
- EV rank 2: +77.24%

### Spread

- EV rank 1: 54 rows, approximately **-2.51% ROI**
- current cross-market selected spread subset: **+17.31% ROI**

Estimated EV magnitude is therefore not a trustworthy universal rank statistic. This is consistent with the earlier Value optimizer's-curse evidence.

## 6. Model provenance matters strongly for selected Balanced ML

Among the 25 selected strict-VALUE ML headlines:

- inside frozen Task05E model regions: 3 bets, 2-1, **+13.43% ROI**
- outside frozen regions: 22 bets, 8-14, **-34.51% ROI**

The full 133-row Balanced strict-VALUE ML pool was +3.15%, including +2.66% outside the frozen regions, so model-region membership is not itself a sufficient final rule. But the selector's chosen generic evaluator-created ML subset is clearly the failure population.

This supports preserving a distinct model-confidence/provenance axis rather than letting evaluator EV alone decide which ML candidate represents Balanced.

## 7. Spread is not the current Balanced problem

The 27 selected strict-VALUE spread headlines returned +17.31% ROI.

Both provenance groups were positive:

- inside frozen Expected Margin region: 11 selections, +13.38%
- outside frozen region: 16 selections, +20.02%

The strict-VALUE spread pool itself was +2.85%.

Therefore a universal Balanced rewrite that discards the useful spread evaluation/ranking behavior would be poorly targeted.

## 8. Totals should not drive a headline selector without upstream edge evidence

The strict-VALUE totals pool was 94 rows at -16.64% ROI. The 12 selected totals were 3-9 at -52.18%.

Totals still have no frozen Task05E betting-edge candidate family. Their inclusion in a generic cross-market Balanced selector is unsupported by the upstream evidence and is a large source of loss.

No production exclusion is adopted in this audit, but the evidence for keeping totals headline-eligible is currently weak.

## 9. Reliability inversion is mostly a chronology/cold-start confound

The earlier audit appeared to show that HIGH/MEDIUM reliability removed profitable ML dog Value rows. The new cause trace explains why.

### ML dog-value AVG strict VALUE

All reliability tiers:
- 76 rows, **+16.87% ROI**

LOW:
- 32 rows, 19-13, **+45.94% ROI**

MEDIUM:
- 44 rows, 17-27, **-4.27% ROI**

But LOW is concentrated in the earliest chronology:

- 2020: 4 LOW rows, 4-0, +127%
- 2021: 24 LOW rows, +46.5%
- 2022: 2 LOW rows, -100%
- 2024: 2 LOW rows, +23%

Twenty-eight of the 32 LOW rows were 2020-2021, when the dog model region was strongest and Task05F's reliability history was still cold.

LOW failure reasons overlap:
- insufficient MEDIUM support: 8
- unstable reliability history: 21
- uncertainty above MEDIUM requirement / missing: 24
- QB-Elo/XGB constituent gap >15pp: 13

### Corroborated dog strict VALUE

- all: 45 rows, +12.33%
- LOW: 16 rows, +39.19%
- MEDIUM: 29 rows, -2.48%

Again, 15 of the 16 LOW rows were in 2020-2021.

Therefore it would be incorrect to conclude that LOW reliability is intrinsically superior or to simply remove the reliability gate based on these returns.

## 10. Reliability needs semantic separation

The current LOW label conflates at least two very different states:

1. **cold-start LOW** — insufficient prior reliability history, unstable block history, or missing/large early uncertainty;
2. **signal-disagreement LOW** — mature-history rows downgraded because QB-Elo and XGB disagree materially.

For a live 2026 product with mature historical support, cold-start LOW is not operationally equivalent to a genuine mature-history confidence warning.

Future selector/evaluator design and historical validation should not treat these two reasons as if they mean the same thing.

## 11. Architecture implications before any tuning

The forensic evidence now supports these design principles:

### Hit Rate

- HHR must not use market-derived actionable probability as a proxy for football-model confidence.
- HHR should remain value-agnostic within a bounded price-sanity rule.
- A separate **market-independent calibrated model-confidence probability/score** is needed.
- Price/juice should constrain HHR, not create its confidence ranking.
- Raw QB-Elo/XGB AVG probability cannot simply be dropped in as the final rank without calibration.

### Balanced

- Balanced should not be defined as strict VALUE first.
- The primary football-quality signal should be model confidence/probability, with a tighter price constraint than HHR.
- Estimated EV magnitude should not be the primary cross-market rank.
- Spread behavior should be preserved rather than destroyed by a universal rewrite.
- Totals should not compete for headline Balanced selection without demonstrated upstream betting-edge evidence.

### Value

- Continue model-derived candidate -> exact-price evaluation -> economic ranking, as supported by the remediation and frozen candidate preservation tests.

## 12. Recommended next experiment

Do not tune arbitrary thresholds against all 2020-2024 outcomes.

First build a market-independent model-confidence layer:

- ML: calibrate raw QB-Elo/XGB AVG probability using strictly-prior football-model outcomes, without Pinnacle as an input.
- Spread: derive a model-only cover probability from Expected Margin and its residual distribution, without market blending.
- Totals: model-only probability may be computed for display/diagnosis, but totals headline eligibility remains unproven.

Then preregister a small HHR/Balanced selector family before seeing its results:

- HHR: rank model-confidence first; use price only as a bounded sanity guardrail.
- Balanced: rank model-confidence first; apply a stricter model-price tolerance than HHR.
- Value: preserve current model-first economic architecture.

Use 2020-2022 as selector-development evidence and 2023-2024 as untouched confirmation for the selector-family comparison. Keep 2025 sealed.

No threshold values are selected in this audit.