# Task05G Final Selector Candidate V1 — Preregistration

Status: **FROZEN BEFORE REPLAY / 2025 SEALED**

This experiment is subordinate to the final three-protocol architecture in `docs/task05g_final_selector_architecture.md` and the bounded-audit review in `reports/task05g/final_selector_bounded_audit_review.md`.

All 2020-2024 outcomes are already exposed development evidence. This replay can freeze a production candidate but cannot constitute untouched validation. 2025 remains sealed for one future acceptance run after code/config/tests/staking/output contracts are frozen.

## 1. Fixed shared preparation

Reproduce, without modification:

1. Task05F historical evaluator board;
2. Model Confidence V2 ML calibration;
3. Spread Confidence V3;
4. exact DK/FD shopping;
5. frozen Task05E candidate provenance registry.

No totals headline candidate is allowed.

## 2. Hit Rate — fixed candidate

No new HHR tuning is permitted.

Eligibility:

- Task05F supported;
- model confidence supported, support N >= 256;
- moneyline or spread;
- q >= 0.55;
- best exact DK/FD price between -300 and +200 inclusive.

No EV, price-status, or model-price-gap eligibility gate.

ML trust:

```text
hhr_market_trust = q - 0.50 * max(q - pinnacle_no_vig, 0)
```

Spread trust:

```text
hhr_market_trust = Spread Confidence V3 q
```

Ranking:

1. HHR trust descending;
2. raw calibrated model q descending;
3. reliability/support descending;
4. American odds descending;
5. candidate ID.

This is the same HALF_SHRINK mechanism already preregistered/tested. The 0.50 coefficient may not change.

## 3. Balanced — DUAL_TRUST candidate

Eligibility remains exactly the corrected bounded-audit universe:

- Task05F supported;
- model confidence supported, support N >= 256;
- moneyline or spread;
- q >= 0.52;
- best exact DK/FD price between -220 and +200 inclusive.

No EV, price-status, or model-price-gap eligibility gate.

### Moneyline trust components

Already-preregistered market-corroboration component:

```text
market_trust = q - 0.50 * max(q - pinnacle_no_vig, 0)
```

Already-preregistered constituent-agreement component:

```text
agreement_trust = q - 0.50 * abs(qbelo_selected - xgb_selected)
```

Frozen final candidate:

```text
balanced_dual_trust = min(market_trust, agreement_trust)
```

This introduces **no new fitted coefficient**. It applies whichever already-established trust concern is more conservative without summing/double-penalizing both.

The trust score is ranking-only. It does not overwrite calibrated q and is not presented as a calibrated probability.

### Spread trust

```text
balanced_dual_trust = Spread Confidence V3 q
```

### Ranking

1. Balanced dual trust descending;
2. raw calibrated model q descending;
3. reliability/support descending;
4. American odds descending;
5. candidate ID.

### Fixed comparators

With identical eligibility/coverage, report:

- `RAW_Q`;
- `T050_AGREEMENT_ONLY`;
- `MARKET_HALF_ONLY`;
- `DUAL_TRUST` primary.

No additional coefficient, threshold, cap, or sensitivity grid is allowed.

Report model-rank-1 and Pinnacle-rank-1 overlap, selected disagreement, q-minus-Pinnacle, confidence buckets, price distribution, hit rate, and ROI as secondary evidence.

## 4. Value — FRONTIER_STATE_V3 candidate

Value remains a distinct strict-+EV protocol. It may return PASS.

### 4.1 Frozen candidate-family universe

Only these Task05E model regions are allowed:

ML:

- `ML_DOG_VALUE_ZONE_AVG`
- `ML_DOG_VALUE_ZONE_CORROB`
- `ML_AVG_DISAGREEMENT_AVG_0_2`

Spread:

- `SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4`

Totals remain prohibited.

Every Value frontier candidate must also satisfy:

- Task05F supported;
- model confidence supported, support N >= 256;
- best exact DK/FD offer;
- exact Task05F expected value > 0;
- Task05F price status `VALUE`;
- price between -180 and +250 inclusive.

### 4.2 ML frontier

ML must additionally have:

```text
model_price_gap = q - break_even_probability > 0
```

This prevents market/evaluator-only positive EV from creating an ML Value candidate when the football model itself does not support value.

Within each block, choose the single ML frontier candidate by:

1. model-price gap descending;
2. raw calibrated model q descending;
3. Task05F evaluated edge descending;
4. reliability descending;
5. American odds descending;
6. candidate ID.

### 4.3 Spread frontier

Spread does **not** require V3 q-minus-break-even > 0. Spread Confidence V3 is a calibrated cover-confidence/support layer and correctly sits near 50%; the frozen Task05E Expected Margin 0-4 region provides the football-model directional/value provenance.

Spread must have a finite positive `model_cover_margin_v3` within the frozen Task05E candidate region.

Within each block, choose the single spread frontier candidate by:

1. raw `model_cover_margin_v3` descending;
2. Task05F evaluated edge descending;
3. reliability descending;
4. American odds descending;
5. candidate ID.

This keeps the Expected Margin football signal first inside its already-validated 0-4 support region rather than ranking spread Value by V3 q-minus-price or unrestricted estimated EV.

### 4.4 Cross-market frontier comparison

At most one ML frontier and one spread frontier may reach this step.

Define exact probability-edge scores:

```text
ml_dynamic_edge = min(ml_model_price_gap * ml_frontier_trust,
                      ml_evaluated_edge_probability)

spread_dynamic_edge = spread_evaluated_edge_probability
```

In GREEN state, select the finalist with the larger dynamic edge; deterministic tie-break uses reliability, American odds, candidate ID.

This is **not** an unrestricted whole-board max-EV search: each market is reduced to one model-first frontier candidate before the cross-market economic comparison.

### 4.5 Frozen causal ML frontier trust

Reuse the exact prior frontier-trust constants:

```text
season_reset_trust = 0.50
pseudo_count = 8
```

For each season, trust observations use only the counterfactual **top ML frontier candidate** from each prior settled block, whether or not it became the final Value headline.

For one observation:

```text
predicted_edge = ml_q - ml_break_even
realized_edge  = outcome_binary - ml_break_even
```

Aggregate:

```text
predicted_edge_sum = sum(predicted_edge)
realized_edge_sum  = sum(realized_edge)
data_trust = clip(realized_edge_sum / predicted_edge_sum, 0, 1)
trust = (8 * 0.50 + n * data_trust) / (8 + n)
```

No broad-pool ML opportunities may enter the trust stream.

### 4.6 Frozen GREEN / AMBER / RED states

Reuse the previously preregistered state constants exactly:

- `GREEN`: fewer than 3 prior frontier observations OR trust >= 0.50;
- `AMBER`: at least 3 observations and trust < 0.50, unless RED;
- `RED`: at least 8 observations and trust < 0.25.

Selection behavior:

- `GREEN`: normal cross-market frontier comparison using the dynamic-edge scores above;
- `AMBER`: if a valid spread frontier exists, it has priority; otherwise ML remains eligible;
- `RED`: ML is barred; select valid spread frontier if present, otherwise PASS.

No state threshold or pseudo-count may change after replay.

### 4.7 Fixed Value comparators

Report:

1. `STATIC_FRONTIER`: same ML/spread frontiers, trust fixed at 1.0, normal cross-market comparison;
2. `FRONTIER_SHRINK`: causal frontier trust in ranking, no AMBER/RED overrides;
3. `FRONTIER_STATE_V3`: primary GREEN/AMBER/RED candidate.

Report by season and 2020-22 / 2023-24 / overall:

- plays / coverage;
- market mix;
- hit rate;
- ROI;
- max losing streak;
- state counts;
- first AMBER / RED timing;
- ML-to-spread displacements;
- RED no-play blocks;
- ML frontier trust trajectory;
- Value no-play reasons.

Coverage has no minimum success target for Value.

## 5. Confidence sanity and protocol separation

The replay must prove:

- HHR/Balanced eligibility does not read EV or price status;
- Balanced DUAL_TRUST does not overwrite q;
- HHR/Balanced primary coverage exactly equals their fixed comparator coverage;
- no totals headline;
- Value requires strict EV > 0 and price status `VALUE`;
- Value candidates all have frozen Task05E provenance;
- ML Value cannot enter when model-price gap <= 0;
- spread Value cannot enter outside the Expected Margin 0-4 frozen region;
- 2025 appears nowhere.

Selected HHR/Balanced rows report raw q separately from ranking trust, including q >=80% tail diagnostics. A high raw q is not automatically invalid; the question is whether the appropriate lane trust prevents unsupported extremity from winning solely because it is the maximum number.

## 6. Interpretation rules

Because all 2020-2024 outcomes are exposed:

- no numeric success threshold will be invented for this replay;
- no post-result coefficient or state threshold may be changed;
- no new candidate family may be added;
- no 2025 data may be inspected.

The final decision is architectural/coherence based: distinct lane objectives, model agency, confidence sanity, coverage, cross-period direction, and absence of known anti-selection mechanisms.

If coherent, the next step is to implement/freeze the exact production selector code/config/tests plus unit/risk-profile/output contracts, then open 2025 once for untouched acceptance.
