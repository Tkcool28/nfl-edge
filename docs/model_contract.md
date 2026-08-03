# Model Contract

## Purpose

Define the Version 1 model components, their boundaries, artifacts, and approval requirements.

## Common requirements

Every model must:

- Consume only approved point-in-time features.
- Emit a home-team win probability in `(0, 1)`.
- Record training cutoff, data version, feature version, configuration, and code commit.
- Be deterministic given the same inputs and random seed.
- Produce predictions for every eligible game or an explicit reason for abstention.
- Be evaluated independently before stacking.

## Base Model A — QB-adjusted Elo

Responsibilities:

- Sequential team-strength state
- Explicit starting-QB component
- Conservative QB initialization and shrinkage
- Neutral-site handling
- Dynamic home-field estimate from prior data only
- Postgame updates only after completion

Required tests:

- Probability symmetry
- Neutral-site behavior
- No update before game completion
- State replay determinism
- QB change sensitivity
- Rookie/backup prior behavior
- Season transition behavior

The initial implementation must not copy undocumented constants from the superseded prototype without evidence.

## Base Model B — regularized XGBoost

Responsibilities:

- Learn nonlinear relationships in the approved feature matrix
- Use shallow trees and strong regularization
- Tune only inside the development period
- Use early stopping without exposing future or holdout outcomes

Configuration must define bounded candidate ranges for:

- `max_depth`
- `learning_rate`
- `n_estimators`
- `min_child_weight`
- `subsample`
- `colsample_bytree`
- `reg_alpha`
- `reg_lambda`

The search should remain intentionally small. Exhaustive tuning is not a project goal.

## Base Model C — opponent-adjusted expected margin

Responsibilities:

- Estimate team offensive and defensive scoring strength while accounting for opponent quality
- Estimate expected home and away scoring or direct expected margin
- Use prior games only
- Convert expected margin to win probability through a mapping learned in the development window
- Regularize early-season and low-sample estimates

Required tests:

- Schedule-strength sensitivity
- Symmetry under home/away reversal except for HFA
- Future-opponent-result isolation
- Early-season shrinkage
- Expected-margin-to-probability monotonicity

## Meta-model — regularized logistic stacker

Inputs are limited to out-of-sample base-model probabilities and explicitly approved static metadata if later authorized.

Initial inputs:

```text
p_qb_elo
p_xgboost
p_opponent_adjusted_margin
```

Rules:

- Never train on in-sample base-model predictions.
- Begin with a simple regularized logistic regression.
- Do not claim probability-region-specific weighting unless nonlinear terms are explicitly implemented and validated.
- Store coefficients and preprocessing metadata.
- Remove a base model when evidence shows it contributes no value and harms generalization.

## Calibration

Separate calibration is optional, not automatic.

It may be added only when development walk-forward evidence shows a repeatable improvement and the calibration fit uses independent predictions.

Small-sample-safe sigmoid calibration is preferred before isotonic methods.

## Artifact package

Every approved artifact package must contain:

```text
model_version
model_type
created_at_utc
training_cutoff_utc
development_period
holdout_period
data_version
feature_version
configuration_sha256
code_commit_sha
random_seed
base_model_versions
stacker_version
calibration_version
metrics_summary
artifact_files
artifact_sha256
```

## Approval rules

A model may be labeled:

- `development_only`
- `holdout_evaluated`
- `approved_for_forward_scoring`
- `retired`

Only `approved_for_forward_scoring` artifacts may be loaded by the scheduled scoring workflow.

Approval requires complete acceptance-gate evidence. A failed stack does not prevent approval of a stronger simpler base model.

## Prohibited behavior

- Market prices or closing lines in model inputs
- Fitting base models and stacker on the same in-sample predictions
- Tuning to the untouched holdout
- Selecting a random seed because it produces the best result
- Hiding weak base-model scorecards
- Loading an unversioned local model file in production
- Replacing an approved artifact without a new version and checksum
