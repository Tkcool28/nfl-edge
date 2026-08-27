# Task05G Value ML 2023 State-Depth Audit V1 Review

Verdict: `RESIDUAL_VALUE_FAILURE_LOCALIZES_TO_UNCORROBORATED_NONMATURE_SINGLETON_ML_PLUS_ONE_COLD_CROSSMARKET_LOSS`

This was a preregistered retrospective forensic audit only. No football model, Task05F evaluator, confidence mapping, candidate family, selector, spread Pareto rule, PR #47 spread fail-safe, staking rule, or 2025 data was changed.

## Evidence identity

- preregistration: `e9257250dc937e360e60d14473b062d65cbff6d5`
- validated workflow: `33040224105` — SUCCESS
- artifact: `9633578970`
- digest: `sha256:69e4a978e5f41d1abff947012a642605cc0f6157b719daaf116ac42aeb8135b1`
- deterministic double replay: PASS
- frozen focused tests: PASS
- Task05F reproduction: PASS
- Model Confidence V2 reproduction: PASS
- Spread Confidence V3 reproduction: PASS
- 2025 firewall: PASS

## 1. Critical state-label clarification

The existing causal ML state machine calls every block with fewer than three prior settled ML-frontier observations `GREEN`, because AMBER cannot legally activate until `n >= 3`.

For reporting only, this audit split that existing GREEN state into:

- `COLD`: n < 3;
- `MATURE_GREEN`: n >= 3 and existing state remains GREEN.

This introduced no new policy threshold. It merely exposed that `GREEN` currently conflates "healthy" and "insufficient same-season evidence."

## 2. Selected ML Value by season

The final Pareto Value baseline / PR #47 user-facing card selected 36 ML headlines over 2020-2024. PR #47 changes only spread->PASS, so ML headline identity is unchanged.

- 2020: 3 ML, **3-0**, +3.800u, +126.67% flat ROI
- 2021: 16 ML, **10-6**, +8.742u, +54.64%
- 2022: 10 ML, **6-4**, +4.490u, +44.90%
- 2023: 4 ML, **0-4**, -4.000u, -100.0%
- 2024: 3 ML, **0-3**, -3.000u, -100.0%

Thus later-period ML Value decay is real in the selected headline stream and is not limited to 2023. This is consistent with prior Task05G evidence that ML Value families weakened in the exposed later period while spread Value remained healthier.

## 3. Exact four 2023 ML losses

### Week 4 — ATL/JAX away ML +150

- settlement: LOSS
- existing ML state: GREEN
- descriptive evidence status: **COLD**
- prior ML frontier observations: n=0
- trust: 0.500
- strict ML candidate depth: **3**
- q: 53.34%
- break-even: 40.00%
- model-price gap: +13.34pp
- evaluated edge: +1.41pp
- exact expected value: +3.49%
- valid Pareto spread frontier: YES, depth 3
- selection reason: **GREEN cross-market comparison winner**

This loss is not a singleton/only-family case. Any narrow singleton fail-safe would correctly leave it untouched.

### Week 7 — LV/CHI away ML -126

- settlement: LOSS
- existing state: GREEN
- evidence status: **COLD**
- n=1
- trust already down to **0.444**
- ML candidate depth: **1**
- q: 59.94%
- break-even: 55.75%
- model-price gap: +4.18pp
- evaluated edge: +1.86pp
- expected value: +3.32%
- valid spread frontier: **NO**
- selection reason: **COLD only family**

### Week 8 — CLE/SEA away ML +176

- settlement: LOSS
- existing state: GREEN
- evidence status: **COLD**
- n=2
- trust down to **0.400**
- ML candidate depth: **1**
- q: 45.47%
- break-even: 36.23%
- model-price gap: +9.23pp
- evaluated edge: only **+0.54pp**
- expected value: +1.48%
- valid spread frontier: **NO**
- selection reason: **COLD only family**

### Week 12 — TB/IND away ML +130

- settlement: LOSS
- existing state: **AMBER**
- n=4
- trust: **0.333**
- ML candidate depth: **1**
- q: 47.24%
- break-even: 43.48%
- model-price gap: +3.77pp
- evaluated edge: only **+0.27pp**
- expected value: only **+0.61%**
- valid spread frontier: **NO**
- selection reason: **AMBER only family**

Three of the four 2023 ML losses therefore share a very narrow structure: the ML family lacks mature healthy same-season evidence, exactly one strict ML candidate survives, and no valid spread alternative exists.

## 4. Cross-season state x depth guard

Selected ML headlines over all 2020-2024:

### COLD singleton

- 4 plays
- **1-3**
- 25.0% hit
- -1.700u
- -42.50% ROI

The one winner was 2020 Week 14 and **had a valid spread alternative**.

The three COLD singleton headlines with **no spread alternative** were:

- 2023 Week 7 — LOSS
- 2023 Week 8 — LOSS
- 2024 Week 5 — LOSS

Result: **0-3, -3.0u**.

### AMBER singleton

- 2 selected plays
- **0-2**
- -2.0u
- both had **no spread alternative**
- seasons: 2023 and 2024

They were:

- 2023 Week 12 — LOSS
- 2024 Week 11 — LOSS

### Combined non-mature/degraded singleton + no spread alternative

Using only already-defined evidence states plus exact candidate depth and family availability:

- COLD singleton + no spread: 0-3
- AMBER singleton + no spread: 0-2
- combined: **0-5, -5.0u**
- all five occurrences are in 2023-2024

This is the sharpest coherent cell in the audit.

## 5. Why this is not a global singleton ban

Singleton ML itself is not bad.

### MATURE_GREEN singleton selected headlines

- 10 plays
- **8-2**
- 80.0% hit
- +8.522u
- +85.22% flat ROI
- seasons: 2020-2022

The full ML frontier tells the same directional story:

- MATURE_GREEN singleton frontier: 11 rows, 8-3, +68.38% ROI
- AMBER singleton frontier: 8 rows, 3-5, -21.15% ROI
- COLD singleton frontier: 4 rows, 1-3, -42.50% ROI

Therefore `singleton = bad` is contradicted by the evidence. The interaction with immature/degraded family evidence is what matters.

## 6. Why this is not a global cold-start ban

COLD ML with no spread alternative is also not universally bad.

Examples that would be wrongly removed by a blanket cold/no-spread ban:

- 2020 Week 12, candidate depth 2, +130: WIN
- 2022 Week 5, candidate depth 4, +198: WIN

The six selected COLD/no-spread headlines across all depths were 2-4 but still -0.72u only because the two wins were plus-money. Candidate depth materially distinguishes the strongest failure cell.

Similarly, COLD competitive selected headlines overall were 4-4 with +2.18u / +27.25% ROI. Cold-start alone does not justify a PASS.

## 7. Why this is not a global AMBER ban

The full ML frontier had four AMBER competitive opportunities:

- 2-2
- +1.34u
- +33.5% ROI

No AMBER competitive ML became the existing user-facing headline, because the current state machine gives a valid spread frontier priority in AMBER. This supports preserving competitive alternatives rather than globally barring all AMBER ML.

## 8. Family-availability finding

Across all 36 selected ML Value headlines, simple `no spread alternative` is not itself a failure mechanism:

- no spread alternative: 18 plays, 9-9, +4.590u, +25.50% ROI
- spread alternative present: 18 plays, 10-8, +5.442u, +30.23% ROI

The harmful cell is narrower: **non-mature/degraded ML evidence + singleton ML + no spread alternative**.

## 9. 2024 corroborates the mechanism

2024 selected ML Value was also 0-3:

- Week 4 SEA/DET +185: COLD, depth 2, no spread — LOSS
- Week 5 CLE/WAS +142: COLD, depth 1, no spread — LOSS
- Week 11 ATL/DEN +114: AMBER, depth 1, no spread — LOSS

The exact proposed narrow cell catches Weeks 5 and 11 but intentionally leaves the competitive Week 4 cold-start loss untouched.

Thus the mechanism is not created solely by 2023; the same structure recurs in the already-exposed 2024 diagnostic period.

## 10. Interpretation

The residual Value failure is now much more localized.

The leading spread architecture from PR #47 contains 2023 spread damage without touching healthy seasons. On ML, the strongest mechanistic warning is not merely `AMBER`, `COLD`, `singleton`, or `no spread` individually. It is their corroborated combination:

> **The ML family is not mature/healthy, exactly one strict ML candidate survives, and no valid spread frontier exists.**

This is effectively a "do not manufacture Value from the last remaining uncorroborated candidate" condition.

A bounded selector experiment may now test exactly one candidate fail-safe:

- if ML evidence is `COLD` or `AMBER`;
- AND strict ML candidate depth == 1;
- AND no valid Pareto spread frontier exists;
- then ML Value = PASS;
- otherwise leave the existing ML policy unchanged;
- RED behavior remains unchanged;
- no ML/spread backfill is introduced.

Such a test would remove five already-exposed ML losses (three in 2023, two in 2024) and no 2020-2022 headline in the observed sample, so it must be treated as exposed development evidence rather than independent validation.

Do not tune the trust constants, add an EV threshold, globally ban singleton ML, globally ban cold-start ML, or open 2025 from this audit.
