# Task05F Evaluator Final V1

This branch finishes the Market Evaluation Layer without reopening football-model selection or entering selector/user-staking scope.

## Frozen incumbents

- Moneyline: ML V4 — calibrated Pinnacle no-vig probability with optional bounded exact-AVG QB-Elo/XGB logit pool.
- Spread: Spread V3 — price-aware Pinnacle anchor plus bounded Expected Margin contribution.
- Total: Total V3 — price-aware Pinnacle anchor plus bounded Ridge R4 contribution; prior evidence remains weak/no demonstrated global value edge.

## Corrections in this freeze

1. **Integer Pinnacle push semantics.** Paired no-vig prices on an integer spread/total line are conditional on a non-push settlement. The corrected evaluator solves for the market mean using the explicit one-point push cell. Half-point lines retain the prior closed-form Normal inversion.
2. **Accepted-family reliability ownership.** Reliability is assigned once from accepted-family support/OOD evidence plus that accepted family's strictly-prior OOS calibration uncertainty. ML V4 no longer inherits an `exact_avg` reliability tier and point V3 no longer inherits a `normal_cdf` tier before a second downgrade.
3. **Replayable frozen state.** The serialized state includes ML V4 calibration parameters, point V3 sigma/beta, the point residual distributions, support envelopes, and final accepted-family uncertainty state.
4. **One production evaluator interface.** Historical stored offers and equivalent manual offers go through the same `evaluate_offer(...)` function. The chronological runner asserts identical results.
5. **Account-independent candidate table.** Candidate rows retain DK/FD/Pinnacle offer context, evaluator probabilities/EV/reliability, and the frozen 1.5pp Play Through status. Historical outcome fields are excluded.

## Boundaries

- Development/scoring: 2020–2024 expanding prior season-week blocks only.
- 2025 remains sealed.
- Frozen QB-Elo, chronology-corrected XGBoost, Expected Margin V1 stable, and Ridge R4 are not modified.
- Strict `VALUE` remains `expected_value > 0`.
- Play Through may label a negative-EV offer `PLAYABLE` but cannot relabel it `VALUE`.
- `staking_probability` remains an evaluator risk axis only. This task contains no user bankroll, unit recommendation, Kelly system, selector ranking, or dollar stake.

The frozen Task05E ML/spread regions are reported only as external preservation evidence. They cannot create a new bucket, threshold, or tuning target in this task.
