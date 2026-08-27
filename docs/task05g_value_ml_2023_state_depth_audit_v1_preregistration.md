# Task05G Value ML 2023 State-Depth Audit V1 — Preregistration

Status: **FROZEN BEFORE NEW ML STATE/DEPTH OUTPUT / 2025 SEALED**

This is a retrospective forensic audit only. It follows the leading spread-Value candidate in PR #47 and asks whether the residual 2023 Value failure is caused by ML headline behavior, especially early-season cold start and/or forcing a lone ML frontier when no spread alternative exists.

All 2020-2024 outcomes are exposed development evidence. This audit does not authorize production policy. 2025 remains sealed.

## 1. Frozen upstream and user-facing baseline

Freeze all existing components:

- football models unchanged;
- Task05F evaluator unchanged;
- Model Confidence V2 unchanged;
- Spread Confidence V3 unchanged;
- strict Value candidate families and exact-offer requirements unchanged;
- ML frontier ranking unchanged;
- Pareto spread frontier from PR #45 unchanged;
- non-GREEN singleton spread fail-safe from PR #47 unchanged;
- no totals;
- no staking/risk/profile changes.

The PR #47 spread fail-safe never changes an ML-selected Value card, so the ML headlines selected by the Pareto Value baseline and the PR #47 user-facing card are identical.

## 2. Existing causal ML trust — unchanged

Reproduce the existing ML frontier trust exactly:

- season reset trust = 0.50;
- pseudo-count = 8;
- observation stream = top strict ML frontier from prior settled blocks, whether or not it became the final Value headline;
- predicted edge = ML calibrated model confidence q minus exact break-even probability;
- realized edge = binary outcome minus exact break-even probability;
- data trust = clip(realized_edge_sum / predicted_edge_sum, 0, 1);
- trust = `(8 * 0.50 + n * data_trust) / (8 + n)`;
- AMBER = n >= 3 and trust < 0.50 unless RED;
- RED = n >= 8 and trust < 0.25;
- otherwise existing state label = GREEN.

No constant may be changed.

## 3. Descriptive COLD label — reporting only

The current state machine labels all n < 3 observations as GREEN because AMBER cannot activate before three observations.

For forensic reporting only, split existing GREEN into:

- `COLD`: n < 3;
- `MATURE_GREEN`: n >= 3 and the existing state is GREEN.

AMBER and RED retain their exact existing definitions.

`COLD` is **not a new threshold or policy gate**. It is simply the complement implied by the already-frozen `AMBER_MIN_N = 3`, used to distinguish "healthy" from "insufficient same-season evidence."

## 4. Exact ML candidate depth

For every block, count the exact strict ML Value candidates *after exact shopping* using the existing final Value ML contract:

- Task05F supported;
- model-confidence supported with N >= 256;
- DraftKings/FanDuel exact shopped offer;
- Task05F `price_status == VALUE`;
- Task05F expected value > 0;
- odds inside the frozen Value band;
- frozen ML Task05E provenance region;
- positive football-model `model_price_gap`;
- positive evaluated edge.

Report:

- `singleton`: exactly 1 strict ML candidate;
- `competitive`: 2+ strict ML candidates;
- zero candidates separately.

Do not remove or preference a candidate based on depth.

## 5. Required 2023 headline trace

For every 2023 user-facing ML Value headline, report at prediction time:

- week/block;
- candidate ID / game / selected side;
- odds;
- settlement / flat 1u result;
- pre-block existing ML state;
- descriptive evidence status (`COLD`, `MATURE_GREEN`, `AMBER`, `RED`);
- prior ML frontier observation count n;
- causal ML trust value;
- ML strict-candidate depth;
- model confidence q;
- exact break-even probability;
- football-model price gap;
- Task05F evaluated edge;
- exact expected value;
- reliability;
- whether a valid Pareto spread frontier existed in the same block;
- spread candidate depth and spread candidate ID if present;
- whether ML was the only strict Value family available.

The audit must identify exactly why the existing Value state machine selected the ML headline (only family, GREEN-vs-AMBER family priority, or normal cross-market comparison).

## 6. Cross-season guard

The audit must not diagnose 2023 in isolation. Report the same ML headline evidence cells across 2020-2024 for final selected ML Value headlines and separately for the full ML frontier stream.

Required cells:

- COLD singleton;
- COLD competitive;
- MATURE_GREEN singleton;
- MATURE_GREEN competitive;
- AMBER singleton;
- AMBER competitive;
- RED singleton;
- RED competitive.

For each cell report:

- plays/frontiers;
- W/L/P;
- non-push hit rate;
- flat 1u ROI / cumulative units;
- seasons represented;
- average odds;
- average q;
- average model-price gap;
- average evaluated edge;
- average exact expected value.

For final ML headlines also split by:

- valid spread alternative present;
- no valid spread alternative.

## 7. Early-season causal trace

Because the 2023 ML losses may occur before AMBER can legally activate, report the exact prior-observation trajectory for the first three ML frontier observations of every season.

This is descriptive only. Do **not** retune `AMBER_MIN_N`, reset trust, pseudo-count, or RED thresholds from these results.

## 8. Interpretation rules frozen before output

This audit may support one of several mechanisms, but no policy is automatically promoted:

1. **Cold-start forcing:** early n<3 ML headlines are materially less trustworthy, especially when ML is the only family available.
2. **Degraded-state forcing:** AMBER/RED ML remains dangerous when no spread alternative exists.
3. **Candidate-depth effect:** singleton ML frontiers are materially less trustworthy under weak/cold evidence.
4. **No coherent state/depth mechanism:** the four 2023 losses are not distinguishable ex ante using the existing causal evidence.

The audit explicitly does **not** authorize:

- changing trust constants;
- globally banning singleton ML;
- globally banning early-season ML;
- choosing rank 2 retrospectively;
- adding a new model or feature;
- changing the Pareto spread rule;
- changing HHR or Balanced;
- opening 2025.

If a coherent mechanism exists, any selector fail-safe must be separately preregistered before replay.
