# Task05F Application / Model-Development History

This directory preserves **application/model-development history**, not historical sports data.

It exists so the reasoning, failed experiments, accepted milestones, and provenance from early Task05F work remain visible in the repository without keeping obsolete executable alternatives open as merge candidates.

## Canonical production lineage

The accepted Task05F evaluator did **not** merge from PR #19 or PR #20.

Clean production lineage:

- PR #21 — CI bootstrap for bounded Task05F evaluator validation.
- PR #22 — frozen canonical T-60 market inputs for reproducible Task05F validation.
- PR #23 — clean accepted Task05F evaluator freeze/reconstruction.
  - accepted families: Moneyline V4, Spread V3, Total V3;
  - corrected integer-line push semantics;
  - one accepted-family reliability calculation;
  - complete replayable evaluator state;
  - common `evaluate_offer(...)` runtime for stored/manual exact offers;
  - strict `VALUE = expected_value > 0`;
  - frozen Play Through maximum break-even concession of 1.5 percentage points;
  - 2025 remained sealed.

Task05G downstream production policy was later cleanly promoted to `main` through PR #59. Its development history is indexed separately under `docs/app_history/task05g/`.

## Retired Task05F development PRs

| PR | Exact historical head | Disposition | Why it is retained here |
|---|---|---|---|
| #19 | `082f36e4ebb7fed6d0d918ca5ae25941aa8c6104` | `SUPERSEDED_EVALUATOR_PROTOTYPE` | First serious Task05F evaluator implementation and validation. Useful for support/OOD, orientation-coordinate, reliability, and early market-quality findings. Executable implementation was superseded by clean PR #23. |
| #20 | `68d20c71934e59fc5dcc1f7d34beda2bebdc0189` | `DEVELOPMENT_LAB_SUPERSEDED_BY_23_AND_59` | Large 192-commit development branch containing evaluator V1/V2/V3, ML V4, reliability/uncertainty, Play Through, candidate-table, staking, selector, product, and model-confidence experiments. Important research ancestry, but too broad and stale to remain a merge target. |

Full historical code remains recoverable from Git and the exact PR head SHAs above. It is intentionally **not** copied into a callable `legacy` implementation tree.

## Preserved research summaries

- `pr19_evaluator_prototype.md` — focused record of the original evaluator prototype and its final validated conclusions.
- `pr20_development_milestones.md` — consolidated record of the important experimental sequence and the findings that fed the clean Task05F and final Task05G architecture.

## Important architectural lessons carried forward

1. **Fair-value probability and football-model confidence are different axes.**
   - Evaluator fair probability answers price/value quality.
   - Football-model probability answers model-native winner confidence.
   - HHR cannot use fair-value probability as a substitute for football confidence.

2. **Strict Value and Play Through are different product concepts.**
   - `VALUE` remains strict positive expected value at the current exact offer.
   - Play Through is a bounded current-price/actionability policy and cannot relabel negative EV as Value.

3. **Point-market push semantics matter.**
   - Integer spread/total lines require explicit push-cell treatment and conditional-nonpush inversion.

4. **Reliability/uncertainty is not a second Value classifier.**
   - It informs confidence and conservative staking probability without rewriting evaluator EV or strict Value status.

5. **Do not preserve failed selector/staking generations as production alternatives.**
   - Their useful lessons were incorporated into later architecture; their callable implementations are intentionally retired.

6. **2025 remained sealed throughout this development chain.**

## Retirement rule

PR #19 and PR #20 may be closed once this archive is merged. Closing them does not delete their Git history, comments, workflow evidence, or exact commits; it removes stale merge targets while keeping the research map permanently visible on `main`.
