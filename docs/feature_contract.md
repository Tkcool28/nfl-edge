# Feature Contract

## Purpose

Define how model features are created without future information and how every prediction row can be replayed.

## Prediction grain

One row per game and scoring timestamp.

Required identity:

```text
game_id
as_of_utc
scheduled_start_utc
home_team
away_team
expected_home_qb_id
expected_away_qb_id
qb_status
data_version
feature_version
```

## Availability rule

Every source value must have an availability timestamp. A value is eligible only when its availability is not later than `as_of_utc`.

Completed-game aggregates must exclude the game being predicted and all later games.

## Feature families allowed for Version 1

### Team strength and form

Examples:

- Rolling offensive EPA per play
- Rolling defensive EPA per play allowed
- Rolling success rate
- Explosive-play rate
- Early-down performance
- Neutral-situation pass rate when defensible
- Turnover-related features only with strong shrinkage
- Opponent-adjusted versions of approved metrics

### Quarterback

Examples:

- Shrunk EPA per dropback
- CPOE
- Sack rate
- Interception rate
- Dropback sample size
- Recency-weighted QB form
- Starter certainty and alternate-starter scenario indicators

### Schedule and context

Examples:

- Rest days
- Bye week
- Travel distance when deterministically available
- Time-zone change
- Neutral site
- Dome/outdoor and roof type
- Rolling home-field estimate

### Matchup deltas

Constructed only from separately point-in-time-safe team offense and opponent defense values.

## Excluded from Version 1

- Closing odds
- Current sportsbook probabilities
- Later line movement
- Final weather observations
- Postgame injury outcomes
- End-of-season rankings
- Future schedule results
- Features added solely because they improve one holdout result
- High-dimensional player-level features without adequate sample support

## Rolling calculation rules

1. Sort by event completion time.
2. Shift before rolling or expanding aggregation.
3. Use only completed prior games.
4. Declare windows and minimum sample sizes in `config/features.yaml`.
5. Keep raw sample counts beside shrunk estimates where practical.
6. Do not backfill early-season rows with later-season values.

## Opponent adjustment

Opponent-adjusted features must be calculated inside each historical training window or through a sequential method that does not use future results.

A full-season opponent rating may not be joined backward into earlier weeks.

## QB shrinkage

Low-sample quarterbacks are shrunk toward a documented prior. The weight must be a deterministic function of approved sample size, such as dropbacks.

Required outputs include:

```text
qb_observed_value
qb_prior_value
qb_sample_size
qb_shrinkage_weight
qb_shrunk_value
```

## Missingness and imputation

- Missingness indicators are explicit where useful.
- Imputation values are learned from the training window only.
- Global medians calculated from future seasons are prohibited.
- Unknown QB status is not ordinary numeric missingness.
- A feature with excessive or unstable missingness must be removed or separately justified.

## Feature registry

Every production feature must have a registry entry containing:

```text
feature_name
description
source_table
source_columns
availability_rule
transformation
window
minimum_samples
imputation
version_added
leakage_risk
owner_test
```

## Required tests

- Same-game exclusion
- Future-row poisoning
- One-second cutoff boundary
- Early-season minimum-sample behavior
- Training-window-only imputation
- Opponent-adjustment future isolation
- QB shrinkage at zero, low, and high sample sizes
- Deterministic column order and dtypes
- Feature registry coverage for every model column

## Acceptance output

The feature builder must produce:

1. A deterministic model-ready table.
2. A feature registry.
3. A missingness report.
4. A point-in-time audit report.
5. A checksum and schema fingerprint.
6. Proof that no prohibited market column is present.
