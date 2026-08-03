# Backtest Contract

## Purpose

Ensure historical performance is generated in the same temporal direction as live use and cannot benefit from future information.

## Development and holdout periods

The initial intended design is:

- Development: historical seasons before 2025, subject to the final data audit
- Untouched holdout: 2025
- Forward use: 2026

The exact first development season is selected after coverage and quality are measured. The holdout may change only before implementation and with a documented data reason.

## Expanding weekly walk-forward

For every prediction week:

1. Set a deterministic `as_of_utc`.
2. Build features using only records available by that time.
3. Fit or update each base model using only prior eligible rows.
4. Predict the entire current week.
5. Persist predictions before revealing outcomes to the next step.
6. Advance chronologically.

Random train/test splitting and ordinary shuffled cross-validation are prohibited.

## Stacker dataset

The stacker training table consists only of persisted out-of-sample base-model predictions from the development walk-forward.

Required columns:

```text
game_id
as_of_utc
season
week
actual_home_win
p_qb_elo
p_xgboost
p_opponent_adjusted_margin
base_model_version_ids
```

## Hyperparameter selection

- Search space is fixed before scoring a candidate window.
- Selection uses development-period walk-forward results only.
- The holdout is not used for early stopping, feature choice, threshold choice, or calibration choice.
- All attempted configurations and results are retained in a compact tuning ledger.
- Search effort remains bounded to avoid mining noise.

## Holdout procedure

1. Freeze data, feature, model, and backtest versions.
2. Record the code commit and configuration checksums.
3. Generate holdout predictions sequentially.
4. Persist the prediction ledger.
5. Compute the complete scorecard once.
6. Publish the result before any holdout-informed change.
7. Mark any later analysis as post-holdout research.

## Metrics

Primary:

```text
Brier Skill Score vs QB-adjusted Elo
```

Supporting:

- Brier score for each model
- Log loss for each model
- Calibration intercept and slope
- Reliability table/diagram
- Accuracy, descriptive only
- Weekly and seasonal results
- Favorite/underdog buckets
- Probability buckets
- QB-certainty buckets
- Missingness/coverage counts
- Block-bootstrap confidence interval for the primary comparison

## Brier Skill Score

```text
BSS = 1 - (candidate_brier / qb_elo_brier)
```

Interpretation:

- `BSS > 0`: candidate improves on QB-Elo
- `BSS = 0`: no improvement
- `BSS < 0`: candidate is worse

## Approval assessment

### `MODEL_VALIDATED`

Positive holdout Brier Skill Score with supporting metrics that do not reveal a serious calibration or overconfidence failure, and evidence not dominated by a tiny cluster of weeks.

### `MODEL_PROMISING_BUT_UNPROVEN`

Point estimate is positive but uncertainty is broad, improvement is small, or evidence is not yet stable.

### `MODEL_FAILED_BASELINE`

The stack fails to improve on QB-Elo or creates materially worse probability quality.

A simpler base model may still be approved if its own evidence is acceptable.

## Required reports

- Data coverage report
- Leakage test report
- Base-model development scorecards
- Stacker development scorecard
- Tuning ledger
- Holdout prediction ledger
- Holdout scorecard
- Calibration table
- Uncertainty report
- Final go/no-go memorandum

## Reproducibility

A backtest run receives a unique ID derived from or linked to:

```text
code_commit_sha
data_version
feature_version
model_config_sha256
backtest_config_sha256
random_seed
run_started_at_utc
```

The same declared inputs must reproduce the same prediction ledger within documented numerical tolerance.

## Prohibited behavior

- Using final-season aggregates to create earlier features
- Using holdout outcomes for tuning or feature selection
- Dropping losing predictions after generation
- Reporting only favorable probability buckets
- Changing thresholds after seeing holdout results without labeling the result post-hoc
- Treating ROI without timestamped historical prices as a model-validation metric
- Claiming validation from accuracy alone
