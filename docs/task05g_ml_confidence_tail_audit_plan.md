# Task05G ML Confidence Tail Audit — Frozen Diagnostic Plan

Status: **FROZEN BEFORE AUDIT OUTPUT**

## Purpose

Determine whether the remaining ML-led HHR/Balanced weakness after Spread Confidence V3 is caused by the ML model-confidence layer overstating the high-probability tail, by headline ranking anti-selection, by price/juice concentration, by QB-Elo/XGBoost disagreement, or by early chronology/cold-start effects.

This is a read-only diagnostic. It does not change any football model, Task05F evaluator, selector, threshold, price tolerance, unit policy, candidate family, or historical data.

## Frozen scope

- Start from the validated Spread Confidence V3 stack.
- ML confidence remains the V2 strictly-prior Platt/logistic calibration of the QB-Elo/XGBoost average.
- Spread Confidence V3 remains unchanged.
- HHR and Balanced selector mechanics remain unchanged.
- Value is out of scope for this audit except where a shared ML calibration diagnostic is useful.
- 2020–2022 are development-era diagnostics.
- 2023–2024 are locked diagnostic only because outcomes have already been exposed.
- 2025 remains sealed and prohibited.

## Questions

1. Does aggregate ML calibration hide miscalibration specifically above 60%, 65%, 70%, or 75% model confidence?
2. Does the Platt layer systematically inflate or deflate the raw QB-Elo/XGBoost average in the selected high-confidence tail?
3. Are actual HHR/Balanced ML headlines better calibrated than the eligible ML pool, or are they anti-selected by taking the highest stated probability?
4. Are rank-1 ML candidates better than rank-2/rank-3 candidates within the same block?
5. Does large QB-Elo/XGBoost disagreement identify a less trustworthy high-confidence tail?
6. Is high confidence concentrated in expensive favorites whose break-even requirement outruns realized hit rate?
7. Is the apparent weakness concentrated in early chronology/cold-start seasons rather than mature calibration states?
8. What is the descriptive coverage-versus-accuracy frontier if progressively higher ML confidence floors are applied, without selecting a new production threshold from these exposed outcomes?

## Frozen diagnostic bins

### Model-confidence buckets

- <52%
- 52–55%
- 55–60%
- 60–65%
- 65–70%
- 70–75%
- >=75%

### Raw QB-Elo/XGB average buckets

Same boundaries as model confidence.

### QB-Elo/XGB absolute disagreement

- <2 percentage points
- 2–5pp
- 5–10pp
- >=10pp

### American-odds / juice buckets

- <= -250
- -249 to -201
- -200 to -151
- -150 to -111
- -110 to +100
- +101 to +200
- > +200

### Fixed descriptive confidence floors

HHR ML-only frontier: 55%, 60%, 65%, 70%, 75%.

Balanced B0 ML-only frontier: 52%, 55%, 60%, 65%, 70%, 75%.

These floors are diagnostic only. They may not be adopted as a selector rule from this audit.

## Required outputs

For 2020–2022 and 2023–2024 separately:

- full exact-shopped supported ML calibration summary;
- calibration by model-confidence bucket;
- calibration by raw-average bucket;
- calibration by season;
- calibration by QB-Elo/XGB disagreement bucket;
- calibration by odds/juice bucket;
- calibrated-minus-raw probability shift;
- HHR ML eligible pool vs actual HHR ML headlines;
- Balanced B0 ML eligible pool vs actual Balanced B0 ML headlines;
- ML-only rank-1, rank-2, rank-3 comparisons within blocks;
- fixed confidence-floor coverage frontier: plays, play-block coverage, W/L, hit rate, ROI, average odds, average model confidence, average break-even probability;
- season-entry ML calibration state (N/intercept/slope);
- 2025 firewall proof.

## Interpretation guardrails

- A globally near-1 calibration slope does not clear the upper tail if the upper buckets are materially overconfident.
- Improved hit rate caused only by collapsing play count must be reported as a coverage tradeoff, not a free improvement.
- A threshold is not to be chosen by maximizing exposed historical ROI/hit rate.
- If the high-confidence tail is well calibrated but rank-1 headlines underperform rank-2/rank-3, diagnose ranking/selection rather than recalibrating ML probabilities.
- If high-confidence rows fail primarily when QB-Elo/XGB disagree, treat constituent disagreement as a candidate trust question for a future preregistered experiment, not as an immediate new filter.
- If calibration is sound and high-probability rows genuinely cash more often, accept that a truthful HHR product may sometimes have no distinct Balanced/Value companion rather than forcing three cards.

No result from this audit authorizes production promotion or opening 2025.
