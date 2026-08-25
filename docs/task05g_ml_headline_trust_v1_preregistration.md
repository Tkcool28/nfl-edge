# Task05G ML Headline Trust V1 — Preregistration

Status: FROZEN BEFORE EXPERIMENT OUTPUT

Purpose: test whether the Task05G HHR/Balanced moneyline anti-selection identified by the ML confidence-tail audit is caused by maximizing an otherwise broadly calibrated ensemble probability when QB-Elo and XGBoost materially disagree.

This experiment is diagnostic only. It does not authorize production promotion. 2025 remains sealed.

## 1. Frozen upstream state

Base branch: `audit/task05g-ml-confidence-tail-v1`.

The following are frozen and must not be modified by this experiment:

- football model predictions and features;
- Task05F evaluator semantics and historical board;
- Model Confidence V2 Platt calibration;
- Spread Confidence V3 calibration;
- HHR/Balanced eligibility thresholds and odds bounds;
- exact-offer shopping semantics;
- Value selector/policy;
- units, risk profiles, bankroll conversion, and Play Through policy;
- all historical source/model data.

Allowed experiment seasons are 2020-2024 only. Season 2025 must not be loaded into the experiment candidate population, outputs, metrics, or selection decisions.

## 2. Motivation fixed before output

The prior audit found that broad high-confidence ML buckets are not globally broken, while development rank-1 headlines selected by maximum ML confidence underperformed rank-2 candidates and carried materially larger QB-Elo/XGBoost disagreement.

The experiment therefore changes ranking trust only. It does not recalibrate `model_confidence_probability` and does not reinterpret the trust score as a calibrated probability.

## 3. Primary trust rule

For each exact-shopped supported moneyline candidate:

```text
disagreement = abs(raw_qbelo_probability_selected - raw_xgb_probability_selected)
headline_trust_score = model_confidence_probability - 0.50 * disagreement
```

For spread candidates:

```text
headline_trust_score = model_confidence_probability
```

The coefficient `0.50` is fixed a priori. Half the constituent disagreement is the distance from the two-model arithmetic mean to the more conservative constituent model. It is not selected from realized outcomes.

The trust score is a ranking score only. It must not overwrite or relabel `model_confidence_probability`.

## 4. Frozen selector change

Eligibility is unchanged from the validated Spread Confidence V3 stack.

### HHR V1 trust ranking

Among already-eligible exact-shopped candidates in a block, rank by:

1. descending `headline_trust_score`;
2. descending reliability rank;
3. descending `model_price_gap`;
4. descending American odds using the existing deterministic convention;
5. existing candidate-id tie break.

### Balanced B0 V1 trust ranking

Use the already-frozen B0 tolerance and unchanged eligibility. Rank by:

1. descending `headline_trust_score`;
2. descending `model_price_gap`;
3. descending reliability rank;
4. descending American odds using the existing deterministic convention;
5. existing candidate-id tie break.

No additional confidence floor, disagreement cutoff, fail-close rule, or minimum trust score is allowed in the primary experiment.

Because eligibility is unchanged, primary HHR and Balanced block coverage is required to be exactly equal to the corresponding V3 baseline coverage. Any coverage difference is an implementation failure.

## 5. Primary comparisons

The experiment must compare V3 baseline versus the fixed 0.50 disagreement-penalty trust ranking for:

- HHR, 2020-2022 development;
- Balanced B0, 2020-2022 development;
- HHR, 2023-2024 locked diagnostic;
- Balanced B0, 2023-2024 locked diagnostic.

Report for each lane/period:

- plays and play-block coverage;
- wins/losses/pushes;
- non-push hit rate;
- ROI;
- average sportsbook odds;
- average calibrated ML confidence of selected moneylines;
- average `headline_trust_score`;
- average QB-Elo/XGBoost disagreement for selected moneylines;
- selected market mix;
- number and percentage of blocks whose headline changes versus V3;
- when both old/new selections settle non-push, paired outcome counts (new-only win, old-only win, both win, both lose).

## 6. Frozen interpretation gates

No production promotion is allowed regardless of result because all 2020-2024 outcomes have already been exposed in prior Task05G work.

The primary diagnostic verdict is determined without choosing a new parameter after output:

### `PRIMARY_TRUST_CORRECTION_DIRECTIONALLY_SUCCESSFUL`

All of the following must hold in 2020-2022 development:

- HHR coverage equals baseline exactly;
- Balanced B0 coverage equals baseline exactly;
- HHR non-push hit rate improves by at least 5 percentage points versus V3 baseline;
- Balanced B0 non-push hit rate improves by at least 5 percentage points versus V3 baseline;
- neither HHR nor Balanced B0 ROI is lower than its V3 baseline ROI.

The locked 2023-2024 diagnostic is reported separately and cannot change the development verdict. A stronger robustness note may be added only if both lanes also avoid a hit-rate decline greater than 2 percentage points versus their V3 baselines.

### `PRIMARY_TRUST_CORRECTION_MIXED`

Coverage invariants pass, but the full development success gate does not.

### `PRIMARY_TRUST_CORRECTION_INVALID`

Any frozen-scope, chronology, deterministic-replay, eligibility, or coverage-parity invariant fails.

## 7. Sensitivity analysis frozen before output

Two secondary ranking-only sensitivity scores are permitted:

```text
T025 = q - 0.25 * disagreement
T100 = q - 1.00 * disagreement
```

They must use the identical unchanged eligibility and tie-break structure.

These sensitivities are descriptive only. They may not replace the primary `0.50` rule, may not be called a winner, and may not determine any production threshold or penalty coefficient.

No other coefficient may be added after outcomes are exposed.

## 8. Required controls and invariants

The implementation/workflow must enforce:

- experiment-only changed-file allowlist;
- 2025 exclusion from all candidate and result artifacts;
- focused upstream Task05F/Task05G tests pass;
- V2 candidate table reproduces from the frozen board;
- Spread Confidence V3 reproduces before trust scoring;
- trust scoring does not change `model_confidence_probability`;
- primary and sensitivity rules do not change eligibility;
- primary HHR/Balanced coverage exactly matches V3 baseline;
- deterministic replay produces byte-identical primary JSON/row outputs;
- Value outputs are not changed or evaluated as a headline-trust experiment target.

## 9. Required artifacts

The experiment must emit at minimum:

- `ml_headline_trust_v1_scorecard.json`;
- `ml_headline_trust_v1_rows.parquet` containing baseline/primary selection identities and trust diagnostics;
- a permanent review markdown only after the validated workflow result exists.

## 10. Follow-up boundaries

A fail-close disagreement threshold, a new minimum trust score, coefficient tuning, dynamic trust state, or production selector change requires a separate preregistration. None may be inferred or adopted from this experiment after viewing results.
