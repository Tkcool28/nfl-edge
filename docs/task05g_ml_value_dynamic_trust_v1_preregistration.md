# Task05G ML Value Dynamic Trust V1 — Preregistration

Status: preregistered before implementation/results on this branch.

Purpose: test whether the ML Value lane can preserve a generally well-calibrated football win-probability model while adapting when the *betting edge versus price* stops realizing during a season.

This experiment does **not** modify Task05F evaluator semantics, football models, Task05E candidate evidence, historical data, HHR/Balanced policy, or sealed 2025.

## Motivation

The completed V2 experiment showed:

- general ML model-confidence calibration remained stable from 2020–2022 to 2023–2024;
- Value V2 development ML was strong, but confirmation/stress-period ML collapsed badly, especially 2023;
- therefore the problem is better framed as **nonstationary ML betting-edge trust**, not wholesale ML probability failure.

A causal system cannot know at Week 1 of 2023 that an edge that worked through 2022 has died. It can only (a) avoid carrying full certainty across the offseason and (b) update trust from strictly prior settled evidence as the new season unfolds.

## Chronology and evidence-use rules

- 2018–2019: upstream model-confidence warmup only; no special use here.
- 2020–2022: development replay for this dynamic-trust design.
- 2023–2024: **retrospective stress replay only**. These seasons have already been exposed by earlier V2 analysis and are not an untouched confirmation set.
- 2025: sealed/prohibited. No reads, tuning, diagnostics, or results.

Every trust state used for block `season-week` must be computed from settled ML Value opportunities in **strictly earlier blocks of the same season only**. Same-week outcomes are prohibited.

## Frozen base Value eligibility

Start from the already-implemented V2 Value opportunity definition. A row must remain:

- supported by Task05F and the model-confidence layer;
- moneyline or spread;
- exact DK/FD shopped offer;
- positive model-price gap;
- Task05F `price_status == VALUE`;
- Task05F expected value > 0;
- within frozen Value price bounds.

No base eligibility threshold is changed by this experiment.

## ML trust observation stream

For trust updates, use **all unique prior ML opportunities that satisfy the frozen V2 Value eligibility**, not only previously selected headline wagers.

To avoid duplicate-book double counting, trust observations are deduplicated to one row per `(block, game_id, selected_side)` after exact shopping; use the best exact offer produced by the existing shopping function.

For each prior ML opportunity:

- `q_model` = model-confidence probability for the selected side;
- `p_be` = exact-offer break-even probability;
- `predicted_edge = q_model - p_be`;
- `y = 1` for WIN, `0` for LOSS; pushes are excluded from the trust numerator/denominator;
- `realized_edge = y - p_be`.

Only rows with finite values and settled WIN/LOSS outcomes are admitted to the trust calculation.

## Season-reset prior

At the start of every season:

- prior trust ratio = **0.50**;
- prior pseudo-count = **8** opportunities.

This intentionally does not carry full betting-edge confidence across an offseason, while still allowing evidence from the current season to move the state quickly.

## Weekly trust update

Let `n` be the number of strictly prior, same-season, unique settled ML Value opportunities.

If `n == 0`, `trust = 0.50`.

Otherwise:

1. `predicted_edge_sum = sum(q_model - p_be)` over prior observations.
2. `realized_edge_sum = sum(y - p_be)` over prior observations.
3. If `predicted_edge_sum <= 0`, data trust is 0.
4. Otherwise `data_trust = clip(realized_edge_sum / predicted_edge_sum, 0, 1)`.
5. Shrink to the season-reset prior:

   `trust = (8 * 0.50 + n * data_trust) / (8 + n)`

Trust is therefore bounded to `[0, 1]` and is strictly causal.

## Candidate ranking effect

For spread Value candidates, keep the existing V2 consensus-edge ranking unchanged.

For ML Value candidates:

- `trusted_model_price_gap = trust * model_price_gap`
- `dynamic_consensus_edge = min(trusted_model_price_gap, evaluated_edge_probability)`

All other ranking tie-breaks remain as in V2 Value.

## Preregistered variants

### D0 — frozen V2 baseline

No dynamic trust. Reproduce the existing Value V2 headline stream.

### D1 — dynamic ranking shrink only

Use `dynamic_consensus_edge` for ML ranking. No hard trust gate.

### D2 — dynamic ranking shrink + RED gate

Same as D1, plus:

- the RED gate is inactive until at least **8** prior same-season trust observations exist;
- once `n >= 8`, an ML candidate is ineligible to become the Value headline when `trust < 0.25`;
- ML can become eligible again automatically if later strictly prior evidence raises trust to `>= 0.25`.

Spread Value candidates are unaffected.

No other trust cutoffs, pseudo-counts, reset values, windows, or variants may be added after results are observed.

## Primary diagnostics

For D0/D1/D2, report separately for 2020–2022 and stress replay 2023–2024:

- total Value plays and coverage;
- ML/spread play counts;
- hit rate and ROI overall and by market;
- season-by-season results;
- number of ML headlines displaced by spread;
- number of ML no-plays caused by D2 RED gate;
- ML trust trajectory by week;
- first week each season where trust falls below 0.50 and 0.25;
- trust observation count at those crossings;
- max losing streak.

## Anti-neutering guard

D2 is flagged `COVERAGE_COLLAPSE` if its 2020–2022 total Value play count is below **75% of D0** or if its 2023–2024 stress-replay play count is below **75% of D0**.

Coverage is a product guard, not a tuning target. The rule must not be loosened after results.

## Interpretation rules

This experiment is diagnostic/retrospective and cannot create a new untouched 2023–2024 confirmation claim.

A useful result would show that D1/D2:

- preserves substantial Value coverage;
- reduces exposure to a deteriorating ML edge after strictly prior evidence accumulates;
- does not merely replace ML losses with no-play weeks;
- does not damage strong prior periods enough to erase the product's usefulness.

Because 2023–2024 are already known, even a strong stress-replay result is **not sufficient for production promotion**. Any final adaptive trust policy must remain frozen for future validation, with 2025 still sealed until the project explicitly reaches that gate.
