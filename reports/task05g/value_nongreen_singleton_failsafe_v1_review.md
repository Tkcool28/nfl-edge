# Task05G Value Non-GREEN Singleton Fail-Safe V1 Review

Verdict: `NONGREEN_SINGLETON_FAILSAFE_SELECTIVELY_CONTAINS_2023_SPREAD_DAMAGE_AND_PRESERVES_HEALTHY_YEARS`

This is exposed retrospective development evidence, not independent confirmation. No football model, Task05F evaluator, Spread Confidence V3 mapping, Pareto ranking, strict-Value eligibility, candidate family, HHR, Balanced, or 2025 data was changed.

## Evidence identity

- preregistration: `c2ed014da80241a10f67c3c56b19b7783dcf82aa`
- validated workflow: `33038540592` — SUCCESS
- artifact: `9632973642`
- digest: `sha256:2aadb747c0c66ec55b80907e98d713095645c77fa7b426177cc48ffd5a8839c4`
- deterministic double replay: PASS
- frozen tests / Task05F / Model Confidence V2 / Spread Confidence V3 reproduction: PASS
- 2025 firewall: PASS
- only non-GREEN singleton spread -> PASS changes: PASS
- no ML backfill: PASS
- no new plays: PASS

## 1. Frozen rule tested

Comparator: PR #45 `VALUE_PARETO_SPREAD_V1`.

Primary `VALUE_NONGREEN_SINGLETON_FAILSAFE_V1`:

- ML baseline selections unchanged;
- GREEN spread selections unchanged regardless candidate depth;
- AMBER/RED competitive spread selections (depth >=2) unchanged;
- AMBER/RED singleton spread selections (depth ==1) -> PASS;
- no ML backfill.

Trust constants remained exactly frozen:

- reset .50;
- pseudo-count 8;
- AMBER >=3 and trust <.50;
- RED >=8 and trust <.25.

## 2. It cut volume only in the abnormal season

Final-card spread -> PASS changes:

- 2020: **0**
- 2021: **0**
- 2022: **0**
- 2023: **5**
- 2024: **0**

Thus the rule did not globally neuter spread.

### 2020-2022

Exactly unchanged:

- 47 plays
- 32-15
- 68.09% hit
- +50.97% ROI
- +23.955u
- 29 ML / 18 spread

### 2024

Exactly unchanged:

- 16 plays
- 11-5
- 68.75% hit
- +29.53% ROI
- +4.725u
- 3 ML / 13 spread

The known-good 2022 and 2024 Value behavior is fully preserved.

## 3. 2023 result

Baseline Pareto Value:

- 15 plays
- 4-11
- 26.67% hit
- -48.83% ROI
- **-7.325u cumulative**
- 4 ML / 11 spread

Non-GREEN singleton fail-safe:

- 10 plays
- 3-7
- 30.0% hit
- -43.05% ROI
- **-4.305u cumulative**
- 4 ML / 6 spread

The rule therefore reduced the 2023 flat-unit drawdown by:

- **+3.020u**
- approximately **41% of the baseline cumulative loss**
- five fewer wagers

Percentage ROI remains very negative because the remaining ML losses stay in the denominator and the policy is deliberately not allowed to alter ML.

## 4. Exact cards removed

The five removed 2023 spreads were all non-GREEN singletons:

| Week | State | Result | Flat units |
|---|---|---|---:|
| 9 | AMBER | WIN | +0.980 |
| 10 | AMBER | LOSS | -1.000 |
| 13 | AMBER | LOSS | -1.000 |
| 15 | AMBER | LOSS | -1.000 |
| 16 | RED | LOSS | -1.000 |

Totals:

- 1 win / 4 losses
- **-3.020u** counterfactual net
- 4.000 losing units avoided
- 0.980 winning units forfeited

The rule preserved the two competitive RED spreads from Weeks 17 and 18 that PR #46's broader policy had incorrectly removed; both won.

## 5. Spread-specific 2023 decomposition

The baseline PR #45 final Value card contained 11 selected spreads in 2023.

From the validated trajectory their settlements were:

- 4 wins
- 7 losses

The non-GREEN singleton fail-safe removes exactly:

- 1 spread win
- 4 spread losses

Therefore the **remaining user-facing spread stream is exactly 3-3**.

This is the key result. The targeted fail-safe turns the selected 2023 spread component from 4-7 into a 50/50 stream while preserving all competitive Pareto spreads and every healthy-year user-facing selection.

It does not make the full 2023 Value card good because spread is no longer the only failing market.

## 6. Remaining 2023 failure localizes to ML

The baseline 2023 Value card was 4-11 overall with:

- 11 spread selections = 4-7;
- 4 ML selections.

Therefore the four ML selections are arithmetically **0-4**.

The validated trajectory identifies those ML Value blocks as:

- Week 4: ATL-JAX moneyline;
- Week 7: LV-CHI moneyline;
- Week 8: CLE-SEA moneyline;
- Week 12: TB-IND moneyline.

The spread-only fail-safe intentionally leaves all four untouched. After removing the five risky spread singletons, the remaining 2023 card is:

- spread: 3-3;
- ML: 0-4;
- total: 3-7.

Thus the residual 2023 drawdown is no longer primarily a spread-frontier problem. It is now clearly ML-led.

This materially clarifies why 2023 looked so pathological: **both Value families failed in the same season, but the spread failure can be substantially contained by a causal regime+depth gate. The remaining ML stream still needs its own protection.**

## 7. Later-period and overall effect

### 2023-2024

Baseline Pareto Value:

- 31 plays
- 15-16
- 48.39% hit
- -8.39% ROI
- -2.600u

Fail-safe:

- 26 plays
- 14-12
- **53.85% hit**
- **+1.61% ROI**
- **+0.420u**

The exposed later period moves from negative to approximately break-even/positive while 2024 itself is unchanged.

### 2020-2024 overall

Baseline Pareto Value:

- 78 plays
- 47-31
- 60.26% hit
- +27.38% ROI
- +21.355u
- 36 ML / 42 spread

Fail-safe:

- 73 plays
- 46-27
- **63.01% hit**
- **+33.39% ROI**
- **+24.374u**
- 36 ML / 37 spread

Overall coverage moves from 71.56% to 66.97% of the 109 exposed weekly blocks. The reduction is entirely five 2023 spread passes.

## 8. Interpretation

This version is materially better aligned with the product contract than PR #46's blanket RED rule.

It demonstrates that a Value safety valve can intentionally reduce volume in a detected abnormal regime **without globally suppressing spread**:

- no healthy-year final-card changes;
- no competitive spread suppression;
- no ML substitution;
- 41% reduction in 2023 flat-unit drawdown;
- 2023 selected spread stream after filtering = 3-3;
- 2023-2024 combined period becomes slightly profitable.

Because the rule was motivated by already-exposed PR #46 evidence, it is not independent validation and cannot by itself authorize production promotion. However, it is coherent enough to treat as the leading spread-Value safety candidate for final integration.

## 9. Remaining problem

Do not keep digging into spread merely because the full 2023 Value ROI is still negative. After this fail-safe, the remaining 2023 failure is plainly ML-led: 0-4.

The next bounded Value diagnostic should therefore examine the four 2023 ML headline plays under the **existing causal ML trust state**, especially the current behavior that can still allow an AMBER ML frontier when no spread alternative is available. The objective is to determine whether Value is still forcing an ML play because it is the only surviving family candidate during a degrading regime.

Do not change spread thresholds, Pareto ranking, singleton definition, or trust constants based on this output.

2025 remains sealed. No production promotion is authorized until the final three-lane selector/config/tests/output contract is frozen and the user explicitly authorizes the single sealed 2025 acceptance run.