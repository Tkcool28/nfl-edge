# Task05G Stage-by-Stage Model/Evaluator/Selector Provenance Audit V1

Status: read-only diagnostic plan

Purpose: locate where competent frozen football-model candidate populations are degraded, suppressed, or anti-selected by the downstream evaluator/selector path without changing any football model, Task05F evaluator, selector policy, candidate region, threshold, or 2025 seal.

## Key architecture correction

The frozen Task05G remediation intentionally restricted all three selectors to the Task05E frozen model-candidate regions as a diagnostic experiment. That restriction is not the intended permanent Hit Rate universe.

The updated Market Evaluation Layer plan defines a common evaluated-wager table consumed by Hit Rate, Balanced, and Value. Hit Rate's primary objective is actionable win probability subject to reliability, price sanity, historical support, and product constraints. Balanced seeks a combination of win probability, price/value, and reliability. Value seeks historically supported price advantage.

Therefore this audit separates:

1. the intended full common-candidate-table selector universe;
2. the remediation's model-region-only diagnostic universe;
3. the frozen Task05E region populations used to trace football-model provenance.

No result from this audit may be used to silently redefine selector eligibility.

## Questions

1. For each market and season, what happens to ROI/hit rate/population at each downstream stage: exact shopped offer -> supported -> HIGH/MEDIUM -> VALUE/PLAYABLE -> selector eligibility -> selected top-ranked wager?
2. For the frozen Task05E candidate populations, at which stage does positive or decent model-region performance deteriorate?
3. Does Task05F actionable-probability ordering preserve, flatten, or reverse football-model disagreement ordering?
4. How often is evaluator football-model influence zero in the blocks where candidates are ranked?
5. For Hit Rate, how much of the original full-board selection comes from outside the Task05E frozen regions, and how does that outside-region population perform? Hit Rate must not be assumed to require a historical +ROI region.
6. For Balanced, is the severe loss caused by candidate admission, evaluator filtering, probability ranking, particular markets/seasons, or some interaction of these?
7. For spread specifically, how does Expected Margin disagreement strength relate to Task05F actionable probability rank and realized outcome among the same weekly candidate set?

## Guardrails

- 2025 remains sealed.
- Read-only diagnostics only.
- No threshold search.
- No alternate selector adopted.
- No model/evaluator retuning.
- No candidate-region changes.
- Report all seasons and markets, including bad results.
- Preserve original Task05G and remediation outputs for direct comparison.

## Intended output

A permanent stage audit with counts, hit rate, ROI, estimated EV, actionable probability, model-disagreement diagnostics, evaluator influence diagnostics, and season/market decomposition at every stage. The report may identify a structural failure point but must not choose a replacement policy from these same outcomes.
