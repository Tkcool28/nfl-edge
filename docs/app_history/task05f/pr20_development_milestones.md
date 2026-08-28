# PR #20 — Task05F development milestones

Historical PR: #20  
Exact head: `68d20c71934e59fc5dcc1f7d34beda2bebdc0189`  
Disposition: `DEVELOPMENT_LAB_SUPERSEDED_BY_23_AND_59`

PR #20 became a 192-commit development laboratory rather than a clean merge candidate. It accumulated multiple evaluator, reliability, Play Through, staking, selector, product, and audit generations. This document preserves the important research sequence without copying obsolete executable alternatives into `main`.

## Evaluator rebuild V1

Verdict: `VALID EXECUTION / NO V1 CANDIDATE PROMOTED`.

Key findings:

- Raw exact-AVG moneyline was too poorly calibrated for direct full-board valuation.
- Empirical-residual spread probability had materially worse probability quality than the incumbent calibrated-normal approach and failed frozen spread-edge preservation.
- Totals showed no demonstrated positive-value layer.
- The exact-offer and explicit-push architecture itself remained useful.

The experiment also corrected the frozen pooled spread baseline to approximately +5.538% ROI rather than the earlier carried-forward approximation.

## Evaluator rebuild V2

Verdict: `VALID EXECUTION / NO V2 CANDIDATE PROMOTED`.

Key findings:

- Monotone exact-AVG ML calibration only slightly improved proper scoring and still did not repair full-board wagering discrimination.
- Spread V2 used Pinnacle line anchor + Expected Margin global slope; fitted incremental contribution was near zero globally and the frozen spread edge remained concentrated in rejected wagers.
- Totals remained probability-usable but with no demonstrated value edge.
- A post-hoc totals EV-band pattern was explicitly recorded as observational only and not used to tune a threshold.

## Evaluator rebuild V3

Verdict: `SPREAD ARCHITECTURE ACCEPTED / TOTALS PROBABILITY BASE ACCEPTED-WEAK / ML NOT ACCEPTED`.

Important transition:

- Spread V3 added Pinnacle **price** to the market-implied mean rather than treating every identical line as a 50/50 belief.
- Frozen `SPREAD_0_4_DISCOVERY_UNION` evidence was materially enriched by strict +EV filtering while probability quality remained competitive with the incumbent.
- Spread V3 was frozen as the accepted point-market evaluator architecture.
- Totals V3 was frozen as the probability/valuation architecture but retained `TOTALS_VALUE_WEAK_NO_DEMONSTRATED_EDGE`.
- ML V3 collapsed to the Pinnacle anchor and produced a severe false apparent +EV concentration, so it was rejected.

## Moneyline V4

Verdict: `ML FAIR-VALUE BASE ACCEPTED / UNIVERSAL FULL-BOARD ML VALUE EDGE NOT DEMONSTRATED`.

V4 separated two stages:

1. prior-only calibration of Pinnacle no-vig probability;
2. optional bounded contribution from frozen exact-AVG football-model probability.

Key findings:

- Final moneyline probability preserved Pinnacle's strong proper-scoring performance.
- Exact-AVG model weight was zero in 91/98 supported calibration blocks and final weight was zero.
- This did **not** mean the football model was useless; it meant it was not justified as a universal fair-value correction.
- Raw frozen football-model probability/disagreement was deliberately retained as a separate downstream axis.
- V4 strongly enriched previously frozen ML dog-value regions while not demonstrating a universal full-board ML +EV population.

This separation between **fair-value probability** and **football-model signal** became a crucial later architectural principle.

## Locked evaluator consolidation

The accepted component architecture was consolidated as:

- Moneyline: `ml_v4`
- Spread: `spread_v3`
- Total: `total_v3`
- strict Value: `expected_value > 0`
- seasons: 2020–2024 only
- 2025 sealed

The consolidation reproduced source component rows deterministically and established a common evaluator board without inventing a new probability family.

## Phase F V1.1 — reliability / uncertainty / staking probability

Verdict: `STRUCTURALLY ACCEPTED / NOT A VALUE-SELECTOR`.

A pre-result exact-offer correction was made because the initial design anchored point-market staking shrinkage to Pinnacle probability at Pinnacle's own line rather than the actionable wager's exact line.

The corrected V1.1:

- translated the sharp-market distribution to the actionable wager's own exact line;
- reproduced the locked evaluator fields exactly;
- assigned chronological reliability/uncertainty;
- produced conservative staking probability;
- did **not** change `p_win`, `p_push`, `p_loss`, fair price, EV, strict Value, or support.

Core lesson: staking probability is a bankroll-sizing input, **not** a substitute Value classifier.

## Play Through V1.1

Verdict: `STRUCTURALLY ACCEPTED PRODUCT POLICY / NOT A VALUE SIGNAL`.

Frozen product contract:

- maximum break-even concession: 1.5 percentage points;
- confidence-scaled rather than blanket;
- one global formula across ML/spread/total;
- no ROI input or market-specific tuning;
- negative EV is never relabeled as Value;
- 2025 sealed.

Historical `PLAYABLE` profitability was explicitly observational only and was not used to alter the accepted product policy.

## Selector V1

Verdict: `HIGH-HIT ENCOURAGING / BALANCED AND VALUE NOT ACCEPTED`.

The common candidate-table and weekly selection machinery worked, but the first selector architecture ranked primarily on the evaluator/fair-value axis.

Critical diagnosis:

- ML V4 was accepted as a fair-value base while universal full-board ML Value was not proven.
- Raw football-model signal had intentionally been preserved separately.
- Selector V1 failed to use that separate football-confidence axis correctly.

This exposed the first explicit selector architecture mismatch.

## Selector V2

Verdict: `VALID EXECUTION / NOT PROMOTED`.

V2 required strictly positive direction-only support from the frozen football signal for every primary-card wager.

Result:

- coverage fell modestly;
- High Hit Rate weakened materially;
- Balanced and Value did not improve;
- the favorable V1 spread-selection behavior was suppressed.

Conclusion: a universal zero-threshold football-direction gate was too blunt. The answer was not to discard football confidence, but to stop treating one universal gate as the solution for every product lane.

## Selector V3.4 structural replay

Verdict: `VALID STRUCTURAL EXECUTION / COVERAGE RESTORED / PRICE-SUPPRESSION AUDIT REQUIRED`.

No historical outcomes were opened for this structural replay.

Key structural findings:

- removing the LOW-reliability hard veto materially restored featured-card coverage;
- reliability remained a risk label rather than an automatic actionability veto;
- the highest football-confidence wager was still often blocked by evaluator `LEAN`/`PASS` status;
- the remaining HHR question was price/Play Through suppression rather than raw model availability.

This helped clarify the responsibility split between evaluator actionability, staking, and selector objectives.

## Model-confidence coverage audit

Verdict: `CURRENT_HHR_CONFIDENCE_AXIS_MISMATCH_CONFIRMED`.

This is the most important research artifact from #20 for the final downstream architecture.

It established that Task05F already had two distinct concepts by design:

1. **football-model confidence** — who the football model thinks is likely to win;
2. **evaluator fair probability** — calibrated price/value quality.

The audit found that the HHR selector had incorrectly used evaluator fair probability/reliability as its primary hit-rate axis.

Notable development diagnostics:

- raw exact-AVG favorite on the same 2020–2024 universe: about 63.5% hit rate;
- top raw model pick on model-available weekly slates: about 80.7% hit rate;
- restricting to the current evaluator `VALUE/PLAYABLE + HIGH/MEDIUM` universe materially changed the chosen candidates and collapsed the diagnostic hit rate;
- many HHR no-play weeks still contained high model-native confidence.

The audit explicitly concluded:

- HHR should rank model-native football confidence, not evaluator fair probability;
- Balanced should combine a football-confidence axis with price/value information;
- Value should remain strict evaluator `EV > 0`;
- evaluator fair price and Play Through should remain visible without being mislabeled as football confidence;
- Expected Margin straight-up accuracy must not be misused as ATS cover probability.

This diagnosis directly informed the later Task05G separation of HHR, Balanced, and Value objectives.

## What was incorporated later

The useful #20 findings were carried into the clean accepted architecture rather than merging the branch itself:

- accepted evaluator families were rebuilt cleanly in PR #23;
- strict Value / Play Through separation was preserved;
- model confidence and evaluator price/value were treated as different axes;
- final Task05G selectors/staking/product policy were promoted cleanly in PR #59;
- Task05G development history is archived separately under `docs/app_history/task05g/`.

## Why #20 should not remain open

The branch contains many obsolete callable implementations:

- evaluator generations V1/V2/V3;
- multiple selector generations;
- multiple staking generations;
- product simulations;
- historical workflows/configs/runners.

Those files are valuable as Git history but harmful as an apparent alternative production merge target. The exact head remains permanently recoverable at:

`68d20c71934e59fc5dcc1f7d34beda2bebdc0189`

Closing the PR after this archive merges preserves the evidence while removing ambiguity about the canonical system on `main`.
