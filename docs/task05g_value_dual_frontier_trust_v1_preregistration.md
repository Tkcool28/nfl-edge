# Task05G Value Dual Frontier Trust V1 — Preregistration

Status: **FROZEN BEFORE REPLAY / 2025 SEALED**

This is the bounded follow-up to `reports/task05g/value_spread_frontier_rank_audit_v1_review.md`.

The prior audit established that the frozen Expected-Margin spread strict-Value population remains broadly viable, but the current weekly spread frontier can suffer severe rank-1 anti-selection when raw Expected-Margin extremity loses ordering value. This test does **not** switch to rank 2, remove a disagreement bucket, or tune a new spread-ranking coefficient.

All 2020-2024 outcomes are exposed retrospective evidence. 2025 remains sealed.

## 1. Fixed candidate universes

### ML Value

Keep the existing frozen ML Value universe and ML frontier semantics from Final Selector Candidate V1:

- frozen Task05E ML regions only;
- Task05F supported;
- model confidence supported, support N >= 256;
- exact shopped DK/FD offer;
- `VALUE` status;
- exact expected value > 0;
- price -180 to +250;
- positive ML model-price gap;
- one counterfactual top ML frontier per block using the existing model-first ML frontier ordering.

### Spread Value

Keep the exact frozen spread Value universe and current counterfactual spread frontier:

- `SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4` only;
- Task05F supported;
- Spread Confidence V3 supported, support N >= 256;
- exact shopped DK/FD offer;
- `VALUE` status;
- exact expected value > 0;
- price -180 to +250;
- positive `model_cover_margin_v3`;
- one counterfactual top spread frontier per block using the current raw-cover-margin-first ordering.

The raw-margin ordering is intentionally retained **for this trust test only** so that the experiment isolates whether causal family trust can protect the product from a failing frontier without retrospectively choosing a lower rank.

No totals.

## 2. Independent causal trust streams

ML and spread maintain completely separate same-season trust streams.

Each stream is updated only from its own counterfactual top frontier candidate from prior settled blocks, regardless of which market became the final Value headline.

### ML observation

Keep the existing frontier observation:

```text
predicted_edge = ml_model_q - ml_break_even
realized_edge  = outcome_binary - ml_break_even
```

Observation is admitted only when `predicted_edge > 0` and settlement is WIN/LOSS.

### Spread observation

For the counterfactual top spread frontier candidate:

```text
predicted_edge = Task05F evaluated_edge_probability
realized_edge  = outcome_binary - break_even_probability
```

Rationale: Spread Confidence V3 is a support/calibration layer near 50% and is not itself a price-edge estimate at ordinary -110 prices. The exact Task05F evaluated edge is the already-frozen positive edge claim that makes the candidate a strict Value offer, while Expected-Margin provenance remains mandatory football-model evidence.

Spread observation is admitted only when `predicted_edge > 0` and settlement is WIN/LOSS.

No realized result from another candidate in the block enters either trust stream.

## 3. Frozen trust calculation

Reuse the already-preregistered ML frontier-trust constants exactly for **both** families:

```text
season_reset_trust = 0.50
pseudo_count = 8
```

For a family's prior observations:

```text
predicted_edge_sum = sum(predicted_edge)
realized_edge_sum  = sum(realized_edge)
data_trust = clip(realized_edge_sum / predicted_edge_sum, 0, 1)
trust = (8 * 0.50 + n * data_trust) / (8 + n)
```

No new coefficient or pseudo-count is allowed.

## 4. Frozen GREEN / AMBER / RED definitions

Reuse the previously preregistered constants for each family independently:

- `GREEN`: fewer than 3 prior frontier observations OR trust >= 0.50;
- `AMBER`: at least 3 observations and trust < 0.50, unless RED;
- `RED`: at least 8 observations and trust < 0.25.

No threshold grid or post-result adjustment.

## 5. Primary selector — DUAL_FRONTIER_TRUST_V1

At each block, construct at most one ML frontier candidate and one spread frontier candidate.

### Family dynamic edge

```text
ml_dynamic_edge = min(ml_model_price_gap * ml_trust,
                      ml_evaluated_edge_probability)

spread_dynamic_edge = spread_evaluated_edge_probability * spread_trust
```

These scores are selector ranking scores, not reported calibrated probabilities.

### Family state behavior

1. `RED` family: barred from the Value headline.
2. `GREEN` vs `AMBER`: GREEN family has priority when both valid frontiers exist.
3. same-state GREEN/GREEN or AMBER/AMBER: choose the larger family dynamic edge.
4. only one non-RED valid family: it may play even if AMBER.
5. both families RED, or no non-RED valid frontier: `PASS`.

Deterministic tie-break after dynamic edge:

1. reliability;
2. American odds;
3. candidate ID.

This prevents the previous one-way failure mode where ML distrust automatically handed Value to spread without asking whether spread itself had earned trust.

## 6. Fixed comparators

Report all three using the exact same candidate universes/frontiers:

### `CURRENT_ML_ONLY_STATE`

Reproduce Final Selector Candidate V1 Value behavior as closely as possible:

- ML causal trust/state active;
- spread has no causal trust stream;
- AMBER ML gives spread priority when spread exists;
- RED ML bars ML.

### `DUAL_SHRINK_ONLY`

- both independent trust streams active continuously in dynamic-edge ranking;
- no GREEN priority and no AMBER/RED state overrides except RED bar;
- larger trusted dynamic edge wins among non-RED families.

### `DUAL_FRONTIER_TRUST_V1` — primary

Use the independent state behavior in Section 5.

No other variants.

## 7. Required reporting

Report for 2020-2022, 2023-2024, overall, and each season:

- plays / coverage;
- hit rate;
- flat 1u ROI;
- market mix;
- max losing streak;
- ML and spread trust trajectories separately;
- ML and spread state counts separately;
- first AMBER and RED for each family;
- cross-market displacements caused by family state;
- PASS blocks caused by RED/no trusted frontier;
- counterfactual ML frontier performance;
- counterfactual spread frontier performance;
- 2023 week-by-week final headline and both family states/trust values.

Coverage is descriptive only. Value may legitimately become sparser.

## 8. Interpretation guardrails

This experiment answers only whether **independent causal family trust** materially protects the Value card from a failing ML or spread frontier while preserving strong seasons.

It does not authorize:

- choosing rank 2 or rank 3;
- changing raw spread frontier ordering;
- deleting a frozen Task05E bucket;
- changing Task05F evaluator semantics;
- changing ML calibration or Spread V3;
- changing trust thresholds/pseudo-count;
- adding totals;
- opening 2025.

If the trust mechanism still fails catastrophically in 2023, the next step must return to the within-spread frontier ranking problem with a separately preregistered corroborated ranking score. Do not tune this trust mechanism on exposed outcomes.
