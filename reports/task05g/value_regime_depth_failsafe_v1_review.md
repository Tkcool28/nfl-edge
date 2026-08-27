# Task05G Value Regime-Depth Fail-Safe V1 Review

Verdict: `REGIME_DEPTH_INTERACTION_IS_REAL_BUT_PRIMARY_FAILSAFE_IS_TOO_BLUNT`

This was a preregistered retrospective safety experiment only. No football model, Task05F evaluator, Spread Confidence V3 mapping, Pareto spread ranking, strict-Value eligibility, candidate family, HHR, Balanced, staking rule, or 2025 data was changed.

## Evidence identity

- preregistration: `d544cbfdd63a6f6858ed568ff5ed0fe9e1dd5ed8`
- validated workflow: `33038203970` — SUCCESS
- artifact: `9632845285`
- digest: `sha256:ec9b7c8eb22b113aff1625884360a8628b146dbbca3855345e9941ee230eeff7`
- deterministic double replay: PASS
- frozen focused tests: PASS
- Task05F reproduction: PASS
- Model Confidence V2 reproduction: PASS
- Spread Confidence V3 reproduction: PASS
- 2025 firewall: PASS
- only spread -> PASS changes: PASS
- no ML backfill: PASS
- no new plays: PASS

## 1. Primary policy tested

Baseline: PR #45 `VALUE_PARETO_SPREAD_V1`.

Spread-family trust reused the frozen causal constants:

- reset trust 0.50;
- pseudo-count 8;
- AMBER after >=3 prior frontier observations with trust <0.50;
- RED after >=8 with trust <0.25.

Primary safety action:

- GREEN spread: keep regardless candidate depth;
- AMBER + depth >=2: keep Pareto spread;
- AMBER + singleton: PASS;
- RED spread: PASS regardless depth;
- never backfill a removed spread with ML.

## 2. The regime-selective behavior worked exactly as intended

User-facing spread -> PASS changes by season:

- 2020: **0**
- 2021: **0**
- 2022: **0**
- 2023: **7**
- 2024: **0**

Thus the safety mechanism did **not** globally neuter spread or reduce healthy-year Value volume. Every user-facing removal occurred in the abnormal 2023 season.

Development 2020-2022 was byte-for-byte unchanged at the selected-card level:

- baseline: 47 plays, 32-15, 68.09% hit, +50.97% ROI, +23.955u
- fail-safe: identical 47 plays, 32-15, 68.09%, +50.97%, +23.955u

2024 was also completely unchanged:

- 16 plays
- 11-5
- 68.75% hit
- +29.53% ROI
- +4.725u

This directly addresses the anti-neutering concern: the same causal rule left the known-good 2022/2024 Value card untouched.

## 3. 2023 protection was too small

Baseline Pareto Value 2023:

- 15 plays / 68.18% block coverage
- 4-11
- 26.67% hit
- -48.83% ROI
- **-7.325u cumulative**
- 4 ML / 11 spread
- max losing streak 6

Primary fail-safe:

- 8 plays / 36.36% block coverage
- 1-7
- 12.50% hit
- -76.14% ROI
- **-6.091u cumulative**
- 4 ML / 4 spread
- max losing streak 6

The safety rule reduced actual flat-unit loss by only **1.234u** despite removing seven wagers. It did not materially solve the 2023 drawdown and made percentage ROI/hit rate look worse because several winning late-season spreads were also withheld.

Therefore the preregistered primary policy is **not promotable**.

## 4. What the seven removed 2023 spreads were

All removals occurred after the strictly-prior spread state had degraded.

- first AMBER: Week 4
- first RED: Week 16
- baseline Value spread plays before first AMBER: 3
- baseline Value spread plays at/after first AMBER: 8

Removed cards:

| Week | State | Depth | Result | Flat units |
|---|---|---:|---|---:|
| 9 | AMBER | 1 | WIN | +0.980 |
| 10 | AMBER | 1 | LOSS | -1.000 |
| 13 | AMBER | 1 | LOSS | -1.000 |
| 15 | AMBER | 1 | LOSS | -1.000 |
| 16 | RED | 1 | LOSS | -1.000 |
| 17 | RED | 2 | WIN | +0.893 |
| 18 | RED | 3 | WIN | +0.893 |

Totals removed:

- 3 wins
- 4 losses
- counterfactual net = **-1.234u**
- losing units avoided = 4.000u
- winning units forfeited = 2.766u

The key implementation mistake in the primary fail-safe is visible here: the blanket RED rule discarded two competitive Pareto spreads in Weeks 17-18, and both won.

## 5. State x candidate-depth diagnostic

Across the complete Pareto spread-frontier observation stream in 2020-2024:

### GREEN singleton

- 16 plays
- 13-3
- 81.25% hit
- **+54.42% ROI**
- seasons: 2022, 2023, 2024

### GREEN competitive (depth >=2)

- 28 plays
- 16-12
- 57.14% hit
- **+9.43% ROI**
- seasons: all five

### AMBER singleton

- 5 plays
- **1-4**
- 20.0% hit
- **-60.39% ROI**
- seasons: 2021, 2023

### AMBER competitive

- 8 plays
- **6-2**
- 75.0% hit
- **+42.99% ROI**
- seasons: 2020, 2021, 2023

### RED singleton

- 1 play
- 0-1
- -100% ROI
- season: 2023 only

### RED competitive

- 2 plays
- **2-0**
- **+89.29% ROI**
- season: 2023 only

These samples are small and fully exposed, so they cannot establish a new production rule by themselves. But the interaction is mechanistically coherent and materially sharper than a blanket family-state ban:

> Candidate depth is not globally valuable as an eligibility gate. Singleton spreads are excellent in GREEN states. The concerning combination is specifically **degraded same-season trust + singleton depth**.

Competitive Pareto frontiers continued to perform well even when the family-level state was AMBER/RED.

## 6. Overall effect

2020-2024 baseline Pareto Value:

- 78 plays
- 47-31
- 60.26% hit
- +27.38% ROI
- +21.355u
- 36 ML / 42 spread

Primary fail-safe:

- 71 plays
- 44-27
- 61.97% hit
- +31.82% ROI
- +22.589u
- 36 ML / 35 spread

The aggregate improves because the seven removed 2023 spreads were net losing, but this does not rescue the policy: the user-facing 2023 drawdown remains unacceptable and the primary rule removed two valuable competitive RED spreads.

## 7. Interpretation

This experiment answers two important questions.

### A. Does a causal regime/depth mechanism necessarily neuter spread?

**No.** The preregistered mechanism made zero user-facing changes in 2020, 2021, 2022, and 2024. It cut volume only in 2023.

### B. Is `RED -> ban all spreads` the right fail-safe?

**No.** The evidence directly rejects that implementation. Competitive Pareto spreads survived the same bad regime and the two RED competitive cases both won.

The sharper hypothesis is now:

> In a degraded spread regime, a **singleton** strict-Value spread lacks the cross-candidate corroboration that makes Pareto useful. A competitive Pareto frontier may remain playable even when family trust is poor.

This is closer to the user's original product intuition: if the system says both “this season's spread Value stream is behaving abnormally” and “I only have one surviving spread this week,” reducing Value volume is reasonable. It should not automatically suppress a multi-candidate spread that still wins a real Pareto comparison.

## 8. What is not authorized

Do not promote the primary fail-safe.

Do not:

- blanket-ban RED spreads;
- globally ban singleton spreads;
- alter the frozen trust thresholds;
- tune candidate-depth cutoffs;
- use 2023 season identity;
- shift removed spreads into ML;
- alter HHR/Balanced;
- open 2025.

A next candidate, if tested, should be a single coefficient-free refinement that is faithful to the mechanism rather than the outcomes: **PASS only a singleton spread when the pre-block spread state is non-GREEN; keep competitive Pareto spreads.** Because this hypothesis is now informed by exposed 2020-2024 evidence, it must remain clearly labeled development evidence and must be frozen before any replay. Final acceptance still requires the one sealed 2025 run after all policy/config/test/output decisions are complete.