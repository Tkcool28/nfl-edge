# Task05G Value Non-GREEN Singleton Fail-Safe V1 — Preregistration

Status: **FROZEN BEFORE REPLAY / 2025 SEALED**

This is a retrospective development experiment derived from the mechanism exposed in PR #46. It is explicitly **not** independent confirmation: all 2020-2024 outcomes are exposed. The purpose is to test the user's narrower original safety idea without the extra blanket RED suppression that PR #46 showed was too blunt.

## Frozen base

Comparator: PR #45 `VALUE_PARETO_SPREAD_V1`.

Unchanged:
- all football models;
- Task05F evaluator;
- Spread Confidence V3;
- strict spread-Value eligibility;
- Expected Margin 0-4 provenance;
- exact DK/FD shopping;
- odds band -180 through +250;
- model-confidence support N >=256;
- Pareto spread ranking;
- ML Value frontier/state logic;
- no totals;
- 2025 sealed.

## Frozen spread-family trust

Reuse exactly:
- season reset trust 0.50;
- pseudo-count 8;
- AMBER: >=3 prior settled spread-frontier observations and trust <0.50 unless RED;
- RED: >=8 and trust <0.25;
- trust uses only prior same-season settled Pareto spread-frontier observations;
- predicted edge = evaluated_edge_probability;
- realized edge = binary outcome - break_even_probability;
- pushes do not update trust.

No threshold or coefficient may change.

## Candidate depth

`spread_candidate_depth` is the count of exact shopped spread candidates satisfying the complete frozen strict spread-Value contract in the current block before Pareto selects a finalist.

- depth 0 = no spread candidate;
- depth 1 = singleton;
- depth >=2 = competitive Pareto frontier.

## Primary policy: `VALUE_NONGREEN_SINGLETON_FAILSAFE_V1`

Start from the exact final user-facing `VALUE_PARETO_SPREAD_V1` card.

- baseline ML selection: keep unchanged;
- baseline spread + GREEN state: keep regardless depth;
- baseline spread + non-GREEN state (AMBER or RED) + depth >=2: keep;
- baseline spread + non-GREEN state + depth ==1: **PASS**.

No backfill:
- a withheld spread is not replaced by ML;
- no new play may be created;
- no ML selection may be removed;
- no spread candidate identity may change.

Thus the only allowed delta is:

```text
spread -> PASS
```

and only when:

```text
spread_state in {AMBER, RED} AND spread_candidate_depth == 1
```

## Required reporting

Compare baseline and primary by:
- 2020, 2021, 2022, 2023, 2024;
- 2020-2022;
- 2023-2024;
- 2020-2024.

Report:
- plays / coverage;
- W/L/P;
- hit rate;
- ROI;
- cumulative flat units;
- max losing streak;
- ML/spread mix;
- exact spread->PASS changes.

For every removed spread report:
- block / season / week;
- pre-block trust state, n, and trust;
- candidate depth;
- candidate identity;
- line / odds;
- Expected Margin cover margin;
- Spread V3 q;
- evaluated edge / expected value;
- settlement / realized profit.

Report state x depth frontier cells again for context, but they may not be used to alter this frozen rule after output.

## Fixed interpretation

The candidate is useful only if it behaves like a selective safety valve rather than a global volume reducer:

1. all decisions are causal and pre-block;
2. only non-GREEN singletons are removed;
3. healthy-season Value volume is substantially preserved;
4. 2023 cumulative drawdown is materially reduced without suppressing competitive Pareto spreads;
5. overall Value remains useful;
6. no post-hoc rule or threshold is added.

No production promotion is authorized from this exposed development replay. If this candidate is coherent enough to freeze, the next step is production integration/config/tests/output freeze before one sealed 2025 acceptance run.