# XGBoost V1 Scorecard — Selected Candidate: conservative

*Generated*: 2026-08-07T20:22:16.689653+00:00
*Status*: `XGBOOST_V1_CONSERVATIVE_SELECTED_AND_FROZEN`

## Identity

| Field | Value |
|---|---|
| Model | XGBoost V1 |
| Selected candidate | conservative |
| Development seasons | 2018–2024 |
| Scored rows | 1651 |
| Total rows | 1942 |
| Binary scored rows | 1651 |
| Warm-up rows | 288 |
| Tie/non-binary rows | 3 |
| Features | 132 |

> *Row-accounting note:* Earlier Task 03C reporting used total minus scored as a shorthand for warm-up rows, producing 291. Canonical replay confirmed that 3 of those rows are tie/non-binary rows rather than true warm-up rows. No model outputs or scored metrics changed.

## Selected Parameters (frozen)

| Param | Value |
|---|---|
| max_depth | 2 |
| learning_rate | 0.05 |
| min_child_weight | 5.0 |
| subsample | 0.8 |
| colsample_bytree | 0.6 |
| reg_alpha | 0.5 |
| reg_lambda | 2.0 |
| gamma | 0.5 |
| max_delta_step | 1.0 |
| max_rounds | 200 |

**Selected parameter hash**: `a044ba76fd138bde1a52e364fd7fce5de042a2ddfdb6cdac22e592d4819ed58b`

## Aggregate Metrics

| Metric | Value |
|---|---|
| Brier | 0.232614 |
| Logloss | 0.657516 |
| Accuracy | 0.614779 |
| ROC-AUC | 0.648708 |
| ECE | 0.024647 |
| Mean probability | 0.555929 |
| Std probability | 0.131645 |
| Min probability | 0.164227 |
| Max probability | 0.929974 |

## Calibration

**ECE = 0.024647** (primary calibration evidence, with reliability bins).

Descriptive OLS statistics (NOT conventional calibration intercept/slope):

| Field | Value |
|---|---|
| ols_outcome_on_logit_slope | 0.211131 |
| ols_outcome_on_logit_intercept | 0.49403 |

> These are OLS linear-regression coefficients of the binary outcome on
> logit(predicted probability). They are NOT conventional logistic calibration
> intercept/slope. ECE + reliability bins are the authoritative calibration
> evidence. No post-hoc calibrator was fit.

## Seen Metrics by Season

| Season | Rows | Brier | Logloss | Acc | AUC |
|---|---|---|---|---|---|
| 2018 | 193 | 0.236035 | 0.663154 | 0.611399 | 0.575753 |
| 2019 | 228 | 0.250094 | 0.696045 | 0.539474 | 0.580179 |
| 2020 | 233 | 0.229113 | 0.651621 | 0.622318 | 0.687168 |
| 2021 | 249 | 0.237447 | 0.668591 | 0.614458 | 0.651164 |
| 2022 | 248 | 0.225356 | 0.641532 | 0.625 | 0.667926 |
| 2023 | 250 | 0.232075 | 0.655434 | 0.628 | 0.620192 |
| 2024 | 250 | 0.22022 | 0.630427 | 0.656 | 0.700529 |

## Time-of-Season Metrics

| Segment | Rows | Brier | Logloss | Acc | AUC |
|---|---|---|---|---|---|
| early_weeks_1_4 | 189 | 0.245392 | 0.686237 | 0.582011 | 0.632809 |
| middle_weeks_5_9 | 503 | 0.229132 | 0.648413 | 0.610338 | 0.656449 |
| late_weeks_10_plus | 959 | 0.231922 | 0.65663 | 0.623566 | 0.646043 |
| postseason | 54 | 0.248404 | 0.691253 | 0.592593 | 0.497744 |

## QB-Elo Comparison (1,651 common rows)

| Model | Brier | Logloss | Acc | AUC |
|---|---|---|---|---|
| QB-Elo | 0.222546 | 0.636666 | 0.637795 | 0.689392 |
| XGBoost conservative | 0.232614 | 0.657516 | 0.614779 | 0.648708 |

**Conclusion: `XGBOOST_V1_SELECTED_BUT_WEAKER_THAN_QB_ELO_STANDALONE`**

## Expected-Margin Context

Prior conclusion retained: `EXPECTED_MARGIN_V1_IMPLEMENTED_BUT_WEAK`

## Blocked-Bootstrap Evidence

Seed **20260802**, **1000** resamples, **block-level**. Conservative favored over balanced in 91% and over expressive in 96.3% of resamples. XGB-vs-XGB 95% intervals slightly overlap zero.

## Prediction Correlations

- qb_elo_vs_conservative: `0.676192`
- qb_elo_vs_balanced: `0.661676`
- qb_elo_vs_expressive: `0.64236`
- conservative_vs_balanced: `0.928353`
- conservative_vs_expressive: `0.902098`
- balanced_vs_expressive: `0.922789`

## Deterministic Replay

`DETERMINISM_REPLAY_MATCH = True` — prediction probabilities, block states, best-iteration, and final-refit sequences identical on replay.

## Limitations

- QB-Elo remains stronger standalone
- QB features in this frozen extraction are structurally present but effectively prior-driven/constant
- roof_category uses deterministic global-vocabulary integer encoding in V1
- no 2025 holdout was accessed
- no market information used
- no SHAP/pruning
- no post-hoc calibration
- no blend/stack

## Future Research Notes

- `FUTURE_V2_RESEARCH_NOT_IMPLEMENTED` — see JSON artifact for full list.
- `FUTURE_BLEND_RESEARCH_NOT_IMPLEMENTED` — preferred first blend: logistic regression on QB-Elo probability + conservative probability. Not built.

## Flags

| Flag | Value |
|---|---|
| 2025_HOLDOUT_ACCESSED | FALSE |
| MARKET_DATA_USED | FALSE |
| POST_RESULT_RETUNING_OCCURRED | FALSE |
| CANDIDATE_SELECTION_PERFORMED | TRUE |
