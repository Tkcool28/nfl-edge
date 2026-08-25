# Task05G Final Selector Bounded Audit Review

Verdict: `THREE_PROTOCOL_ARCHITECTURE_VALIDATED_MECHANICALLY_FINAL_TRUST_INTEGRATION_REMAINS`

This report records the bounded audit run under the frozen three-protocol architecture. It is not a production-promotion report. 2025 remained sealed.

## Evidence identity

- architecture freeze: `0aec344d800d7c7ab3d9f76b1ff31975ddfd54cc`
- bounded-audit preregistration: `79dda37f50136ea606da027256915f4931205e32`
- validated workflow head: `0c853f4bbf48c1d31dee85bc3731a4b95580bdad`
- workflow: `32884671714` — SUCCESS
- artifact: `9577169379`
- artifact digest: `sha256:73810fa928f1cdb75fba27dd25e73087ea77aabdd3b1ef9ee4447e6b4d66b4ac`
- frozen focused tests: 61 PASS
- Task05F reproduction: PASS
- Model Confidence V2 reproduction: PASS
- Spread Confidence V3 reproduction: PASS
- deterministic double replay: PASS
- exact RAW_Q-vs-trust coverage parity: PASS
- totals headline firewall: PASS
- 2025 firewall: PASS

The first workflow attempt stopped before selector output because the CI guard incorrectly expected each split Task05E ledger to contain all five seasons. The guard was corrected to the actual frozen chronology: discovery = 2020-2022, confirmation = 2023-2024, combined = 2020-2024. No selector rule, coefficient, threshold, candidate family, or preregistration changed.

## 1. Architecture separation is now real

The bounded audit deliberately removed the legacy economic/status coupling from HHR and Balanced:

- no HHR/Balanced `VALUE` requirement;
- no HHR/Balanced `PLAYABLE` requirement;
- no HHR/Balanced EV floor;
- no HHR/Balanced positive model-price-gap requirement;
- no EV/status field in HHR/Balanced ranking;
- Value remained strict +EV and frozen-model-provenance only.

The run passed explicit invariants proving ranking-only trust changes cannot alter the HHR/Balanced eligibility universe or card coverage.

## 2. Hit Rate

### Development 2020-2022

Architecture HHR (HALF_SHRINK):

- 46 / 65 play blocks = 70.77% coverage
- 28 wins, 17 losses, 1 push
- **62.22% non-push hit rate**
- -7.13% ROI (reporting only; not optimized)
- average odds -219
- 43 moneylines / 3 spreads

RAW_Q comparator with identical eligibility:

- 46 / 65 exact same coverage
- 57.78% hit rate
- -10.97% ROI

HALF_SHRINK therefore improved development hit rate by **+4.44pp** without changing coverage.

Model agency remained dominant:

- pure model rank-1 overlap: 36 / 46 = **78.26%**
- Pinnacle rank-1 overlap among comparable ML blocks: 17 / 43 = **39.53%**

### 2023-2024 exposed diagnostic

- 35 / 44 = 79.55% coverage
- 25-10
- **71.43% hit rate**
- +3.01% ROI
- all 35 headlines moneyline

RAW_Q hit 68.57% at identical coverage. HALF_SHRINK again improved hit rate, by +2.86pp, while ROI declined by 2.33pp. Since HHR's objective is hit rate rather than ROI, this is directionally consistent with the lane contract.

Model rank-1 overlap remained 74.29%; Pinnacle rank-1 overlap was 31.43%.

### Overall 2020-2024

- 81 / 109 = **74.31% coverage**
- 53 wins, 27 losses, 1 push
- **66.25% hit rate**
- RAW_Q comparator: 62.50%
- HALF_SHRINK delta: **+3.75pp hit rate**
- 78 moneylines / 3 spreads

No-play reasons:

- 12 `NO_SUPPORTED_MODEL_CONFIDENCE` — early/cold-start blocks
- 15 `NO_CANDIDATE_ABOVE_CONFIDENCE_FLOOR`
- 1 `PRICE_OUTSIDE_PRODUCT_BAND`
- 0 trust-computation failures
- 0 shopping failures

In 2023-2024 there were no support-cold-start misses: eight misses were confidence-floor misses and one was the price band. Thus mature HHR coverage is constrained mainly by genuine model-confidence availability rather than economics.

### Confidence sanity

Raw selected model-confidence >=80% is still a small, volatile tail:

- development: 4 rows, 0% realized hit
- 2023-2024: 4 rows, 100% realized hit
- overall: 8 rows, 50% realized hit

HALF_SHRINK does not rewrite these calibrated model probabilities. It lowers ranking trust only when model confidence outruns Pinnacle. This is the intended architecture: preserve model confidence as a separate signal while preventing an extreme model-v-market discrepancy from automatically winning the HHR slot.

## 3. Balanced

The corrected Balanced protocol increased availability without weakening the price band because the legacy EV/status/model-price-gap gates were removed.

### Development 2020-2022

T050 agreement trust:

- 50 / 65 = **76.92% coverage**
- 27-23
- 54.00% hit rate
- -6.28% ROI (secondary)
- average odds -131
- 40 ML / 10 spread

RAW_Q comparator with identical eligibility:

- 50 / 65 exact same coverage
- 25-25 = 50.00% hit rate
- -15.48% ROI

T050 improved development hit rate by +4.00pp and reduced selected ML constituent disagreement materially.

### 2023-2024 exposed diagnostic

T050:

- 38 / 44 = **86.36% coverage**
- 21-17 = 55.26% hit
- -8.49% ROI

RAW_Q:

- same 38 / 44 coverage
- 23-15 = **60.53% hit**
- +2.38% ROI

The same fixed T050 penalty therefore hurt later-period hit rate by 5.26pp.

### Overall 2020-2024

- both protocols: 88 / 109 = **80.73% coverage**
- both: 48-40 = **54.55% hit rate**
- T050 changed 27 selected blocks but finished exactly tied with RAW_Q on overall hit rate
- T050 reduced average selected ML disagreement, but that reduction was not reliably linked to higher hit rate

No-play reasons:

- 12 `NO_SUPPORTED_MODEL_CONFIDENCE` — early/cold-start
- 9 `NO_CANDIDATE_ABOVE_CONFIDENCE_FLOOR`
- **0 price-band misses**
- 0 trust/shopping failures

In 2023-2024 Balanced coverage reached 86.36%; all six missing blocks were below the 52% model-confidence floor. The current -220 to +200 price band did not remove a single block in this historical evidence.

### Balanced conclusion

The architecture is correct, but **T050 alone is not the final Balanced trust rule**.

Completed evidence now establishes two separate ML trust concerns:

1. constituent QB-Elo/XGBoost disagreement can create maximum-confidence anti-selection;
2. even strong constituent agreement does not protect against extreme football-model confidence outrunning the sharp market.

A final Balanced rule therefore needs to preserve raw calibrated model confidence while applying both already-established trust checks. It should not introduce a new tuned coefficient grid.

## 4. Value family evidence

Strict Task05F `VALUE` rows inside the four frozen Task05E model regions produced the following row-level evidence.

### ML AVG 0-2 disagreement

- development: 39 plays, +4.72% ROI
- 2023-2024: 13 plays, -31.84%
- overall: 52 plays, -4.42%

### ML dog AVG zone

- development: 58 plays, +27.83%
- 2023-2024: 18 plays, -18.44%
- overall: 76 plays, **+16.87%**

### ML corroborated dog zone

- development: 36 plays, +19.58%
- 2023-2024: 9 plays, -16.67%
- overall: 45 plays, **+12.33%**

### Expected Margin spread 0-4 region

- development: 95 plays, +8.15%
- 2023-2024: 46 plays, **+13.98%**
- overall: 141 plays, **+10.05%**

The spread family is the clearest cross-period row-level Value family. ML Value shows material regime instability.

However, selecting the maximum `consensus_edge` headline inside a good region still anti-selected later-period outcomes:

- `SPREAD_ONLY` scenario: development +24.71% headline ROI; 2023-2024 -15.95%
- `ALL_ML_FROZEN_REGIONS`: development +56.79%; 2023-2024 -33.01%
- `ALL_FROZEN_REGIONS`: development +43.56%; 2023-2024 -17.56%

This confirms that **candidate-family validity and weekly ranking are separate problems**. The final Value selector must preserve frozen model provenance and strict +EV while avoiding an unrestricted point-estimate edge optimizer.

## 5. Prior Value trust work recovered

Existing preregistered Task05G diagnostics already developed the needed causal trust concept:

1. broad-pool same-season ML trust reacted quickly but monitored the wrong population and falsely killed profitable 2022 ML;
2. frontier-aligned trust fixed the 2022 false alarm but a RED-only response reacted too slowly in the severe 2023 ML collapse;
3. a preregistered GREEN/AMBER/RED frontier state machine preserved 2020-2022 behavior and materially reduced 2023 ML damage, but its spread replacements were poor because that experiment predated the Spread Confidence V3 repair.

The state-machine report explicitly recommended rerunning the same frozen trust-state concept after spread confidence was corrected. Spread Confidence V3 is now mechanically validated, so that rerun is the appropriate final Value diagnostic. No new state thresholds need to be invented.

## 6. What is frozen vs still bounded

### Frozen architecture

- one common evidence table, three separate protocols;
- HHR: hit-probability objective, no EV/status objective;
- Balanced: probability-first plus real price band, no EV/status objective;
- Value: frozen model provenance + strict +EV, no forced coverage;
- no totals headline family;
- 2025 sealed.

### Strong final HHR candidate

HALF_SHRINK remains the strongest model-led HHR trust mechanism tested so far. It improves hit-rate direction across both historical periods while keeping roughly three-quarters model-rank-1 agency.

### Remaining final Balanced item

T050 alone is not stable. The final integrated candidate should combine the already-established model-v-market HALF_SHRINK trust and constituent-agreement T050 trust **without introducing a new coefficient**; this combined rule must be preregistered before replay.

### Remaining final Value item

Rerun the already-preregistered frontier GREEN/AMBER/RED trust concept after Spread Confidence V3 and under the frozen model-family/strict-Value contract. Do not retune its state thresholds.

## 7. Next bounded milestone

One final selector-candidate integration should be preregistered before output:

- HHR: fixed HALF_SHRINK;
- Balanced: one fixed dual-trust candidate built only from the two already-preregistered 0.50 trust transforms;
- Value: the existing frontier GREEN/AMBER/RED state constants, rerun with Spread V3 and frozen Value provenance;
- exact HHR/Balanced coverage parity;
- deterministic no-play reasons;
- 2020-2024 treated as development/exposed evidence only;
- 2025 remains sealed.

If that integrated candidate is coherent, freeze selector code/config/tests and staking interfaces before opening 2025 once for untouched acceptance.
