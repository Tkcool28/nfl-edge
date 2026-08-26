# Task05G Value Spread Pareto Frontier V1 Review

Verdict: `PARETO_PRESERVES_SPREAD_AND_IMPROVES_STABILITY_BUT_DOES_NOT_FIX_2023_VALUE_FAILURE`

This was a preregistered retrospective selector experiment only. No Task05F evaluator, football model, Spread Confidence V3 mapping, strict-Value eligibility, candidate family, HHR, Balanced, staking rule, or 2025 data was changed.

## Evidence identity

- preregistration: `b66405a9e8f6b3f485a4a021ad33a51c3df861be`
- validated latest-head workflow: `32973201055` — SUCCESS
- artifact: `9608438080`
- digest: `sha256:5e459339be30ffbda8355e408f50fce9471cc12e8f0813f97c9b7899f371fa79`
- deterministic double replay: PASS
- frozen focused tests: PASS
- Task05F reproduction: PASS
- Model Confidence V2 reproduction: PASS
- Spread Confidence V3 reproduction: PASS
- 2025 firewall: PASS
- spread-frontier coverage parity: PASS

An earlier workflow attempt failed before Pareto output because the new runner called a reliability tie-break helper from the wrong module. The implementation-only defect was corrected from `final._reliability_rank(r)` to the existing frozen helper `final._rel(core, r)`. The preregistration, eligibility, ranking formula, anti-neutering invariant, models, thresholds, and candidate families were unchanged.

## 1. Anti-neutering result — PASS

The user concern that corroboration might neuter spread was not realized.

- current valid spread-frontier blocks: 60
- Pareto valid spread-frontier blocks: 60
- exact block identity parity: PASS
- current final Value spread plays: 42
- Pareto final Value spread plays: 42
- spread -> ML final-card changes: 0
- ML -> spread final-card changes: 0
- new PASS changes: 0

Thus Pareto changed **which spread** won in selected blocks without reducing spread availability or final Value spread share.

## 2. Isolated spread frontier

### 2020-2024 overall

Current raw-margin frontier:
- 60 plays
- 37-23
- 61.67% hit rate
- +17.65% ROI
- max losing streak 4
- average raw cover margin 3.029
- average Spread V3 q 51.123%

Pareto:
- 60 plays
- **38-22**
- **63.33% hit rate**
- **+20.92% ROI**
- max losing streak 4
- average raw cover margin 2.931
- average Spread V3 q 51.098%
- average original raw-margin rank selected: 1.13

Pareto changed 8 of 60 frontier blocks. Paired changed-block outcomes:
- Pareto win / raw loss: 2
- raw win / Pareto loss: 1
- both win: 4
- both loss: 1

This is directionally favorable and confirms that modest smoothing can improve the frontier without discarding model signal.

### Development 2020-2022

Current:
- 35 plays
- 24-11
- 68.57% hit
- +31.40% ROI

Pareto:
- 35 plays
- 23-12
- 65.71% hit
- +26.15% ROI

Pareto lost one net win in the development period. The damage was concentrated in 2021; 2022 was completely unchanged.

### Exposed 2023-2024 diagnostic

Current:
- 25 plays
- 13-12
- 52.0% hit
- -1.61% ROI

Pareto:
- 25 plays
- **15-10**
- **60.0% hit**
- **+13.60% ROI**

Both changed blocks in 2023-2024 converted current rank-1 losses into Pareto wins.

## 3. 2023 — partial repair, not enough

Current raw-margin spread frontier:
- 12 plays
- **3-9**
- 25.0% hit
- **-51.81% ROI**
- max losing streak 4

Pareto:
- same 12 plays / same spread coverage
- **4-8**
- **33.33% hit**
- **-36.04% ROI**
- max losing streak 4

Pareto therefore improved 2023 by:
- +8.33pp hit rate
- +15.77pp ROI
- zero coverage loss

But -36% remains unacceptable for a Value product.

The reason Pareto could not do more is important: it changed only one of the twelve 2023 spread-frontier blocks. In most bad weeks the maximum raw-margin candidate was also first or second on Task05F economic corroboration, so the two signals were jointly wrong rather than disagreeing.

The one changed 2023 block was Week 18:
- current raw-margin frontier: TB-CAR home +5 -110, raw margin 4.905, LOSS
- Pareto: MIN-DET home -3.5 -112, raw margin 4.290, original raw rank 2, WIN

This converted one loss to one win but left the other eight rank-1 losses untouched because they remained strongly Pareto-ranked.

## 4. 2024 — favorable and preserved

Current:
- 13 spread-frontier plays
- 10-3
- 76.92% hit
- +44.74% ROI

Pareto:
- same 13 plays
- **11-2**
- **84.62% hit**
- **+59.42% ROI**

Only one 2024 block changed, converting another current loss to a Pareto win.

Thus Pareto did not destroy the strong 2024 spread signal.

## 5. Full user-facing Value card

The existing Final Selector Candidate V1 was rerun with only the spread frontier substituted.

### Overall 2020-2024

Current Value:
- 78 plays
- 45-33
- 57.69% hit
- +22.41% ROI
- 36 ML / 42 spread

Value with Pareto spread:
- same 78 plays
- **47-31**
- **60.26% hit**
- **+27.38% ROI**
- same 36 ML / 42 spread

Changed Value blocks: 5.
No market-type changes and no PASS changes occurred.

### Development 2020-2022

Current:
- 47 plays
- 32-15
- 68.09% hit
- +50.82% ROI

Pareto spread:
- same 47 plays
- 32-15
- 68.09% hit
- +50.97% ROI

Essentially unchanged user-facing development performance despite the isolated spread-frontier 2021 loss, because the full Value card did not always select the altered spread finalist.

### 2023-2024

Current:
- 31 plays
- 13-18
- 41.94% hit
- -20.65% ROI

Pareto spread:
- same 31 plays
- **15-16**
- **48.39% hit**
- **-8.39% ROI**

Material improvement, still negative.

### 2023 specifically

Current:
- 15 plays
- 3-12
- 20.0% hit
- -61.45% ROI
- 4 ML / 11 spread

Pareto spread:
- same 15 plays
- **4-11**
- **26.67% hit**
- **-48.83% ROI**
- same 4 ML / 11 spread

The 2023 disaster is reduced but not solved.

### 2024 specifically

Current:
- 16 plays
- 10-6
- 62.5% hit
- +17.60% ROI

Pareto spread:
- same 16 plays
- **11-5**
- **68.75% hit**
- **+29.53% ROI**

## 6. Model-signal preservation

Pareto did not collapse toward a lower-rank or economics-only selector.

Across all 60 spread-frontier blocks:
- average original raw-margin rank selected = 1.13
- current = 1.00
- average raw cover margin changed only 3.029 -> 2.931
- average calibrated Spread V3 q changed only 51.123% -> 51.098%
- max raw cover margin remained 5.253

So the method made a small smoothing adjustment rather than suppressing strong Expected-Margin candidates.

The full frozen Task05E 0-4 provenance remains intact; no bucket was removed.

## 7. Verdict

`PARETO_BALANCED` is a **useful partial improvement**:

- exact spread availability preserved;
- final Value spread volume preserved 42/42;
- overall spread-frontier hit/ROI improved;
- 2023 and 2024 both improved;
- full Value overall improved from 57.69% / +22.41% to 60.26% / +27.38%;
- later 2023-2024 improved from -20.65% to -8.39%.

But it does **not** meet the product objective of making Value acceptably robust because 2023 remains 4-11 / -48.83% in the user-facing Value card.

Do not promote this as final Value policy yet.

## 8. Remaining diagnosis

The remaining 2023 losses are not predominantly cases where raw model extremity and Task05F economics disagree. In most of those weeks they rank the same candidate highly. Therefore a two-signal Pareto rule cannot identify the failure.

The next bounded question should be whether the **strict-Value confidence itself is overstated when Spread V3 says all candidates are essentially ~50-52% cover propositions**. The existing spread family can remain eligible, but Value may need an independent minimum evidence/edge-quality requirement or a calibrated economic-confidence layer rather than simply ranking among all EV > 0 rows.

Any such rule must be separately preregistered and must preserve the user's concern that the proven 0-4 Expected-Margin region not be arbitrarily removed or reduced to near-zero spread coverage.

No 2025 data was opened.
