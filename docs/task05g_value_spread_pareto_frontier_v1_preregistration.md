# Task05G Value Spread Pareto Frontier V1 — Preregistration

Status: **FROZEN BEFORE REPLAY / 2025 SEALED**

This test is subordinate to the final three-protocol selector architecture and the forensic result in `reports/task05g/value_spread_frontier_rank_audit_v1_review.md`.

The purpose is narrow: replace unrestricted maximum raw Expected-Margin spread ranking with a coefficient-free corroborated ranking **without changing the spread-Value eligibility universe or spread-frontier block coverage**.

All 2020-2024 outcomes are already exposed retrospective evidence. This test cannot create untouched validation. 2025 remains sealed.

## 1. Frozen spread-Value eligibility

A spread candidate is eligible only if it satisfies the exact final Value spread contract:

- market type = spread;
- frozen Task05E provenance includes `SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4`;
- Task05F `supported == True`;
- Model Confidence / Spread Confidence V3 supported with support N >= 256;
- exact best shopped DraftKings/FanDuel offer;
- Task05F price status = `VALUE`;
- exact Task05F expected value > 0;
- American odds between -180 and +250 inclusive;
- finite positive `model_cover_margin_v3`;
- finite positive `evaluated_edge_probability`.

No candidate family, price bound, support threshold, model, evaluator, or strict-Value definition may change.

## 2. Current comparator frontier

`RAW_MARGIN_FRONTIER` reproduces the current final-selector spread frontier exactly:

1. `model_cover_margin_v3` descending;
2. `evaluated_edge_probability` descending;
3. reliability descending;
4. American odds descending;
5. candidate ID.

## 3. Primary PARETO_BALANCED frontier

For every eligible spread candidate in a block, compute two **ordinal ranks** over the same candidate set.

### Football-model rank

`model_rank`:

1. `model_cover_margin_v3` descending;
2. candidate ID for deterministic ties.

### Economic-corroboration rank

`economic_rank`:

1. `evaluated_edge_probability` descending;
2. exact expected value descending;
3. candidate ID for deterministic ties.

The primary coefficient-free corroboration quantities are:

```text
worst_rank = max(model_rank, economic_rank)
rank_sum   = model_rank + economic_rank
```

Select `PARETO_BALANCED` by:

1. `worst_rank` ascending;
2. `rank_sum` ascending;
3. `model_rank` ascending;
4. `economic_rank` ascending;
5. reliability descending;
6. American odds descending;
7. candidate ID.

Interpretation:

- a candidate cannot win solely by being the most extreme raw Expected-Margin number if it ranks poorly on exact economic corroboration;
- a candidate cannot win solely by estimated economics while being weak on the football-model signal;
- model evidence remains the final rank-level tie-break after balanced corroboration;
- no fitted weights, coefficients, thresholds, or season-specific rules are introduced.

This rule **always selects exactly one candidate whenever RAW_MARGIN_FRONTIER can select one**. It is ranking-only.

## 4. Hard anti-neutering invariant

For every 2020-2024 block:

```text
PARETO spread-frontier exists <=> RAW_MARGIN spread-frontier exists
```

Therefore:

- exact spread-frontier block coverage must be identical overall and in every season;
- no new spread PASS may be created;
- no eligible spread candidate may be removed;
- candidate-count distribution must be unchanged.

If this invariant fails, the experiment hard-fails.

## 5. Required spread-frontier reporting

Report `RAW_MARGIN_FRONTIER` and `PARETO_BALANCED` by:

- 2020;
- 2021;
- 2022;
- 2023;
- 2024;
- 2020-2022;
- 2023-2024;
- 2020-2024.

For each report:

- plays / identical coverage;
- W/L/P;
- non-push hit rate;
- flat 1u ROI;
- max losing streak;
- average American odds;
- average raw cover margin;
- average Spread V3 q;
- average evaluated edge;
- average exact expected value;
- average original raw-margin rank chosen by Pareto;
- number / share changed from current rank 1.

Also report changed-block paired outcomes:

- Pareto win / raw-margin loss;
- raw-margin win / Pareto loss;
- both win;
- both loss;
- push involved.

## 6. Original Task05E 0-4 support-region guard

Report selected candidates by frozen original disagreement bucket:

- 0-1;
- 1-2;
- 2-3;
- 3-4.

The audit may not delete or preference a bucket based on output. The purpose is to confirm that the selector remains inside the already-supported 0-4 region and does not achieve improvement by effectively eliminating the upper portion of that region.

Also report average and maximum `model_cover_margin_v3` under both selectors so we can determine whether Pareto smooths extreme selection rather than simply collapsing model signal.

## 7. Full Value-card integration comparator

After the spread-frontier comparison, rerun the **existing Final Selector Candidate V1 Value state machine** with exactly one substitution:

```text
current spread frontier -> PARETO_BALANCED spread frontier
```

Everything else remains frozen:

- exact ML frontier;
- ML same-season causal trust;
- reset trust = 0.50;
- pseudo-count = 8;
- AMBER >= 3 observations and trust < 0.50;
- RED >= 8 observations and trust < 0.25;
- GREEN / AMBER / RED behavior from Final Selector Candidate V1;
- cross-market dynamic-edge comparison;
- strict +EV requirement;
- Value may PASS;
- no totals.

Call this integrated comparator `VALUE_PARETO_SPREAD_V1`.

Compare it against `CURRENT_VALUE_V1` by season and period for:

- plays / coverage;
- ML / spread mix;
- W/L/P;
- hit rate;
- ROI;
- max losing streak;
- changed Value blocks;
- spread-to-ML / ML-to-spread changes;
- PASS changes.

### Integrated spread-preservation reporting

Because cross-market ranking can legitimately change the final Value market, report:

- number of blocks where both versions had a valid spread frontier;
- number where Pareto spread still won the final Value card;
- number where the new spread finalist lost the cross-market comparison to ML;
- total final Value spread plays versus current.

There is **no post-hoc minimum spread-share success threshold**. The hard non-neutering invariant applies to the spread frontier itself; final cross-market mix is diagnostic.

## 8. Fixed interpretation rules

This test does **not** authorize:

- choosing rank 2 because retrospective rank 2 won;
- raw-margin caps or thresholds;
- deleting 3-4 or another Task05E bucket;
- tuning rank weights;
- adding family trust thresholds;
- season-specific behavior;
- changing ML Value;
- changing HHR or Balanced;
- opening 2025.

Evidence will be judged on whether the coefficient-free corroborated ranking:

1. preserves exact spread-frontier coverage;
2. preserves meaningful Expected-Margin model agency within the frozen 0-4 region;
3. reduces the 2023 conditional rank-1 catastrophe;
4. is not paid for by destroying 2021/2022/2024 performance;
5. produces a more stable full Value card without forcing spread out of the product.

No numeric success threshold will be invented after output.
