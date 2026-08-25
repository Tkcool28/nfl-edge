# Task05G ML Value Frontier Trust V1 — Preregistration

Status: preregistered before implementation/results on this branch.

Purpose: test whether dynamic ML Value trust works better when its evidence stream is aligned to the selector's **ML decision frontier** rather than the full eligible ML Value pool.

This experiment does not modify Task05F evaluator semantics, football models, Task05E evidence, production selector policy, historical data, HHR/Balanced logic, or sealed 2025.

## Motivation

Dynamic Trust V1 showed that a causal same-season RED gate could materially limit the 2023 ML collapse while preserving overall Value coverage, but it falsely suppressed profitable 2022 ML because trust was computed from every eligible ML Value opportunity.

The broad 2022 eligible pool had negative realized edge even while the actually selected ML headline stream was strongly profitable. Therefore the trust population was misaligned with the decision being protected.

## Chronology

- 2020–2022: development replay.
- 2023–2024: exposed retrospective stress replay only, not fresh confirmation.
- 2025: sealed/prohibited.

Trust at block `season-week` may use only settled observations from strictly earlier blocks of the same season.

## Frozen base Value logic

Use the same V2 Value eligibility and ranking logic as Dynamic Trust V1.

No base eligibility threshold, model probability, evaluator quantity, price status, or odds bound changes.

## Frontier observation stream

For every block, construct the exact-shopped ML Value candidate set using frozen V2 eligibility.

Restrict the frozen V2 Value ranking to **moneyline candidates only** and identify the single highest-ranked ML candidate for that block. This is the counterfactual ML frontier candidate: the ML wager Value would prefer if the weekly headline were required to come from ML.

After that block is fully settled, and only for future blocks:

- if the frontier candidate settled WIN/LOSS and has finite `q_model` and `p_be`, add one trust observation;
- pushes do not enter trust calculations;
- no lower-ranked ML candidate enters trust state;
- at most one ML trust observation per block.

For that frontier observation:

- `predicted_edge = q_model - p_be`
- `realized_edge = y - p_be`, where WIN=1 and LOSS=0.

## Trust formula — frozen from Dynamic Trust V1

No constants change:

- season-reset trust = 0.50
- pseudo-count = 8
- RED threshold = 0.25
- RED gate cannot activate until >=8 prior same-season frontier observations

For `n` prior frontier observations:

- `predicted_edge_sum = sum(predicted_edge)`
- `realized_edge_sum = sum(realized_edge)`
- if predicted-edge sum <= 0, `data_trust = 0`
- otherwise `data_trust = clip(realized_edge_sum / predicted_edge_sum, 0, 1)`
- `trust = (8*0.50 + n*data_trust)/(8+n)`

## Variants

### F0 — frozen V2 baseline

No dynamic trust.

### F1 — frontier-trust ranking shrink

For ML candidates:

- `trusted_model_price_gap = trust * model_price_gap`
- `dynamic_consensus_edge = min(trusted_model_price_gap, evaluated_edge_probability)`

Spread ranking stays frozen V2.

### F2 — F1 + RED gate

Same as F1, plus once >=8 prior frontier observations exist, ML candidates are barred from the Value headline whenever frontier trust <0.25. ML eligibility automatically returns if future strictly prior frontier evidence raises trust to >=0.25.

## Anti-neutering guard

F2 is flagged `COVERAGE_COLLAPSE` if total Value play count falls below 75% of F0 in either 2020–2022 or exposed 2023–2024 stress replay.

## Required diagnostics

Report for F0/F1/F2:

- total plays, coverage, hit rate, ROI;
- ML/spread counts and ROI;
- results by season;
- max losing streak;
- number of F0 ML headlines displaced by spread;
- number of RED-gate no-play weeks;
- frontier trust by week;
- first block each season below trust 0.50 and 0.25;
- frontier observation count at each crossing;
- final predicted-edge and realized-edge sums per season.

## Interpretation rule

The key test is whether frontier-aligned trust avoids the 2022 false alarm **without** losing the ability to check the 2023 deterioration causally.

No constants or variants may be changed after results are exposed. 2023–2024 remain retrospective stress evidence only. 2025 remains sealed for future true validation.