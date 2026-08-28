# PR #19 — Task05F evaluator prototype

Historical PR: #19  
Exact head: `082f36e4ebb7fed6d0d918ca5ae25941aa8c6104`  
Disposition: `SUPERSEDED_EVALUATOR_PROTOTYPE`

## Purpose

PR #19 was the first focused implementation of the Task05F market-evaluation layer. It introduced the source-agnostic exact-offer contract, evaluator families for moneyline/spread/totals, reliability/support handling, uncertainty, deterministic chronological validation, and 2025 fail-closed boundaries.

It is retained as research provenance only. The accepted production evaluator was later rebuilt cleanly and merged through PR #23.

## Final validated prototype findings

The last validated #19 evidence fixed a support-coordinate inconsistency before concluding the prototype:

- Moneyline `avg_pin_gap` used the same **signed** coordinate in historical fitting and live/manual evaluation.
- Spread/totals support moved to orientation-invariant `delta_magnitude = abs(delta)` while probability math retained the selected-side signed delta.
- Point-market support therefore treated mirrored away/under sides consistently with canonical home/over orientation.
- Prior reliability/support fixes remained intact: fail-closed out-of-support behavior, prior-block stability, uncertainty defaults, exact-AVG fail-closed behavior, and the 2025 firewall.

Development/scoring universe was explicitly 2020–2024 only. No evaluator-scored row exceeded 2024.

## Prototype scorecard

Preregistered selected families at the end of #19:

- Moneyline: `global_shrinkage`
  - Brier approximately `0.2071`
  - AUC approximately `0.740`
  - showed incremental discrimination over the Pinnacle benchmark in this prototype.
- Spread: `calibrated_normal`
  - Brier approximately `0.2503`
  - AUC approximately `0.493`
  - calibrated translation but weak/no demonstrated global discrimination.
- Totals: `calibrated_normal`
  - Brier approximately `0.2508`
  - AUC approximately `0.500`
  - similarly weak as a global betting-discrimination layer.

The final validation reported 42 focused value-layer tests passing and byte-identical deterministic scorecard/provenance outputs across two independent chronological runs.

## Why it was not promoted

The prototype was useful but not the final architecture. Later Task05F work found and corrected additional issues that #19 did not fully resolve, including:

- integer-line Pinnacle conditional-nonpush push-cell inversion;
- accepted-family reliability inheritance/combination semantics;
- complete replayable state for point residual distributions;
- unified production/manual exact-offer execution through the final `evaluate_offer(...)` runtime;
- the final accepted per-market architecture (ML V4 / Spread V3 / Total V3).

Those corrections were incorporated into the clean PR #23 evaluator freeze rather than merging #19.

## Historical evidence pointers

Full original reports remain recoverable at the exact PR head, including:

- `reports/value_evaluator_v1/validation_summary.md`
- `reports/value_evaluator_v1/reliability_support_validation.md`
- `reports/value_evaluator_v1/scorecard.json`
- `reports/value_evaluator_v1/provenance.json`

Do not use the #19 executable implementation as a production alternative to the Task05F evaluator on `main`.
