# Task05G Final Selector Bounded Audit — Preregistration

This audit is subordinate to `docs/task05g_final_selector_architecture.md`.

Architecture commit preceding this preregistration:

`0aec344d800d7c7ab3d9f76b1ff31975ddfd54cc`

2025 remains sealed. 2020-2024 outcomes are development evidence and are already exposed; this audit is for final design freeze, not a new untouched confirmation claim.

## Scope

Only three questions may be answered:

1. Why do architecture-correct HHR/Balanced protocols miss weeks?
2. Does the already-preregistered 0.50 QB-Elo/XGBoost agreement correction remain useful when Balanced is finally separated from Value economics?
3. Which already-frozen Task05E Value families remain credible enough for the V1 Value allowlist?

No football model, Task05F evaluator, Spread Confidence V3 mapping, ML confidence calibration, historical data, staking policy, or 2025 data may change.

## Shared candidate preparation

Reproduce in order:

1. frozen Task05F historical evaluator board;
2. Model Confidence V2 candidate table;
3. Spread Confidence V3 candidate table;
4. exact DK/FD shopping using existing semantics.

Allowed headline markets in this audit:

- moneyline
- spread

Totals remain excluded.

## HHR protocol under audit

Eligibility:

- Task05F `supported == True`;
- model confidence supported with support N >= 256;
- ML or spread;
- model confidence >= 0.55;
- exact best DK/FD price between -300 and +200 inclusive.

Price status (`VALUE`, `PLAYABLE`, `LEAN`, `PASS`) and expected value are **not eligibility fields**. `UNSUPPORTED` enters through `supported == False` and therefore fails closed.

ML ranking trust:

```text
hhr_trust = q - 0.50 * max(q - pinnacle_no_vig, 0)
```

Spread ranking trust:

```text
hhr_trust = Spread Confidence V3 q
```

Ranking:

1. HHR trust descending
2. raw model confidence descending
3. Task05F reliability tier descending only as support metadata
4. actionable American odds descending
5. candidate ID

EV/status may not rank HHR.

## Balanced protocol under audit

Eligibility:

- Task05F `supported == True`;
- model confidence supported with support N >= 256;
- ML or spread;
- model confidence >= 0.52;
- exact best DK/FD price between -220 and +200 inclusive.

Explicit removals from earlier experiments:

- no `VALUE` requirement;
- no `PLAYABLE` requirement;
- no EV floor;
- no positive model-price-gap requirement.

Primary Balanced ML trust uses the **already-preregistered PR #38 T050 rule** and no alternative coefficient is allowed:

```text
balanced_trust = q - 0.50 * abs(qbelo_selected - xgb_selected)
```

This score is ranking-only and does not replace calibrated model confidence.

Spread Balanced trust:

```text
balanced_trust = Spread Confidence V3 q
```

Ranking:

1. Balanced trust descending
2. raw model confidence descending
3. Task05F reliability tier descending only as support metadata
4. actionable American odds descending
5. candidate ID

EV/status may not rank Balanced.

Comparator:

- `RAW_Q`: identical eligibility, raw model-confidence ranking first.

No T025/T100 or other coefficient sensitivity is allowed in this audit.

## Coverage audit

For HHR and Balanced, each no-play block must receive the earliest applicable deterministic reason:

1. `NO_SUPPORTED_MODEL_CONFIDENCE`
2. `NO_CANDIDATE_ABOVE_CONFIDENCE_FLOOR`
3. `PRICE_OUTSIDE_PRODUCT_BAND`
4. `NO_TRUST_COMPUTABLE_CANDIDATE`
5. `NO_CANDIDATE_AFTER_SHOPPING`

Report by:

- 2020-2022
- 2023-2024
- 2020-2024 overall

Coverage is descriptive. No threshold may be altered from the output.

## Balanced acceptance interpretation

Report:

- coverage versus RAW_Q (must be exact parity because ranking alone changes);
- hit-rate delta;
- ROI delta as secondary evidence;
- changed blocks;
- selected average q;
- selected average QB-Elo/XGBoost disagreement;
- model-rank-1 overlap;
- Pinnacle-rank-1 overlap for ML diagnostic only;
- selected confidence buckets.

The audit does not contain a post-result success threshold. The final architecture decision must weigh direction, stability, model agency, and coverage together; it may not tune the 0.50 coefficient.

## HHR reporting

Report the architecture HHR versus the frozen V3/raw-q HHR baseline with identical eligibility where possible:

- coverage;
- hit rate;
- ROI secondary;
- changed blocks;
- model-rank-1 overlap;
- Pinnacle-rank-1 overlap;
- selected q and model-minus-Pinnacle diagnostics.

The HHR HALF_SHRINK coefficient may not be retuned.

## Value family audit

Build the already-frozen Task05E provenance registry from:

- `ML_DOG_VALUE_ZONE_AVG`
- `ML_DOG_VALUE_ZONE_CORROB`
- `ML_AVG_DISAGREEMENT_AVG_0_2`
- `SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4`

A strict-Value row must have:

- frozen provenance membership;
- Task05F supported;
- model confidence supported;
- exact best DK/FD offer;
- exact expected value > 0;
- price status `VALUE`;
- price between -180 and +250 inclusive.

Report each region separately for 2020-2022, 2023-2024, and overall:

- plays;
- hit rate;
- flat 1u ROI;
- average exact EV;
- average model confidence;
- average model-price gap;
- average evaluator edge.

Also report the following fixed structural allowlist scenarios, without searching combinations:

1. `SPREAD_ONLY`
2. `ALL_ML_FROZEN_REGIONS`
3. `ALL_FROZEN_REGIONS`

For each block/scenario, rank legitimate strict-Value survivors by:

1. `consensus_edge = min(model_price_gap, evaluated_edge_probability)` descending;
2. model confidence descending;
3. reliability descending;
4. American odds descending;
5. candidate ID.

Do not rank unrestricted maximum EV.

This audit does not automatically select the V1 allowlist; it supplies the bounded evidence needed to freeze it.

## Confidence sanity

For selected HHR/Balanced rows, report probability buckets:

- 52-60%
- 60-70%
- 70-80%
- >=80%

Each bucket reports average predicted model confidence and realized non-push hit rate. This is diagnostic for crazy selected confidence; it does not create new thresholds.

## Determinism / firewall

The audit must run twice byte-identically.

Hard fail if:

- 2025 appears in any input/output season;
- totals appear in HHR/Balanced/Value headline selections;
- HHR/Balanced eligibility reads expected value or price status;
- Balanced coefficient differs from 0.50;
- HHR corroboration coefficient differs from 0.50.

No production promotion is authorized from this audit alone. The output feeds the final selector implementation and then the one integrated 2020-24 simulation before 2025 is opened.
