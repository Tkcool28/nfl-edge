# Task05G Value Spread Frontier Rank Audit V1 — Preregistration

Status: **AUDIT FROZEN BEFORE RANK OUTPUT / 2025 SEALED**

Purpose: explain the severe 2023 Value failure after the final three-protocol architecture correctly moved Value toward Expected-Margin spread candidates. This is a retrospective diagnostic only. It may not modify Task05F, football models, Spread Confidence V3, selector policy, candidate families, thresholds, staking, or 2025 data.

All 2020-2024 outcomes are already exposed. The audit is intended to distinguish a **population failure** from a **conditional rank-1 / optimizer-selection failure**.

## 1. Frozen upstream

Reproduce exactly:

1. Task05F historical evaluator board;
2. Model Confidence V2;
3. Spread Confidence V3;
4. exact DK/FD shopping;
5. frozen Task05E provenance registry.

2025 hard-fails.

## 2. Audit population

Use only spread candidates satisfying the final Value candidate's spread universe:

- market type `spread`;
- frozen provenance region `SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4`;
- Task05F `supported == True`;
- model confidence supported with support N >= 256;
- exact best DK/FD offer after shopping;
- Task05F price status `VALUE`;
- exact Task05F expected value > 0;
- American odds between -180 and +250 inclusive;
- finite positive `model_cover_margin_v3`.

No totals and no ML candidates enter this rank audit.

## 3. Current frontier rank

Within each season-week block, rank all eligible spread Value candidates exactly as the final candidate currently does:

1. `model_cover_margin_v3` descending;
2. `evaluated_edge_probability` descending;
3. reliability descending;
4. American odds descending;
5. candidate ID.

Assign deterministic ranks 1, 2, 3, 4, 5, and `6_plus`.

Rank 1 is the current model-first spread frontier candidate. This audit does not change that rule.

## 4. Primary diagnostic question

Determine which of these mutually distinguishable explanations best fits 2023:

### A. Population/regime failure

The full strict Expected-Margin 0-4 spread Value population is itself materially poor in 2023, with no healthier lower ranks.

### B. Rank-1 optimizer / conditional anti-selection

The full population remains viable or materially healthier than the weekly rank-1 frontier, and ranks 2/3 or non-rank-1 candidates outperform rank 1.

### C. Subregion concentration

Rank 1 over-concentrates in a specific frozen Task05E disagreement bucket (`0-1`, `1-2`, `2-3`, `3-4`) or side/price/reliability slice that deteriorates in 2023.

### D. Economic corroboration mismatch

Rank 1 maximizes raw model cover margin but often has weak exact Task05F EV/evaluator edge relative to lower-ranked candidates, indicating that the current frontier priority overweights model extremity within an already-qualified +EV population.

The audit may conclude that more than one mechanism is present.

## 5. Required reports

Report separately for:

- each season 2020, 2021, 2022, 2023, 2024;
- development 2020-2022;
- exposed 2023-2024;
- overall 2020-2024.

### 5.1 Full eligible population

For all eligible exact-shopped spread candidates:

- candidate count;
- block count;
- wins/losses/pushes;
- non-push hit rate;
- flat 1u ROI;
- average American odds;
- average `model_cover_margin_v3`;
- average Spread V3 q;
- average Task05F expected value;
- average `evaluated_edge_probability`;
- reliability mix;
- home/away mix.

### 5.2 Rank table

For each rank 1, 2, 3, 4, 5, `6_plus`:

- plays / available blocks;
- wins/losses/pushes;
- hit rate;
- ROI;
- average odds;
- average raw cover margin;
- average Spread V3 q;
- average exact EV;
- average evaluator edge;
- reliability mix;
- side mix.

Ranks are descriptive. No rank may be promoted from this output without a subsequent preregistered selector test.

### 5.3 Paired rank comparisons

For blocks where both ranks exist, report paired rank-1 vs rank-2 and rank-1 vs rank-3:

- number of paired blocks;
- rank-1 wins when lower rank loses;
- lower-rank wins when rank 1 loses;
- both win;
- both lose;
- push cases;
- average differences in cover margin, q, EV, evaluator edge, and price.

This is intended to expose conditional winner's-curse behavior rather than compare unmatched populations.

### 5.4 Frozen disagreement bucket

Attach the original Task05E Expected-Margin bucket from the corrected discovery/confirmation ledgers using candidate identity `(game_id, market_type=spread, selected_side)`.

Report `0-1`, `1-2`, `2-3`, `3-4` separately by season and rank.

### 5.5 Fixed economic bins

Use only these preregistered descriptive bins:

Task05F expected value:

- `0_to_1pct`
- `1_to_2_5pct`
- `2_5_to_5pct`
- `gt_5pct`

Evaluator edge probability:

- `0_to_1pp`
- `1_to_2_5pp`
- `2_5_to_5pp`
- `gt_5pp`

American odds:

- `le_-121`
- `-120_to_-111`
- `-110_to_-101`
- `-100_to_100`
- `gt_100`

No bin boundary may be changed after output.

### 5.6 2023 week-by-week ledger

For every 2023 block with at least one eligible spread Value candidate, output every candidate with:

- rank;
- game ID;
- side;
- line;
- sportsbook;
- odds;
- frozen Task05E bucket;
- `model_cover_margin_v3`;
- Spread V3 q;
- break-even probability;
- model-price gap (reporting only);
- Task05F evaluated probability;
- evaluator edge;
- expected value;
- reliability;
- settlement;
- realized 1u profit.

This ledger is the primary forensic artifact.

## 6. Sanity / anti-leakage

Hard fail if:

- 2025 appears anywhere;
- a total or moneyline enters the audit population;
- a candidate lacks frozen Expected-Margin 0-4 provenance;
- expected value <= 0 or price status != `VALUE` enters;
- `model_cover_margin_v3 <= 0` enters;
- current rank-1 reproduction is nondeterministic;
- audit output differs across two identical runs.

## 7. Interpretation guard

This audit does **not** authorize:

- choosing rank 2 because it looks better;
- introducing a new margin/EV/edge threshold;
- changing the Expected-Margin 0-4 family;
- changing Spread V3 calibration;
- changing the GREEN/AMBER/RED state constants;
- opening 2025.

If rank-1 anti-selection is confirmed, the next action is a separate preregistered spread-frontier selector rule using the simplest mechanism justified by this audit. If the 2023 population itself failed, the next action must be a causal regime/support guard rather than rank substitution.
