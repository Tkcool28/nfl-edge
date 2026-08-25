# Task05G Spread Confidence V3 — Preregistration

Status: **FROZEN BEFORE V3 OUTCOME EXECUTION**

This document freezes the next spread-confidence experiment before any V3 HHR/Balanced outcomes are generated.

## 1. Motivation

The failed Model Confidence V2 experiment showed that HHR and Balanced became dominated by spread selections with implausibly high model-confidence probabilities (~77% average) that realized near 45% in 2023–2024.

The follow-up read-only spread-confidence audit localized the mechanism:

- spread orientation / settlement mismatches: **0**;
- entering-2023 residual MAE 10.64 points vs realized-2023 MAE 10.92 (only +2.65%);
- entering-2023 residual SD 13.72 vs realized-2023 SD 14.17 (+3.30%);
- entering-2024 prior and realized residual distributions were essentially identical;
- therefore stale 2020–2022 residual variance does **not** explain the 75–85% spread probabilities;
- the unconditional empirical-residual conversion is the problem: it assumes prediction residual is independent of how far Expected Margin disagrees with the offered spread;
- that assumption is contradicted by the historical offered-line evidence.

Across exact-shopped supported spreads, V2 model-cover-margin buckets behaved as follows:

- 0–2 points: 54.13% non-push cover rate, +3.18% ROI;
- 2–4: 56.04%, +6.78%;
- 4–6: 44.88%, -14.31%;
- 6–8: 52.54%, approximately flat;
- >=8: 48.28%, -7.87%.

Yet the residual bootstrap mapped the >=8-point group to ~78.63% average confidence. The probability conversion was therefore treating large model/market disagreement as much more informative than the data support.

## 2. Scope

This experiment changes **only the spread model-confidence conversion used by the experimental HHR/Balanced V2 selectors**.

Frozen and unchanged:

- Expected Margin football model and all model artifacts;
- Task05F evaluators and VALUE/PLAYABLE/LEAN/PASS semantics;
- ML model-confidence calibration;
- HHR eligibility/ranking rules from V2;
- Balanced eligibility/ranking rules from V2;
- Balanced B0/B1/B2 price-gap tolerances (0pp / -1pp / -2pp);
- all Task05E candidate definitions/evidence;
- all historical data;
- 2025 remains sealed;
- Value V2 is **out of scope** for V3 because its confirmed failure is dominated by later-period ML edge decay, a separate mechanism.

## 3. Chronology and interpretation

Because 2023–2024 outcomes have already been inspected during V2 forensics, they are **not** a pristine holdout for V3.

V3 will use:

- 2020–2022: development / chronological evaluation;
- 2023–2024: locked diagnostic check only;
- 2025: sealed and prohibited.

No claim of final out-of-sample promotion may be made from 2023–2024 V3 results. A future final test must preserve 2025 until the broader Task05G policy is frozen.

## 4. Corrected spread-confidence definition

For each exact spread proposition, define **model cover margin** without sportsbook price:

- home side: `m = expected_home_margin + offered_line`;
- away side: `m = -expected_home_margin + offered_line`.

Positive `m` means Expected Margin predicts the selected side to cover the exact offered spread by `m` points.

V3 will no longer convert `m` to probability by replaying an unconditional residual distribution.

Instead, V3 will fit a **strictly-prior direct logistic calibration** of actual non-push cover outcome on model cover margin.

### Training observations

At every chronological block:

1. use only prior blocks from the Task05F historical evaluator board;
2. exact-shop DK/FD spread offers using the frozen shopping function;
3. deduplicate calibration propositions on `(game_id, selected_side, line)` so identical DK/FD offers do not double-weight one event;
4. exclude pushes from the binary calibration target;
5. exclude missing/non-finite Expected Margin, line, or settlement;
6. use no American odds, Pinnacle probability, Task05F actionable probability, Task05F EV, Task05F status, or future result information as calibration features.

### Logistic form

Feature:

`x = model_cover_margin / 7.0`

Target:

- WIN = 1
- LOSS = 0
- PUSH excluded from fit

Fit:

`LogisticRegression(C=1.0, solver="lbfgs", max_iter=2000, random_state=0)`

with intercept enabled and default L2 regularization.

Resulting selected-side probability:

`q_spread_v3 = sigmoid(intercept + slope * x)`

### Support / fail-closed rules

A chronological spread calibration is supported only when:

- prior non-push calibration observations >= 256;
- both binary outcome classes are present;
- fitted intercept and slope are finite;
- fitted slope is strictly positive.

If any condition fails, spread model confidence is unsupported for that block and spread cannot enter experimental HHR/Balanced through V3.

The positive-slope rule is a truthfulness guard: if prior data do not show larger positive model cover margin corresponding to greater cover probability, the system must not manufacture HHR/Balanced confidence from that signal.

## 5. HHR V3 — unchanged selector policy

HHR selector mechanics remain exactly those frozen in V2:

- common supported exact DK/FD moneyline/spread table;
- model-confidence probability >= 0.55;
- American odds -300 through +200;
- rank model-confidence probability first;
- then frozen reliability / model-price-gap / odds / deterministic ID tie-break sequence.

Only spread `model_confidence_probability` changes from the failed unconditional-residual value to `q_spread_v3`.

ML model confidence remains the existing chronological QB-Elo/XGB calibration.

## 6. Balanced V3 — unchanged selector policy and price grid

Balanced mechanics remain exactly those frozen in V2:

- model-confidence probability >= 0.52;
- odds -220 through +200;
- model-price gap = `model_confidence_probability - exact_offer_break_even_probability`;
- B0 tolerance = 0.00;
- B1 tolerance = -0.01;
- B2 tolerance = -0.02;
- rank model-confidence probability first, then model-price gap, reliability, odds, deterministic ID.

The same preregistered B0/B1/B2 grid is rerun because V2's inflated spread confidence made all three variants select the same wagers. V3 asks whether a calibrated spread probability finally makes the price tolerances meaningfully different.

## 7. Coverage / anti-neutering diagnostics

V3 must not be judged solely by ROI if it collapses recommendation frequency.

For development 2020–2022 report:

- HHR V1 plays and V3 plays;
- Balanced V1 plays and each V3 variant's plays;
- play-block coverage;
- no-play blocks;
- eligible candidates per block;
- ML/spread market mix;
- hit rate, ROI, average odds, maximum losing streak.

Product coverage guardrails remain:

- HHR V3 play coverage must be at least 75% of HHR V1 development coverage;
- a Balanced V3 variant must have at least 75% of Balanced V1 development coverage to be considered usable.

These guardrails do **not** authorize loosening calibration or selector rules after seeing results.

## 8. Spread calibration diagnostics

For every chronological phase report:

- calibration support count;
- fitted intercept and slope by block/season entry;
- Brier score and log loss on spread propositions;
- average predicted probability vs realized non-push hit rate;
- confidence buckets: <50%, 50–55%, 55–60%, 60–65%, >=65%;
- model-cover-margin buckets: <0, 0–2, 2–4, 4–6, 6–8, >=8;
- season breakdown;
- selected HHR spread calibration;
- selected Balanced spread calibration.

The key diagnostic question is whether direct calibration prevents 8–12 point model/line disagreements from automatically becoming 75–85% cover probabilities unless strictly-prior offered-line outcomes actually justify that confidence.

## 9. Development decision rule for Balanced

Among B0/B1/B2, a variant is development-usable only if it passes the 75%-of-V1 coverage guardrail.

If multiple variants are usable, choose by this frozen lexicographic rule on 2020–2022 only:

1. higher non-push hit rate;
2. higher ROI;
3. greater coverage;
4. tighter price discipline in exact tie: B0 before B1 before B2.

The winner is frozen before reading the V3 2023–2024 diagnostic output.

## 10. No post-result tuning

After V3 outcomes are generated, do not change in this experiment:

- logistic `C`;
- feature scale 7.0;
- minimum support 256;
- positive-slope guard;
- HHR/Balanced probability floors;
- odds bounds;
- B0/B1/B2 tolerances;
- ranking order;
- calibration population/dedup definition.

If V3 fails, record the failure and diagnose it separately.

## 11. Expected verdict language

Mechanical success with useful development behavior but no pristine holdout available:

`SPREAD_CONFIDENCE_V3_MECHANICALLY_VALIDATED_DIAGNOSTIC_ONLY`

If development/diagnostic behavior remains materially miscalibrated or product coverage collapses:

`SPREAD_CONFIDENCE_V3_FAILED`

Neither verdict authorizes production promotion or opening 2025.
