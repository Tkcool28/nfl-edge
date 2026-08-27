# Task05G Value Regime-Depth Fail-Safe V1 — Preregistration

Status: **FROZEN BEFORE REPLAY / 2025 SEALED**

This experiment is stacked on the preregistered Pareto spread frontier in PR #45. It tests one narrow product-safety question raised by the 2023 forensic results:

> Should Value intentionally reduce spread volume when the strictly-prior same-season spread family is behaving abnormally and the current block has weak candidate depth, instead of forcing the lone surviving spread into the user-facing Value card?

This is retrospective exposed evidence only. All 2020-2024 outcomes have already been seen. No result from this experiment is untouched confirmation. 2025 remains sealed.

## 1. Frozen base policy

The comparator is `VALUE_PARETO_SPREAD_V1` from PR #45:

- HHR unchanged and out of scope;
- Balanced unchanged and out of scope;
- ML Value frontier unchanged;
- spread Value eligibility unchanged;
- strict Task05F `VALUE` / expected value > 0 unchanged;
- Expected Margin spread provenance remains `SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4`;
- Spread Confidence V3 unchanged;
- price bounds unchanged at -180 through +250;
- model-confidence support N >= 256 unchanged;
- best exact DraftKings/FanDuel shopping unchanged;
- spread finalist is the coefficient-free `PARETO_BALANCED` frontier from PR #45;
- no totals;
- 2025 sealed.

No candidate family, evaluator, football model, probability mapping, price band, support threshold, or Pareto ranking formula may change.

## 2. Candidate depth

For each block, define `spread_candidate_depth` as the number of exact shopped spread candidates that satisfy the complete frozen strict spread-Value eligibility contract before selecting the Pareto finalist.

Depth is therefore:

- `0`: no valid spread Value candidate;
- `1`: singleton — one valid spread candidate survives all gates;
- `>=2`: competitive frontier — Pareto has at least two valid spread candidates to compare.

Depth is descriptive evidence only. A singleton is **not** globally disqualified.

## 3. Frozen causal spread-family trust

Reuse the exact spread-family trust mechanics already preregistered in the dual-family trust experiment. Do not retune them.

Season reset:

- reset trust = 0.50;
- pseudo-count = 8.

For each season, before evaluating the current block, trust may use only settled Pareto spread-frontier observations from **earlier blocks in that same season**. The observation stream is the top Pareto spread frontier whenever it exists, whether or not the final cross-market Value card selected that spread.

For each settled prior spread frontier:

- `predicted_edge = evaluated_edge_probability`;
- `realized_edge = outcome_binary - break_even_probability`, where WIN = 1 and LOSS = 0;
- pushes do not create observations.

Aggregate:

```text
data_trust = clip(realized_edge_sum / predicted_edge_sum, 0, 1)
trust = (8 * 0.50 + n * data_trust) / (8 + n)
```

State constants remain frozen:

- `GREEN`: fewer than 3 observations OR trust >= 0.50;
- `AMBER`: at least 3 observations and trust < 0.50, unless RED;
- `RED`: at least 8 observations and trust < 0.25.

No new trust coefficient or state threshold may be introduced.

## 4. Primary fail-safe policy

Call the preregistered primary policy `VALUE_REGIME_DEPTH_FAILSAFE_V1`.

Start from the exact user-facing `VALUE_PARETO_SPREAD_V1` selection for each block.

### If the baseline final Value selection is moneyline

Keep it unchanged.

The experiment does not use spread weakness as a reason to manufacture or alter an ML selection.

### If the baseline final Value selection is spread

Apply only the following fail-safe:

- **GREEN spread state:** keep the spread regardless of candidate depth.
- **AMBER spread state + depth >= 2:** keep the Pareto spread.
- **AMBER spread state + depth == 1:** **PASS** the Value lane for that block.
- **RED spread state:** **PASS** the Value lane for that block regardless of depth.

### No-backfill invariant

A spread removed by this fail-safe is **not replaced by ML** in the same block.

This is deliberate. The prior dual-family trust test showed that suppressing a deteriorating spread stream and automatically leaning harder on ML can make the user-facing Value card worse. This experiment measures whether reducing Value volume itself is the safer response.

Thus the only allowed user-facing changes relative to `VALUE_PARETO_SPREAD_V1` are:

```text
spread -> PASS
```

There may be no:

- spread -> ML replacement;
- ML -> spread replacement;
- ML -> PASS change;
- different spread candidate selection;
- new candidate family.

If any such change occurs, the experiment hard-fails.

## 5. Why this may reduce coverage

Unlike PR #45, **coverage parity is not a requirement**. Reduced Value volume during an abnormal same-season spread regime is the behavior under test.

This is acceptable because Value is explicitly permitted to be absent. The experiment must therefore report the cost and benefit of every removed card rather than treat lower volume as an automatic failure.

## 6. Required reporting

Report the comparator and fail-safe for:

- each season 2020, 2021, 2022, 2023, 2024;
- 2020-2022;
- 2023-2024;
- 2020-2024.

For each:

- total weekly blocks;
- plays and coverage;
- W/L/P;
- non-push hit rate;
- flat 1u ROI;
- cumulative flat-unit profit;
- max losing streak;
- ML / spread mix;
- number of spread -> PASS changes.

For every removed spread card, report:

- season/week/block;
- trust state before the block;
- prior trust n and trust value;
- candidate depth;
- selected Pareto spread identity;
- line / odds;
- Expected Margin cover margin;
- Spread V3 q;
- evaluated edge;
- expected value;
- actual settlement;
- realized profit avoided or forfeited.

Also report spread-frontier outcomes stratified by the **pre-block** state/depth cells:

- GREEN singleton;
- GREEN competitive (depth >= 2);
- AMBER singleton;
- AMBER competitive;
- RED singleton;
- RED competitive.

Report counts, hit rate, ROI, and seasons represented for each cell.

## 7. Required 2023 diagnosis

For 2023 specifically report:

- when spread first enters AMBER and RED;
- number of baseline Pareto Value spreads before versus after first AMBER;
- number removed by the fail-safe;
- counterfactual W/L/P and units of removed cards;
- final Value record / ROI after the fail-safe;
- whether the improvement comes primarily from avoiding singleton cards, RED cards, or both.

The goal is not to make 2023 profitable by construction. The goal is to determine whether a causal, pre-block safety response materially limits a 2023-style drawdown without deleting healthy spread behavior in other seasons.

## 8. Cross-season anti-overfit guard

The following are explicitly forbidden:

- globally banning singleton spread weeks;
- choosing a threshold from 2023 outcomes;
- changing the frozen GREEN/AMBER/RED constants;
- changing Pareto ranking;
- using season identity in policy;
- using current-block or future settlement to decide whether to PASS;
- requiring a fixed number of Value cards;
- opening 2025.

Interpretation must explicitly quantify what the fail-safe would have removed in 2020, 2021, 2022, and 2024. A rule that protects 2023 only by destroying the known-good spread years is not acceptable.

## 9. Fixed interpretation criteria

There is no post-hoc optimization grid and no numeric ROI target to tune against.

The primary policy is directionally credible only if all of the following are true:

1. all decisions are strictly causal and pre-block;
2. only spread -> PASS changes occur;
3. the 2023 catastrophic Value drawdown is materially reduced;
4. the reduction is explainable by degraded trust / candidate-depth evidence rather than arbitrary season-specific filtering;
5. strong 2022 and 2024 spread behavior is substantially preserved;
6. overall Value remains useful rather than collapsing to near-zero coverage.

If these do not hold, record the failure and do not retune this policy from exposed outcomes.

No production promotion is authorized by this retrospective experiment alone.