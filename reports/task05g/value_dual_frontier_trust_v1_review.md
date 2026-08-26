# Task05G Value Dual Frontier Trust V1 Review

Verdict: `DUAL_FAMILY_TRUST_DOES_NOT_FIX_2023_VALUE_FAILURE_WITH_CURRENT_FRONTIERS`

This was a preregistered retrospective selector diagnostic only. No production policy, Task05F evaluator, football model, Spread Confidence V3 mapping, frozen Task05E candidate family, trust threshold, staking rule, or 2025 data was changed.

## Evidence identity

- preregistration commit: `8660c03bb27c581f65c3c640aaa9fd2bcfbaf8f0`
- workflow: `32940757582` — SUCCESS
- artifact: `9596455937`
- digest: `sha256:6ead810df93ffcac7e1692b7ae652ab3e1c847ace3f18bc477b0420ce1d61872`
- deterministic double replay: PASS
- frozen focused tests: PASS
- Task05F reproduction: PASS
- Model Confidence V2 reproduction: PASS
- Spread Confidence V3 reproduction: PASS
- 2025 firewall: PASS

## 1. Primary result

The independent spread-family trust stream did **not** repair the 2023 Value collapse while the current raw-cover-margin spread frontier remained frozen.

### 2023

| Variant | Plays | W-L | Hit rate | ROI | ML / Spread |
|---|---:|---:|---:|---:|---:|
| CURRENT_ML_ONLY_STATE | 15 | 3-12 | 20.00% | -61.45% | 4 / 11 |
| DUAL_SHRINK_ONLY | 14 | 2-12 | 14.29% | -69.43% | 9 / 5 |
| **DUAL_FRONTIER_TRUST_V1** | **14** | **2-12** | **14.29%** | **-69.43%** | **9 / 5** |

The primary dual-family trust rule was therefore materially worse than the current already-failing selector in 2023.

## 2. Trust did detect the spread problem

The spread trust stream reacted earlier than the ML trust stream in 2023:

- spread first AMBER: **Week 4**, after 3 prior spread-frontier observations, trust 0.364;
- spread first RED: **Week 16**, after 9 prior observations, trust 0.235;
- ML first AMBER: Week 9, after 3 prior ML-frontier observations, trust 0.364;
- ML first RED: Week 18, after 9 prior observations, trust 0.235.

Thus the failure is **not** that spread-family trust was blind to deterioration. It recognized the failing rank-1 spread stream very early.

The problem is what happened next: while spread was AMBER and ML was still classified GREEN or later AMBER, the primary state logic shifted more Value volume into an ML frontier that was itself extremely weak in 2023.

The primary 2023 market mix moved from:

- current: 4 ML / 11 spread

to:

- dual trust: **9 ML / 5 spread**.

That substitution worsened rather than improved the card.

## 3. The 2023 sequence

The primary dual-family selector began 2023 with four straight losses:

- Week 1 spread LOSS
- Week 2 spread LOSS
- Week 3 spread LOSS
- Week 4 ML LOSS after spread became AMBER

It continued losing through the subsequent ML substitutions. The only wins in the 14 plays were Week 9 spread and Week 11 ML.

By Week 18 both families were RED and the selector correctly produced PASS. That was too late to repair the already accumulated loss.

## 4. Cross-period behavior

### 2020-2022 development

The trust rule did not damage the historically strong development period:

- current: 47 plays, 68.09% hit, +50.82% ROI
- dual trust: 47 plays, 68.09% hit, **+52.88% ROI**

Coverage was unchanged at 47/65.

### 2023-2024 exposed diagnostic

- current: 31 plays, 41.94% hit, -20.65% ROI
- dual trust: 30 plays, 40.00% hit, **-23.01% ROI**

### Overall 2020-2024

- current: 78 plays, 57.69% hit, +22.41% ROI
- dual trust: 77 plays, 57.14% hit, +23.31% ROI

The superficially slightly higher overall ROI is driven by the strong earlier seasons and does not offset the fact that the mechanism failed its core purpose: protecting the 2023 regime.

## 5. Family-frontier context

The counterfactual top spread frontier itself remained:

- 2020-2022: 35 plays, 68.57% hit, +31.40% ROI
- 2023-2024: 25 plays, 52.00% hit, -1.61% ROI
- overall: 60 plays, 61.67% hit, +17.65% ROI

The counterfactual ML frontier was much weaker in the later period:

- 2020-2022: 35 plays, 62.86% hit, +50.44% ROI
- 2023-2024: 18 plays, 27.78% hit, -42.16% ROI

This explains why moving away from an AMBER spread frontier toward a nominally GREEN/AMBER ML frontier was not protective.

## 6. Spread trust is also too coarse as a complete solution

The same spread trust constants generated early AMBER states in seasons where the spread frontier ultimately performed well:

- 2020: first spread AMBER Week 15;
- 2021: first spread AMBER Week 5 even though the full 2021 rank-1 spread frontier later finished strongly positive;
- 2022: no spread AMBER;
- 2024: no spread AMBER.

Therefore the same-season family trust signal contains useful warning information but is too coarse to replace the within-family selection problem. It can react to a run of poor frontier results, but it cannot determine **which** candidate inside the eligible spread Value population should have been the weekly headline.

## 7. What this rules out

Do not:

- lower or raise AMBER/RED thresholds after seeing this result;
- change the pseudo-count;
- create a special 2023 state rule;
- blindly choose rank 2/rank 3;
- remove a Task05E disagreement bucket;
- let ML automatically replace distrusted spread;
- let spread automatically replace distrusted ML;
- open 2025.

The independent trust concept did not solve the core 2023 Value problem with the current frontiers.

## 8. Remaining root cause

The prior rank audit remains the strongest diagnosis:

- the Expected-Margin strict spread-Value **population** is broadly viable;
- the raw-cover-margin **rank-1 weekly frontier** is fragile and catastrophically anti-selected in 2023;
- Spread Confidence V3 compresses raw-margin differences into tiny calibrated-probability differences;
- the final Value frontier then reintroduced raw margin as the primary maximization target.

This trust experiment shows that a downstream family-level state machine cannot reliably compensate for that bad within-spread ordering.

## 9. Recommended next bounded test

Return to the within-spread frontier ranking, but do **not** tune numeric thresholds.

The next preregistered candidate should be a **corroborated spread frontier** that requires the Expected-Margin model signal and Task05F economic signal to agree in rank rather than selecting the unrestricted maximum raw margin.

A principled coefficient-free design is ordinal/pareto corroboration inside each block:

1. keep the exact frozen strict spread-Value population;
2. rank candidates separately by raw Expected-Margin cover margin and Task05F evaluated edge;
3. prefer candidates that are strong on **both** ranks rather than extreme on only one;
4. use a deterministic maximin / Pareto rule with no fitted coefficient;
5. compare against the current raw-margin frontier across 2020-2024;
6. no lower-rank targeting, no threshold grid, no 2025.

A separate preregistration is required before fixing the exact ordinal rule.
