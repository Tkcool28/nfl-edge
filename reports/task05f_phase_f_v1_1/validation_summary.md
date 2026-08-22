# Task05F Phase F V1.1 — Reliability / Uncertainty / Staking Probability Evidence

Status: **VALID EXECUTION / STRUCTURALLY ACCEPTED / NOT A VALUE-SELECTOR**

Phase F is strictly downstream of the locked Task05F evaluator. It does not modify frozen football models, evaluator `p_win/p_push/p_loss`, fair price, strict expected value, strict `VALUE`, or support decisions.

## Exact-offer correction before result inspection

The initial Phase F preregistration used Pinnacle's point-market probability at Pinnacle's own line as the staking shrinkage anchor. While its first workflow was still executing, before any Phase F result/artifact inspection, this was recognized as an exact-offer semantic error: an actionable DK/FD wager at +3.5 is not the same event as a Pinnacle wager at +3.

- Invalidated workflow: `32548922531`
- PR audit comment: `5377613930`
- Invalidated status: `INVALIDATED_BEFORE_RESULT_INSPECTION`
- Corrected preregistration: `config/task05f_reliability_uncertainty_v1_1_prereg.yaml`
- Correction prereg commit: `9fbc2cd3cbb425e526056e491cb8e4703196957c`

V1.1 translates the V3 Pinnacle line+price implied market distribution to each actionable wager's **own exact line**, including the integer-line push cell, before computing the conditional non-push staking anchor. ML remains the V4 selected-side calibrated-market probability because the ML event does not change with price.

## Valid execution

- Feature commit executed: `f213f02b443c85040defa618c91f9b098f88ef34`
- Workflow run: `32549390727`
- Artifact ID: `9469653744`
- Artifact ZIP digest: `sha256:544703bcc9519c330c4e85a32a30e8dced826fbdd439fdef92033e2e26db9339`
- Value-layer tests: **96 passed**
- Evaluator-only scope guard: PASS
- 2025 firewall: PASS
- Exact-offer correction guard: PASS
- Two complete chronological Phase F runs: PASS
- Deterministic output comparison: PASS
- Locked board rows: **8,448**
- `full_board.parquet` SHA-256, both runs: `24353db9543879a23f732679b25ce35ba4bfdd1c477ddb71472ef3a59a3e858a`
- `scorecard.json` SHA-256, both runs: `d92061ddcb9d4137f0600b34a3b05e74b08b46505611c5f7d903a634d6f4a0d3`

## Locked evaluator reproduction hard gate

The Phase F enrichment reproduced the locked evaluator exactly:

- locked rows: 8,448
- Phase F rows: 8,448
- immutable rows equal: true
- strict Value labels unchanged: true
- support flags unchanged: true
- immutable payload SHA before/after:
  `0f5fa7115392c9b6262ac29df675629fb4623c9fb0208847ae9006c9a55c75fd`

Immutable fields include `p_win`, `p_push`, `p_loss`, `actionable_probability`, `fair_price_american`, `expected_value`, `strict_positive_value`, and `supported`.

## Reliability / uncertainty result

### Moneyline

- supported: 2,202
- final reliability: 747 MEDIUM, 1,455 LOW, 0 HIGH
- mean uncertainty radius: **0.04075**
- staking probability available: 2,202

By 2023–2024, meaningful MEDIUM support appears, but no ML rows reach HIGH under the preregistered candidate-uncertainty gate.

### Spread

- supported: 2,548
- final reliability: **32 HIGH, 1,618 MEDIUM, 898 LOW**
- mean uncertainty radius: **0.03903**
- staking probability available: 2,548

Reliability strengthens chronologically: 2023 has 570 MEDIUM supported rows; 2024 has 32 HIGH and 538 MEDIUM.

### Total

- supported: 2,542
- final reliability: **2,542 LOW**
- mean uncertainty radius: **0.06526**
- staking probability available: 2,542

The uncertainty layer therefore independently confirms the earlier totals caution. Totals remain evaluable in the game explorer but should not be treated as high-confidence simply because a point estimate exists.

## Preregistered staking-EV diagnostics

These are diagnostic only; they are not used to tune Phase F or define Value.

- ML staking-positive-EV: 755 rows, realized ROI **-4.72%**
- ML staking-nonpositive-EV: 1,447 rows, realized ROI **-4.73%**
- Spread staking-positive-EV: 161 rows, realized ROI **-2.73%**
- Spread staking-nonpositive-EV: 2,387 rows, realized ROI **-3.84%**
- Total staking-positive-EV: 59 rows, realized ROI **-16.76%**
- Total staking-nonpositive-EV: 2,483 rows, realized ROI **-3.41%**

Decision: **staking probability is accepted as a conservative bankroll-sizing probability, not as a new candidate-selection or Value-classification signal.** Strict Value continues to come from the locked evaluator. The selector layer must not substitute `staking_expected_value > 0` for `expected_value > 0`.

## Phase F decision

Phase F V1.1 is accepted as the locked post-probability reliability/uncertainty/staking-probability layer because it:

1. is strictly chronological and prior-only;
2. preserves every locked evaluator probability/Value/support field;
3. uses the sharp-market anchor for the same exact actionable event;
4. is deterministic;
5. keeps 2025 sealed;
6. gives the downstream staking policy a conservative probability and transparent reliability/uncertainty evidence.

No historical diagnostic is used to alter the preregistered formula. New observations remain `OBSERVATIONAL_ONLY_NOT_TUNED`.

Next phase: preregister the separate global Play Through price/presentation policy. Play Through may consume accepted reliability/uncertainty evidence but may not change strict `VALUE` or the frozen evaluator.
