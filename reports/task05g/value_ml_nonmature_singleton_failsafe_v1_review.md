# Task05G Value ML Nonmature Singleton Fail-Safe V1 Review

Verdict: `ML_NONMATURE_SINGLETON_FAILSAFE_SELECTIVELY_REMOVES_LATER_PERIOD_FAILURE_AND_CONTAINS_2023_VALUE_DRAWDOWN`

This was a preregistered retrospective development experiment only. No football model, Task05F evaluator, confidence mapping, candidate family, HHR, Balanced, Pareto spread ranking, or 2025 data was changed.

## Evidence identity

- preregistration: `b3fd4521c16cfb42e2067c13baf370995154a926`
- validated workflow: `33041535561` — SUCCESS
- artifact: `9634062767`
- digest: `sha256:b9e18df04f8451dc4ee588b7a58741c111027a4b776f7b19cb602ace48a57ad5`
- deterministic double replay: PASS
- frozen focused tests: PASS
- Task05F / Model Confidence V2 / Spread Confidence V3 reproduction: PASS
- 2025 firewall: PASS
- no backfill / no new plays / unaffected candidate identity: PASS

## Frozen rule

Starting from the leading Value baseline of Pareto spread ranking plus the PR #47 non-GREEN singleton spread fail-safe, convert an ML headline to PASS only when all three conditions are true before the block:

1. ML evidence is `COLD` or `AMBER`;
2. strict ML Value candidate depth is exactly 1;
3. no valid Pareto spread frontier exists.

No replacement is allowed. All other Value behavior is unchanged.

## Exact removals

Five ML headlines were removed. All five lost:

- 2023 W7 LV/CHI away ML -126 — COLD, n=1, singleton, no spread — LOSS
- 2023 W8 CLE/SEA away ML +176 — COLD, n=2, singleton, no spread — LOSS
- 2023 W12 TB/IND away ML +130 — AMBER, n=4, singleton, no spread — LOSS
- 2024 W5 CLE/WAS away ML +142 — COLD, n=2, singleton, no spread — LOSS
- 2024 W11 ATL/DEN away ML +114 — AMBER, n=5, singleton, no spread — LOSS

No 2020, 2021, or 2022 user-facing Value play was removed.

## 2023

Baseline entering this test already includes Pareto spread selection and the PR #47 spread safety valve:

- 10 plays
- 3-7
- 30.0% hit
- -43.05% ROI
- -4.305u
- 4 ML / 6 spread
- max losing streak 6

After the ML fail-safe:

- **7 plays**
- **3-4**
- **42.86% hit**
- **-18.65% ROI**
- **-1.305u**
- 1 ML / 6 spread
- max losing streak **4**

Thus this rule removes three 2023 ML losses and saves exactly **3.0u** relative to the already spread-protected baseline.

Relative to the earlier PR #45 Pareto Value card before either safety valve, 2023 moved from:

- 15 plays, 4-11, -48.83% ROI, -7.325u

to the combined safety architecture:

- **7 plays, 3-4, -18.65% ROI, -1.305u**.

The catastrophic 2023 loss is therefore reduced by about **6.02u (~82%)** while allowing the season to remain naturally losing rather than forcing a retrospective profit.

The remaining 2023 losses are not targeted further: the spread stream after its safety valve is 3-3, and the remaining ML loss is the cold competitive/cross-market Week 4 ATL/JAX play that had three valid ML candidates and a valid spread frontier. Removing it would require a broader rule contradicted by healthy cross-season evidence.

## 2024

Baseline:

- 16 plays
- 11-5
- 68.75% hit
- +29.53% ROI
- +4.725u

Fail-safe:

- **14 plays**
- **11-3**
- **78.57% hit**
- **+48.03% ROI**
- **+6.725u**

The two removed 2024 ML plays were both losses. Spread volume remained exactly 13 plays.

## 2020-2022 preservation

The primary anti-overfitting product guard passed exactly:

- baseline: 47 plays, 32-15, 68.09% hit, +50.97% ROI, +23.955u
- fail-safe: **identical**
- removed plays: **0**

Thus the rule did not sacrifice the historically profitable mature/competitive ML Value behavior in 2020-2022.

## 2023-2024 combined

Baseline after spread safety:

- 26 plays
- 14-12
- 53.85% hit
- +1.61% ROI
- +0.420u

Combined spread + ML safety:

- **21 plays**
- **14-7**
- **66.67% hit**
- **+25.81% ROI**
- **+5.420u**
- max losing streak 4

## 2020-2024 overall

Baseline after spread safety:

- 73 plays
- 46-27
- 63.01% hit
- +33.39% ROI
- +24.374u
- 36 ML / 37 spread

Combined spread + ML safety:

- **68 plays**
- **46-22**
- **67.65% hit**
- **+43.20% ROI**
- **+29.374u**
- 31 ML / 37 spread
- coverage 62.39% of 109 exposed blocks
- max losing streak 4

## Interpretation

This is the strongest final Value development candidate so far.

The safety behavior is mechanistically narrow:

- spread is not globally suppressed; only non-GREEN singleton spread headlines are withheld;
- ML is not globally suppressed; only COLD/AMBER singleton ML headlines with no spread corroboration are withheld;
- mature singleton ML remains eligible;
- competitive ML remains eligible;
- competitive spread remains eligible even in degraded spread state;
- no alternate wager is manufactured when a headline is withheld.

The combined architecture converts the 2023 catastrophe into a contained losing season without touching 2020-2022 and while improving 2024.

Because both safety rules were motivated by exposed 2020-2024 forensics, these statistics are development evidence, not independent confirmation. Do not retune Value further from this output. The next appropriate step is to freeze the complete HHR / Balanced / Value selector architecture, deterministic staking and product policy, then use the still-sealed 2025 season as the first acceptance test only after explicit authorization.

No production promotion is authorized by this PR alone.